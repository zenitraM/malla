"""
Unit tests for NodeRepository.

Tests the repository methods in isolation with mocked database connections.
"""

from unittest.mock import Mock, patch

import pytest

from src.malla.database.repositories import NodeRepository


class TestNodeRepository:
    """Test NodeRepository methods."""

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_node_details_with_valid_node_id(self, mock_get_db):
        """Test get_node_details with a valid node ID."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query results
        mock_cursor.fetchall.return_value = [
            {
                "node_id": 1128074276,
                "hex_id": "!433d0c24",
                "node_name": "Test Gateway Alpha",
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "total_packets": 50,
                "last_seen": 1640995200.0,  # 2022-01-01 00:00:00
                "first_seen": 1640908800.0,  # 2021-12-31 00:00:00
                "unique_destinations": 5,
                "unique_gateways": 2,
                "avg_rssi": -75.5,
                "avg_snr": 8.2,
                "avg_hops": 1.5,
            }
        ]

        # Mock the recent packets query
        mock_cursor.fetchall.side_effect = [
            [],  # recent packets
            [],  # protocols
            [],  # neighbors
        ]

        # Mock the location query
        mock_cursor.fetchone.side_effect = [
            {
                "node_id": 1128074276,
                "node_name": "Test Gateway Alpha",
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "total_packets": 50,
                "last_seen": 1640995200.0,
                "first_seen": 1640908800.0,
                "unique_destinations": 5,
                "unique_gateways": 2,
                "avg_rssi": -75.5,
                "avg_snr": 8.2,
                "avg_hops": 1.5,
            },
            None,  # location query
        ]

        # Mock get_bulk_node_names
        with patch.object(NodeRepository, "get_bulk_node_names", return_value={}):
            result = NodeRepository.get_node_details(1128074276)

        # Verify the result structure
        assert result is not None
        assert "node" in result
        assert "recent_packets" in result
        assert "protocols" in result
        assert "received_gateways" in result
        assert "location" in result

        # Verify node data
        node = result["node"]
        assert node["node_id"] == 1128074276
        assert node["hex_id"] == "!433d0c24"  # Fixed hex ID
        assert node["node_name"] == "Test Gateway Alpha"
        assert node["hw_model"] == "TBEAM"
        assert node["role"] == "ROUTER"
        assert node["total_packets"] == 50
        assert node["unique_destinations"] == 5
        assert node["avg_rssi"] == -75.5
        assert node["avg_snr"] == 8.2
        assert node["avg_hops"] == 1.5

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_node_details_with_hex_node_id(self, mock_get_db):
        """Test get_node_details with a hex node ID."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query results
        mock_cursor.fetchone.side_effect = [
            {
                "node_id": 1128074276,
                "node_name": "Test Gateway Alpha",
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "total_packets": 50,
                "last_seen": 1640995200.0,
                "first_seen": 1640908800.0,
                "unique_destinations": 5,
                "unique_gateways": 2,
                "avg_rssi": -75.5,
                "avg_snr": 8.2,
                "avg_hops": 1.5,
            },
            None,  # location query
        ]

        mock_cursor.fetchall.side_effect = [[], [], []]  # packets, protocols, neighbors

        with patch.object(NodeRepository, "get_bulk_node_names", return_value={}):
            # Test with hex format - convert to int first
            hex_node_id = "!433d0c24"
            node_id_int = int(hex_node_id[1:], 16)  # Convert hex to int
            result = NodeRepository.get_node_details(node_id_int)

        assert result is not None
        assert result["node"]["node_id"] == 1128074276

        # Verify the execute call was made with the correct integer node ID
        mock_cursor.execute.assert_called()
        # The first call should be with the converted integer node ID
        first_call_args = mock_cursor.execute.call_args_list[0]
        assert first_call_args[0][1] == (1128074276,)

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_node_details_with_nonexistent_node(self, mock_get_db):
        """Test get_node_details with a non-existent node ID."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query to return no results
        mock_cursor.fetchone.side_effect = [None, None]  # main query, node_info query

        result = NodeRepository.get_node_details(999999999)

        assert result is None

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_node_details_node_exists_but_no_packets(self, mock_get_db):
        """Test get_node_details for a node that exists but has no packets."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query results - no packets but node exists in node_info
        mock_cursor.fetchone.side_effect = [
            None,  # main query (no packets)
            {  # node_info query
                "node_id": 1128074276,
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
                "hw_model": "TBEAM",
                "role": "ROUTER",
            },
        ]

        result = NodeRepository.get_node_details(1128074276)

        assert result is not None
        assert result["node"]["node_id"] == 1128074276
        assert result["node"]["total_packets"] == 0
        assert result["node"]["last_seen_relative"] == "Never"
        assert result["recent_packets"] == []
        assert result["protocols"] == []
        assert result["received_gateways"] == []

    @pytest.mark.unit
    def test_get_node_details_with_invalid_node_id(self):
        """Test get_node_details with invalid node ID."""
        # Test with an invalid node ID (negative number)
        result = NodeRepository.get_node_details(-1)
        assert result is None

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_bulk_node_names(self, mock_get_db):
        """Test get_bulk_node_names method."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query results
        mock_cursor.fetchall.return_value = [
            {
                "node_id": 1128074276,
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
            },
            {"node_id": 1128074277, "long_name": None, "short_name": "TMB"},
            {"node_id": 1128074278, "long_name": None, "short_name": None},
        ]

        node_ids = [1128074276, 1128074277, 1128074278, 999999999]
        result = NodeRepository.get_bulk_node_names(node_ids)

        assert result[1128074276] == "Test Gateway Alpha"
        assert result[1128074277] == "TMB"
        assert result[1128074278] == "!433d0c26"  # Fixed hex ID
        assert result[999999999] == "!3b9ac9ff"  # Missing node, hex fallback

    @pytest.mark.unit
    def test_get_bulk_node_names_empty_list(self):
        """Test get_bulk_node_names with empty list."""
        result = NodeRepository.get_bulk_node_names([])
        assert result == {}
