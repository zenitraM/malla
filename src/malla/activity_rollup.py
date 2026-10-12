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
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: Bucket width. Anything coarser than 15 minutes mis-assigns the packets around
#: a day boundary for offsets such as +05:30, +05:45 or +12:45.
BUCKET_SECONDS = 900

DAY_SECONDS = 86400


def snap_offset_minutes(tz_offset_minutes: int) -> int:
    """Floor a viewer's UTC offset to a multiple of the bucket width.

    Local day boundaries must land on bucket boundaries for the stored buckets
    to tile a viewer's day exactly. Every real-world UTC offset already is a
    multiple of a quarter hour; anything else (a hand-crafted request) is
    floored to the quarter hour below, east-positive, so the boundary never
    moves backwards into the day being summed.
    """
    minutes = BUCKET_SECONDS // 60
    return int(tz_offset_minutes) // minutes * minutes


@dataclass(frozen=True)
class ViewerWindow:
    """A viewer's local-calendar range, aligned to bucket boundaries.

    Built by :func:`viewer_window`. Readers take one of these rather than an
    offset plus a time range, so the offset a day is bucketed with and the
    boundaries it is summed over can never disagree.
    """

    offset_minutes: int
    offset_sec: int
    start_local: int
    today_local: int

    @property
    def start_utc(self) -> int:
        """Start of the window in UTC (bucket-aligned)."""
        return self.start_local - self.offset_sec

    @property
    def end_utc(self) -> int:
        """Exclusive end: the viewer's current local midnight, in UTC."""
        return self.today_local - self.offset_sec

    @property
    def day_epochs(self) -> list[int]:
        """Local-midnight epochs in the window, oldest first; today is last."""
        return list(
            range(self.start_local, self.today_local + DAY_SECONDS, DAY_SECONDS)
        )


def viewer_window(
    tz_offset_minutes: int,
    *,
    now: float | None = None,
    days: int | None = None,
    since: float | None = None,
) -> ViewerWindow:
    """The local-calendar window a viewer's request covers.

    *days* is a fixed trailing window (7d/30d), *since* a UTC epoch the window
    starts at (the "all" range starts at the first packet), and with neither the
    window is today alone.
    """
    offset_minutes = snap_offset_minutes(tz_offset_minutes)
    offset_sec = offset_minutes * 60
    current = time.time() if now is None else now
    today_local = (int(current + offset_sec) // DAY_SECONDS) * DAY_SECONDS
    if days is not None:
        start_local = today_local - max(0, days) * DAY_SECONDS
    elif since is not None:
        start_local = min(
            (int(since + offset_sec) // DAY_SECONDS) * DAY_SECONDS, today_local
        )
    else:
        start_local = today_local
    return ViewerWindow(offset_minutes, offset_sec, start_local, today_local)


def day_key(local_epoch: int) -> str:
    """ISO date for a local-midnight epoch (local time == shifted UTC)."""
    return datetime.fromtimestamp(local_epoch, tz=UTC).date().isoformat()


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


def prune_before(conn: sqlite3.Connection, cutoff: float) -> int:
    """Drop the buckets that are wholly older than the retention *cutoff*.

    Called when data retention deletes old packets, so the store stops growing
    and the timeline stops reporting days whose source rows are gone. The bucket
    containing *cutoff* is kept even though part of it may already be expired:
    that way a bucket is never dropped while any of its packets are still
    retained. Returns rows deleted across the three bucket tables."""
    cutoff_bucket = bucket_start(cutoff)
    deleted = 0
    for table in TABLES:
        cursor = conn.execute(f"DELETE FROM {table} WHERE bucket < ?", (cutoff_bucket,))
        deleted += cursor.rowcount
    return deleted


def _shifted_day(offset_sec: int) -> str:
    """SQL expression mapping a UTC bucket to the viewer's local date."""
    return f"date(bucket + {int(offset_sec)}, 'unixepoch')"


def daily_buckets(
    conn: sqlite3.Connection, window: ViewerWindow
) -> dict[str, dict[str, int]]:
    """Per-local-day totals for *window*: packets, distinct nodes, distinct gateways."""
    day = _shifted_day(window.offset_sec)
    stats: dict[str, dict[str, int]] = {}

    def entry(key: str) -> dict[str, int]:
        return stats.setdefault(key, {})

    for row in conn.execute(
        f"SELECT {day} AS day, SUM(total_packets) FROM {PACKET_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (window.start_utc, window.end_utc),
    ):
        entry(row[0])["total_packets"] = int(row[1] or 0)

    for row in conn.execute(
        f"SELECT {day} AS day, COUNT(DISTINCT node_id) FROM {NODE_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (window.start_utc, window.end_utc),
    ):
        entry(row[0])["active_nodes"] = int(row[1] or 0)

    for row in conn.execute(
        f"SELECT {day} AS day, COUNT(DISTINCT gateway_id) FROM {GATEWAY_TABLE} "
        "WHERE bucket >= ? AND bucket < ? GROUP BY day",
        (window.start_utc, window.end_utc),
    ):
        entry(row[0])["gateway_count"] = int(row[1] or 0)

    return stats


def new_nodes_by_day(conn: sqlite3.Connection, window: ViewerWindow) -> dict[str, int]:
    """Nodes first seen in each local day (``node_info`` is small and per-node)."""
    rows = conn.execute(
        "SELECT date(first_seen + ?, 'unixepoch') AS day, COUNT(*) "
        "FROM node_info WHERE first_seen >= ? AND first_seen < ? GROUP BY day",
        (window.offset_sec, window.start_utc, window.end_utc),
    ).fetchall()
    return {row[0]: int(row[1] or 0) for row in rows}
