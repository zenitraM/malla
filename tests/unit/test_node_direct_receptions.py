from unittest.mock import Mock, patch

import pytest

from src.malla.database.repositories import NodeRepository


class TestNodeRepositoryDirectReceptions:
    """Unit tests for NodeRepository.get_direct_receptions"""

    @pytest.mark.unit
    @patch("src.malla.database.repositories.get_db_connection")
    def test_get_direct_receptions_returns_expected_structure(self, mock_get_db):
        """Verify the method returns properly structured dictionaries."""
        # Arrange – set up mocked DB connection/ cursor
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock stats query results
        mock_cursor.fetchall.side_effect = [
            # First call: stats query
            [
                {
                    "from_node_id": 123,
                    "long_name": "Alpha",
                    "short_name": "A",
                    "packet_count": 2,
                    "rssi_avg": -75.0,
                    "rssi_min": -70.0,
                    "rssi_max": -80.0,
                    "snr_avg": 7.5,
                    "snr_min": 5.0,
                    "snr_max": 10.0,
                    "first_seen": 1700000000.0,
                    "last_seen": 1700000100.0,
                }
            ],
            # Second call: packets query
            [
                {
                    "packet_id": 1,
                    "timestamp": 1700000000.0,
                    "from_node_id": 123,
                    "rssi": -80,
                    "snr": 5,
                },
                {
                    "packet_id": 2,
                    "timestamp": 1700000100.0,
                    "from_node_id": 123,
                    "rssi": -70,
                    "snr": 10,
                },
            ],
        ]

        # Act
        result = NodeRepository.get_direct_receptions(11223344, limit=100)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1  # One node with aggregated stats
        first = result[0]
        assert set(first.keys()) == {
            "from_node_id",
            "from_node_name",
            "packet_count",
            "rssi_avg",
            "rssi_min",
            "rssi_max",
            "snr_avg",
            "snr_min",
            "snr_max",
            "first_seen",
            "last_seen",
            "packets",
        }
        assert first["from_node_name"] == "Alpha"
