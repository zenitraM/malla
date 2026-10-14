"""Versioned JSON REST API (v1) for Malla.

Contract shared with the web frontend:

* Success responses are ``{"data": ..., "meta": {...}}`` with HTTP 200.
  ``meta`` is always present; list endpoints carry ``meta.pagination`` and
  ``meta.query`` (the normalized echo of the effective query parameters).
* Error responses are ``{"error": {"code": ..., "message": ..., ...}}`` with
  the documented status code (400 bad parameters, 404 unknown resource, 500
  internal error).
* All scalar timestamps are ISO-8601 UTC with a ``Z`` suffix. Telemetry series
  points remain ``[unix_epoch_seconds, value]`` pairs (chart-friendly).

The blueprint reuses the service/repository layer. The only new SQL in this
module is the node-listing query: ``NodeRepository.get_nodes`` cannot express
the ``has_position`` / ``last_seen_since`` filters or the ``snr``/``battery``
sorts, and node-scoped packet listings need ``from OR to`` semantics which the
packet repositories (AND semantics) cannot express.
"""

import importlib.metadata
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from ..config import get_config
from ..database.connection import get_db_connection
from ..database.packet_repository_optimized import PacketRepositoryOptimized
from ..database.repositories import (
    _TELEMETRY_METRICS,
    DashboardRepository,
    NodeRepository,
    PacketRepository,
    TracerouteRepository,
)
from ..models.traceroute import TraceroutePacket
from ..services.analytics_service import AnalyticsService
from ..services.gateway_service import GatewayService
from ..services.location_service import LocationService
from ..services.meshtastic_service import MeshtasticService
from ..services.node_service import NodeNotFoundError, NodeService
from ..services.traceroute_service import TracerouteService
from ..utils.node_utils import (
    get_bulk_node_names,
    get_bulk_node_short_names,
)
from ..utils.traceroute_utils import parse_traceroute_payload
from . import api_routes as _legacy_api
from .packet_routes import get_packet_details

logger = logging.getLogger(__name__)

API_V1_VERSION = "1.0.0"
URL_PREFIX = "/api/v1"

api_v1_bp = Blueprint("api_v1", __name__, url_prefix=URL_PREFIX)

# Conservative caching for append-only history listings.
CACHEABLE_SUFFIXES = ("/packets", "/traceroutes", "/locations")
CACHE_HEADER = "public, max-age=30"

PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 100
PAGE_SIZE_MAX = 500
# Bulk latest positions and per-node history bounds.
LOCATIONS_DEFAULT_WINDOW_DAYS = 14
LOCATIONS_PAGE_SIZE_DEFAULT = 1000
LOCATIONS_PAGE_SIZE_MAX = 5000
LOCATION_HISTORY_MAX = 2000

