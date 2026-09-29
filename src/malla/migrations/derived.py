"""Data migrations: derived work over already-committed rows.

Every migration here only touches rows that are already stored, so they are safe
to run while the capture daemon keeps ingesting (``Phase.DERIVED``). They keep
their own "is there anything to do?" check instead of a one-shot marker, which
is what the startup code did before the framework existed.
"""

from __future__ import annotations

import logging
import sqlite3

from .. import activity_rollup
from ..database.statistics import (
    ensure_query_planner_stats,
    query_planner_stats_present,
)
from .base import Migration, Phase, Watermark
from .structural import tables

logger = logging.getLogger(__name__)


def _node_info_present(conn: sqlite3.Connection) -> bool:
    return "node_info" in tables(conn)


def _pending_primary_channel(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    if not _node_info_present(conn):
        return False
    row = conn.execute(
        "SELECT COUNT(*) FROM node_info WHERE primary_channel IS NULL OR primary_channel = ''"
    ).fetchone()
    return bool(row and row[0])


def _apply_primary_channel(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    """Fill node_info.primary_channel from the node's newest NodeInfo packet."""
    before = conn.total_changes
    conn.execute(
        """
        UPDATE node_info
        SET primary_channel = (
            SELECT ph.channel_id
            FROM packet_history ph
            WHERE ph.from_node_id = node_info.node_id
              AND ph.portnum_name = 'NODEINFO_APP'
              AND ph.channel_id IS NOT NULL AND ph.channel_id != ''
            ORDER BY ph.timestamp DESC
            LIMIT 1
        )
        WHERE (primary_channel IS NULL OR primary_channel = '')
          AND EXISTS (
            SELECT 1
            FROM packet_history ph
            WHERE ph.from_node_id = node_info.node_id
              AND ph.portnum_name = 'NODEINFO_APP'
              AND ph.channel_id IS NOT NULL AND ph.channel_id != ''
          )
    """
    )
    changed = conn.total_changes - before
    if changed:
        logger.info("Backfilled primary_channel values for %s nodes", changed)
    return None


def _pending_activity_quarters(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    if activity_rollup.PACKET_TABLE not in tables(conn):
        return False
    return activity_rollup.pending(conn)


def _apply_activity_quarters(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    """Fill the quarter-hour activity buckets from stored packets.

    Incremental and idempotent, so an interrupted or repeated run costs nothing;
    the capture daemon keeps it current from here on.
    """
    inserted = activity_rollup.refresh(conn)
    newest = activity_rollup.latest_bucket(conn)
    logger.info("Activity buckets: %s rows inserted, newest bucket %s", inserted, newest)
    return None if newest is None else str(newest)


def _pending_planner_stats(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    return not query_planner_stats_present(conn.cursor())


def _apply_planner_stats(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    ensure_query_planner_stats(conn.cursor())
    return None


PRIMARY_CHANNEL_BACKFILL = Migration(
    name="primary_channel_backfill",
    phase=Phase.DERIVED,
    apply=_apply_primary_channel,
    description="fill node_info.primary_channel from stored NodeInfo packets",
    pending=_pending_primary_channel,
)

ACTIVITY_QUARTER_BACKFILL = Migration(
    name="activity_quarter_backfill",
    phase=Phase.DERIVED,
    apply=_apply_activity_quarters,
    description="fill quarter-hour activity buckets from stored packets",
    pending=_pending_activity_quarters,
)

PLANNER_STATS = Migration(
    name="planner_stats",
    phase=Phase.DERIVED,
    apply=_apply_planner_stats,
    description="seed query-planner statistics with a bounded ANALYZE",
    pending=_pending_planner_stats,
)

DERIVED_MIGRATIONS: tuple[Migration, ...] = (
    PRIMARY_CHANNEL_BACKFILL,
    PLANNER_STATS,
    ACTIVITY_QUARTER_BACKFILL,
)
