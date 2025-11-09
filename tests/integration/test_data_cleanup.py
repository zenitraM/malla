"""
Integration tests for data cleanup functionality.

Tests the automatic cleanup of old packet_history and node_info records
based on the data_retention_hours configuration parameter.
"""

import os
import sqlite3
import tempfile
import time

import pytest

from malla import mqtt_capture


class TestDataCleanup:
    """Test data cleanup functionality."""

    @pytest.mark.integration
    def test_cleanup_functionality(self):
        """Test that data cleanup correctly removes old records."""
        # Create a temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_db:
            temp_db_path = temp_db.name

        try:
            # Override database file path
            original_db_file = mqtt_capture.DATABASE_FILE
            mqtt_capture.DATABASE_FILE = temp_db_path

            # Initialize the database
            mqtt_capture.init_database()

            # Insert test data
            current_time = time.time()
            old_time = current_time - (48 * 3600)  # 48 hours ago

            with mqtt_capture.db_lock:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()

                # Insert old packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (old_time, "test/topic", 123456, 654321, 1, "TEXT_MESSAGE_APP"),
                )
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        old_time + 3600,
                        "test/topic2",
                        123457,
                        654322,
                        1,
                        "TEXT_MESSAGE_APP",
                    ),
                )

                # Insert recent packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        current_time - 3600,
                        "test/topic3",
                        123458,
                        654323,
                        1,
                        "TEXT_MESSAGE_APP",
                    ),
                )

                # Insert old node info records
                cursor.execute(
                    "INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                    (123456, "!123456", "Old Node 1", "ON1", old_time, old_time),
                )
                cursor.execute(
                    "INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                    (123457, "!123457", "Old Node 2", "ON2", old_time, old_time),
                )

                # Insert recent node info records
                cursor.execute(
                    "INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        123458,
                        "!123458",
                        "Recent Node",
                        "RN",
                        current_time - 3600,
                        current_time - 3600,
                    ),
                )

                conn.commit()
                conn.close()

            # Verify initial data
            with mqtt_capture.db_lock:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) FROM packet_history")
                cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM node_info")
                cursor.fetchone()[0]

                conn.close()

            # Override data retention hours to 24 hours
            original_retention = mqtt_capture.DATA_RETENTION_HOURS
            mqtt_capture.DATA_RETENTION_HOURS = 24

            try:
                # Run the cleanup function
                mqtt_capture.cleanup_old_data()

                # Verify cleanup results
                with mqtt_capture.db_lock:
                    conn = sqlite3.connect(temp_db_path)
                    cursor = conn.cursor()

                    cursor.execute("SELECT COUNT(*) FROM packet_history")
                    remaining_packets = cursor.fetchone()[0]

                    cursor.execute("SELECT COUNT(*) FROM node_info")
                    remaining_nodes = cursor.fetchone()[0]

                    # Check that old packets were deleted but recent ones remain
                    cursor.execute(
                        "SELECT COUNT(*) FROM packet_history WHERE timestamp < ?",
                        (current_time - 24 * 3600,),
                    )
                    old_packets_remaining = cursor.fetchone()[0]

                    # Check that old nodes were deleted but recent ones remain
                    cursor.execute(
                        "SELECT COUNT(*) FROM node_info WHERE last_updated < ?",
                        (current_time - 24 * 3600,),
                    )
                    old_nodes_remaining = cursor.fetchone()[0]

                    conn.close()

                # Verify results
                assert remaining_packets == 1, (
                    f"Expected 1 packet to remain, got {remaining_packets}"
                )
                assert remaining_nodes == 1, (
                    f"Expected 1 node to remain, got {remaining_nodes}"
                )
                assert old_packets_remaining == 0, (
                    f"Expected 0 old packets to remain, got {old_packets_remaining}"
                )
                assert old_nodes_remaining == 0, (
                    f"Expected 0 old nodes to remain, got {old_nodes_remaining}"
                )

            finally:
                # Restore original retention hours
                mqtt_capture.DATA_RETENTION_HOURS = original_retention

        finally:
            # Restore original database file path
            mqtt_capture.DATABASE_FILE = original_db_file

            # Clean up temporary database
            if os.path.exists(temp_db_path):
                os.unlink(temp_db_path)

    @pytest.mark.integration
    def test_cleanup_disabled(self):
        """Test that cleanup is disabled when retention hours is 0."""
        # Create a temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_db:
            temp_db_path = temp_db.name

        try:
            # Override database file path
            original_db_file = mqtt_capture.DATABASE_FILE
            mqtt_capture.DATABASE_FILE = temp_db_path

            # Initialize the database
            mqtt_capture.init_database()

            # Insert test data
            current_time = time.time()
            old_time = current_time - (48 * 3600)  # 48 hours ago

            with mqtt_capture.db_lock:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()

                # Insert old packet history records
                cursor.execute(
                    "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (old_time, "test/topic", 123456, 654321, 1, "TEXT_MESSAGE_APP"),
                )

                # Insert old node info records
                cursor.execute(
                    "INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                    (123456, "!123456", "Old Node 1", "ON1", old_time, old_time),
                )

                conn.commit()
                conn.close()

            # Verify initial data
            with mqtt_capture.db_lock:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) FROM packet_history")
                initial_packets = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM node_info")
                initial_nodes = cursor.fetchone()[0]

                conn.close()

            # Override data retention hours to 0 (disabled)
            original_retention = mqtt_capture.DATA_RETENTION_HOURS
            mqtt_capture.DATA_RETENTION_HOURS = 0

            try:
                # Run the cleanup function
                mqtt_capture.cleanup_old_data()

                # Verify no cleanup occurred
                with mqtt_capture.db_lock:
                    conn = sqlite3.connect(temp_db_path)
                    cursor = conn.cursor()

                    cursor.execute("SELECT COUNT(*) FROM packet_history")
                    remaining_packets = cursor.fetchone()[0]

                    cursor.execute("SELECT COUNT(*) FROM node_info")
                    remaining_nodes = cursor.fetchone()[0]

                    conn.close()

                # Verify results
                assert remaining_packets == initial_packets, (
                    f"Expected {initial_packets} packets to remain, got {remaining_packets}"
                )
                assert remaining_nodes == initial_nodes, (
                    f"Expected {initial_nodes} nodes to remain, got {remaining_nodes}"
                )

            finally:
                # Restore original retention hours
                mqtt_capture.DATA_RETENTION_HOURS = original_retention

        finally:
            # Restore original database file path
            mqtt_capture.DATABASE_FILE = original_db_file

            # Clean up temporary database
            if os.path.exists(temp_db_path):
                os.unlink(temp_db_path)
