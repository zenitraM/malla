"""Tests for SQLite query-planner statistics seeding.

Without ``sqlite_stat1`` the planner can pick full-scan plans that degrade as
``packet_history`` grows. Seeding it is a DERIVED migration, so these tests
cover both the helper it calls and the migration itself.
"""

import sqlite3

from malla.database.statistics import (
    ensure_query_planner_stats,
    query_planner_stats_present,
)
from malla.migrations import MIGRATIONS, Phase, Status, read_marker, run_migrations
from malla.migrations.derived import PLANNER_STATS


def _make_populated_db(path: str) -> None:
    """Create a small packet_history/node_info DB with the real SCHEMA migrations."""

    conn = sqlite3.connect(path)
    run_migrations(conn, MIGRATIONS, phases=(Phase.SCHEMA,), take_lock=False)
    conn.executemany(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, portnum_name) "
        "VALUES (?, ?, ?, ?)",
        [(1000.0 + i, "msh/x", i % 20, "TEXT_MESSAGE_APP") for i in range(200)],
    )
    conn.commit()
    conn.close()


def test_stats_absent_then_seeded(tmp_path):
    """ensure_query_planner_stats creates sqlite_stat1 the first time only."""

    db = str(tmp_path / "stats.db")
    _make_populated_db(db)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    assert query_planner_stats_present(cur) is False

    ran = ensure_query_planner_stats(cur)
    conn.commit()
    assert ran is True
    assert query_planner_stats_present(cur) is True

    # Second call is a no-op because stats already exist.
    assert ensure_query_planner_stats(cur) is False
    conn.close()


def test_planner_stats_migration_seeds_once(tmp_path):
    """The DERIVED migration seeds planner stats, then reports nothing to do."""

    db = str(tmp_path / "migration.db")
    _make_populated_db(db)

    conn = sqlite3.connect(db)
    first = run_migrations(
        conn, (PLANNER_STATS,), phases=(Phase.DERIVED,), take_lock=False
    )
    assert [result.status for result in first] == [Status.APPLIED]
    assert query_planner_stats_present(conn.cursor()) is True
    recorded, _watermark = read_marker(conn, PLANNER_STATS.name)
    assert recorded is True

    second = run_migrations(
        conn, (PLANNER_STATS,), phases=(Phase.DERIVED,), take_lock=False
    )
    assert [result.status for result in second] == [Status.SKIPPED]
    conn.close()
