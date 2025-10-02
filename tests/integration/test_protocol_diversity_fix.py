"""
Integration test to verify Protocol Diversity is not limited to 10 types.

This test ensures that the dashboard stats endpoint returns ALL protocol types
from the last 24 hours, not just the top 10.
"""

import tempfile
import time

import pytest

from malla.config import AppConfig
from src.malla.web_ui import create_app


class TestProtocolDiversityFix:
    """Test that protocol diversity shows all protocol types, not just 10."""

    @pytest.fixture
    def test_db_with_many_protocols(self):
        """Create a test database with more than 10 protocol types."""
        # Create a temporary database
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        # Create connection directly using sqlite3
        import sqlite3

        conn = sqlite3.connect(temp_db.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_info (
                node_id TEXT PRIMARY KEY,
                short_name TEXT,
                long_name TEXT,
                last_seen INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                from_node_id TEXT,
                to_node_id TEXT,
                portnum INTEGER,
                portnum_name TEXT,
                gateway_id TEXT,
                channel_id INTEGER,
                mesh_packet_id INTEGER,
                rssi REAL,
                snr REAL,
                hop_limit INTEGER,
                hop_start INTEGER,
                payload_length INTEGER,
                processed_successfully INTEGER,
                raw_payload BLOB
            )
        """)

        # Insert 15 different protocol types (more than the old limit of 10)
        # Each with recent timestamps (within 24 hours)
        current_time = time.time()
        protocol_types = [
            "TEXT_MESSAGE_APP",
            "POSITION_APP",
            "NODEINFO_APP",
            "TELEMETRY_APP",
            "TRACEROUTE_APP",
            "ROUTING_APP",
            "ADMIN_APP",
            "NEIGHBORINFO_APP",
            "AUDIO_APP",
            "DETECTION_SENSOR_APP",
            "REPLY_APP",
            "IP_TUNNEL_APP",
            "PAXCOUNTER_APP",
            "SERIAL_APP",
            "STORE_FORWARD_APP",
        ]

        # Insert packets for each protocol type
        for idx, protocol in enumerate(protocol_types):
            cursor.execute(
                """
                INSERT INTO packet_history
                (timestamp, from_node_id, to_node_id, portnum, portnum_name,
                 gateway_id, channel_id, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    current_time - (idx * 60),  # Recent timestamps
                    f"!{1000 + idx:08x}",
                    f"!{2000 + idx:08x}",
                    idx,
                    protocol,
                    "!gateway01",
                    0,
                    1,
                ),
            )

        conn.commit()
        conn.close()

        yield temp_db.name

        # Cleanup
        import os

        os.unlink(temp_db.name)

    @pytest.mark.integration
    @pytest.mark.api
    def test_protocol_diversity_shows_all_types_not_limited_to_10(
        self, test_db_with_many_protocols
    ):
        """Test that protocol diversity returns all protocol types, not just 10.

        This test verifies the fix for the issue where protocol diversity was
        limited to 10 types even when more were present in the database.
        """
        # Create test app with the test database
        cfg = AppConfig(database_file=test_db_with_many_protocols)
        app = create_app(cfg)

        with app.test_client() as client:
            # Call the stats API endpoint
            response = client.get("/api/stats")
            assert response.status_code == 200

            data = response.get_json()
            assert "packet_types" in data

            packet_types = data["packet_types"]
            assert isinstance(packet_types, list)

            # This is the key assertion - we should get all 15 protocol types,
            # not just 10 (the old LIMIT)
            assert len(packet_types) == 15, (
                f"Expected 15 protocol types, but got {len(packet_types)}. "
                f"Protocol types returned: {[pt['portnum_name'] for pt in packet_types]}"
            )

            # Verify all expected protocols are present
            protocol_names = {pt["portnum_name"] for pt in packet_types}
            expected_protocols = {
                "TEXT_MESSAGE_APP",
                "POSITION_APP",
                "NODEINFO_APP",
                "TELEMETRY_APP",
                "TRACEROUTE_APP",
                "ROUTING_APP",
                "ADMIN_APP",
                "NEIGHBORINFO_APP",
                "AUDIO_APP",
                "DETECTION_SENSOR_APP",
                "REPLY_APP",
                "IP_TUNNEL_APP",
                "PAXCOUNTER_APP",
                "SERIAL_APP",
                "STORE_FORWARD_APP",
            }
            assert protocol_names == expected_protocols, (
                f"Missing or unexpected protocols. "
                f"Expected: {expected_protocols}, Got: {protocol_names}"
            )

            # Verify each protocol type has a count
            for pt in packet_types:
                assert "portnum_name" in pt
                assert "count" in pt
                assert pt["count"] > 0