NODE_SORTS = ("name", "last_seen", "snr", "battery")
PACKET_SORTS = {
    "timestamp": "timestamp",
    "from_node": "from_node_id",
    "to_node": "to_node_id",
    "gateway": "gateway_id",
    "portnum_name": "portnum_name",
    "rssi": "rssi",
    "snr": "snr",
    "payload_length": "payload_length",
    "hop_count": "hop_count",
}
# Traceroute sorts proven index-ordered by EXPLAIN QUERY PLAN on the fixture DB
# (timestamp/id are served by idx_packet_portnum_name without a temp b-tree;
# mesh_packet_id and payload_length need a temp b-tree, so they are not offered).
TRACEROUTE_SORTS = {"timestamp": "timestamp", "id": "id"}
# Server-side grouping modes for the listing endpoints (the ``group_by`` param).
GROUP_BY_MODES = ("mesh_packet_id",)
TELEMETRY_METRIC_NAMES = sorted(field for _, field, _, _ in _TELEMETRY_METRICS)
STATS_RANGES = ("24h", "7d", "30d", "all")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class APIError(Exception):
    """An error with a machine-readable code, mapped to an HTTP status."""

    def __init__(
        self, code: str, message: str, status: int = 400, **details: Any
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def _error_payload(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def _error_response(payload: dict[str, Any], status: int) -> Response:
    response: Response = jsonify(_sanitize(payload))
    response.status_code = status
    return response


@api_v1_bp.errorhandler(APIError)
def _handle_api_error(exc: APIError) -> Response:
    return _error_response(
        _error_payload(exc.code, exc.message, exc.details), exc.status
    )


@api_v1_bp.errorhandler(NodeNotFoundError)
def _handle_node_not_found(exc: NodeNotFoundError) -> Response:
    return _error_response(
        _error_payload("node_not_found", str(exc) or "Node not found"), 404
    )


@api_v1_bp.errorhandler(ValueError)
def _handle_value_error(exc: ValueError) -> Response:
    return _error_response(_error_payload("invalid_parameter", str(exc)), 400)


@api_v1_bp.errorhandler(Exception)
def _handle_uncaught(exc: Exception) -> Response:
    logger.exception("Unhandled error in API v1: %s", exc)
    return _error_response(_error_payload("internal_error", str(exc)), 500)


@api_v1_bp.app_errorhandler(404)
@api_v1_bp.app_errorhandler(405)
def _handle_routing_error(exc: HTTPException) -> Response:
    """Shape routing errors inside this blueprint's URL space.

    Blueprint error handlers only fire once a route matched, so unknown paths
    under ``/api/v1`` land in this app-level handler; requests elsewhere are
    passed through untouched.
    """
    if request.blueprint == api_v1_bp.name or request.path.startswith(URL_PREFIX):
        code = "not_found" if exc.code == 404 else "method_not_allowed"
        message = exc.description or exc.name
        return _error_response(_error_payload(code, message), exc.code or 500)
    return exc.get_response(request.environ)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------


def _sanitize(value: Any) -> Any:
    """Make ``value`` JSON-serializable (bytes → hex, datetimes → ISO).

    Objects that are not plain JSON types fall back to their ``__dict__``
    (mirroring ``web_ui.make_json_safe``) so a live model instance leaking
    into a payload can never turn a response into a 500.
    """
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return _iso(value.timestamp())
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_sanitize(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _sanitize(item) for key, item in vars(value).items()}
    return value


def _iso(ts: float | int | datetime | None) -> str | None:
    """Format a Unix timestamp as ISO-8601 UTC with ``Z`` suffix."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        ts = ts.timestamp()
    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_fields(row: dict[str, Any], *names: str) -> dict[str, Any]:
    """Replace the named epoch fields with ISO strings (numeric only)."""
    for name in names:
        value = row.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[name] = _iso(value)
    return row


def _ok(data: Any, meta: dict[str, Any] | None = None) -> Response:
    body = {"data": _sanitize(data), "meta": _sanitize(meta or {})}
    return jsonify(body)


def _pagination_meta(total: int, page: int, page_size: int, query: dict[str, Any]):
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        },
        "query": query,
    }


# ---------------------------------------------------------------------------
# Request parameter parsing
# ---------------------------------------------------------------------------


def _pagination_params() -> tuple[int, int]:
    page_raw = request.args.get("page")
    page = PAGE_DEFAULT
    if page_raw is not None:
        try:
            page = int(page_raw)
        except ValueError as exc:
            raise APIError(
                "invalid_page", "page must be an integer", page=page_raw
            ) from exc
        if page < 1:
            raise APIError("invalid_page", "page must be >= 1", page=page)

    size_raw = request.args.get("page_size")
    page_size = PAGE_SIZE_DEFAULT
    if size_raw is not None:
        try:
            page_size = int(size_raw)
        except ValueError as exc:
            raise APIError(
                "invalid_page_size", "page_size must be an integer", page_size=size_raw
            ) from exc
        if not 1 <= page_size <= PAGE_SIZE_MAX:
            raise APIError(
                "invalid_page_size",
                f"page_size must be between 1 and {PAGE_SIZE_MAX}",
                page_size=page_size,
            )
    return page, page_size


def _parse_bool(name: str, default: bool | None = None) -> bool | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    details: dict[str, Any] = {name: raw}
    raise APIError("invalid_parameter", f"{name} must be a boolean", **details)


def _parse_timestamp(name: str) -> float | None:
    """Parse a query timestamp given as Unix epoch seconds or ISO-8601."""
    raw = request.args.get(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        details: dict[str, Any] = {name: raw}
        raise APIError(
            "invalid_parameter",
            f"{name} must be Unix epoch seconds or ISO-8601",
            **details,
        ) from None


def _parse_enum(name: str, allowed: tuple[str, ...] | set[str], default: str) -> str:
    raw = request.args.get(name, default)
    if raw not in allowed:
        details: dict[str, Any] = {name: raw}
        raise APIError(
            "invalid_parameter",
            f"{name} must be one of: {', '.join(sorted(allowed))}",
            **details,
        )
    return raw


def _group_by_param() -> str | None:
    """Optional ``group_by``; ``None`` keeps the ungrouped response shape."""
    raw = request.args.get("group_by")
    if raw is None:
        return None
    if raw not in GROUP_BY_MODES:
        raise APIError(
            "invalid_parameter",
            f"group_by must be one of: {', '.join(GROUP_BY_MODES)}",
            group_by=raw,
        )
    return raw


def _parse_int(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        details: dict[str, Any] = {name: raw}
        raise APIError(
            "invalid_parameter", f"{name} must be an integer", **details
        ) from None


def _parse_node_id(value: str) -> int:
    """Parse a node id in any format the existing node routes accept.

    ``!xxxxxxxx`` (the canonical 32-bit hex form used throughout Malla),
    ``0x...`` hex, bare hex such as ``433d0c24`` and plain decimal are all
    accepted.
    """
    text = str(value).strip()
    try:
        if text.startswith("!"):
            return int(text[1:], 16)
        if text.startswith("0x"):
            return int(text, 16)
        if text.isdigit():
            return int(text, 10)
        return int(text, 16)  # bare hex, e.g. 433d0c24
    except ValueError:
        raise APIError(
            "invalid_node_id",
            "node id must be !xxxxxxxx hex, 0x hex or decimal",
            node_id=value,
        ) from None


def _node_id_param(name: str) -> int | None:
    raw = request.args.get(name)
    return _parse_node_id(raw) if raw else None


def _require_node(node_id: int) -> dict[str, Any]:
    """Return the lightweight node row or raise a 404 APIError."""
    node = NodeRepository.get_basic_node_info(node_id)
    if node is None:
        raise APIError("node_not_found", f"Node {node_id} not found", 404)
    return dict(node)


def _normalize_gateway_id(raw: str) -> str:
    """Normalize a gateway reference to the stored ``!xxxxxxxx`` form."""
    try:
        return f"!{_parse_node_id(raw):08x}"
    except APIError:
        return raw.strip()


def _gateway_id_param() -> str | None:
    raw = (request.args.get("gateway_id") or "").strip()
    return _normalize_gateway_id(raw) if raw else None


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------


def _packet_public(row: dict[str, Any]) -> dict[str, Any]:
    packet = dict(row)
    packet.pop("raw_payload", None)
    packet.pop("timestamp_str", None)
    packet["timestamp"] = _iso(packet.get("timestamp"))
    packet["success"] = packet.get("processed_successfully")
    return packet


def _name_entry(
    node_id: Any, display: dict[int, str], short: dict[int, str]
) -> dict[str, Any] | None:
    """One resolved endpoint/gateway entry, or None when absent."""
    if not isinstance(node_id, int) or isinstance(node_id, bool) or node_id <= 0:
        return None
    return {
        "node_id": node_id,
        "hex_id": f"!{node_id:08x}",
        "display_name": display.get(node_id),
        "short_name": short.get(node_id),
    }


def _collect_packet_ids(
    rows: list[dict[str, Any]],
) -> tuple[set[int], dict[str, int]]:
    node_ids: set[int] = set()
    gateway_nodes: dict[str, int] = {}
    for row in rows:
        for key in ("from_node_id", "to_node_id"):
            value = row.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                node_ids.add(value)
        gateway = row.get("gateway_id")
        if isinstance(gateway, str) and gateway.startswith("!"):
            try:
                gateway_node = int(gateway[1:], 16)
            except ValueError:
                continue
            node_ids.add(gateway_node)
            gateway_nodes[gateway] = gateway_node
    return node_ids, gateway_nodes


def _attach_packet_names(rows: list[dict[str, Any]]) -> None:
    """Attach legacy-level name enrichment to packet rows, in place.

    ``names`` carries ``from``/``to``/``gateway`` entries resolved with the
    same bulk helpers the legacy table endpoints use
    (``get_bulk_node_names`` / ``get_bulk_node_short_names``), plus a
    ``text_content`` preview decoded by
    ``PacketRepository._decode_text_content`` when not already present.
    """
    node_ids, gateway_nodes = _collect_packet_ids(rows)
    display = get_bulk_node_names(list(node_ids)) if node_ids else {}
    short = get_bulk_node_short_names(list(node_ids)) if node_ids else {}

    for row in rows:
        if "text_content" not in row:
            row["text_content"] = PacketRepository._decode_text_content(row)
        gateway_id = row.get("gateway_id")
        gateway_node = (
            gateway_nodes.get(gateway_id) if isinstance(gateway_id, str) else None
        )
        row["names"] = {
            "from": _name_entry(row.get("from_node_id"), display, short),
            "to": _name_entry(row.get("to_node_id"), display, short),
            "gateway": _name_entry(gateway_node, display, short)
            if gateway_node
            else None,
        }


def _collect_traceroute_ids(
    rows: list[dict[str, Any]],
) -> tuple[set[int], dict[str, int], list[list[int]]]:
    node_ids: set[int] = set()
    gateway_nodes: dict[str, int] = {}
    routes: list[list[int]] = []
    for row in rows:
        for key in ("from_node_id", "to_node_id"):
            value = row.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                node_ids.add(value)
        gateway = row.get("gateway_id")
        if isinstance(gateway, str) and gateway.startswith("!"):
            try:
                gateway_node = int(gateway[1:], 16)
            except ValueError:
                gateway_node = None
            if gateway_node is not None:
                node_ids.add(gateway_node)
                gateway_nodes[gateway] = gateway_node

        route: list[int] = []
        raw_route = row.get("route")
        if isinstance(raw_route, str) and raw_route.strip():
            try:
                parsed = json.loads(raw_route)
                if isinstance(parsed, list):
                    route = [node for node in parsed if isinstance(node, int)]
            except ValueError:
                route = []
        if not route and row.get("raw_payload"):
            try:
                route_data = parse_traceroute_payload(row["raw_payload"])
                route = [
                    node
                    for node in (route_data.get("route_nodes") or [])
                    if isinstance(node, int)
                ]
            except Exception:
                route = []
        routes.append(route)
        node_ids.update(route)
    return node_ids, gateway_nodes, routes


def _attach_traceroute_names(rows: list[dict[str, Any]]) -> None:
    """Attach legacy-level name enrichment to traceroute rows, in place.

    Mirrors the fields the legacy ``/api/traceroute/data`` endpoint derives
    (endpoint, gateway and route-node names) under a single ``names`` object;
    route members follow wire order when the route is parseable.
    """
    node_ids, gateway_nodes, routes = _collect_traceroute_ids(rows)
    display = get_bulk_node_names(list(node_ids)) if node_ids else {}
    short = get_bulk_node_short_names(list(node_ids)) if node_ids else {}

    for row, route in zip(rows, routes, strict=False):
        gateway_id = row.get("gateway_id")
        gateway_node = (
            gateway_nodes.get(gateway_id) if isinstance(gateway_id, str) else None
        )
        row["names"] = {
            "from": _name_entry(row.get("from_node_id"), display, short),
            "to": _name_entry(row.get("to_node_id"), display, short),
            "gateway": _name_entry(gateway_node, display, short)
            if gateway_node
            else None,
            "route": [
                entry
                for entry in (_name_entry(node_id, display, short) for node_id in route)
                if entry is not None
            ],
        }


def _resolve_group_gateways(rows: list[dict[str, Any]]) -> None:
    """Swap raw group gateway ids for PacketNameEntry enrichment, in place.

    The repositories attach each group's distinct gateway ids as stored
    (``!xxxxxxxx``); the public shape reuses the ``names.gateway`` entry
    schema for them.
    """

    def _gateway_node_id(gateway: Any) -> int | None:
        if isinstance(gateway, str) and gateway.startswith("!"):
            try:
                return int(gateway[1:], 16)
            except ValueError:
                return None
        return None

    grouped = [row for row in rows if isinstance(row.get("group"), dict)]
    if not grouped:
        return

    node_ids = {
        node_id
        for row in grouped
        for gateway in row["group"].get("gateways", [])
        if (node_id := _gateway_node_id(gateway)) is not None
    }
    display = get_bulk_node_names(list(node_ids)) if node_ids else {}
    short = get_bulk_node_short_names(list(node_ids)) if node_ids else {}

    for row in grouped:
        entries = []
        for gateway in row["group"].get("gateways", []):
            node_id = _gateway_node_id(gateway)
            if node_id is None:
                continue
            entry = _name_entry(node_id, display, short)
            if entry is not None:
                entries.append(entry)
        row["group"]["gateways"] = entries


def _node_public(node_id: int, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "node_id": node_id,
        "hex_id": f"!{node_id:08x}",
        "long_name": None,
        "short_name": None,
        "hw_model": None,
        "role": None,
        "primary_channel": None,
        "last_seen": None,
        "packet_count_24h": 0,
        "avg_snr": None,
        "battery_level": None,
        "has_position": None,
    }
    row.update(fields)
    row["last_seen"] = _iso(row["last_seen"])
    return row


# ---------------------------------------------------------------------------
# Node listing
#
# NodeRepository.get_nodes cannot express has_position / last_seen_since
# filters or snr/battery sorts, and its row shape lacks those fields, so the
# v1 listing uses one dedicated query. The 24h counters and direct-SNR average
# come from the capture-maintained ``node_hour_rollup`` (hour buckets; the
# boundary bucket makes the window 24-25h wide) instead of aggregating
# packet_history per request; batteries come from the ``node_latest_telemetry``
# rollup via a TTL-cached map.
# ---------------------------------------------------------------------------

_NODE_AGG_WINDOW_SEC = 86400

_NODE_AGG_JOIN = """
    LEFT JOIN (
        SELECT
            node_id,
            SUM(packet_count) AS packet_count_24h,
            MAX(last_seen) AS last_packet_time
        FROM node_hour_rollup INDEXED BY sqlite_autoindex_node_hour_rollup_1
        WHERE hour_epoch >= ?
        GROUP BY node_id
    ) AS agg ON agg.node_id = ni.node_id
"""

# Direct-reception signal average, pre-aggregated per hour bucket by the
# capture refresh. The stored sums apply the same acceptance rule as the
# legacy SQL (hop_start == hop_limit, 0..7, plausible SNR); parity is pinned
# by tests/unit/test_capture_rollups.py.
_NODE_SIGNAL_JOIN = """
    LEFT JOIN (
        SELECT
            node_id,
            SUM(direct_snr_sum) / NULLIF(SUM(direct_snr_count), 0) AS avg_snr
        FROM node_hour_rollup INDEXED BY sqlite_autoindex_node_hour_rollup_1
        WHERE hour_epoch >= ?
        GROUP BY node_id
    ) AS sig ON sig.node_id = ni.node_id
"""

_NODE_POSITION_EXPR = (
    "(EXISTS (SELECT 1 FROM packet_history pp"
    " WHERE pp.portnum = 3 AND pp.raw_payload IS NOT NULL"
    " AND pp.from_node_id = ni.node_id))"
)
# Position existence is expressed as a correlated EXISTS against the existing
# covering partial index idx_packet_history_position_lookup_time
# (portnum, timestamp DESC, from_node_id)
# WHERE portnum = 3 AND raw_payload IS NOT NULL AND from_node_id IS NOT NULL,
# instead of a MATERIALIZEd DISTINCT join over the whole table.

# Latest device battery per node, from the capture-maintained
# ``node_latest_telemetry`` rollup (decoded once at refresh time).
_BATTERY_MAP_SQL = """
    SELECT node_id, battery_level
    FROM node_latest_telemetry
    WHERE battery_level IS NOT NULL
"""

_BATTERY_CACHE_TTL_SEC = 120
_battery_cache: dict[tuple[str, int], tuple[float, dict[int, float]]] = {}


def _node_hour_window() -> int:
    """Lowest ``node_hour_rollup`` bucket covering the rolling 24h window.

    Whole hour buckets are the finest grain the rollup stores, so the window
    they cover is 24-25h wide (the boundary bucket is included); see the
    freshness contract in ``malla.capture_rollups``.
    """
    return int((time.time() - _NODE_AGG_WINDOW_SEC) // 3600)


_NODE_SELECT = """
    SELECT
        ni.node_id,
        printf('!%08x', ni.node_id) AS hex_id,
        ni.long_name,
        ni.short_name,
        ni.hw_model,
        ni.role,
        ni.primary_channel,
        COALESCE(agg.last_packet_time, ni.last_updated) AS last_seen,
        COALESCE(agg.packet_count_24h, 0) AS packet_count_24h,
        sig.avg_snr,
        {has_position_expr} AS has_position
        {battery_select}
    FROM node_info ni
"""

_NODE_ORDER_EXPRS = {
    "name": "ni.long_name",
    "last_seen": "COALESCE(agg.last_packet_time, ni.last_updated)",
    "snr": "sig.avg_snr",
}


def _node_filters() -> tuple[str, list[Any], dict[str, bool]]:
    """Build the WHERE clause shared by every node-listing variant.

    Also reports which optional joins the filters reference, so the COUNT
    statement can skip joins it does not need (the common unfiltered case
    counts node_info alone).
    """
    conditions: list[str] = []
    params: list[Any] = []
    needs = {"agg": False}

    search = (request.args.get("q") or "").strip()
    if search:
        conditions.append(
            "(ni.long_name LIKE ? OR ni.short_name LIKE ? OR ni.hw_model LIKE ?"
            " OR printf('!%08x', ni.node_id) LIKE ?)"
        )
        params.extend([f"%{search}%"] * 4)

    role = (request.args.get("role") or "").strip()
    if role:
        conditions.append("ni.role = ?")
        params.append(role)

    channel = (request.args.get("channel") or "").strip()
    if channel:
        conditions.append("ni.primary_channel = ?")
        params.append(channel)

    has_position = _parse_bool("has_position")
    if has_position is not None:
        conditions.append(
            _NODE_POSITION_EXPR if has_position else f"NOT {_NODE_POSITION_EXPR}"
        )

    last_seen_since = _parse_timestamp("last_seen_since")
    if last_seen_since is not None:
        conditions.append("COALESCE(agg.last_packet_time, ni.last_updated) >= ?")
        params.append(last_seen_since)
        needs["agg"] = True

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, params, needs


def _node_row(row: Any, battery_level: float | None = None) -> dict[str, Any]:
    return _node_public(
        row["node_id"],
        hex_id=row["hex_id"],
        long_name=row["long_name"],
        short_name=row["short_name"],
        hw_model=row["hw_model"],
        role=row["role"],
        primary_channel=row["primary_channel"],
        last_seen=row["last_seen"],
        packet_count_24h=row["packet_count_24h"],
        avg_snr=row["avg_snr"],
        battery_level=battery_level,
        has_position=bool(row["has_position"]),
    )


def _battery_map() -> dict[int, float]:
    """node_id -> latest decoded battery level, cached briefly.

    Nodes whose latest telemetry row carries no battery_level are absent; the
    120s TTL keeps repeat sorts cheap while staying fresh enough for a table
    column.
    """
    now = time.time()
    bucket = int(now // _BATTERY_CACHE_TTL_SEC)
    key = (str(current_app.config["DATABASE_FILE"]), bucket)
    cached = _battery_cache.get(key)
    if cached is not None and now - cached[0] < _BATTERY_CACHE_TTL_SEC:
        return cached[1]

    conn = get_db_connection()
    try:
        rows = conn.execute(_BATTERY_MAP_SQL).fetchall()
    finally:
        conn.close()

    result: dict[int, float] = {row["node_id"]: row["battery_level"] for row in rows}

    # Bound the cache: keep the current bucket and the previous one.
    stale = [
        entry_key
        for entry_key, (seen, _) in _battery_cache.items()
        if now - seen > 2 * _BATTERY_CACHE_TTL_SEC
    ]
    for entry_key in stale:
        _battery_cache.pop(entry_key, None)
    _battery_cache[key] = (now, result)
    return result


def _nodes_joins(*, need_agg: bool = True, need_signal: bool = True) -> str:
    """Join fragment for the node listing.

    ``need_agg``/``need_signal`` control the 24h count/max and the direct
    signal average; the COUNT statement and the battery stub omit the joins
    they don't use. Batteries come from the cached battery map, not a join.
    """
    joins = ""
    if need_agg:
        joins += _NODE_AGG_JOIN
    if need_signal:
        joins += _NODE_SIGNAL_JOIN
    return joins


def _nodes_join_params(need_agg: bool = True, need_signal: bool = True) -> list[int]:
    """Window parameters for the joins produced by :func:`_nodes_joins`."""
    window = _node_hour_window()
    params: list[int] = []
    if need_agg:
        params.append(window)
    if need_signal:
        params.append(window)
    return params


def _count_nodes(where_sql: str, params: list[Any], needs: dict[str, bool]) -> int:
    """Exact node count, joining only what the active filters reference."""
    joins = ""
    join_params: list[int] = []
    if needs["agg"]:
        joins += _NODE_AGG_JOIN
        join_params.append(_node_hour_window())
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM node_info ni {joins} {where_sql}",
            [*join_params, *params],
        )
        return cursor.fetchone()["total"]
    finally:
        conn.close()


def _query_nodes_page(
    where_sql: str,
    params: list[Any],
    needs: dict[str, bool],
    order_expr: str,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    order_dir = "DESC" if descending else "ASC"
    joins = _nodes_joins()
    sql = (
        f"{_NODE_SELECT.format(battery_select='', has_position_expr=_NODE_POSITION_EXPR)} {joins} "
        f"{where_sql} ORDER BY {order_expr} {order_dir}, ni.node_id ASC"
    )
    full_params = [*_nodes_join_params(), *params]
    total = _count_nodes(where_sql, params, needs)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            sql + " LIMIT ? OFFSET ?",
            [*full_params, page_size, (page - 1) * page_size],
        )
        return [_node_row(row) for row in cursor.fetchall()], total
    finally:
        conn.close()


def _query_nodes_by_battery(
    where_sql: str,
    params: list[Any],
    needs: dict[str, bool],
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Battery sort: order by the cached battery map, then hydrate the page.

    The ordering pass needs only ids and last_seen (the cheap aggregate join);
    batteries come from the TTL-cached map, and the page rows are hydrated with
    the full join set like every other sort.
    """
    stub_sql = (
        "SELECT ni.node_id,"
        " COALESCE(agg.last_packet_time, ni.last_updated) AS last_seen"
        f" FROM node_info ni {_nodes_joins(need_signal=False)}"
        f" {where_sql}"
    )
    full_params = [*_nodes_join_params(need_signal=False), *params]
    battery_map = _battery_map()
    total = _count_nodes(where_sql, params, needs)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(stub_sql, full_params)
        stubs: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            node_id = row["node_id"]
            stubs.append(
                {
                    "node_id": node_id,
                    "last_seen": row["last_seen"],
                    "battery": battery_map.get(node_id),
                }
            )

        def battery_key(stub: dict[str, Any]) -> tuple[int, float, float]:
            battery = stub["battery"]
            absent_last = -(stub["last_seen"] or 0)
            if battery is None:
                return (1, 0.0, absent_last)
            return (0, battery if not descending else -battery, absent_last)

        stubs.sort(key=battery_key)
        page_stubs = stubs[(page - 1) * page_size : page * page_size]
        if not page_stubs:
            return [], total

        placeholders = ",".join("?" * len(page_stubs))
        hydrate_sql = (
            f"{_NODE_SELECT.format(battery_select='', has_position_expr=_NODE_POSITION_EXPR)}"
            f" {_nodes_joins()}"
            f" WHERE ni.node_id IN ({placeholders})"
        )
        cursor.execute(
            hydrate_sql,
            [*_nodes_join_params(), *(stub["node_id"] for stub in page_stubs)],
        )
        by_id = {row["node_id"]: row for row in cursor.fetchall()}
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for stub in page_stubs:
        row = by_id.get(stub["node_id"])
        if row is not None:
            results.append(_node_row(row, battery_level=stub["battery"]))
    return results, total


# ---------------------------------------------------------------------------
# Node-scoped packet listing
#
# The packet repositories AND from/to filters together; "packets relevant to
# a node" needs from OR to, so this endpoint runs one lean dedicated query.
# ---------------------------------------------------------------------------

_NODE_PACKETS_SELECT = """
    SELECT
        id, timestamp, from_node_id, to_node_id, portnum, portnum_name,
        gateway_id, channel_id, mesh_packet_id, rssi, snr, hop_limit, hop_start,
        payload_length, processed_successfully, raw_payload, relay_node, via_mqtt,
        want_ack, pki_encrypted,
        (hop_start - hop_limit) AS hop_count
    FROM packet_history
"""


def _query_node_packets(
    node_id: int,
    direction: str,
    extra_where: str,
    extra_params: list[Any],
    order_column: str,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    if direction == "sent":
        scope = "from_node_id = ?"
        params: list[Any] = [node_id]
    elif direction == "received":
        scope = "to_node_id = ?"
        params = [node_id]
    else:
        scope = "(from_node_id = ? OR to_node_id = ?)"
        params = [node_id, node_id]

    where_parts = [scope]
    if extra_where:
        where_parts.append(extra_where)
        params.extend(extra_params)
    where_sql = "WHERE " + " AND ".join(where_parts)
    order_dir = "DESC" if descending else "ASC"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM packet_history {where_sql}", params)
        total = cursor.fetchone()[0]
        cursor.execute(
            f"{_NODE_PACKETS_SELECT} {where_sql}"
            f" ORDER BY {order_column} {order_dir}, id {order_dir} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return [_packet_public(dict(row)) for row in cursor.fetchall()], total
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cache headers
# ---------------------------------------------------------------------------


@api_v1_bp.after_request
def _cache_headers(response: Response) -> Response:
    """Conservative caching for append-only history listings."""
    if request.method == "GET" and request.path.endswith(CACHEABLE_SUFFIXES):
        response.headers["Cache-Control"] = CACHE_HEADER
    return response


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@api_v1_bp.route("/nodes")
def nodes_list() -> Response:
    """List nodes with filters, sorting and pagination."""
    page, page_size = _pagination_params()
    descending = _parse_enum("order", ("asc", "desc"), "desc") == "desc"
    sort = _parse_enum("sort", NODE_SORTS, "last_seen")
    where_sql, params, needs = _node_filters()

    if sort == "battery":
        nodes, total = _query_nodes_by_battery(
            where_sql, params, needs, descending, page, page_size
        )
    else:
        nodes, total = _query_nodes_page(
            where_sql,
            params,
            needs,
            _NODE_ORDER_EXPRS[sort],
            descending,
            page,
            page_size,
        )

    query: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "order": "desc" if descending else "asc",
    }
    for name in ("q", "role", "channel"):
        value = (request.args.get(name) or "").strip()
        if value:
            query[name] = value
    has_position = _parse_bool("has_position")
    if has_position is not None:
        query["has_position"] = has_position
    last_seen_since = _parse_timestamp("last_seen_since")
    if last_seen_since is not None:
        query["last_seen_since"] = _iso(last_seen_since)

    return _ok(nodes, _pagination_meta(total, page, page_size, query))


@api_v1_bp.route("/nodes/<node_id>")
def node_detail(node_id: str) -> Response:
    """Node detail: identity, traceroute stats, recent locations, neighbors.

    ``node_id`` accepts ``!xxxxxxxx`` (canonical), ``0x...``, bare hex and
    decimal forms; responses always carry the canonical ``!xxxxxxxx`` hex in
    ``hex_id``.
    """
    node_id_int = _parse_node_id(node_id)
    details = NodeService.get_node_info(node_id_int)
    node = details.get("node")
    if isinstance(node, dict):
        _iso_fields(node, "first_seen", "last_updated", "last_seen")
        if "gateway_count_24h" not in node or "packet_count_24h" not in node:
            # Same source and semantics as the legacy /api/node/<id>/info
            # endpoint: packets from the node and distinct gateways that heard
            # it, both over the trailing 24h.
            basic = NodeRepository.get_basic_node_info(node_id_int)
            node.setdefault(
                "gateway_count_24h",
                int(basic["gateway_count_24h"]) if basic else 0,
            )
            node.setdefault(
                "packet_count_24h",
                int(basic["packet_count_24h"]) if basic else 0,
            )
    return _ok(details, {"query": {"node_id": f"!{node_id_int:08x}"}})


@api_v1_bp.route("/nodes/<node_id>/locations")
def node_locations(node_id: str) -> Response:
    """Bounded position history for a node (newest first)."""
    node_id_int = _parse_node_id(node_id)
    _require_node(node_id_int)

    limit_raw = _parse_int("limit", 10)
    limit = 10 if limit_raw is None else limit_raw
    if not 1 <= limit <= LOCATION_HISTORY_MAX:
        raise APIError(
            "invalid_parameter",
            f"limit must be between 1 and {LOCATION_HISTORY_MAX}",
            limit=limit,
        )

    result = NodeService.get_node_location_history(node_id_int, limit=limit)
    history = []
    for row in result.get("location_history", []):
        if isinstance(row, dict):
            row.pop("timestamp_str", None)
            _iso_fields(row, "timestamp")
        history.append(row)

    data = {
        "node_id": node_id_int,
        "hex_id": f"!{node_id_int:08x}",
        "locations": history,
    }
    return _ok(data, {"query": {"node_id": f"!{node_id_int:08x}", "limit": limit}})


@api_v1_bp.route("/nodes/<node_id>/telemetry")
def node_telemetry(node_id: str) -> Response:
    """Telemetry time series for a node.

    ``since``/``until`` bound the window (epoch seconds or ISO-8601);
    ``metric`` is a comma-separated list of series names.
    """
    node_id_int = _parse_node_id(node_id)
    _require_node(node_id_int)

    since = _parse_timestamp("since")
    until = _parse_timestamp("until")
    now = time.time()
    window_start: float | None
    window_end: float | None
    if since is not None and until is not None:
        if until <= since:
            raise APIError(
                "invalid_parameter",
                "until must be greater than since",
                since=since,
                until=until,
            )
        window_start, window_end = since, until
        result = NodeService.get_node_telemetry_history(
            node_id_int, start=since, end=until
        )
    elif since is not None:
        window_start, window_end = since, now
        result = NodeService.get_node_telemetry_history(
            node_id_int, start=since, end=now
        )
    elif until is not None:
        window_start, window_end = 0.0, until
        result = NodeService.get_node_telemetry_history(
            node_id_int, start=0.0, end=until
        )
    else:
        range_key = _parse_enum("range", tuple(NodeService.TELEMETRY_RANGES), "7d")
        window_start = (
            now - NodeService.TELEMETRY_RANGES[range_key]
            if NodeService.TELEMETRY_RANGES[range_key]
            else None
        )
        window_end = now
        result = NodeService.get_node_telemetry_history(
            node_id_int, range_key=range_key
        )

    series: dict[str, Any] = dict(result.get("series", {}))
    metric_param = (request.args.get("metric") or "").strip()
    requested_metrics: list[str] | None = None
    if metric_param:
        requested_metrics = [m.strip() for m in metric_param.split(",") if m.strip()]
        unknown = [m for m in requested_metrics if m not in TELEMETRY_METRIC_NAMES]
        if unknown:
            raise APIError(
                "invalid_metric",
                "unknown metric; allowed: " + ", ".join(TELEMETRY_METRIC_NAMES),
                metrics=unknown,
            )
        series = {
            name: entry for name, entry in series.items() if name in requested_metrics
        }

    data = {
        "node_id": node_id_int,
        "hex_id": f"!{node_id_int:08x}",
        "window": {"start": _iso(window_start), "end": _iso(window_end)},
        "series": series,
        "count": result.get("count", 0),
        "decimated": result.get("decimated", False),
        "latest": _iso(result.get("latest")),
    }
    query: dict[str, Any] = {"node_id": f"!{node_id_int:08x}"}
    if requested_metrics is not None:
        query["metric"] = requested_metrics
    if since is not None:
        query["since"] = _iso(since)
    if until is not None:
        query["until"] = _iso(until)
    return _ok(data, {"query": query})


@api_v1_bp.route("/nodes/<node_id>/packets")
def node_packets(node_id: str) -> Response:
    """Packets sent by or addressed to a node (direction selectable)."""
    node_id_int = _parse_node_id(node_id)
    _require_node(node_id_int)
    page, page_size = _pagination_params()
    direction = _parse_enum("direction", ("all", "sent", "received"), "all")
    descending = _parse_enum("order", ("asc", "desc"), "desc") == "desc"
    sort_key = _parse_enum("sort", tuple(PACKET_SORTS), "timestamp")

    conditions: list[str] = []
    params: list[Any] = []

    portnum = (request.args.get("portnum") or "").strip()
    if portnum:
        conditions.append("portnum_name = ?")
        params.append(portnum)

    gateway_id = _gateway_id_param()
    if gateway_id is not None:
        conditions.append("gateway_id = ?")
        params.append(gateway_id)

    primary_channel = (request.args.get("primary_channel") or "").strip()
    if primary_channel:
        conditions.append("channel_id = ?")
        params.append(primary_channel)

    min_rssi = _parse_int("min_rssi")
    if min_rssi is not None:
        conditions.append("rssi >= ?")
        params.append(min_rssi)
    max_rssi = _parse_int("max_rssi")
    if max_rssi is not None:
        conditions.append("rssi <= ?")
        params.append(max_rssi)
    hop_count = _parse_int("hop_count")
    if hop_count is not None:
        conditions.append("(hop_start - hop_limit) = ?")
        params.append(hop_count)

    since = _parse_timestamp("since")
    if since is not None:
        conditions.append("timestamp >= ?")
        params.append(since)
    until = _parse_timestamp("until")
    if until is not None:
        conditions.append("timestamp <= ?")
        params.append(until)

    search = (request.args.get("q") or "").strip()
    if search:
        conditions.append(
            "(portnum_name LIKE ? OR gateway_id LIKE ? OR channel_id LIKE ?"
            " OR CAST(from_node_id AS TEXT) LIKE ?"
            " OR CAST(to_node_id AS TEXT) LIKE ?)"
        )
        params.extend([f"%{search}%"] * 5)

    rows, total = _query_node_packets(
        node_id_int,
        direction,
        " AND ".join(conditions),
        params,
        PACKET_SORTS[sort_key],
        descending,
        page,
        page_size,
    )
    _attach_packet_names(rows)
    packets = rows

    query: dict[str, Any] = {
        "node_id": f"!{node_id_int:08x}",
        "page": page,
        "page_size": page_size,
        "direction": direction,
        "sort": sort_key,
        "order": "desc" if descending else "asc",
    }
    for name in ("portnum", "primary_channel"):
        value = (request.args.get(name) or "").strip()
        if value:
            query[name] = value
    if gateway_id is not None:
        query["gateway_id"] = gateway_id
    for name in ("min_rssi", "max_rssi", "hop_count"):
        value = _parse_int(name)
        if value is not None:
            query[name] = value
    if since is not None:
        query["since"] = _iso(since)
    if until is not None:
        query["until"] = _iso(until)
    if search:
        query["q"] = search

    return _ok(packets, _pagination_meta(total, page, page_size, query))


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------


def _packet_filters() -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    """Build repository filters from the shared packet filter parameters.

    Returns ``(filters, search, query_echo)``. Mirrors the packets page filter
    set: from/to/gateway, portnum, RSSI bounds, hop count, channel, exclusions,
    time window; plus free-text ``q``.
    """
    filters: dict[str, Any] = {}
    query: dict[str, Any] = {}

    from_node = _node_id_param("from_node")
    if from_node is not None:
        filters["from_node"] = from_node
        query["from_node"] = f"!{from_node:08x}"

    to_node = _node_id_param("to_node")
    if to_node is not None:
        filters["to_node"] = to_node
        query["to_node"] = f"!{to_node:08x}"

    gateway_id = _gateway_id_param()
    if gateway_id is not None:
        filters["gateway_id"] = gateway_id
        query["gateway_id"] = gateway_id

    portnum = (request.args.get("portnum") or "").strip()
    if portnum:
        filters["portnum"] = portnum
        query["portnum"] = portnum

    primary_channel = (request.args.get("primary_channel") or "").strip()
    if primary_channel:
        filters["primary_channel"] = primary_channel
        query["primary_channel"] = primary_channel

    min_rssi = _parse_int("min_rssi")
    if min_rssi is not None:
        filters["min_rssi"] = min_rssi
        query["min_rssi"] = min_rssi
    max_rssi = _parse_int("max_rssi")
    if max_rssi is not None:
        filters["max_rssi"] = max_rssi
        query["max_rssi"] = max_rssi
    hop_count = _parse_int("hop_count")
    if hop_count is not None:
        filters["hop_count"] = hop_count
        query["hop_count"] = hop_count

    exclude_from = _node_id_param("exclude_from")
    if exclude_from is not None:
        filters["exclude_from"] = exclude_from
        query["exclude_from"] = f"!{exclude_from:08x}"
    exclude_to = _node_id_param("exclude_to")
    if exclude_to is not None:
        filters["exclude_to"] = exclude_to
        query["exclude_to"] = f"!{exclude_to:08x}"

    if _parse_bool("exclude_self") and "gateway_id" in filters:
        try:
            gateway_node = _parse_node_id(filters["gateway_id"])
        except APIError:
            gateway_node = None
        if gateway_node is not None:
            filters["exclude_from"] = gateway_node
            query["exclude_self"] = True

    since = _parse_timestamp("since")
    if since is not None:
        filters["start_time"] = since
        query["since"] = _iso(since)
    until = _parse_timestamp("until")
    if until is not None:
        filters["end_time"] = until
        query["until"] = _iso(until)

    search = (request.args.get("q") or "").strip() or None
    if search:
        query["q"] = search

    return filters, search, query


@api_v1_bp.route("/packets")
def packets_list() -> Response:
    """Packet history with the full packets-page filter set plus ``q``.

    Uses the optimized packet repository; the plain repository is only
    engaged for ``primary_channel``, which the optimized path does not
    filter on, and for ``group_by`` grouping. Without ``group_by`` rows are
    ungrouped; ``group_by=mesh_packet_id`` collapses receptions onto the
    earliest one (the legacy grouped rule) and counts groups in the
    pagination meta.
    """
    page, page_size = _pagination_params()
    descending = _parse_enum("order", ("asc", "desc"), "desc") == "desc"
    sort_key = _parse_enum("sort", tuple(PACKET_SORTS), "timestamp")
    group_by = _group_by_param()

    filters, search, query = _packet_filters()
    if group_by:
        result = PacketRepository.get_packets_grouped(
            limit=page_size,
            offset=(page - 1) * page_size,
            filters=filters,
            order_by=PACKET_SORTS[sort_key],
            order_dir="desc" if descending else "asc",
            search=search,
        )
    else:
        repository = (
            PacketRepository
            if "primary_channel" in filters
            else PacketRepositoryOptimized
        )
        result = repository.get_packets(
            limit=page_size,
            offset=(page - 1) * page_size,
            filters=filters,
            order_by=PACKET_SORTS[sort_key],
            order_dir="desc" if descending else "asc",
            search=search,
        )

    raw_packets = list(result.get("packets", []))
    _attach_packet_names(raw_packets)
    _resolve_group_gateways(raw_packets)
    packets = [_packet_public(packet) for packet in raw_packets]
    total = int(result.get("total_count") or 0)
    if group_by:
        query["group_by"] = group_by
    query.update(
        {
            "page": page,
            "page_size": page_size,
            "sort": sort_key,
            "order": "desc" if descending else "asc",
        }
    )
    return _ok(packets, _pagination_meta(total, page, page_size, query))


@api_v1_bp.route("/packets/<int:packet_id>")
def packet_detail(packet_id: int) -> Response:
    """Full detail for one packet, including receptions and relay candidates."""
    details = get_packet_details(packet_id)
    if details is None:
        raise APIError("packet_not_found", f"Packet {packet_id} not found", 404)

    # The legacy helper embeds the live TraceroutePacket model instance next to
    # its own derived fields (route_nodes, display paths, has_return_path, …).
    # Drop the redundant object; _sanitize also hardens against any leak.
    payload_info = details.get("payload_info")
    if isinstance(payload_info, dict):
        payload_data = payload_info.get("data")
        if isinstance(payload_data, dict):
            payload_data.pop("traceroute_packet", None)

    for section in ("packet", "other_receptions", "context_packets"):
        rows = details.get(section)
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                row.pop("timestamp_str", None)
                _iso_fields(row, "timestamp")
    return _ok(details, {"query": {"packet_id": packet_id}})


# ---------------------------------------------------------------------------
# Traceroutes
# ---------------------------------------------------------------------------


def _enhance_traceroute(row: dict[str, Any]) -> dict[str, Any]:
    """Apply the same enrichment TracerouteService adds to list results."""
    packet = TraceroutePacket(packet_data=row, resolve_names=True)
    enhanced = dict(row)
    enhanced.pop("timestamp_str", None)
    _iso_fields(enhanced, "timestamp")
    enhanced.update(
        {
            "has_return_path": packet.has_return_path(),
            "is_complete": packet.is_complete(),
            "display_path": packet.format_path_display("display"),
            "total_hops": packet.forward_path.total_hops,
            "rf_hops": len(packet.get_rf_hops()),
        }
    )
    return enhanced


def _normalize_traceroutes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        traceroute = dict(row)
        traceroute.pop("timestamp_str", None)
        _iso_fields(traceroute, "timestamp")
        normalized.append(traceroute)
    return normalized


@api_v1_bp.route("/traceroutes")
def traceroutes_list() -> Response:
    """Traceroute packets with time, endpoint and gateway filters.

    ``group_by=mesh_packet_id`` collapses receptions onto the most recent
    one (the legacy grouped rule) and counts groups in the pagination meta.
    """
    page, page_size = _pagination_params()

    since = _parse_timestamp("since")
    until = _parse_timestamp("until")
    sort_key = _parse_enum("sort", tuple(TRACEROUTE_SORTS), "timestamp")
    descending = _parse_enum("order", ("asc", "desc"), "desc") == "desc"
    from_node = _node_id_param("from")
    to_node = _node_id_param("to")
    gateway_raw = (request.args.get("gateway") or "").strip()
    gateway_id = _normalize_gateway_id(gateway_raw) if gateway_raw else None
    search = (request.args.get("q") or "").strip() or None

    group_by = _group_by_param()
    use_repository = (
        group_by is not None
        or since is not None
        or until is not None
        or sort_key != "timestamp"
        or not descending
    )
    if use_repository:
        # TracerouteService exposes neither a time upper bound nor grouping;
        # use the repository directly and apply the same model-level
        # enrichment the service uses.
        filters: dict[str, Any] = {}
        if since is not None:
            filters["start_time"] = since
        if until is not None:
            filters["end_time"] = until
        if from_node is not None:
            filters["from_node"] = from_node
        if to_node is not None:
            filters["to_node"] = to_node
        if gateway_id:
            filters["gateway_id"] = gateway_id
        if group_by:
            result = TracerouteRepository.get_traceroutes_grouped(
                limit=page_size,
                offset=(page - 1) * page_size,
                filters=filters,
                search=search,
                order_by=TRACEROUTE_SORTS[sort_key],
                order_dir="desc" if descending else "asc",
            )
        else:
            result = TracerouteRepository.get_traceroute_packets(
                limit=page_size,
                offset=(page - 1) * page_size,
                filters=filters,
                search=search,
                order_by=TRACEROUTE_SORTS[sort_key],
                order_dir="desc" if descending else "asc",
            )
        rows = [_enhance_traceroute(row) for row in result.get("packets", [])]
        total = int(result.get("total_count") or 0)
    else:
        result = TracerouteService.get_traceroutes(
            page=page,
            per_page=page_size,
            gateway_id=gateway_id,
            from_node=from_node,
            to_node=to_node,
            search=search,
        )
        rows = _normalize_traceroutes(result.get("traceroutes", []))
        total = int(result.get("total_count") or 0)

    _attach_traceroute_names(rows)
    _resolve_group_gateways(rows)

    query: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
        "sort": sort_key,
        "order": "desc" if descending else "asc",
    }
    if group_by:
        query["group_by"] = group_by
    if since is not None:
        query["since"] = _iso(since)
    if until is not None:
        query["until"] = _iso(until)
    if from_node is not None:
        query["from"] = f"!{from_node:08x}"
    if to_node is not None:
        query["to"] = f"!{to_node:08x}"
    if gateway_id:
        query["gateway"] = gateway_id
    if search:
        query["q"] = search
    return _ok(rows, _pagination_meta(total, page, page_size, query))


@api_v1_bp.route("/traceroutes/<int:packet_id>")
def traceroute_detail(packet_id: int) -> Response:
    """One traceroute packet with parsed path summary."""
    row = TracerouteRepository.get_traceroute_details(packet_id)
    if row is None:
        raise APIError(
            "traceroute_not_found", f"Traceroute packet {packet_id} not found", 404
        )
    data = _enhance_traceroute(row)
    _attach_traceroute_names([data])
    return _ok(data, {"query": {"packet_id": packet_id}})


# ---------------------------------------------------------------------------
# Gateways
# ---------------------------------------------------------------------------


def _gateway_hours() -> int:
    hours = _parse_int("hours", 24) or 24
    if not 1 <= hours <= 168:
        raise APIError(
            "invalid_parameter", "hours must be between 1 and 168", hours=hours
        )
    return hours


def _gateway_statistics_map(hours: int) -> dict[str, dict[str, Any]]:
    try:
        stats = GatewayService.get_gateway_statistics(hours=hours)
    except Exception as exc:  # pragma: no cover - stats are supplementary
        logger.warning("Gateway statistics unavailable: %s", exc)
        return {}
    return {row["gateway_id"]: row for row in stats.get("gateway_distribution", [])}


@api_v1_bp.route("/gateways")
def gateways_list() -> Response:
    """Known gateways with optional statistics and name/id search."""
    page, page_size = _pagination_params()
    hours = _gateway_hours()

    distribution = _gateway_statistics_map(hours)
    gateways: list[dict[str, Any]] = []
    for gateway in GatewayService.get_available_gateways():
        gateway_id = gateway["id"]
        entry = distribution.get(gateway_id)
        gateways.append(
            {
                "gateway_id": gateway_id,
                "display_name": gateway.get("display_name"),
                "packet_count": entry["packet_count"] if entry else None,
                "unique_sources": entry["unique_sources"] if entry else None,
                "avg_rssi": entry["avg_rssi"] if entry else None,
                "avg_snr": entry["avg_snr"] if entry else None,
                "last_seen": _iso(entry["last_seen"]) if entry else None,
            }
        )

    search = (request.args.get("q") or "").strip().casefold()
    if search:
        gateways = [
            gateway
            for gateway in gateways
            if search in (gateway["gateway_id"] or "").casefold()
            or search in (gateway["display_name"] or "").casefold()
        ]

    total = len(gateways)
    page_rows = gateways[(page - 1) * page_size : page * page_size]
    query: dict[str, Any] = {"page": page, "page_size": page_size, "hours": hours}
    if search:
        query["q"] = request.args["q"].strip()
    return _ok(page_rows, _pagination_meta(total, page, page_size, query))


@api_v1_bp.route("/gateways/<gateway_id>")
def gateway_detail(gateway_id: str) -> Response:
    """Statistics and recent traffic for one gateway.

    Hex node-style ids in any format are normalized to the stored
    ``!xxxxxxxx`` form; opaque gateway identifiers are matched verbatim.
    """
    hours = _gateway_hours()
    canonical = _normalize_gateway_id(gateway_id)
    available = {gw["id"]: gw for gw in GatewayService.get_available_gateways()}
    gateway = available.get(canonical) or available.get(gateway_id)
    if gateway is None:
        raise APIError("gateway_not_found", f"Gateway {gateway_id} not found", 404)

    entry = _gateway_statistics_map(hours).get(canonical)
    statistics = None
    if entry:
        statistics = {
            "hours": hours,
            "packet_count": entry["packet_count"],
            "unique_sources": entry["unique_sources"],
            "avg_rssi": entry["avg_rssi"],
            "avg_snr": entry["avg_snr"],
            "last_seen": _iso(entry["last_seen"]),
        }

    try:
        recent = PacketRepositoryOptimized.get_packets(
            limit=10, offset=0, filters={"gateway_id": canonical}
        )
        recent_packets = [
            _packet_public(packet) for packet in recent.get("packets", [])
        ]
    except Exception as exc:  # pragma: no cover - recent traffic is supplementary
        logger.warning("Recent packets unavailable for %s: %s", canonical, exc)
        recent_packets = []

    data = {
        "gateway_id": canonical,
        "display_name": gateway.get("display_name"),
        "statistics": statistics,
        "recent_packets": recent_packets,
    }
    return _ok(data, {"query": {"gateway_id": canonical, "hours": hours}})


# ---------------------------------------------------------------------------
# Legacy-parity analysis endpoints
#
# These mirror internal /api endpoints whose logic (SQL analysis, composite
# payload assembly, parameter clamps) lives in the legacy handlers. Rather
# than duplicating that logic, the view functions are invoked in-process with
# the same request (identical query string / path args); payloads are wrapped
# verbatim in the v1 envelope so page migrations stay mechanical.
# ---------------------------------------------------------------------------


def _legacy_payload(view, *args, **kwargs):
    """Run a legacy /api view in this request and return its JSON payload."""
    response = view(*args, **kwargs)
    status = 200
    if isinstance(response, tuple):
        response, status = response[0], response[1]
    payload = response.get_json(silent=True)
    if status != 200:
        message = payload.get("error") if isinstance(payload, dict) else None
        code = {
            400: "invalid_parameter",
            404: "not_found",
            405: "method_not_allowed",
        }.get(status, "internal_error")
        raise APIError(
            code, str(message or f"legacy endpoint failed ({status})"), status
        )
    return payload


def _query_echo():
    """Raw echo of the request's query parameters (values are strings)."""
    return dict(request.args)


@api_v1_bp.route("/chat/messages")
def chat_messages():
    """Chat rows for the message stream (mirrors /api/chat/messages)."""
    data = _legacy_payload(_legacy_api.api_chat_messages)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/chat/relay-filters")
def chat_relay_filters():
    """Relay candidates for chat gateway/last-byte pairs."""
    data = _legacy_payload(_legacy_api.api_chat_relay_filters)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/longest-links")
def longest_links():
    """Longest RF links analysis (mirrors /api/longest-links)."""
    data = _legacy_payload(_legacy_api.api_longest_links)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/traceroute-graph")
def traceroute_graph():
    """Traceroute network graph (mirrors /api/traceroute/graph)."""
    data = _legacy_payload(_legacy_api.api_traceroute_graph)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/traceroute-hops/nodes")
def traceroute_hops_nodes():
    """Nodes seen in traceroutes, with names (for hop-analysis selects)."""
    data = _legacy_payload(_legacy_api.api_traceroute_hops_nodes)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/traceroute-link/<node1_id>/<node2_id>")
def traceroute_link(node1_id: str, node2_id: str):
    """Per-link hop analysis between two nodes."""
    data = _legacy_payload(_legacy_api.api_traceroute_link, node1_id, node2_id)
    return _ok(data, {"query": {"node1": node1_id, "node2": node2_id}})


@api_v1_bp.route("/related-nodes/<node_id>")
def related_nodes(node_id: str):
    """Nodes with traceroute connections to the given node."""
    node_id_int = _parse_node_id(node_id)
    data = NodeService.get_traceroute_related_nodes(node_id_int)
    return _ok(data, {"query": {"node_id": f"!{node_id_int:08x}"}})


@api_v1_bp.route("/nodes/<node_id>/direct-receptions")
def node_direct_receptions(node_id: str):
    """Bidirectional 0-hop direct receptions for a node."""
    data = _legacy_payload(_legacy_api.api_node_direct_receptions, node_id)
    return _ok(data, {"query": _query_echo()})


@api_v1_bp.route("/nodes/<node_id>/relay-node-analysis")
def node_relay_node_analysis(node_id: str):
    """Relay-node statistics for a gateway's reported packets."""
    data = _legacy_payload(_legacy_api.api_node_relay_node_analysis, node_id)
    return _ok(data, {"query": _query_echo()})


# ---------------------------------------------------------------------------
# Stats & meta
# ---------------------------------------------------------------------------


@api_v1_bp.route("/stats/summary")
def stats_summary() -> Response:
    """Dashboard-level summary for the requested window.

    Activity buckets use the local-day timezone logic from
    ``AnalyticsService.get_activity_timeline``; ``tz_offset`` is the viewer's
    minutes east of UTC (clamped to the real-world UTC-12..UTC+14 range).
    """
    range_key = _parse_enum("range", STATS_RANGES, "24h")
    tz_offset = _parse_int("tz_offset", 0) or 0
    tz_offset = max(-720, min(840, tz_offset))

    dashboard = DashboardRepository.get_stats()
    analytics = AnalyticsService.get_analytics_data()
    timeline = AnalyticsService.get_activity_timeline(
        range_key=range_key, tz_offset_minutes=tz_offset
    )

    for node in analytics.get("top_nodes", []):
        if isinstance(node, dict):
            _iso_fields(node, "last_seen")

    data = {
        "range": range_key,
        "totals": {
            key: dashboard[key]
            for key in (
                "total_nodes",
                "active_nodes_24h",
                "nodes_seen_7d",
                "total_packets",
                "recent_packets",
                "success_rate",
            )
        },
        "activity": {
            "granularity": timeline.get("granularity"),
            "buckets": timeline.get("buckets", []),
            "pending": timeline.get("pending", False),
        },
        "top_nodes": analytics.get("top_nodes", []),
        "signal_quality": analytics.get("signal_quality", {}),
        "transport_types": analytics.get("packet_types", []),
    }
    return _ok(data, {"query": {"range": range_key, "tz_offset": tz_offset}})


@api_v1_bp.route("/locations")
def locations_list() -> Response:
    """Bulk latest position per node (mirrors the legacy /api/locations rows).

    Defaults to the legacy 14-day window; ``since``/``until`` override it.
    Rows keep the legacy field names, with ``timestamp`` normalized to
    ISO-8601 UTC (``timestamp_str`` dropped) per the v1 timestamp convention.
    """
    page_raw = request.args.get("page")
    page = PAGE_DEFAULT
    if page_raw is not None:
        try:
            page = int(page_raw)
        except ValueError as exc:
            raise APIError(
                "invalid_page", "page must be an integer", page=page_raw
            ) from exc
        if page < 1:
            raise APIError("invalid_page", "page must be >= 1", page=page)

    size_raw = request.args.get("page_size")
    page_size = LOCATIONS_PAGE_SIZE_DEFAULT
    if size_raw is not None:
        try:
            page_size = int(size_raw)
        except ValueError as exc:
            raise APIError(
                "invalid_page_size", "page_size must be an integer", page_size=size_raw
            ) from exc
        if not 1 <= page_size <= LOCATIONS_PAGE_SIZE_MAX:
            raise APIError(
                "invalid_page_size",
                f"page_size must be between 1 and {LOCATIONS_PAGE_SIZE_MAX}",
                page_size=page_size,
            )

    now = time.time()
    since = _parse_timestamp("since")
    until = _parse_timestamp("until")
    if since is None:
        since = now - LOCATIONS_DEFAULT_WINDOW_DAYS * 86400
    if until is None:
        until = now
    if until <= since:
        raise APIError(
            "invalid_parameter",
            "until must be greater than since",
            since=_iso(since),
            until=_iso(until),
        )

    gateway_id = _node_id_param("gateway_id")
    filters: dict[str, Any] = {"start_time": since, "end_time": until}
    if gateway_id is not None:
        filters["gateway_id"] = gateway_id

    include_links = bool(_parse_bool("include_links", False))
    enrich = _parse_bool("enrich", True)
    if enrich is False:
        # Positions-only fast path: hand the service empty enrichment inputs so
        # it skips the per-request 24h network-graph build and link lookups
        # (neighbour-derived fields come back empty; positions are identical).
        locations = LocationService.get_node_locations(
            filters, network_data={"nodes": [], "links": []}, packet_links=[]
        )
    else:
        locations = LocationService.get_node_locations(filters)
    rows: list[dict[str, Any]] = []
    for row in locations:
        if isinstance(row, dict):
            row.pop("timestamp_str", None)
            _iso_fields(row, "timestamp")
        rows.append(row)

    total = len(rows)
    page_rows = rows[(page - 1) * page_size : page * page_size]
    query: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
        "since": _iso(since),
        "until": _iso(until),
    }
    if gateway_id is not None:
        query["gateway_id"] = f"!{gateway_id:08x}"
    if include_links:
        query["include_links"] = True
    if request.args.get("enrich") is not None:
        query["enrich"] = bool(enrich)

    meta = _pagination_meta(total, page, page_size, query)
    if not include_links:
        return _ok(page_rows, meta)

    # Opt-in link overlays: built with the exact helpers the legacy
    # /api/locations composite uses (same window-derived hours, same
    # limit_packets), so the arrays are identical to the legacy ones.
    network_filters: dict[str, Any] = {
        "start_time": since,
        "end_time": until,
    }
    if gateway_id is not None:
        network_filters["gateway_id"] = gateway_id
    try:
        network_data = TracerouteService.get_network_graph_data(
            hours=max(1, min(168, int((until - since) / 3600))),
            include_indirect=False,
            filters=network_filters,
            limit_packets=2000,
        )
    except Exception as exc:  # pragma: no cover - overlays are supplementary
        logger.warning("Network graph unavailable for /locations links: %s", exc)
        network_data = {"nodes": [], "links": []}

    packet_links = LocationService.get_packet_links(filters)
    traceroute_links = LocationService.get_traceroute_links(
        filters, network_data=network_data
    )

    body = {
        "data": _sanitize(page_rows),
        "meta": _sanitize(meta),
        "links": _sanitize(
            {"traceroute_links": traceroute_links, "packet_links": packet_links}
        ),
    }
    return jsonify(body)


@api_v1_bp.route("/meta/filters")
def meta_filters() -> Response:
    """Enumerations behind the UI filter dropdowns.

    Values and order come from the exact helpers behind the legacy
    ``/api/meshtastic/*`` endpoints, so dropdown contents are identical.
    """
    data = {
        "hardware_models": MeshtasticService.get_hardware_models(),
        "roles": MeshtasticService.get_node_roles(),
        "channels": NodeRepository.get_unique_primary_channels(),
        "packet_types": MeshtasticService.get_packet_types(),
        "packet_channels": NodeRepository.get_unique_packet_channels(),
    }
    return _ok(data)


@api_v1_bp.route("/meta")
def meta_info() -> Response:
    """Instance metadata for footers and healthchecks."""
    cfg = current_app.config.get("APP_CONFIG") or get_config()

    try:
        version = importlib.metadata.version("malla")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    node_count = NodeRepository.get_nodes(limit=1, order_by="node_id")["total_count"]

    database_file = str(cfg.database_file)
    try:
        db_size = os.path.getsize(database_file)
    except OSError:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            page_count = cursor.execute("PRAGMA page_count").fetchone()[0]
            page_size = cursor.execute("PRAGMA page_size").fetchone()[0]
            db_size = int(page_count) * int(page_size)
        finally:
            conn.close()

    data = {
        "name": cfg.name,
        "version": version,
        "api_version": API_V1_VERSION,
        "node_count": int(node_count),
        "database_size_bytes": int(db_size),
        "database_file": database_file,
        "server_time_utc": _iso(time.time()),
    }
    return _ok(data)


# ---------------------------------------------------------------------------
# OpenAPI 3.1 document
# ---------------------------------------------------------------------------

_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Machine-readable code."},
                "message": {"type": "string", "description": "Human-readable message."},
                "details": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional machine-readable context.",
                },
            },
            "required": ["code", "message"],
        }
    },
    "required": ["error"],
}

