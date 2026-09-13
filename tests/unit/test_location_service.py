"""
Unit tests for LocationService node activity consolidation and location enrichment.
"""

from unittest.mock import patch

import pytest

from malla.services.location_service import LocationService


class TestLocationServiceNodeLocations:
    """Test LocationService.get_node_locations consolidation of timestamps."""

    @pytest.mark.unit
    def test_node_active_timestamp_consolidated_from_traceroute(self):
        """When traceroute activity is newer than position, node.timestamp uses traceroute time."""
        pos_time = 1000.0
        tr_time = 5000.0

        mock_raw_locations = [
            {
                "node_id": 12345,
                "hex_id": "!00003039",
                "display_name": "Test Node",
                "long_name": "Test Node Long",
                "short_name": "TN",
                "hw_model": "T-Beam",
                "role": "ROUTER",
                "latitude": 40.0,
                "longitude": -95.0,
                "altitude": 100,
                "timestamp": pos_time,
                "precision_bits": 16,
                "precision_meters": 364.0,
                "sats_in_view": 8,
            }
        ]

        mock_network_data = {
            "nodes": [
                {
                    "id": 12345,
                    "name": "Test Node",
                    "packet_count": 5,
                    "avg_snr": 8.5,
                    "last_seen": tr_time,
                }
            ],
            "links": [],
        }

        with patch("malla.database.repositories.LocationRepository.get_node_locations", return_value=mock_raw_locations):
            results = LocationService.get_node_locations(
                filters={},
                network_data=mock_network_data,
                packet_links=[],
            )

        assert len(results) == 1
        node = results[0]
        # timestamp must be updated to the active (traceroute) timestamp
        assert node["timestamp"] == tr_time
        # position_timestamp must preserve original position packet timestamp
        assert node["position_timestamp"] == pos_time
        assert "position_timestamp_str" in node
        assert node["last_seen_network"] == tr_time

    @pytest.mark.unit
    def test_node_active_timestamp_consolidated_from_packet_link(self):
        """When packet link activity is newer than position and traceroute, node.timestamp uses packet time."""
        pos_time = 1000.0
        pkt_time = 8000.0

        mock_raw_locations = [
            {
                "node_id": 12345,
                "hex_id": "!00003039",
                "display_name": "Test Node",
                "long_name": "Test Node Long",
                "short_name": "TN",
                "hw_model": "T-Beam",
                "role": "ROUTER",
                "latitude": 40.0,
                "longitude": -95.0,
                "altitude": 100,
                "timestamp": pos_time,
            }
        ]

        mock_packet_links = [
            {
                "from_node_id": 12345,
                "to_node_id": 99999,
                "last_seen": pkt_time,
                "total_hops_seen": 2,
            }
        ]

        with patch("malla.database.repositories.LocationRepository.get_node_locations", return_value=mock_raw_locations):
            results = LocationService.get_node_locations(
                filters={},
                network_data={"nodes": [], "links": []},
                packet_links=mock_packet_links,
            )

        assert len(results) == 1
        node = results[0]
        assert node["timestamp"] == pkt_time
        assert node["position_timestamp"] == pos_time
        assert node["last_seen_packet"] == pkt_time

    @pytest.mark.unit
    def test_node_active_timestamp_defaults_to_position_when_newest(self):
        """When position is newest, node.timestamp remains the position timestamp."""
        pos_time = 10000.0
        tr_time = 5000.0

        mock_raw_locations = [
            {
                "node_id": 12345,
                "hex_id": "!00003039",
                "display_name": "Test Node",
                "long_name": "Test Node Long",
                "short_name": "TN",
                "hw_model": "T-Beam",
                "role": "ROUTER",
                "latitude": 40.0,
                "longitude": -95.0,
                "altitude": 100,
                "timestamp": pos_time,
            }
        ]

        mock_network_data = {
            "nodes": [
                {
                    "id": 12345,
                    "name": "Test Node",
                    "packet_count": 1,
                    "last_seen": tr_time,
                }
            ],
            "links": [],
        }

        with patch("malla.database.repositories.LocationRepository.get_node_locations", return_value=mock_raw_locations):
            results = LocationService.get_node_locations(
                filters={},
                network_data=mock_network_data,
                packet_links=[],
            )

        assert len(results) == 1
        node = results[0]
        assert node["timestamp"] == pos_time
        assert node["position_timestamp"] == pos_time
