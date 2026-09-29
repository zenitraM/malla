"""Quarter-hour activity buckets, shifted to any viewer timezone at query time.

The dashboard timeline needs per-local-day packet volume, distinct senders and
distinct gateways. Aggregating that from ``packet_history`` per request costs
seconds on a multi-gigabyte database, and the previous approach (a
``activity_daily_rollup`` table keyed by the *viewer's* UTC offset) forced the web
UI to write, needed a per-request time budget and still only served the offsets
somebody had already requested.

Storing 15-minute UTC buckets instead makes the shift a query-time operation:
every real-world UTC offset is a multiple of 15 minutes, so day boundaries always
land on a bucket boundary and summing whole buckets is *exact* (hourly buckets are
not — at +05:30 half of the boundary hour belongs to the other day).

Measured on a 9.55 M packet / 7.4 GiB database: building seven days of buckets
takes ~8 s and the per-offset query ~0.2 s, against ~5 s for the live
aggregation. ``active_nodes``/``gateway_count`` cannot be derived from counts
alone (a set cannot be re-cut), which is why the node/gateway buckets store
identities rather than totals.

The capture daemon refreshes the store; the web UI only reads it.
"""

from __future__ import annotations

import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

#: Bucket width. Anything coarser than 15 minutes mis-assigns the packets around
#: a day boundary for offsets such as +05:30, +05:45 or +12:45.
BUCKET_SECONDS = 900

PACKET_TABLE = "activity_packet_quarter"
NODE_TABLE = "activity_node_quarter"
GATEWAY_TABLE = "activity_gateway_quarter"

TABLES: tuple[str, ...] = (PACKET_TABLE, NODE_TABLE, GATEWAY_TABLE)

ACTIVITY_QUARTER_TABLES_SQL = f"""
    CREATE TABLE IF NOT EXISTS {PACKET_TABLE} (
        bucket INTEGER PRIMARY KEY,
        total_packets INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
        bucket INTEGER NOT NULL,
        node_id INTEGER NOT NULL,
        PRIMARY KEY (bucket, node_id)
    ) WITHOUT ROWID;

    CREATE TABLE IF NOT EXISTS {GATEWAY_TABLE} (
        bucket INTEGER NOT NULL,
        gateway_id TEXT NOT NULL,
        PRIMARY KEY (bucket, gateway_id)
    ) WITHOUT ROWID;
"""

CREATE_INDEXES_SQL = (
    f"CREATE INDEX IF NOT EXISTS idx_{NODE_TABLE}_node ON {NODE_TABLE}(node_id)",
)


def bucket_start(epoch: float) -> int:
    """Start of the bucket containing *epoch*."""
    return int(epoch) // BUCKET_SECONDS * BUCKET_SECONDS


def latest_bucket(conn: sqlite3.Connection) -> int | None:
    """Newest bucket the store knows about, or ``None`` when it is empty."""
    row = conn.execute(f"SELECT MAX(bucket) FROM {PACKET_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _first_packet_timestamp(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MIN(timestamp) FROM packet_history").fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def pending(conn: sqlite3.Connection, *, until: float | None = None) -> bool:
    """Whether completed packets are still missing from the store.

    Data-aware on purpose: a quiet mesh produces no new packets, so the store is
    complete even though the clock has moved on, and the capture's per-minute
    check stays a single indexed existence query.
    """
    end = bucket_start(until if until is not None else time.time())
    newest = latest_bucket(conn)
    if newest is not None:
        start = newest + BUCKET_SECONDS
    else:
        first = _first_packet_timestamp(conn)
        if first is None:
            return False
        start = bucket_start(first)
    if start >= end:
        return False
    row = conn.execute(
        "SELECT 1 FROM packet_history WHERE timestamp >= ? AND timestamp < ? LIMIT 1",
        (start, end),
    ).fetchone()
    return row is not None


