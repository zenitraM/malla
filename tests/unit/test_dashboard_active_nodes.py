"""The dashboard's active-24h metric reads the quarter-hour rollup.

``COUNT(DISTINCT from_node_id)`` over ~500k packet_history rows costs a TEMP
B-TREE per request (measured 1.5–4 s on prod); the capture-maintained
``activity_node_quarter`` rollup holds the same (bucket, node_id) facts in
~96 rows per node, so the distinct runs over a tiny indexed table instead.
"""

import sqlite3
import time

import pytest

import malla.database.repositories as repositories
from malla.database.repositories import DashboardRepository


@pytest.fixture()
def stats_db(tmp_path, monkeypatch):
    db = str(tmp_path / "stats.db")
    monkeypatch.setenv("MALLA_DATABASE_FILE", db)
    repositories._dashboard_stats_cache.clear()
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE packet_history ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " timestamp REAL NOT NULL,"
        " from_node_id INTEGER,"
        " gateway_id TEXT,"
        " rssi INTEGER,"
        " snr REAL,"
        " portnum_name TEXT,"
        " portnum INTEGER,"
        " processed_successfully BOOLEAN DEFAULT TRUE)"
    )
    conn.execute(
        "CREATE TABLE node_info (node_id INTEGER PRIMARY KEY, last_updated REAL)"
    )
    conn.execute(
        "CREATE TABLE activity_node_quarter (bucket INTEGER NOT NULL,"
        " node_id INTEGER NOT NULL)"
    )
    yield conn
    repositories._dashboard_stats_cache.clear()
    conn.close()


def _now():
    return time.time()


def test_active_24h_reads_the_rollup(stats_db):
    """Rows in the rollup window count, regardless of packet_history state."""
    now = _now()
    floor = int((now - 24 * 3600) // 900) * 900
    # 2 nodes in-window, 1 node well outside the window: only 2 may count.
    stats_db.executemany(
        "INSERT INTO activity_node_quarter (bucket, node_id) VALUES (?, ?)",
        [(floor + 900, 11), (floor + 1800, 22), (floor - 100 * 900, 33)],
    )
    stats_db.commit()

    stats = DashboardRepository.get_stats()
    assert stats["active_nodes_24h"] == 2


def test_empty_rollup_falls_back_to_packet_history(stats_db):
    """A capture that has not backfilled yet must not pin the panel at 0."""
    now = _now()
    stats_db.executemany(
        "INSERT INTO packet_history (timestamp, from_node_id) VALUES (?, ?)",
        [(now - 3600, 11), (now - 7200, 22), (now - 7200, 11)],
    )
    stats_db.commit()

    stats = DashboardRepository.get_stats()
    assert stats["active_nodes_24h"] == 2


def test_gateway_filter_skips_the_rollup(stats_db):
    """The rollup has no gateway dimension; filtered stats keep the direct path."""
    now = _now()
    stats_db.executemany(
        "INSERT INTO packet_history (timestamp, from_node_id, gateway_id)"
        " VALUES (?, ?, ?)",
        [(now - 3600, 11, "!gw"), (now - 7200, 22, "!gw")],
    )
    stats_db.commit()

    stats = DashboardRepository.get_stats("!gw")
    assert stats["active_nodes_24h"] == 2


def test_pruned_edge_bucket_is_respected(stats_db):
    """A node heard only before the window floor must not count."""
    now = _now()
    floor = int((now - 24 * 3600) // 900) * 900
    stats_db.executemany(
        "INSERT INTO activity_node_quarter (bucket, node_id) VALUES (?, ?)",
        [(floor - 1, 11)],
    )
    # bucket - 1 is *within* the same quarter as the floor boundary check:
    # buckets are quarter-start epochs, so floor-900 is the last full bucket.
    stats_db.execute("DELETE FROM activity_node_quarter WHERE bucket < ?", (floor,))
    stats_db.commit()

    stats = DashboardRepository.get_stats()
    assert stats["active_nodes_24h"] == 0
