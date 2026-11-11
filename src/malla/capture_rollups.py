"""Capture-maintained rollups: completed-bucket rolling refresh.

Slow read paths (node list aggregates, latest positions/telemetry, traceroute
catalogs, longest links) are served from the rollup tables created by
:func:`malla.database.schema.ensure_rollup_schema`. This module is their only
writer. It follows the "rolling refresh" pattern of upstream draft #130
(`activity_rollup.py`): set-based ``INSERT .. SELECT .. GROUP BY`` over
``[done, now)`` ranges, idempotent writes on natural keys, and a resume point
derived from the data (``MAX(bucket)`` in the table) wherever possible.

Freshness contract (read this before changing a read path):

- Bucket tables (``node_hour_rollup``, ``link_day_rollup``, ``route_day_rollup``)
  fold only *completed* buckets, so a reader never sees a partial aggregate. An
  event becomes visible once its bucket completes and the next refresh runs:
  worst-case lag is one bucket plus one refresh interval (about an hour for the
  hourly node counters, until midnight for the daily link tables). The nodes
  page previously recomputed per request; the trade is the same league as the
  old 120s battery cache.
- Latest-state tables (``node_latest_position``, ``node_latest_telemetry``,
  ``traceroute_endpoint``) merge packet rows with ``id > high-water`` and store
  the *snapshot* ``MAX(id)`` as the new cursor (``_rollup_cursor``) in the same
  transaction: rows ``id <= snapshot_max``, never "current max" mid-scan. A
  crash redoes exactly one interval; redoing a range is a no-op because every
  write targets natural keys.

There is no separate backfill mode: the first refresh simply runs until the
pending work is done (bounded chunks, one transaction per chunk), and steady
state degenerates to a cheap indexed scan of the last minutes. The capture
daemon refreshes from its maintenance loop every
``MALLA_ROLLUP_REFRESH_SECONDS`` (default 60, ``0`` disables); the web app runs
one budgeted chunk at boot plus a low-priority refresher thread. Both runners
are safe concurrently - every write is idempotent on its natural keys and
``busy_timeout`` already serialises writers.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

#: Environment knob for the refresh cadence; ``0`` disables scheduling.
REFRESH_SECONDS_ENV = "MALLA_ROLLUP_REFRESH_SECONDS"
DEFAULT_REFRESH_SECONDS = 60

# Budgets, mirroring AnalyticsService._ROLLUP_TIME_BUDGET_SEC semantics: the
# boot chunk stays far below any request timeout, background slices stay small
# enough to interleave with packet writes.
BOOT_BUDGET_SEC = 5.0
THREAD_SLICE_SEC = 15.0

# Chunk sizes: id ranges for the latest-state merges (one transaction each),
# hours/days per statement for the bucket folds.
ID_CHUNK = 50_000
HOUR_CHUNK = 24
DAY_CHUNK = 1

CURSOR_TABLE = "_rollup_cursor"

_LATEST_TABLES = (
    "node_latest_position",
    "node_latest_telemetry",
    "traceroute_endpoint",
)

_HOUR = "CAST(timestamp / 3600 AS INTEGER)"


def _direct_snr_cond() -> str:
    """Direct-reception acceptance rule for the hour fold.

    Mirrors the legacy ``_NODE_SIGNAL_JOIN`` aggregate verbatim (hop_start ==
    hop_limit, 0..7, signal-quality-valid SNR); the parity unit test pins the
    Python mirror against the SQL fragment. Imported lazily: this package's
    siblings init ``malla.utils``/``malla.database`` in a fixed order and a
    top-level import here would flip it into a partial-initialisation cycle.
    """
    from malla.utils.signal_quality import snr_valid_sql

    return (
        "hop_start IS NOT NULL AND hop_start = hop_limit AND hop_start BETWEEN 0 AND 7"
        f" AND {snr_valid_sql()}"
    )


_BROADCAST = 4294967295


def refresh_interval_seconds() -> int:
    """Refresh cadence in seconds; ``0`` disables refresh scheduling."""
    raw = os.environ.get(REFRESH_SECONDS_ENV)
    if raw is None:
        return DEFAULT_REFRESH_SECONDS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_REFRESH_SECONDS


def refresh_enabled() -> bool:
    return refresh_interval_seconds() > 0


# ---------------------------------------------------------------------------
# Cheap state probes
# ---------------------------------------------------------------------------


def _first_timestamp(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MIN(timestamp) FROM packet_history").fetchone()
    value = row[0] if row else None
    return float(value) if value is not None else None


def _max_packet_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(id) FROM packet_history").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _cursor_value(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        f"SELECT last_packet_id FROM {CURSOR_TABLE} WHERE name = ?", (name,)
    ).fetchone()
    return int(row[0]) if row else 0


def _set_cursor(conn: sqlite3.Connection, name: str, packet_id: int) -> None:
    # Monotonic: with two runners (capture maintenance + the web-side backup
    # refresher) a lagging process must never rewind a cursor the other
    # already advanced; the fold is idempotent, but re-folding is waste.
    conn.execute(
        f"INSERT INTO {CURSOR_TABLE} (name, last_packet_id, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET"
        " last_packet_id = MAX(last_packet_id, excluded.last_packet_id),"
        " updated_at = excluded.updated_at",
        (name, int(packet_id), time.time()),
    )


def _pending_hours(conn: sqlite3.Connection, until: float) -> bool:
    newest = conn.execute("SELECT MAX(hour_epoch) FROM node_hour_rollup").fetchone()
    return _hour_pending_from(
        conn, int(newest[0]) + 1 if newest and newest[0] is not None else None, until
    )


def _hour_pending_from(
    conn: sqlite3.Connection,
    start: int | None,
    until: float,
) -> bool:
    if start is None:
        # Empty rollup != no packets: derive from data so the refresher keeps
        # probing (the fold skips the still-open hour and catches up later).
        first = _first_timestamp(conn)
        if first is None:
            return False
        start = int(first // 3600)
    last = int(until // 3600) - 1  # newest *completed* hour
    if start > last:
        return False
    row = conn.execute(
        "SELECT 1 FROM packet_history WHERE timestamp >= ? AND timestamp < ? LIMIT 1",
        (start * 3600, (last + 1) * 3600),
    ).fetchone()
    return row is not None


LINK_DAYS_CURSOR = "link_days_until"


def _link_day_resume(conn: sqlite3.Connection) -> str | None:
    """Day (ISO) the link/path fold must resume from.

    Preference: the persisted day cursor (advances past empty days);
    fallback: the day after the newest folded row; else first packet day.
    """
    marked = _cursor_value(conn, LINK_DAYS_CURSOR)
    if marked:
        return _day_floor(marked)
    newest = conn.execute("SELECT MAX(day) FROM link_day_rollup").fetchone()
    if newest and newest[0]:
        return _day_next(str(newest[0]))
    first = _first_timestamp(conn)
    return _day_floor(first) if first is not None else None


def _day_floor(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()


def _day_next(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date() + timedelta(days=1)
    return d.isoformat()


def has_pending_work(conn: sqlite3.Connection, *, until: float | None = None) -> bool:
    """Cheap data-aware probe: would :func:`refresh` fold anything?

    Existence checks only - a quiet mesh costs one indexed probe per table.
    """
    now = time.time() if until is None else until

    newest_hour = conn.execute(
        "SELECT MAX(hour_epoch) FROM node_hour_rollup"
    ).fetchone()
    start_hour = (
        int(newest_hour[0]) + 1 if newest_hour and newest_hour[0] is not None else None
    )
    if _hour_pending_from(conn, start_hour, now):
        return True

    link_day = _link_day_resume(conn)
    if link_day and link_day < _day_floor(now):
        day_start = (
            datetime.strptime(link_day, "%Y-%m-%d")  # noqa: DTZ002
            .replace(tzinfo=UTC)
            .timestamp()
        )
        row = conn.execute(
            "SELECT 1 FROM packet_history WHERE timestamp >= ? AND timestamp < ?"
            " AND portnum_name = 'TRACEROUTE_APP' AND raw_payload IS NOT NULL LIMIT 1",
            (day_start, now),
        ).fetchone()
        if row:
            return True

    return _max_packet_id(conn) > max(
        _cursor_value(conn, name) for name in _LATEST_TABLES
    )


# ---------------------------------------------------------------------------
# Bucket folds (completed ranges only; resume from MAX(bucket) in the table)
# ---------------------------------------------------------------------------


def _fold_node_hours(
    conn: sqlite3.Connection, until: float, deadline: float | None
) -> int:
    direct_cond = _direct_snr_cond()
    newest = conn.execute("SELECT MAX(hour_epoch) FROM node_hour_rollup").fetchone()
    if newest and newest[0] is not None:
        start = int(newest[0]) + 1
    else:
        first = _first_timestamp(conn)
        if first is None:
            return 0
        start = int(first // 3600)
    last = int(until // 3600) - 1
    folded = 0
    while start <= last:
        end = min(start + HOUR_CHUNK, last + 1)
        cursor = conn.execute(
            f"""
            INSERT OR IGNORE INTO node_hour_rollup
                (hour_epoch, node_id, packet_count, direct_snr_sum,
                 direct_snr_count, last_seen)
            SELECT {_HOUR}, from_node_id, COUNT(*),
                   SUM(CASE WHEN {direct_cond} THEN CAST(snr AS FLOAT) ELSE 0 END),
                   SUM(CASE WHEN {direct_cond} THEN 1 ELSE 0 END),
                   MAX(timestamp)
            FROM packet_history
            WHERE timestamp >= ? AND timestamp < ? AND from_node_id IS NOT NULL
            GROUP BY {_HOUR}, from_node_id
            """,
            (start * 3600, end * 3600),
        )
        folded += cursor.rowcount if cursor.rowcount > 0 else 0
        conn.commit()
        if deadline is not None and time.monotonic() >= deadline:
            break
        start = end
    return folded


def _fold_link_days(
    conn: sqlite3.Connection, until: float, deadline: float | None
) -> int:
    """Fold completed UTC days of traceroute hop/path aggregates.

    The hop pairing replicates ``TraceroutePacket.get_rf_hops`` (the pairing
    the network graph and the legacy longest-links analysis used) via the
    shared parser; acceptance matches the consumers' common core: plausible
    SNR, non-zero (MQTT/UDP marker), no broadcast endpoint.
    """
    from malla.models.traceroute import TraceroutePacket
    from malla.utils.signal_quality import is_plausible_traceroute_snr
    from malla.utils.traceroute_utils import parse_traceroute_payload

    start_day = _link_day_resume(conn)
    if start_day is None:
        return 0
    today = _day_floor(until)
    if start_day >= today:
        return 0

    folded = 0
    day = start_day
    while day < today:
        day_start = (
            datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()  # noqa: DTZ002
        )
        day_end = (
            datetime.strptime(_day_next(day), "%Y-%m-%d")  # noqa: DTZ002
            .replace(tzinfo=UTC)
            .timestamp()
        )
        rows = conn.execute(
            """
            SELECT id, timestamp, from_node_id, to_node_id, raw_payload
            FROM packet_history
            WHERE timestamp >= ? AND timestamp < ?
              AND portnum_name = 'TRACEROUTE_APP' AND raw_payload IS NOT NULL
            """,
            (day_start, day_end),
        ).fetchall()

        links: dict[tuple[int, int], dict[str, Any]] = {}
        paths: dict[tuple[int, int], dict[str, Any]] = {}
        for packet_id, ts, src, dst, payload in rows:
            if src is None or dst is None:
                continue
            route = parse_traceroute_payload(payload)
            packet = TraceroutePacket(
                packet_data={
                    "id": packet_id,
                    "timestamp": ts,
                    "from_node_id": src,
                    "to_node_id": dst,
                    "raw_payload": payload,
                },
                resolve_names=False,
                pre_parsed_route_data=route,
            )
            hops = packet.get_rf_hops()
            for hop in hops:
                if hop.from_node_id is None or hop.to_node_id is None:
                    continue
                if (
                    not is_plausible_traceroute_snr(hop.snr)
                    or hop.snr == 0
                    or _BROADCAST in (hop.from_node_id, hop.to_node_id)
                ):
                    continue
                key = (
                    min(hop.from_node_id, hop.to_node_id),
                    max(hop.from_node_id, hop.to_node_id),
                )
                stat = links.setdefault(
                    key,
                    {
                        "packets": 0,
                        "snr_sum": 0.0,
                        "snr_count": 0,
                        "snr_min": None,
                        "snr_max": None,
                        "last_seen": 0.0,
                        "last_packet_id": 0,
                    },
                )
                snr = float(hop.snr)
                stat["packets"] += 1
                stat["snr_sum"] += snr
                stat["snr_count"] += 1
                stat["snr_min"] = (
                    snr if stat["snr_min"] is None else min(stat["snr_min"], snr)
                )
                stat["snr_max"] = (
                    snr if stat["snr_max"] is None else max(stat["snr_max"], snr)
                )
                if ts > stat["last_seen"]:
                    stat["last_seen"] = ts
                stat["last_packet_id"] = max(stat["last_packet_id"], int(packet_id))

            if len(hops) > 1:
                valid_snrs = [h.snr for h in hops if is_plausible_traceroute_snr(h.snr)]
                if not valid_snrs:
                    continue
                path_key = (
                    min(hops[0].from_node_id, hops[-1].to_node_id),
                    max(hops[0].from_node_id, hops[-1].to_node_id),
                )
                if _BROADCAST in path_key:
                    continue
                pstat = paths.setdefault(
                    path_key,
                    {
                        "paths": 0,
                        "hops": 0,
                        "snr_avg_sum": 0.0,
                        "last_seen": 0.0,
                        "last_packet_id": 0,
                        "last_route": "",
                    },
                )
                # Orientation follows the earliest-seen path; route preview and
                # hop chain are stored for the newest path below.
                pstat["paths"] += 1
                pstat["hops"] += len(hops)
                pstat["snr_avg_sum"] += sum(valid_snrs) / len(valid_snrs)
                if ts > pstat["last_seen"] or (
                    ts == pstat["last_seen"] and packet_id > pstat["last_packet_id"]
                ):
                    pstat["last_seen"] = ts
                    pstat["last_packet_id"] = int(packet_id)
                    pstat["last_route"] = ",".join(
                        str(node_id)
                        for node_id in [hops[0].from_node_id]
                        + [h.to_node_id for h in hops]
                    )

        for (node_a, node_b), stat in links.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO link_day_rollup
                    (day, node_a, node_b, packet_count, snr_sum, snr_count,
                     snr_min, snr_max, last_seen, last_packet_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day,
                    node_a,
                    node_b,
                    stat["packets"],
                    stat["snr_sum"],
                    stat["snr_count"],
                    stat["snr_min"],
                    stat["snr_max"],
                    stat["last_seen"],
                    stat["last_packet_id"] or None,
                ),
            )
        for (end_a, end_b), stat in paths.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO route_day_rollup
                    (day, end_a, end_b, path_count, hop_count_sum, snr_avg_sum,
                     last_seen, last_packet_id, last_route)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day,
                    end_a,
                    end_b,
                    stat["paths"],
                    stat["hops"],
                    stat["snr_avg_sum"],
                    stat["last_seen"],
                    stat["last_packet_id"] or None,
                    stat["last_route"] or None,
                ),
            )
        day = _day_next(day)
        # Advance past every processed day, accepted hops or not: the next
        # run must not re-scan days that simply had no traceroutes. Written
        # before the commit so the cursor lands atomically with the rows.
        _set_cursor(
            conn,
            LINK_DAYS_CURSOR,
            int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()),
        )
        conn.commit()
        folded += len(links) + len(paths)
        if deadline is not None and time.monotonic() >= deadline:
            break
    return folded


# ---------------------------------------------------------------------------
# Latest-state merges (id-high-water; snapshot-bounded)
# ---------------------------------------------------------------------------

_UPSERT_POSITION = """
    INSERT INTO node_latest_position
        (node_id, last_seen, packet_id, gateway_id, latitude, longitude,
         altitude, precision_bits, sats_in_view)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(node_id) DO UPDATE SET
        last_seen = excluded.last_seen,
        packet_id = excluded.packet_id,
        gateway_id = excluded.gateway_id,
        latitude = excluded.latitude,
        longitude = excluded.longitude,
        altitude = excluded.altitude,
        precision_bits = excluded.precision_bits,
        sats_in_view = excluded.sats_in_view
    WHERE excluded.last_seen > node_latest_position.last_seen
       OR (excluded.last_seen = node_latest_position.last_seen
           AND excluded.packet_id > node_latest_position.packet_id)