_PAGINATION_META_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1},
        "page_size": {"type": "integer", "minimum": 1},
        "total": {"type": "integer", "minimum": 0},
        "total_pages": {"type": "integer", "minimum": 0},
        "has_next": {"type": "boolean"},
        "has_prev": {"type": "boolean"},
    },
    "required": [
        "page",
        "page_size",
        "total",
        "total_pages",
        "has_next",
        "has_prev",
    ],
}

_META_SCHEMA = {
    "type": "object",
    "description": "Response envelope metadata.",
    "properties": {
        "pagination": {"$ref": "#/components/schemas/PaginationMeta"},
        "query": {
            "type": "object",
            "additionalProperties": True,
            "description": "Normalized echo of the effective query parameters.",
        },
    },
}

_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "integer", "description": "Numeric node id."},
        "hex_id": {
            "type": "string",
            "description": "Canonical 32-bit hex form, e.g. !433d0c24.",
        },
        "long_name": {"type": ["string", "null"]},
        "short_name": {"type": ["string", "null"]},
        "hw_model": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
        "primary_channel": {"type": ["string", "null"]},
        "last_seen": {
            "type": ["string", "null"],
            "format": "date-time",
            "description": "ISO-8601 UTC (Z suffix).",
        },
        "packet_count_24h": {
            "type": "integer",
            "description": "Packets sent by the node in the trailing 24h "
            "(node detail responses — same helper as the legacy "
            "/api/node/<id>/info endpoint — and node list rows).",
        },
        "gateway_count_24h": {
            "type": "integer",
            "description": "Distinct gateways that heard the node in the "
            "trailing 24h (node detail responses; list rows omit it).",
        },
        "avg_snr": {"type": ["number", "null"]},
        "battery_level": {
            "type": ["number", "null"],
            "description": "Latest decoded device-telemetry battery percentage.",
        },
        "has_position": {
            "type": ["boolean", "null"],
            "description": "Whether a decodable position packet exists.",
        },
    },
    "required": ["node_id", "hex_id"],
}

