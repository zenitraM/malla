"""SQLite query-planner statistics helpers.

Without ``sqlite_stat1`` the planner guesses index selectivity and can pick a
badly-scaling plan (e.g. a full scan of ``packet_history`` for a query a partial
index would serve in milliseconds). A bounded ``ANALYZE`` fixes that.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


def query_planner_stats_present(cursor: sqlite3.Cursor) -> bool:
    """Return ``True`` if SQLite query-planner statistics (sqlite_stat1) exist."""

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_stat1'"
    )
    if cursor.fetchone() is None:
        return False
    cursor.execute("SELECT 1 FROM sqlite_stat1 LIMIT 1")
    return cursor.fetchone() is not None


def ensure_query_planner_stats(cursor: sqlite3.Cursor) -> bool:
    """Seed SQLite query-planner statistics if they are missing.

    ``PRAGMA analysis_limit`` keeps the work bounded so it stays fast even on a
    multi-gigabyte database, at the cost of sampling; ``PRAGMA optimize`` in the
    capture loop keeps the estimates fresh afterwards. Returns ``True`` when
    ``ANALYZE`` ran.
    """

    if query_planner_stats_present(cursor):
        return False  # stats already present – nothing to do

    cursor.execute("PRAGMA analysis_limit=1000")
    logger.info("Query-planner statistics missing – running bounded ANALYZE")
    cursor.execute("ANALYZE")
    return True
