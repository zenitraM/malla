"""Shared capture/backfill decoder, writer, and traceroute readiness checks."""

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError

from ..models.traceroute import TracerouteHop, TraceroutePacket
from ..utils.traceroute_utils import RouteData, decode_traceroute_payload
from .traceroute_schema import TRACEROUTE_PREDICATE

PARSER_VERSION = 1


@dataclass(frozen=True)
class DecodedTraceroute:
    route: RouteData
    hops: tuple[TracerouteHop, ...] = ()
    forward_complete: bool = False
    return_complete: bool = False
    parse_error: str | None = None

    @property
    def parse_status(self) -> str:
        if self.parse_error is not None:
            return "invalid_payload"
        return "parsed" if any(self.route.values()) else "valid_empty"


def decode_traceroute(packet: dict[str, Any]) -> DecodedTraceroute:
    """Decode once, without database/name/location lookups or discarded hops."""
    try:
        if packet.get("raw_payload") is None:
            raise TypeError("Traceroute payload is missing")
        route = decode_traceroute_payload(packet["raw_payload"])
    except (DecodeError, TypeError) as exc:
        return DecodedTraceroute(
            route=RouteData(route_nodes=[], snr_towards=[], route_back=[], snr_back=[]),
            parse_error=str(exc),
        )

    traceroute = TraceroutePacket(
        packet, resolve_names=False, pre_parsed_route_data=route
    )
    return DecodedTraceroute(
        route=route,
        hops=tuple(traceroute.get_rf_hops()),
        forward_complete=traceroute.is_complete(),
        return_complete=traceroute.is_return_complete(),
    )


def write_traceroute(cursor: sqlite3.Cursor, packet: dict[str, Any]) -> None:
    """Replace one reception's decoded data inside the caller's transaction.

    The caller must already have inserted the raw packet. This function neither
    commits nor swallows storage errors, so raw and derived data stay atomic.
    """
    if not cursor.connection.in_transaction:
        raise ValueError("Traceroute writes require an active transaction")
    decoded = decode_traceroute(packet)
    cursor.execute(
        """
        INSERT INTO traceroute_routes (
            packet_id, timestamp, mesh_packet_id, from_node_id, to_node_id,
            route_nodes_json, snr_towards_json, route_back_json, snr_back_json,
            forward_complete, return_complete, parse_status, parse_error,
            parser_version, materialized_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(packet_id) DO UPDATE SET
            timestamp = excluded.timestamp,
            mesh_packet_id = excluded.mesh_packet_id,
            from_node_id = excluded.from_node_id,
            to_node_id = excluded.to_node_id,
            route_nodes_json = excluded.route_nodes_json,
            snr_towards_json = excluded.snr_towards_json,
            route_back_json = excluded.route_back_json,
            snr_back_json = excluded.snr_back_json,
            forward_complete = excluded.forward_complete,
            return_complete = excluded.return_complete,
            parse_status = excluded.parse_status,
            parse_error = excluded.parse_error,
            parser_version = excluded.parser_version,
            materialized_at = excluded.materialized_at
        """,
        (
            packet["id"],
            packet["timestamp"],
            packet.get("mesh_packet_id"),
            packet.get("from_node_id"),
            packet.get("to_node_id"),
            json.dumps(decoded.route["route_nodes"]),
            json.dumps(decoded.route["snr_towards"]),
            json.dumps(decoded.route["route_back"]),
            json.dumps(decoded.route["snr_back"]),
            decoded.forward_complete,
            decoded.return_complete,
            decoded.parse_status,
            decoded.parse_error,
            PARSER_VERSION,
            time.time(),
        ),
    )
    cursor.execute("DELETE FROM traceroute_hops WHERE packet_id = ?", (packet["id"],))
    indices = {"forward_rf": 0, "return_rf": 0}
    for hop in decoded.hops:
        cursor.execute(
            """
            INSERT INTO traceroute_hops
                (packet_id, direction, hop_index, timestamp, from_node_id, to_node_id, snr)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet["id"],
                "forward" if hop.direction == "forward_rf" else "return",
                indices[hop.direction],
                packet["timestamp"],
                hop.from_node_id,
                hop.to_node_id,
                hop.snr,
            ),
        )
        indices[hop.direction] += 1


def inspect_traceroutes(cursor: sqlite3.Cursor) -> dict[str, Any]:
    """Audit stored history explicitly, including databases not yet prepared.

    This is an offline validation query, not a web request helper. The caller
    holds a transaction for a consistent snapshot.
    """
    tables = {
        row[0]
        for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    raw = cursor.execute(
        f"SELECT COUNT(*) FROM packet_history WHERE {TRACEROUTE_PREDICATE}"
    ).fetchone()[0]
    counts: dict[str, Any] = {
        "raw_traceroutes": raw,
        "routes": 0,
        "parsed": 0,
        "valid_empty": 0,
        "invalid_payload": 0,
        "pending": 0,
        "outdated": 0,
        "missing": raw,
        "hops": 0,
        "orphan_routes": 0,
        "orphan_hops": 0,
        "parser_version": PARSER_VERSION,
        "complete": False,
    }
    if not {"traceroute_routes", "traceroute_hops"} <= tables:
        return counts

    for status, version, count in cursor.execute(
        "SELECT parse_status, parser_version, COUNT(*) FROM traceroute_routes "
        "GROUP BY parse_status, parser_version"
    ):
        counts["routes"] += count
        counts[status] += count
        if version not in (0, PARSER_VERSION):
            counts["outdated"] += count
    counts["missing"] = cursor.execute(
        f"""
        SELECT COUNT(*) FROM packet_history
        WHERE {TRACEROUTE_PREDICATE} AND NOT EXISTS (
            SELECT 1 FROM traceroute_routes WHERE packet_id = packet_history.id
        )
        """
    ).fetchone()[0]
    counts["hops"] = cursor.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[
        0
    ]
    counts["orphan_routes"] = cursor.execute(
        f"""
        SELECT COUNT(*) FROM traceroute_routes WHERE NOT EXISTS (
            SELECT 1 FROM packet_history
            WHERE id = traceroute_routes.packet_id AND {TRACEROUTE_PREDICATE}
        )
        """
    ).fetchone()[0]
    counts["orphan_hops"] = cursor.execute(
        """
        SELECT COUNT(*) FROM traceroute_hops WHERE NOT EXISTS (
            SELECT 1 FROM traceroute_routes WHERE packet_id = traceroute_hops.packet_id
        )
        """
    ).fetchone()[0]
    counts["complete"] = not any(
        counts[key]
        for key in ("missing", "pending", "outdated", "orphan_routes", "orphan_hops")
    )
    return counts
