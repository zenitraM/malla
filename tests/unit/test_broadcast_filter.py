"""
Tests for broadcast packet filtering functionality.

This module tests the exclude_broadcast filter functionality in PacketRepository
to ensure broadcast packets (to_node_id == 4294967295) can be properly filtered out.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.malla.database.repositories import PacketRepository


class TestBroadcastFilter:
    """Test broadcast packet filtering at the API/repository level."""

    @patch("src.malla.database.repositories.get_db_connection")
    def test_packet_repository_exclude_broadcast_filter(self, mock_get_db_connection):
        """Test that PacketRepository correctly excludes broadcast packets when filter is enabled."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db_connection.return_value = mock_conn

        # Mock the total count query
        mock_cursor.fetchone.return_value = [2]  # Return as list/tuple with count

        # Mock packet records - some broadcast, some not
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "timestamp": 1000,
                "from_node_id": 123,
                "to_node_id": 456,  # Regular packet
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!433d0c24",
                "channel_id": "LongFast",
                "mesh_packet_id": "abc123",
                "rssi": -80,
                "snr": 5,
                "hop_limit": 3,
                "hop_start": 5,
                "payload_length": 50,
                "processed_successfully": 1,
                "raw_payload": b"test",
                "timestamp_str": "2023-01-01 00:00:00",
                "hop_count": 2,
            },
            {
                "id": 2,
                "timestamp": 2000,
                "from_node_id": 789,
                "to_node_id": 999,  # Another regular packet
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!433d0c25",
                "channel_id": "LongFast",
                "mesh_packet_id": "def456",
                "rssi": -75,
                "snr": 7,
                "hop_limit": 2,
                "hop_start": 4,
                "payload_length": 30,
                "processed_successfully": 1,
                "raw_payload": b"test2",
                "timestamp_str": "2023-01-01 00:01:00",
                "hop_count": 2,
            },
        ]

        # Test with exclude_broadcast filter enabled
        result = PacketRepository.get_packets(
            limit=10, offset=0, filters={"exclude_broadcast": True}
        )

        # Verify the SQL query was called and contains the broadcast filter
        mock_cursor.execute.assert_called()
        
        # Get the SQL query from the execute call
        sql_query_args = mock_cursor.execute.call_args[0]
        sql_query = sql_query_args[0]
        
        # Verify the exclude broadcast condition is in the SQL
        assert "to_node_id != 4294967295" in sql_query or "(to_node_id IS NULL OR to_node_id != 4294967295)" in sql_query

        # Verify the result structure
        assert "packets" in result
        assert "total_count" in result
        assert result["total_count"] == 2

    @patch("src.malla.database.repositories.get_db_connection")
    def test_packet_repository_include_broadcast_filter_disabled(self, mock_get_db_connection):
        """Test that PacketRepository includes broadcast packets when filter is disabled."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db_connection.return_value = mock_conn

        # Mock the total count query
        mock_cursor.fetchone.return_value = [3]  # Return as list/tuple with count

        # Mock packet records including broadcast
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "timestamp": 1000,
                "from_node_id": 123,
                "to_node_id": 456,  # Regular packet
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!433d0c24",
                "channel_id": "LongFast",
                "mesh_packet_id": "abc123",
                "rssi": -80,
                "snr": 5,
                "hop_limit": 3,
                "hop_start": 5,
                "payload_length": 50,
                "processed_successfully": 1,
                "raw_payload": b"test",
                "timestamp_str": "2023-01-01 00:00:00",
                "hop_count": 2,
            },
            {
                "id": 2,
                "timestamp": 2000,
                "from_node_id": 789,
                "to_node_id": 4294967295,  # Broadcast packet
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!433d0c25",
                "channel_id": "LongFast",
                "mesh_packet_id": "def456",
                "rssi": -75,
                "snr": 7,
                "hop_limit": 2,
                "hop_start": 4,
                "payload_length": 30,
                "processed_successfully": 1,
                "raw_payload": b"test2",
                "timestamp_str": "2023-01-01 00:01:00",
                "hop_count": 2,
            },
        ]

        # Test without exclude_broadcast filter (should include broadcast packets)
        result = PacketRepository.get_packets(
            limit=10, offset=0, filters={}
        )

        # Verify the SQL query was called without broadcast filter
        mock_cursor.execute.assert_called()
        
        # Get the SQL query from the execute call
        sql_query_args = mock_cursor.execute.call_args[0]
        sql_query = sql_query_args[0]
        
        # Verify the exclude broadcast condition is NOT in the SQL
        assert "to_node_id != 4294967295" not in sql_query

        # Verify the result structure
        assert "packets" in result
        assert "total_count" in result
        assert result["total_count"] == 3