"""Tests for SQLite query-planner statistics seeding.

Without ``sqlite_stat1`` the planner can pick full-scan plans that degrade as
``packet_history`` grows. These tests cover the helpers that seed those stats
on first run (synchronously and via the non-blocking background thread).
"""

import sqlite3
import time

from malla.database.connection import seed_query_planner_stats_async
from malla.database.schema import (
    ensure_query_planner_stats,
    ensure_startup_schema,
    query_planner_stats_present,
)


def _make_populated_db(path: str) -> None:
    """Create a small packet_history/node_info DB with startup indexes."""

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE packet_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            topic TEXT NOT NULL,
            from_node_id INTEGER,
            to_node_id INTEGER,
            portnum INTEGER,
            portnum_name TEXT,
            gateway_id TEXT,
            channel_id TEXT,
            mesh_packet_id INTEGER,
            rssi INTEGER,
            snr REAL,
            hop_limit INTEGER,
            hop_start INTEGER,
            payload_length INTEGER,
            raw_payload BLOB,
            processed_successfully BOOLEAN DEFAULT TRUE,
            relay_node INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE node_info (
            node_id INTEGER PRIMARY KEY,
            hex_id TEXT,
            long_name TEXT,
            short_name TEXT,
            hw_model TEXT,
            role TEXT,
            first_seen REAL NOT NULL,
            last_updated REAL NOT NULL
        )
        """
    )
    for i in range(200):
        cur.execute(
            "INSERT INTO packet_history (timestamp, topic, from_node_id, portnum_name) "
            "VALUES (?, ?, ?, ?)",
            (1000.0 + i, "msh/x", i % 20, "TEXT_MESSAGE_APP"),
        )
    ensure_startup_schema(cur)
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


def test_async_seeder_populates_stats(tmp_path):
    """The background seeder eventually creates planner statistics."""

    db = str(tmp_path / "async.db")
    _make_populated_db(db)

    started = seed_query_planner_stats_async(db)
    assert started is True

    # Wait for the daemon thread to finish (small DB => milliseconds).
    deadline = time.time() + 10
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    while time.time() < deadline and not query_planner_stats_present(cur):
        time.sleep(0.05)

    assert query_planner_stats_present(cur) is True
    conn.close()


def test_async_seeder_noop_when_stats_present(tmp_path):
    """When stats already exist the seeder returns False and starts no thread."""

    db = str(tmp_path / "present.db")
    _make_populated_db(db)

    conn = sqlite3.connect(db)
    ensure_query_planner_stats(conn.cursor())
    conn.commit()
    conn.close()

    assert seed_query_planner_stats_async(db) is False