_PACKET_NAME_ENTRY_SCHEMA = {
    "type": ["object", "null"],
    "description": "Resolved node identity; null when the id is absent.",
    "properties": {
        "node_id": {"type": "integer"},
        "hex_id": {"type": "string", "description": "Canonical !xxxxxxxx form."},
        "display_name": {
            "type": ["string", "null"],
            "description": "Legacy display name (long name, else short/hex fallback).",
        },
        "short_name": {"type": ["string", "null"]},
    },
    "required": ["node_id", "hex_id"],
}

_GROUP_INFO_SCHEMA = {
    "type": "object",
    "description": "Server-side group aggregates; present only when "
    "group_by=mesh_packet_id is requested.",
    "properties": {
        "reception_count": {
            "type": "integer",
            "description": "Receptions of this mesh packet under the request filters.",
        },
        "gateways": {
            "type": "array",
            "description": "Distinct receiving gateways, first-seen order.",
            "items": {"$ref": "#/components/schemas/PacketNameEntry"},
        },
    },
    "required": ["reception_count", "gateways"],
}

_PACKET_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO-8601 UTC (Z suffix).",
        },
        "from_node_id": {"type": ["integer", "null"]},
        "to_node_id": {"type": ["integer", "null"]},
        "portnum": {"type": ["integer", "null"]},
        "portnum_name": {"type": ["string", "null"]},
        "gateway_id": {"type": ["string", "null"]},
        "channel_id": {"type": ["string", "null"]},
        "mesh_packet_id": {"type": ["integer", "null"]},
        "rssi": {"type": ["number", "null"]},
        "snr": {"type": ["number", "null"]},
        "hop_count": {"type": ["integer", "null"]},
        "payload_length": {"type": ["integer", "null"]},
        "success": {"type": ["integer", "boolean", "null"]},
        "text_content": {
            "type": ["string", "null"],
            "description": "Decoded TEXT_MESSAGE_APP preview (100 chars).",
        },
        "names": {
            "type": "object",
            "description": "Legacy-level node-name enrichment (display + short).",
            "properties": {
                "from": {"$ref": "#/components/schemas/PacketNameEntry"},
                "to": {"$ref": "#/components/schemas/PacketNameEntry"},
                "gateway": {"$ref": "#/components/schemas/PacketNameEntry"},
            },
        },
        "group": {"$ref": "#/components/schemas/GroupInfo"},
    },
    "required": ["id", "timestamp"],
}

_TRACEROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "timestamp": {"type": "string", "format": "date-time"},
        "from_node_id": {"type": ["integer", "null"]},
        "to_node_id": {"type": ["integer", "null"]},
        "gateway_id": {"type": ["string", "null"]},
        "has_return_path": {"type": "boolean"},
        "is_complete": {"type": "boolean"},
        "display_path": {"type": "string"},
        "total_hops": {"type": "integer"},
        "rf_hops": {"type": "integer"},
        "names": {
            "type": "object",
            "description": "Legacy-level name enrichment: endpoints, gateway "
            "(when node-like) and route members in wire order.",
            "properties": {
                "from": {"$ref": "#/components/schemas/PacketNameEntry"},
                "to": {"$ref": "#/components/schemas/PacketNameEntry"},
                "gateway": {"$ref": "#/components/schemas/PacketNameEntry"},
                "route": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/PacketNameEntry"},
                },
            },
        },
        "group": {"$ref": "#/components/schemas/GroupInfo"},
    },
    "required": ["id", "timestamp"],
}

_GATEWAY_SCHEMA = {
    "type": "object",
    "properties": {
        "gateway_id": {"type": "string"},
        "display_name": {"type": ["string", "null"]},
        "packet_count": {"type": ["integer", "null"]},
        "unique_sources": {"type": ["integer", "null"]},
        "avg_rssi": {"type": ["number", "null"]},
        "avg_snr": {"type": ["number", "null"]},
        "last_seen": {"type": ["string", "null"], "format": "date-time"},
    },
    "required": ["gateway_id"],
}

