"""Backfill ``node_fingerprint`` from packets already stored in the database.

The capture daemon accumulates firmware evidence as packets arrive and, on
its first start after this feature is installed, runs this backfill in the
background for the configured number of days (``fingerprint_backfill_days``).
A marker in ``malla_meta`` records the time the backfill covered, so later
restarts skip it and the daemon and the backfill never count a packet twice.

The CLI exists for operators who want a longer window or a re-run::

    malla-fingerprint-backfill --days 90 --until 1789000000
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections.abc import Iterable
from contextlib import nullcontext
from typing import Any

from meshtastic import mesh_pb2, mqtt_pb2

from .config import get_config
from .database.schema import MALLA_META_TABLE_SQL
from .fingerprint import (
    BROADCAST_NODE_ID,
    NODE_FINGERPRINT_UPSERT_SQL,
    FirmwareEvidence,
    ensure_node_fingerprint_table,
    evidence_row,
    observe_map_report,
    observe_packet,
    observe_user,
)

logger = logging.getLogger(__name__)

BACKFILL_MARKER_KEY = "fingerprint_backfill_until"


def read_backfill_marker(db_path: str) -> float | None:
    """Timestamp the last completed backfill covered, or None if never run."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute(MALLA_META_TABLE_SQL)
            row = conn.execute(
                "SELECT value FROM malla_meta WHERE key = ?", (BACKFILL_MARKER_KEY,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug("Could not read backfill marker: %s", e)
        return None
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


# Only these apps can carry a signature or reveal an AEAD channel, so only
# their envelopes are worth parsing (and decrypting).
_SIGNABLE_PORTNUMS = frozenset(
    {
        "NODEINFO_APP",
        "POSITION_APP",
        "TELEMETRY_APP",
        "TEXT_MESSAGE_APP",
        "UNKNOWN_APP",
        None,
    }
)


def _decrypt_candidates(channel_name: str | None, keys: Iterable[str]) -> list[bytes]:
    from .mqtt_capture import derive_key_from_channel_name

    candidates: list[bytes] = []
    for key in keys:
        for name in ("", channel_name or ""):
            try:
                derived = derive_key_from_channel_name(name, key)
            except Exception:  # noqa: BLE001
                continue
            if len(derived) in (16, 32) and derived not in candidates:
                candidates.append(derived)
    return candidates


def _looks_like_data(plain: bytes) -> bool:
    data = mesh_pb2.Data()
    try:
        data.ParseFromString(plain)
    except Exception:  # noqa: BLE001
        return False
    return bool(data.portnum) and data.portnum < 600


def _data_bytes_from_envelope(
    envelope_bytes: bytes | None, channel_name: str | None, keys: list[str]
) -> tuple[bytes | None, bool]:
    """``(serialized Data, used_aead)`` for the packet in an envelope.

    Decrypts when needed, trying AES-CCM (2.8.1 ``use_aead`` channels) before
    AES-CTR because the CCM tag rules out false positives.
    """
    if not envelope_bytes:
        return None, False
    from .mqtt_capture import decrypt_packet, decrypt_packet_ccm

    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.ParseFromString(envelope_bytes)
    packet = envelope.packet
    if packet.HasField("decoded"):
        return packet.decoded.SerializeToString(), False
    if not packet.encrypted or getattr(packet, "pki_encrypted", False):
        return None, False
    sender = getattr(packet, "from")
    encrypted = bytes(packet.encrypted)
    for key in _decrypt_candidates(channel_name, keys):
        plain = decrypt_packet_ccm(encrypted, packet.id, sender, packet.to, key)
        if plain and _looks_like_data(plain):
            return plain, True
        plain = decrypt_packet(encrypted, packet.id, sender, key)
        if plain and _looks_like_data(plain):
            return plain, False
    return None, False


def _log_label_histogram(db_path: str, evidence: dict[int, FirmwareEvidence]) -> None:
    """Log how the evidence would be classified (a sanity check for operators)."""
    from collections import Counter

    from .fingerprint import estimate

    meta: dict[int, tuple[str | None, str | None]] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        try:
            for node_id, role, hw_model in conn.execute(
                "SELECT node_id, role, hw_model FROM node_info"
            ):
                meta[node_id] = (role, hw_model)
        finally:
            conn.close()
    except sqlite3.Error as e:  # pragma: no cover - informational only
        logger.debug("node_info unavailable for histogram: %s", e)
    histogram: Counter[str] = Counter()
    for node_id, ev in evidence.items():
        role, hw_model = meta.get(node_id, (None, None))
        verdict = estimate(ev, role=role, hw_model=hw_model)
        key = (
            verdict["label"] if verdict["source"] != "reported" else "reported (exact)"
        )
        histogram[key] += 1
    for label, count in sorted(histogram.items(), key=lambda kv: -kv[1]):
        logger.info("  %5d  %s", count, label)


def backfill(
    db_path: str,
    *,
    days: float,
    until: float,
    keys: list[str],
    dry_run: bool = False,
    progress_every: int = 200_000,
    lock: Any = None,
) -> dict[str, int]:
    """Compute evidence for ``[until - days, until)`` and merge it into the DB.

    ``lock`` (a context manager such as the capture daemon's ``db_lock``) is
    held only for the final write, which also records the completion marker
    in the same transaction.
    """
    since = until - days * 86400
    evidence: dict[int, FirmwareEvidence] = {}
    stats = {"packets": 0, "signatures": 0, "map_reports": 0, "nodes": 0}

    read = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    read.row_factory = sqlite3.Row
    try:
        logger.info("Scanning MapReport packets (all time)")
        for row in read.execute(
            """
            SELECT from_node_id, timestamp, raw_payload FROM packet_history
            WHERE portnum_name = 'MAP_REPORT_APP' AND raw_payload IS NOT NULL
              AND from_node_id IS NOT NULL AND timestamp < ?
            ORDER BY timestamp
            """,
            (until,),
        ):
            try:
                report = mqtt_pb2.MapReport()
                report.ParseFromString(bytes(row["raw_payload"]))
            except Exception:  # noqa: BLE001
                continue
            ev = evidence.setdefault(row["from_node_id"], FirmwareEvidence())
            observe_map_report(ev, report, row["timestamp"])
            stats["map_reports"] += 1

        logger.info(
            "Scanning packets from %s to %s",
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(since)),
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(until)),
        )
        # Older databases may predate some columns; select what exists.
        present = {r[1] for r in read.execute("PRAGMA table_info(packet_history)")}
        wanted = (
            "from_node_id",
            "to_node_id",
            "hop_start",
            "hop_limit",
            "relay_node",
            "portnum",
            "portnum_name",
            "raw_payload",
            "raw_service_envelope",
            "channel_id",
        )
        select_list = ", ".join(
            col if col in present else f"NULL AS {col}" for col in wanted
        )
        cursor = read.execute(
            f"""
            SELECT {select_list}
            FROM packet_history
            WHERE timestamp >= ? AND timestamp < ? AND from_node_id IS NOT NULL
            ORDER BY id
            """,
            (since, until),
        )
        for row in cursor:
            stats["packets"] += 1
            node_id = row["from_node_id"]
            if node_id <= 0 or node_id == BROADCAST_NODE_ID:
                continue
            ev = evidence.setdefault(node_id, FirmwareEvidence())
            data_bytes = None
            used_aead = False
            if row["portnum_name"] in _SIGNABLE_PORTNUMS:
                try:
                    data_bytes, used_aead = _data_bytes_from_envelope(
                        row["raw_service_envelope"], row["channel_id"], keys
                    )
                except Exception:  # noqa: BLE001
                    data_bytes, used_aead = None, False
            before = ev.xeddsa_signed_count
            observe_packet(
                ev,
                node_id,
                to_node_id=row["to_node_id"],
                hop_start=row["hop_start"],
                hop_limit=row["hop_limit"],
                relay_node=row["relay_node"],
                data_bytes=data_bytes,
                portnum=row["portnum"],
                telemetry_bytes=(
                    bytes(row["raw_payload"])
                    if row["portnum_name"] == "TELEMETRY_APP" and row["raw_payload"]
                    else None
                ),
                aead=used_aead,
            )
            stats["signatures"] += ev.xeddsa_signed_count - before
            if row["portnum_name"] == "NODEINFO_APP" and row["raw_payload"]:
                try:
                    user = mesh_pb2.User()
                    user.ParseFromString(bytes(row["raw_payload"]))
                    observe_user(ev, node_id, user)
                except Exception:  # noqa: BLE001
                    pass
            if stats["packets"] % progress_every == 0:
                logger.info("… %s packets scanned", stats["packets"])
    finally:
        read.close()

    stats["nodes"] = len(evidence)
    _log_label_histogram(db_path, evidence)
    if dry_run:
        logger.info("Dry run: %s", stats)
        return stats

    now = time.time()
    rows = [evidence_row(nid, ev, now) for nid, ev in evidence.items()]
    with lock if lock is not None else nullcontext():
        write = sqlite3.connect(db_path, timeout=60)
        try:
            write.execute("PRAGMA busy_timeout=30000")
            ensure_node_fingerprint_table(write.cursor())
            write.execute(MALLA_META_TABLE_SQL)
            write.executemany(NODE_FINGERPRINT_UPSERT_SQL, rows)
            write.execute(
                "INSERT INTO malla_meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (BACKFILL_MARKER_KEY, repr(float(until)), now),
            )
            write.commit()
        finally:
            write.close()
    logger.info("Backfill done: %s", stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--days", type=float, default=30, help="window length (default 30)"
    )
    parser.add_argument(
        "--until",
        type=float,
        default=None,
        help="end of window as a Unix timestamp (default: now)",
    )
    parser.add_argument(
        "--database", default=None, help="override the configured DB path"
    )
    parser.add_argument("--dry-run", action="store_true", help="scan but do not write")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    cfg = get_config()
    db_path = args.database or cfg.database_file
    stats = backfill(
        db_path,
        days=args.days,
        until=args.until or time.time(),
        keys=cfg.get_decryption_keys(),
        dry_run=args.dry_run,
    )
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
