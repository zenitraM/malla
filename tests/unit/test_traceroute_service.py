"""
Unit tests for TracerouteService class.

Tests the business logic and service methods for traceroute analysis.
"""

from datetime import datetime
from unittest.mock import Mock, patch

from src.malla.services.traceroute_service import TracerouteService


class TestTracerouteServiceLongestLinks:
    """Test TracerouteService longest links analysis functionality."""

    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    def test_longest_links_analysis_basic(self, mock_traceroute_packet, mock_repo):
        """Test basic longest links analysis functionality."""
        # Mock repository response
        mock_packet_data = {
            "id": 1,
            "from_node_id": 100,
            "to_node_id": 200,
            "timestamp": datetime.now().timestamp(),
            "gateway_id": "!12345678",
            "raw_payload": b"mock_payload",
            "processed_successfully": True,
        }

        mock_repo.get_traceroute_packets.return_value = {"packets": [mock_packet_data]}

        # Mock TraceroutePacket
        mock_packet = Mock()
        mock_packet.from_node_id = 100
        mock_packet.to_node_id = 200

        # Mock RF hop
        mock_hop = Mock()
        mock_hop.from_node_id = 100
        mock_hop.to_node_id = 200
        mock_hop.from_node_name = "Node100"
        mock_hop.to_node_name = "Node200"
        mock_hop.distance_km = 5.0  # 5km
        mock_hop.snr = -5.0

        mock_packet.get_rf_hops.return_value = [mock_hop]
        mock_packet.get_display_hops.return_value = [mock_hop]
        mock_packet.calculate_hop_distances = Mock()

        mock_traceroute_packet.return_value = mock_packet

        # Call the method
        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=1.0, min_snr=-10.0, max_results=10
        )

        # Verify TraceroutePacket was called with correct arguments
        mock_traceroute_packet.assert_called_with(
            packet_data=mock_packet_data, resolve_names=True
        )

        # Verify structure
        assert "summary" in result
        assert "direct_links" in result
        assert "indirect_links" in result

        # Verify summary
        summary = result["summary"]
        assert "total_links" in summary
        assert "direct_links" in summary
        assert "longest_direct" in summary
        assert "longest_path" in summary

        # Verify direct links
        assert len(result["direct_links"]) == 1
        direct_link = result["direct_links"][0]
        assert direct_link["from_node_id"] == 100
        assert direct_link["to_node_id"] == 200
        assert direct_link["distance_km"] == 5.0
        assert direct_link["avg_snr"] == -5.0
        assert direct_link["traceroute_count"] == 1

    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_longest_links_analysis_empty_data(self, mock_repo):
        """Test analysis with no traceroute data."""
        # Mock empty repository response
        mock_repo.get_traceroute_packets.return_value = {"packets": []}

        # Call the method
        result = TracerouteService.get_longest_links_analysis()

        # Should return empty results with proper structure
        assert result["summary"]["total_links"] == 0
        assert result["summary"]["direct_links"] == 0
        assert result["summary"]["longest_direct"] is None
        assert result["summary"]["longest_path"] is None
        assert len(result["direct_links"]) == 0
        assert len(result["indirect_links"]) == 0