_NODE_ID_PATH_PARAM = {
    "name": "node_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": (
        "Node identifier. Canonical form is the 32-bit hex string used across "
        "Malla (!xxxxxxxx, e.g. !433d0c24); 0x-prefixed hex, bare hex "
        "(433d0c24) and decimal node numbers are accepted and normalized. "
        "Responses always carry the canonical form in hex_id."
    ),
}

_PAGE_PARAMS = [
    {
        "name": "page",
        "in": "query",
        "schema": {"type": "integer", "minimum": 1, "default": 1},
    },
    {
        "name": "page_size",
        "in": "query",
        "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
    },
]


def _envelope(data_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"data": data_schema, "meta": _META_SCHEMA},
        "required": ["data", "meta"],
    }


def _list_items(item_schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item_schema}


def _json_response(description: str, data_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _envelope(data_schema)}},
    }


def _error_response_schema(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    }


def _query_param(name: str, schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {"name": name, "in": "query", "schema": schema, "description": description}


def _build_openapi() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Malla Internal API",
            "version": API_V1_VERSION,
            "description": "Internal application API powering the Malla web "
            "UI; not a public or stable contract. Success responses use "
            "{data, meta} envelopes; errors use {error: {code, message}}. "
            "All timestamps are ISO-8601 UTC with Z suffix.",
        },
        "tags": [
            {"name": "nodes"},
            {"name": "packets"},
            {"name": "traceroutes"},
            {"name": "gateways"},
            {"name": "meta"},
        ],
        "paths": {
            "/api/v1/nodes": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "List nodes",
                    "description": "Filter, sort and paginate the known node "
                    "roster with per-node activity aggregates.",
                    "parameters": [
                        *_PAGE_PARAMS,
                        _query_param(
                            "q",
                            {"type": "string"},
                            "Case-insensitive substring on name or id.",
                        ),
                        _query_param("role", {"type": "string"}, "Exact role match."),
                        _query_param(
                            "channel",
                            {"type": "string"},
                            "Exact primary channel match.",
                        ),
                        _query_param(
                            "has_position",
                            {"type": "boolean"},
                            "Only nodes with (or without) position data.",
                        ),
                        _query_param(
                            "last_seen_since",
                            {"type": "string"},
                            "ISO-8601 or epoch; only nodes seen at/after.",
                        ),
                        _query_param(
                            "sort",
                            {"type": "string", "enum": list(NODE_SORTS)},
                            "Sort key (default last_seen).",
                        ),
                        _query_param(
                            "order",
                            {"type": "string", "enum": ["asc", "desc"]},
                            "Sort direction (default desc).",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Node page.",
                            _list_items({"$ref": "#/components/schemas/Node"}),
                        ),
                        "400": _error_response_schema("Invalid query parameter."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Node detail",
                    "description": "Identity, packet aggregates, traceroute "
                    "stats, recent locations and neighbors for one node.",
                    "parameters": [_NODE_ID_PATH_PARAM],
                    "responses": {
                        "200": _json_response("Node detail.", {"type": "object"}),
                        "400": _error_response_schema("Malformed node id."),
                        "404": _error_response_schema("Unknown node."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}/locations": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Node position history",
                    "description": "Bounded, newest-first position history for "
                    "one node. Rows keep the legacy location field names; "
                    "``timestamp`` is ISO-8601 UTC.",
                    "parameters": [
                        _NODE_ID_PATH_PARAM,
                        _query_param(
                            "limit",
                            {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 2000,
                                "default": 10,
                            },
                            "Maximum history rows (default 10).",
                        ),
                    ],
                    "responses": {
                        "200": _json_response("Position history.", {"type": "object"}),
                        "400": _error_response_schema("Invalid limit or node id."),
                        "404": _error_response_schema("Unknown node."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}/telemetry": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Node telemetry series",
                    "description": "Decoded telemetry metrics; points are "
                    "[unix epoch seconds, value] pairs.",
                    "parameters": [
                        _NODE_ID_PATH_PARAM,
                        _query_param(
                            "since",
                            {"type": "string"},
                            "Window start (epoch seconds or ISO-8601).",
                        ),
                        _query_param(
                            "until",
                            {"type": "string"},
                            "Window end (epoch seconds or ISO-8601).",
                        ),
                        _query_param(
                            "metric",
                            {"type": "string"},
                            "Comma-separated metric filter, e.g. battery_level,voltage.",
                        ),
                        _query_param(
                            "range",
                            {"type": "string", "enum": ["1d", "7d", "30d", "all"]},
                            "Preset window when since/until absent (default 7d).",
                        ),
                    ],
                    "responses": {
                        "200": _json_response("Telemetry series.", {"type": "object"}),
                        "400": _error_response_schema("Invalid window or metric."),
                        "404": _error_response_schema("Unknown node."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}/packets": {
                "get": {
                    "tags": ["nodes", "packets"],
                    "summary": "Packets involving a node",
                    "description": "Packets where the node is sender or "
                    "recipient; narrow with direction=sent|received. Supports "
                    "the shared packet filters (portnum, gateway_id, "
                    "primary_channel, min/max_rssi, hop_count, since/until, q).",
                    "parameters": [
                        _NODE_ID_PATH_PARAM,
                        *_PAGE_PARAMS,
                        _query_param(
                            "direction",
                            {"type": "string", "enum": ["all", "sent", "received"]},
                            "Scope (default all).",
                        ),
                        _query_param(
                            "portnum", {"type": "string"}, "Exact portnum name."
                        ),
                        _query_param(
                            "gateway_id",
                            {"type": "string"},
                            "Gateway id (!hex or raw).",
                        ),
                        _query_param(
                            "primary_channel", {"type": "string"}, "Channel id."
                        ),
                        _query_param("min_rssi", {"type": "integer"}, "Minimum RSSI."),
                        _query_param("max_rssi", {"type": "integer"}, "Maximum RSSI."),
                        _query_param(
                            "hop_count", {"type": "integer"}, "Exact hop count."
                        ),
                        _query_param(
                            "since", {"type": "string"}, "Lower bound (epoch/ISO-8601)."
                        ),
                        _query_param(
                            "until", {"type": "string"}, "Upper bound (epoch/ISO-8601)."
                        ),
                        _query_param("q", {"type": "string"}, "Free-text filter."),
                        _query_param(
                            "sort",
                            {
                                "type": "string",
                                "enum": [
                                    "timestamp",
                                    "from_node",
                                    "to_node",
                                    "gateway",
                                    "portnum_name",
                                    "rssi",
                                    "snr",
                                    "payload_length",
                                    "hop_count",
                                ],
                            },
                            "Sort key (default timestamp).",
                        ),
                        _query_param(
                            "order",
                            {"type": "string", "enum": ["asc", "desc"]},
                            "Sort direction.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Packet page.",
                            _list_items({"$ref": "#/components/schemas/Packet"}),
                        ),
                        "400": _error_response_schema("Invalid parameter."),
                        "404": _error_response_schema("Unknown node."),
                    },
                }
            },
            "/api/v1/packets": {
                "get": {
                    "tags": ["packets"],
                    "summary": "Query packet history",
                    "description": "Full packets-page filter set plus free-text "
                    "q. Rows carry legacy-level name enrichment (names.from/to/"
                    "gateway) and a decoded text_content preview. Ungrouped by "
                    "default; group_by=mesh_packet_id collapses receptions onto "
                    "the earliest one (legacy rule; NULL/0 mesh ids excluded) "
                    "and counts groups in meta.pagination, adding group."
                    "{reception_count,gateways}. Group sort keys act on "
                    "aggregates: timestamp uses the representative reception, "
                    "rssi/snr/payload_length/hop_count take the group minimum "
                    "and gateway the distinct-gateway count. Use "
                    "/api/v1/packets/{id} for the reception detail of one packet.",
                    "parameters": [
                        *_PAGE_PARAMS,
                        _query_param(
                            "from_node",
                            {"type": "string"},
                            "Sender node (any id form).",
                        ),
                        _query_param(
                            "to_node",
                            {"type": "string"},
                            "Recipient node (any id form).",
                        ),
                        _query_param(
                            "gateway_id",
                            {"type": "string"},
                            "Gateway id (!hex or raw).",
                        ),
                        _query_param(
                            "portnum", {"type": "string"}, "Exact portnum name."
                        ),
                        _query_param(
                            "primary_channel", {"type": "string"}, "Channel id."
                        ),
                        _query_param("min_rssi", {"type": "integer"}, "Minimum RSSI."),
                        _query_param("max_rssi", {"type": "integer"}, "Maximum RSSI."),
                        _query_param(
                            "hop_count", {"type": "integer"}, "Exact hop count."
                        ),
                        _query_param(
                            "exclude_from", {"type": "string"}, "Exclude sender node."
                        ),
                        _query_param(
                            "exclude_to", {"type": "string"}, "Exclude recipient node."
                        ),
                        _query_param(
                            "exclude_self",
                            {"type": "boolean"},
                            "Exclude packets self-reported by gateway_id.",
                        ),
                        _query_param(
                            "since", {"type": "string"}, "Lower bound (epoch/ISO-8601)."
                        ),
                        _query_param(
                            "until", {"type": "string"}, "Upper bound (epoch/ISO-8601)."
                        ),
                        _query_param("q", {"type": "string"}, "Free-text filter."),
                        _query_param(
                            "sort",
                            {
                                "type": "string",
                                "enum": [
                                    "timestamp",
                                    "from_node",
                                    "to_node",
                                    "gateway",
                                    "portnum_name",
                                    "rssi",
                                    "snr",
                                    "payload_length",
                                    "hop_count",
                                ],
                            },
                            "Sort key (default timestamp).",
                        ),
                        _query_param(
                            "order",
                            {"type": "string", "enum": ["asc", "desc"]},
                            "Sort direction.",
                        ),
                        _query_param(
                            "group_by",
                            {"type": "string", "enum": list(GROUP_BY_MODES)},
                            "Collapse receptions into one row per mesh packet "
                            "id (NULL/0 mesh ids excluded, as in the legacy "
                            "grouped view); meta.pagination then counts groups.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Packet page.",
                            _list_items({"$ref": "#/components/schemas/Packet"}),
                        ),
                        "400": _error_response_schema("Invalid query parameter."),
                    },
                }
            },
            "/api/v1/packets/{packet_id}": {
                "get": {
                    "tags": ["packets"],
                    "summary": "Packet detail",
                    "description": "Raw fields, decoded payload, receptions "
                    "and relay candidates for one packet.",
                    "parameters": [
                        {
                            "name": "packet_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": _json_response("Packet detail.", {"type": "object"}),
                        "404": _error_response_schema("Unknown packet."),
                    },
                }
            },
            "/api/v1/traceroutes": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "List traceroutes",
                    "description": "Traceroute packets with parsed path "
                    "summaries and legacy-level name enrichment (names.from/to/"
                    "gateway/route), newest first. group_by=mesh_packet_id "
                    "collapses receptions onto the most recent one (legacy "
                    "rule), counts groups in meta.pagination and adds group."
                    "{reception_count,gateways}; the timestamp sort follows "
                    "the representative.",
                    "parameters": [
                        *_PAGE_PARAMS,
                        _query_param(
                            "since",
                            {"type": "string"},
                            "Lower time bound (epoch/ISO-8601).",
                        ),
                        _query_param(
                            "until",
                            {"type": "string"},
                            "Upper time bound (epoch/ISO-8601).",
                        ),
                        _query_param(
                            "sort",
                            {
                                "type": "string",
                                "enum": list(TRACEROUTE_SORTS),
                            },
                            "Sort key (default timestamp; id is row order).",
                        ),
                        _query_param(
                            "order",
                            {"type": "string", "enum": ["asc", "desc"]},
                            "Sort direction (default desc).",
                        ),
                        _query_param(
                            "from", {"type": "string"}, "Source node (any id form)."
                        ),
                        _query_param(
                            "to", {"type": "string"}, "Destination node (any id form)."
                        ),
                        _query_param(
                            "gateway", {"type": "string"}, "Gateway id (!hex or raw)."
                        ),
                        _query_param("q", {"type": "string"}, "Free-text filter."),
                        _query_param(
                            "group_by",
                            {"type": "string", "enum": list(GROUP_BY_MODES)},
                            "Collapse receptions into one row per mesh packet "
                            "id; meta.pagination then counts groups. The "
                            "representative is the most recent reception "
                            "(legacy rule) and the timestamp sort follows it.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Traceroute page.",
                            _list_items({"$ref": "#/components/schemas/Traceroute"}),
                        ),
                        "400": _error_response_schema("Invalid query parameter."),
                    },
                }
            },
            "/api/v1/traceroutes/{packet_id}": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "Traceroute detail",
                    "description": "Raw fields plus the parsed path summary.",
                    "parameters": [
                        {
                            "name": "packet_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": _json_response("Traceroute detail.", {"type": "object"}),
                        "404": _error_response_schema("Unknown traceroute."),
                    },
                }
            },
            "/api/v1/gateways": {
                "get": {
                    "tags": ["gateways"],
                    "summary": "List gateways",
                    "description": "All observed gateways; statistics are "
                    "attached when the gateway is in the top talkers for the "
                    "window.",
                    "parameters": [
                        *_PAGE_PARAMS,
                        _query_param(
                            "q", {"type": "string"}, "Substring on id or display name."
                        ),
                        _query_param(
                            "hours",
                            {"type": "integer", "minimum": 1, "maximum": 168},
                            "Statistics window (default 24).",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Gateway page.",
                            _list_items({"$ref": "#/components/schemas/Gateway"}),
                        ),
                        "400": _error_response_schema("Invalid query parameter."),
                    },
                }
            },
            "/api/v1/gateways/{gateway_id}": {
                "get": {
                    "tags": ["gateways"],
                    "summary": "Gateway detail",
                    "description": "Statistics and ten most recent packets "
                    "reported by the gateway.",
                    "parameters": [
                        {
                            "name": "gateway_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "!hex form, bare hex, decimal, or the raw id.",
                        },
                        {
                            "name": "hours",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 168},
                        },
                    ],
                    "responses": {
                        "200": _json_response("Gateway detail.", {"type": "object"}),
                        "404": _error_response_schema("Unknown gateway."),
                    },
                }
            },
            "/api/v1/stats/summary": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Dashboard summary",
                    "description": "Totals, local-day activity buckets, top "
                    "nodes, signal-quality distribution and traffic-type "
                    "breakdown for one window.",
                    "parameters": [
                        {
                            "name": "range",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": list(STATS_RANGES),
                                "default": "24h",
                            },
                        },
                        {
                            "name": "tz_offset",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "minimum": -720,
                                "maximum": 840,
                                "default": 0,
                            },
                            "description": "Viewer minutes east of UTC for local-day buckets.",
                        },
                    ],
                    "responses": {
                        "200": _json_response("Summary.", {"type": "object"}),
                        "400": _error_response_schema("Invalid range."),
                    },
                }
            },
            "/api/v1/meta/filters": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Filter enumerations",
                    "description": "One call returning the values behind the UI "
                    "filter dropdowns (identical values and order to the legacy "
                    "/api/meshtastic/* endpoints).",
                    "parameters": [],
                    "responses": {
                        "200": _json_response(
                            "Dropdown enumerations.",
                            {
                                "type": "object",
                                "properties": {
                                    "hardware_models": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "roles": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "channels": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "packet_types": {
                                        "type": "array",
                                        "items": {"type": "array"},
                                    },
                                    "packet_channels": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                        ),
                    },
                }
            },
            "/api/v1/locations": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Bulk latest positions",
                    "description": "Latest decoded position per node over a time "
                    "window (legacy default: last 14 days), with the legacy row "
                    "field names and ISO-8601 UTC ``timestamp``. Includes the "
                    "legacy neighbourhood enrichment; use page/page_size for "
                    "large networks.",
                    "parameters": [
                        *_PAGE_PARAMS,
                        _query_param(
                            "since",
                            {"type": "string"},
                            "Window start (epoch/ISO-8601; default 14 days ago).",
                        ),
                        _query_param(
                            "until",
                            {"type": "string"},
                            "Window end (epoch/ISO-8601; default now).",
                        ),
                        _query_param(
                            "gateway_id",
                            {"type": "string"},
                            "Only positions reported by this gateway (any id form).",
                        ),
                        _query_param(
                            "include_links",
                            {"type": "boolean", "default": False},
                            "Opt-in: also return a sibling `links` object with "
                            "traceroute_links + packet_links (legacy composite "
                            "arrays). Absent unless true; `data` is unchanged "
                            "either way.",
                        ),
                        _query_param(
                            "enrich",
                            {"type": "boolean", "default": True},
                            "Set false for the positions-only fast path: skips "
                            "the per-request 24h network-graph build and link "
                            "lookups (neighbour-derived fields come back empty; "
                            "positions are identical). Default true keeps the "
                            "full legacy enrichment.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Position rows.", _list_items({"type": "object"})
                        ),
                        "400": _error_response_schema("Invalid query parameter."),
                    },
                }
            },
            "/api/v1/meta": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Instance metadata",
                    "description": "App name/version, node count, database "
                    "size and server time; intended for footers/healthchecks.",
                    "parameters": [],
                    "responses": {
                        "200": _json_response("Instance metadata.", {"type": "object"}),
                    },
                }
            },
            "/api/v1/chat/messages": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Chat message rows",
                    "description": "Legacy-parity passthrough of "
                    "/api/chat/messages: raw TEXT_MESSAGE_APP rows with "
                    "after_id/before_id cursor semantics and the sender node "
                    "map.",
                    "parameters": [
                        _query_param(
                            "after_id",
                            {"type": "integer"},
                            "Only rows with id greater than this.",
                        ),
                        _query_param(
                            "before_id",
                            {"type": "integer"},
                            "Only rows with id lower than this.",
                        ),
                        _query_param(
                            "channel", {"type": "string"}, "Filter by channel id."
                        ),
                        _query_param(
                            "limit",
                            {"type": "integer", "default": 300, "maximum": 500},
                            "Max rows.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Chat payload (packets, nodes, last_id).",
                            {"type": "object"},
                        ),
                    },
                }
            },
            "/api/v1/chat/relay-filters": {
                "get": {
                    "tags": ["meta"],
                    "summary": "Chat relay candidates",
                    "description": "Legacy-parity passthrough of "
                    "/api/chat/relay-filters for exact gateway/last-byte pairs "
                    "(`pair` repeated).",
                    "parameters": [
                        _query_param(
                            "pair",
                            {"type": "string"},
                            "gatewayId:lastByte pair; repeatable.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response("Relay filter map.", {"type": "object"}),
                    },
                }
            },
            "/api/v1/longest-links": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "Longest RF links",
                    "description": "Legacy-parity passthrough of /api/longest-links.",
                    "parameters": [
                        _query_param(
                            "min_distance",
                            {"type": "number", "default": 1.0},
                            "Minimum link distance (km).",
                        ),
                        _query_param(
                            "min_snr",
                            {"type": "number", "default": -20.0},
                            "Minimum SNR.",
                        ),
                        _query_param(
                            "max_results",
                            {"type": "integer", "default": 100},
                            "Result cap.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Longest links payload.", {"type": "object"}
                        ),
                    },
                }
            },
            "/api/v1/traceroute-graph": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "Traceroute network graph",
                    "description": "Legacy-parity passthrough of "
                    "/api/traceroute/graph (nodes/links/indirect connections).",
                    "parameters": [
                        _query_param(
                            "hours",
                            {
                                "type": "integer",
                                "default": 24,
                                "minimum": 1,
                                "maximum": 168,
                            },
                            "Lookback window.",
                        ),
                        _query_param(
                            "min_snr",
                            {"type": "number", "default": -30.0},
                            "-200 disables the SNR floor.",
                        ),
                        _query_param(
                            "include_indirect",
                            {"type": "boolean", "default": False},
                            "Include indirect connections.",
                        ),
                        _query_param(
                            "primary_channel", {"type": "string"}, "Channel filter."
                        ),
                    ],
                    "responses": {
                        "200": _json_response("Graph payload.", {"type": "object"}),
                    },
                }
            },
            "/api/v1/traceroute-hops/nodes": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "Traceroute participant nodes",
                    "description": "Legacy-parity passthrough of "
                    "/api/traceroute-hops/nodes.",
                    "parameters": [],
                    "responses": {
                        "200": _json_response(
                            "Nodes involved in traceroutes.", {"type": "object"}
                        ),
                    },
                }
            },
            "/api/v1/traceroute-link/{node1_id}/{node2_id}": {
                "get": {
                    "tags": ["traceroutes"],
                    "summary": "Per-link hop analysis",
                    "description": "Legacy-parity passthrough of "
                    "/api/traceroute/link/<a>/<b>.",
                    "parameters": [
                        {
                            "name": "node1_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "node2_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": _json_response(
                            "Link analysis payload.", {"type": "object"}
                        ),
                        "400": _error_response_schema("Malformed node id."),
                    },
                }
            },
            "/api/v1/related-nodes/{node_id}": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Nodes traceroute-connected to a node",
                    "description": "Legacy-parity payload of "
                    "/api/traceroute/related-nodes/<id>.",
                    "parameters": [_NODE_ID_PATH_PARAM],
                    "responses": {
                        "200": _json_response("Related nodes.", {"type": "object"}),
                        "400": _error_response_schema("Malformed node id."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}/direct-receptions": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Direct (0-hop) receptions",
                    "description": "Legacy-parity passthrough of "
                    "/api/node/<id>/direct-receptions.",
                    "parameters": [
                        _NODE_ID_PATH_PARAM,
                        _query_param(
                            "limit",
                            {"type": "integer", "default": 1000, "maximum": 5000},
                            "Row cap.",
                        ),
                        _query_param(
                            "direction",
                            {"type": "string", "enum": ["received", "transmitted"]},
                            "Direction.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Direct receptions payload.", {"type": "object"}
                        ),
                        "400": _error_response_schema("Invalid direction or node id."),
                    },
                }
            },
            "/api/v1/nodes/{node_id}/relay-node-analysis": {
                "get": {
                    "tags": ["nodes"],
                    "summary": "Relay-node analysis",
                    "description": "Legacy-parity passthrough of "
                    "/api/node/<id>/relay-node-analysis.",
                    "parameters": [
                        _NODE_ID_PATH_PARAM,
                        _query_param(
                            "limit",
                            {"type": "integer", "default": 50, "maximum": 1000},
                            "Row cap.",
                        ),
                    ],
                    "responses": {
                        "200": _json_response(
                            "Relay statistics payload.", {"type": "object"}
                        ),
                        "400": _error_response_schema("Malformed node id."),
                    },
                }
            },
            "/api/v1/openapi.json": {
                "get": {
                    "tags": ["meta"],
                    "summary": "This document",
                    "responses": {
                        "200": {
                            "description": "OpenAPI document.",
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Error": _ERROR_SCHEMA,
                "PaginationMeta": _PAGINATION_META_SCHEMA,
                "PacketNameEntry": _PACKET_NAME_ENTRY_SCHEMA,
                "GroupInfo": _GROUP_INFO_SCHEMA,
                "Node": _NODE_SCHEMA,
                "Packet": _PACKET_SCHEMA,
                "Traceroute": _TRACEROUTE_SCHEMA,
                "Gateway": _GATEWAY_SCHEMA,
            }
        },
    }


@api_v1_bp.route("/openapi.json")
def openapi_json() -> Response:
    response: Response = jsonify(_build_openapi())
    return response
