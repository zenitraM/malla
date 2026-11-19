"""Fallback behavior while the BLOCKING index migration is still running.

The deployment that motivated this: a 7.9 M-row packet_history takes tens of
minutes to index, and during that window every query pinned with
``INDEXED BY idx_packet_history_signal_time`` raised ``no such index`` — the
dashboard's signal panels 500'd (well, 503'd) for the whole build. These tests
pin the contract: missing index → unpinned query runs and returns correct
rows; present index → the pin is used again.
"""

import sqlite3

import pytest

from malla.database import connection as db_connection
from malla.database.connection import pinned_index_available, reset_pinned_index_cache
from malla.migrations.structural import _apply_core_indexes
from malla.services.analytics_service import AnalyticsService


@pytest.fixture()
def indexed_db(tmp_path):
    """A packet_history table with rows but WITHOUT the signal index."""
    path = str(tmp_path / "degraded.db")
    conn = sqlite3.connect(path)
    conn.execute(
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
            relay_node INTEGER,
            message_type TEXT,
            raw_service_envelope BLOB,
            parsing_error TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO packet_history"
        " (timestamp, topic, from_node_id, gateway_id, rssi, snr, portnum_name)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1000.0 + i,
                "msh/t",
                0x1111,
                "!gw",
                -80.0 + (i % 20),
                5.0 + (i % 6),
                "POSITION_APP",
            )
            for i in range(50)
        ],
    )
    conn.commit()
    conn.close()
    reset_pinned_index_cache()
    yield path
    reset_pinned_index_cache()


def test_probe_reports_missing_index(indexed_db, monkeypatch):
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    assert pinned_index_available("idx_packet_history_signal_time") is False


def test_probe_reports_present_index(indexed_db, monkeypatch):
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    conn = sqlite3.connect(indexed_db)
    conn.execute(
        "CREATE INDEX idx_packet_history_signal_time"
        " ON packet_history(timestamp, rssi, snr)"
    )
    conn.commit()
    conn.close()
    reset_pinned_index_cache()
    assert pinned_index_available("idx_packet_history_signal_time") is True


def test_probe_is_cached_within_ttl(indexed_db, monkeypatch):
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    assert pinned_index_available("idx_packet_history_signal_time") is False
    # Build the index behind the cache's back: the cached answer must stand.
    conn = sqlite3.connect(indexed_db)
    conn.execute(
        "CREATE INDEX idx_packet_history_signal_time"
        " ON packet_history(timestamp, rssi, snr)"
    )
    conn.commit()
    conn.close()
    assert pinned_index_available("idx_packet_history_signal_time") is False
    reset_pinned_index_cache()
    assert pinned_index_available("idx_packet_history_signal_time") is True


def test_unreachable_database_counts_as_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        db_connection, "_resolve_db_path", lambda: str(tmp_path / "nope.db")
    )
    assert pinned_index_available("idx_packet_history_signal_time") is False


def test_core_indexes_build_logs_progress(indexed_db, monkeypatch, caplog):
    """The per-index progress lines: an operator must see the build move."""
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    conn = sqlite3.connect(indexed_db)
    with caplog.at_level("INFO", logger="malla.migrations.structural"):
        _apply_core_indexes(conn, None)
    conn.commit()
    conn.close()
    building = [r for r in caplog.records if "Building index" in r.message]
    built = [r for r in caplog.records if "Built index" in r.message]
    assert building, "expected a 'Building index N/M' line per index"
    assert built, "expected a 'Built index' completion line per index"
    assert any("1/" in r.message for r in building)
    # after the run the index actually exists
    conn = sqlite3.connect(indexed_db)
    present = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_packet_history_signal_time" in present


def test_signal_stats_work_without_the_index(indexed_db, monkeypatch):
    """The degradation contract: no index, no error — correct unpinned result."""
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    stats = AnalyticsService._get_signal_quality_statistics({}, 0.0)
    assert stats["avg_rssi"] is not None
    assert stats["avg_snr"] is not None
    assert stats["total_measurements"] == 50
    # distribution shape from the seeded rows
    assert stats["rssi_distribution"]["good"] == 29
    assert stats["snr_distribution"]["good"] == 41


def test_signal_stats_use_the_index_once_built(indexed_db, monkeypatch):
    """After the build completes the pinned plan returns (same results)."""
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: indexed_db)
    conn = sqlite3.connect(indexed_db)
    conn.execute(
        "CREATE INDEX idx_packet_history_signal_time"
        " ON packet_history(timestamp, rssi, snr)"
    )
    conn.commit()
    conn.close()
    reset_pinned_index_cache()
    stats = AnalyticsService._get_signal_quality_statistics({}, 0.0)
    assert stats["total_measurements"] == 50