def refresh(
    conn: sqlite3.Connection, *, until: float | None = None, since: float | None = None
) -> int:
    """Append every completed bucket up to *until*. Returns rows inserted.

    Idempotent (``INSERT OR IGNORE`` on the primary keys) and incremental: with
    no *since* it resumes after the newest bucket already stored, so a first run
    backfills all retained history and later runs only touch the new buckets.
    """
    end = bucket_start(until if until is not None else time.time())
    if since is not None:
        start = bucket_start(since)
    else:
        newest = latest_bucket(conn)
        if newest is not None:
            start = newest + BUCKET_SECONDS
        else:
            first = _first_packet_timestamp(conn)
            if first is None:
                return 0
            start = bucket_start(first)
    if start >= end:
        return 0

    window = (start, end)
    bucket = f"(CAST(timestamp / {BUCKET_SECONDS} AS INT) * {BUCKET_SECONDS})"
    inserted = 0

    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {PACKET_TABLE} (bucket, total_packets) "
        f"SELECT {bucket} AS bucket, COUNT(*) FROM packet_history "
        "WHERE timestamp >= ? AND timestamp < ? GROUP BY bucket",
        window,
    )
    inserted += cursor.rowcount

    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {NODE_TABLE} (bucket, node_id) "
        f"SELECT DISTINCT {bucket} AS bucket, from_node_id FROM packet_history "
        "WHERE timestamp >= ? AND timestamp < ? AND from_node_id IS NOT NULL",
        window,
    )
    inserted += cursor.rowcount

    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {GATEWAY_TABLE} (bucket, gateway_id) "
        f"SELECT DISTINCT {bucket} AS bucket, gateway_id FROM packet_history "
        "WHERE timestamp >= ? AND timestamp < ? AND gateway_id IS NOT NULL",
        window,
    )
    inserted += cursor.rowcount

    conn.commit()
    return inserted


def _shifted_day(offset_sec: int) -> str:
    """SQL expression mapping a UTC bucket to the viewer's local date."""
    return f"date(bucket + {int(offset_sec)}, 'unixepoch')"


def daily_buckets(
    conn: sqlite3.Connection,
    *,
    tz_offset_minutes: int,
    start_utc: float,
    end_utc: float,
) -> dict[str, dict[str, int]]:
    """Per-local-day totals over ``[start_utc, end_utc)`` for one viewer offset.

    The window must be aligned to :data:`BUCKET_SECONDS` (local day boundaries
    are, for any offset that is a multiple of 15 minutes), otherwise the buckets
    at the edges are partially outside it.
    """
    offset_sec = int(tz_offset_minutes) * 60
    day = _shifted_day(offset_sec)
    stats: dict[str, dict[str, int]] = {}

    def entry(key: str) -> dict[str, int]:
        return stats.setdefault(key, {})

    for row in conn.execute(
        f"SELECT {day} AS day, SUM(total_packets) FROM {PACKET_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (start_utc, end_utc),
    ):
        entry(row[0])["total_packets"] = int(row[1] or 0)

    for row in conn.execute(
        f"SELECT {day} AS day, COUNT(DISTINCT node_id) FROM {NODE_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (start_utc, end_utc),
    ):
        entry(row[0])["active_nodes"] = int(row[1] or 0)

    for row in conn.execute(
        f"SELECT {day} AS day, COUNT(DISTINCT gateway_id) FROM {GATEWAY_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (start_utc, end_utc),
    ):
        entry(row[0])["gateway_count"] = int(row[1] or 0)

    return stats


def new_nodes_by_day(
    conn: sqlite3.Connection, *, tz_offset_minutes: int, start_utc: float, end_utc: float
) -> dict[str, int]:
    """Nodes first seen in each local day (``node_info`` is small and per-node)."""
    offset_sec = int(tz_offset_minutes) * 60
    rows = conn.execute(
        "SELECT date(first_seen + ?, 'unixepoch') AS day, COUNT(*) "
        "FROM node_info WHERE first_seen >= ? AND first_seen < ? GROUP BY day",
        (offset_sec, start_utc, end_utc),
    ).fetchall()
    return {row[0]: int(row[1] or 0) for row in rows}