"""

_UPSERT_TELEMETRY = """
    INSERT INTO node_latest_telemetry
        (node_id, last_seen, packet_id, battery_level, voltage,
         channel_utilization, air_util_tx)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(node_id) DO UPDATE SET
        last_seen = excluded.last_seen,
        packet_id = excluded.packet_id,
        battery_level = excluded.battery_level,
        voltage = excluded.voltage,
        channel_utilization = excluded.channel_utilization,
        air_util_tx = excluded.air_util_tx
    WHERE excluded.last_seen > node_latest_telemetry.last_seen
       OR (excluded.last_seen = node_latest_telemetry.last_seen
           AND excluded.packet_id > node_latest_telemetry.packet_id)
"""

_UPSERT_ENDPOINT = """
    INSERT INTO traceroute_endpoint (node_id, first_seen, last_seen)
    VALUES (?, ?, ?)
    ON CONFLICT(node_id) DO UPDATE SET
        last_seen = MAX(last_seen, excluded.last_seen)
"""


def _merge_position_window(conn: sqlite3.Connection, lo: int, hi: int) -> int:
    from meshtastic import mesh_pb2

    rows = conn.execute(
        """
        SELECT id, timestamp, from_node_id, raw_payload, gateway_id
        FROM packet_history
        WHERE id > ? AND id <= ? AND portnum = 3
          AND raw_payload IS NOT NULL AND from_node_id IS NOT NULL
        """,
        (lo, hi),
    ).fetchall()
    if not rows:
        return 0

    # Latest per node within the window by (timestamp, id) - mirrors the
    # legacy window-argmax tie-breaking.
    best: dict[int, tuple[float, int, tuple]] = {}
    for packet_id, ts, node_id, payload, gateway_id in rows:
        try:
            position = mesh_pb2.Position()
            position.ParseFromString(payload)
        except Exception:
            continue  # undecodable payload: leave any older rollup row intact
        # Same normalisation as the legacy read path (0 -> None, truthiness).
        latitude = position.latitude_i / 1e7 if position.latitude_i else None
        longitude = position.longitude_i / 1e7 if position.longitude_i else None
        altitude = position.altitude or None
        values = (
            int(node_id),
            float(ts),
            int(packet_id),
            gateway_id,
            latitude,
            longitude,
            altitude,
            getattr(position, "precision_bits", None),
            getattr(position, "sats_in_view", None),
        )
        key = (float(ts), int(packet_id))
        if node_id not in best or key > best[node_id][:2]:
            best[node_id] = (*key, values)

    for entry in best.values():
        conn.execute(_UPSERT_POSITION, entry[2])
    return len(best)


def _merge_telemetry_window(conn: sqlite3.Connection, lo: int, hi: int) -> int:
    from meshtastic import telemetry_pb2

    rows = conn.execute(
        """
        SELECT id, timestamp, from_node_id, raw_payload
        FROM packet_history
        WHERE id > ? AND id <= ? AND portnum_name = 'TELEMETRY_APP'
          AND raw_payload IS NOT NULL AND from_node_id IS NOT NULL
        """,
        (lo, hi),
    ).fetchall()
    if not rows:
        return 0

    best: dict[int, tuple[float, int, tuple]] = {}
    for packet_id, ts, node_id, payload in rows:
        try:
            telemetry = telemetry_pb2.Telemetry()
            telemetry.ParseFromString(payload)
        except Exception:
            continue
        if not telemetry.HasField("device_metrics"):
            continue
        metrics = telemetry.device_metrics
        values = (
            int(node_id),
            float(ts),
            int(packet_id),
            float(metrics.battery_level) if metrics.HasField("battery_level") else None,
            float(metrics.voltage) if metrics.HasField("voltage") else None,
            float(metrics.channel_utilization)
            if metrics.HasField("channel_utilization")
            else None,
            float(metrics.air_util_tx) if metrics.HasField("air_util_tx") else None,
        )
        key = (float(ts), int(packet_id))
        if node_id not in best or key > best[node_id][:2]:
            best[node_id] = (*key, values)

    for entry in best.values():
        conn.execute(_UPSERT_TELEMETRY, entry[2])
    return len(best)


def _merge_endpoint_window(conn: sqlite3.Connection, lo: int, hi: int) -> int:
    from malla.utils.traceroute_utils import parse_traceroute_payload

    rows = conn.execute(
        """
        SELECT timestamp, from_node_id, to_node_id, raw_payload FROM packet_history
        WHERE id > ? AND id <= ? AND portnum_name = 'TRACEROUTE_APP'
          AND from_node_id IS NOT NULL AND to_node_id IS NOT NULL
        """,
        (lo, hi),
    ).fetchall()
    folded = 0
    for ts, src, dst, payload in rows:
        conn.execute(_UPSERT_ENDPOINT, (int(src), float(ts), float(ts)))
        conn.execute(_UPSERT_ENDPOINT, (int(dst), float(ts), float(ts)))
        folded += 2

        # Route-interior nodes never appear as endpoints, but the traceroute
        # hops picker lists them (they must resolve for hop-only nodes), so
        # fold every node the path mentions. Undecodable payloads keep the
        # endpoint pair, like the legacy parse fallback.
        if not payload:
            continue
        try:
            route = parse_traceroute_payload(payload)
        except Exception:  # noqa: BLE001 - undecodable payload
            continue
        for node_id in (*route["route_nodes"], *route["route_back"]):
            if node_id is None or node_id == _BROADCAST:
                continue
            conn.execute(_UPSERT_ENDPOINT, (int(node_id), float(ts), float(ts)))
            folded += 1
    return folded


_MERGERS = {
    "node_latest_position": _merge_position_window,
    "node_latest_telemetry": _merge_telemetry_window,
    "traceroute_endpoint": _merge_endpoint_window,
}


def _merge_latest_tables(conn: sqlite3.Connection, deadline: float | None) -> int:
    # One shared id-window scan for all three latest-state tables: the windows
    # advance in lockstep, so packet_history is traversed once, not once per
    # table. A crash redoes the current window for every table (idempotent).
    merged = 0
    snapshot = _max_packet_id(conn)
    lo = min(_cursor_value(conn, name) for name in _LATEST_TABLES)
    while lo < snapshot:
        if deadline is not None and time.monotonic() >= deadline:
            return merged
        hi = min(lo + ID_CHUNK, snapshot)
        for name in _LATEST_TABLES:
            if _cursor_value(conn, name) < hi:
                _MERGERS[name](conn, lo, hi)
                _set_cursor(conn, name, hi)  # snapshot-bounded, same txn
        conn.commit()
        merged += hi - lo
        lo = hi
    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refresh(
    conn: sqlite3.Connection,
    *,
    until: float | None = None,
    budget_s: float | None = None,
) -> dict[str, int]:
    """Fold completed buckets and merge latest-state rows up to *until*.

    Idempotent and incremental: resumes from ``MAX(bucket)``/the stored cursors,
    so the first call backfills all retained history and later calls only touch
    the new interval. ``budget_s`` bounds wall clock between chunks; the
    committed progress of every chunk survives, so callers just re-invoke.
    """
    now = time.time() if until is None else until
    deadline = time.monotonic() + budget_s if budget_s is not None else None

    stats = {"latest_rows": 0, "hour_rows": 0, "link_day_rows": 0}
    stats["latest_rows"] = _merge_latest_tables(conn, deadline)
    stats["hour_rows"] = _fold_node_hours(conn, now, deadline)
    stats["link_day_rows"] = _fold_link_days(conn, now, deadline)
    return stats


def run_boot_refresh(db_path: str, *, budget_s: float = BOOT_BUDGET_SEC) -> bool:
    """Budgeted catch-up chunk for process startup. Returns True when work done."""
    if not refresh_enabled():
        return False
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        if not has_pending_work(conn):
            return False
        started = time.monotonic()
        stats = refresh(conn, budget_s=budget_s)
        logger.info(
            "Rollup boot refresh: %s in %.2fs", stats, time.monotonic() - started
        )
        return True
    finally:
        conn.close()


def _refresh_loop(db_path: str) -> None:
    interval = refresh_interval_seconds()
    while True:
        delay = interval
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout=30000")
                if has_pending_work(conn):
                    refresh(conn, budget_s=THREAD_SLICE_SEC)
                    if has_pending_work(conn):
                        delay = 1.0  # catch-up: bounded slices, back-to-back
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                # Verify-only web process over a database the capture has not
                # migrated yet: there is nothing to refresh, and retrying every
                # interval only buries real failures in the log.
                logger.debug("Rollup refresher stopped (rollup tables absent): %s", exc)
                return
            logger.warning("Rollup refresh thread error: %s", exc)
            delay = interval
        except Exception as exc:  # noqa: BLE001 - never kill the refresher
            logger.warning("Rollup refresh thread error: %s", exc)
            delay = interval
        time.sleep(delay)


_refresh_thread: threading.Thread | None = None
_refresh_thread_lock = threading.Lock()


def ensure_refresh_thread(db_path: str) -> bool:
    """Start the process-local refresher daemon once. Returns True if started."""
    global _refresh_thread
    if not refresh_enabled():
        return False
    with _refresh_thread_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return False
        _refresh_thread = threading.Thread(
            target=_refresh_loop,
            args=(db_path,),
            name="malla-rollup-refresh",
            daemon=True,
        )
        _refresh_thread.start()
        return True


def prune_before(conn: sqlite3.Connection, cutoff: float) -> int:
    """Lockstep rollup prune; run in the retention transaction.

    Keeps the bucket containing *cutoff* so a bucket is never dropped while any
    of its packets is still retained (same rule as activity rollup pruning).
    """
    deleted = 0
    for sql, params in (
        ("DELETE FROM link_day_rollup WHERE day < date(?, 'unixepoch')", (cutoff,)),
        ("DELETE FROM route_day_rollup WHERE day < date(?, 'unixepoch')", (cutoff,)),
        (
            "DELETE FROM node_hour_rollup WHERE hour_epoch < CAST(? / 3600 AS INTEGER)",
            (cutoff,),
        ),
        (
            "DELETE FROM node_latest_position WHERE node_id NOT IN"
            " (SELECT node_id FROM node_info)",
            (),
        ),
        (
            "DELETE FROM node_latest_telemetry WHERE node_id NOT IN"
            " (SELECT node_id FROM node_info)",
            (),
        ),
    ):
        cursor = conn.execute(sql, params)
        deleted += cursor.rowcount if cursor.rowcount > 0 else 0
    # traceroute_endpoint is bounded by nodes ever seen - kept.
    return deleted
