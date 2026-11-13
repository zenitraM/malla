"""Tests for position validity filtering (null-island firmware bug).

Firmware sometimes emits near-zero (~0, ~0) coordinates instead of an exact
(0, 0). Such fixes must never reach the map or the longest-link distance
calculations: readers fall back to the previous valid position instead.
"""

import math
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from meshtastic import mesh_pb2

from malla.database.repositories import LocationRepository
from malla.utils.geo_utils import is_valid_position

pytestmark = pytest.mark.unit

VALID_LAT = 52.37
VALID_LON = 4.89


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "positions.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                portnum INTEGER,
                portnum_name TEXT,
                from_node_id INTEGER,
                raw_payload BLOB,
                processed_successfully INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE node_info (
                node_id INTEGER PRIMARY KEY,
                long_name TEXT,
                short_name TEXT,
                hw_model TEXT,
                role TEXT,
                primary_channel TEXT
            )
        """)
        conn.commit()
    return path


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _position_payload(lat, lon, altitude=42):
    return mesh_pb2.Position(
        latitude_i=int(lat * 1e7), longitude_i=int(lon * 1e7), altitude=altitude
    ).SerializeToString()


def _insert_position(conn, node_id, timestamp, lat, lon):
    conn.execute(
        """
        INSERT INTO packet_history
            (timestamp, portnum, portnum_name, from_node_id, raw_payload)
        VALUES (?, 3, 'POSITION_APP', ?, ?)
        """,
        (timestamp, node_id, _position_payload(lat, lon)),
    )
    conn.commit()


class TestIsValidPosition:
    def test_accepts_normal_coordinates(self):
        assert is_valid_position(VALID_LAT, VALID_LON) is True

    def test_accepts_equator_far_from_null_island(self):
        assert is_valid_position(0.0, 36.8) is True

    def test_rejects_none(self):
        assert is_valid_position(None, VALID_LON) is False
        assert is_valid_position(VALID_LAT, None) is False

    def test_rejects_exact_zero(self):
        assert is_valid_position(0.0, 0.0) is False

    def test_rejects_near_null_island_firmware_garbage(self):
        assert is_valid_position(0.00012, -0.003) is False
        assert is_valid_position(0.1, 0.1) is False

    def test_rejects_out_of_range(self):
        assert is_valid_position(95.0, VALID_LON) is False
        assert is_valid_position(VALID_LAT, 200.0) is False
        assert is_valid_position(-91.0, VALID_LON) is False

    def test_rejects_non_finite(self):
        assert is_valid_position(math.nan, VALID_LON) is False
        assert is_valid_position(VALID_LAT, math.inf) is False


class TestGetNodeLocations:
    def test_falls_back_to_previous_valid_fix(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, VALID_LAT, VALID_LON)
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            locations = LocationRepository.get_node_locations()

        assert len(locations) == 1
        entry = locations[0]
        assert entry["node_id"] == 100
        assert entry["latitude"] == pytest.approx(VALID_LAT)
        assert entry["longitude"] == pytest.approx(VALID_LON)
        assert entry["timestamp"] == 100.0

    def test_node_with_only_garbage_is_absent(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, 0.00012, -0.003)
            _insert_position(conn, 100, 200.0, 0.0, 0.0)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            locations = LocationRepository.get_node_locations()

        assert locations == []

    def test_uses_newest_valid_position(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, 51.9, 4.4)
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)
            _insert_position(conn, 100, 300.0, VALID_LAT, VALID_LON)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            locations = LocationRepository.get_node_locations()

        assert len(locations) == 1
        assert locations[0]["timestamp"] == 300.0
        assert locations[0]["latitude"] == pytest.approx(VALID_LAT)


class TestNodeLocationHistory:
    def test_history_filters_garbage_rows(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, 51.9, 4.4)
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)
            _insert_position(conn, 100, 300.0, VALID_LAT, VALID_LON)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            history = LocationRepository.get_node_location_history(100)
            batched = LocationRepository.get_nodes_location_history([100])

        assert [h["timestamp"] for h in history] == [300.0, 100.0]
        assert [h["timestamp"] for h in batched[100]] == [300.0, 100.0]


class TestGetLatestNodeLocation:
    def test_falls_back_past_garbage_latest(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, VALID_LAT, VALID_LON)
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            location = LocationRepository.get_latest_node_location(100)

        assert location is not None
        assert location["latitude"] == pytest.approx(VALID_LAT)
        assert location["timestamp"] == 100.0

    def test_returns_none_when_only_garbage(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            location = LocationRepository.get_latest_node_location(100)

        assert location is None


class TestGetNodeLocationAtTimestamp:
    def test_skips_garbage_before_target(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, VALID_LAT, VALID_LON)
            _insert_position(conn, 100, 200.0, 0.00012, -0.003)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            location = LocationRepository.get_node_location_at_timestamp(100, 250.0)

        assert location is not None
        assert location["latitude"] == pytest.approx(VALID_LAT)
        assert location["timestamp"] == 100.0
        assert "ago" in location["age_warning"]

    def test_falls_forward_to_valid_after_target(self, database):
        with closing(_connection(database)) as conn:
            _insert_position(conn, 100, 100.0, 0.00012, -0.003)
            _insert_position(conn, 100, 200.0, VALID_LAT, VALID_LON)

        with patch(
            "malla.database.repositories.get_db_connection",
            side_effect=lambda: _connection(database),
        ):
            location = LocationRepository.get_node_location_at_timestamp(100, 150.0)

        assert location is not None
        assert location["latitude"] == pytest.approx(VALID_LAT)
        assert location["timestamp"] == 200.0
        assert "later" in location["age_warning"]
