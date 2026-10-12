"""
Unit tests for TracerouteService class.

Tests the business logic and service methods for traceroute analysis.
"""

from datetime import datetime
from unittest.mock import patch

from src.malla.services.traceroute_service import TracerouteService


class TestTracerouteServiceLongestLinks:
    """Test TracerouteService longest links analysis functionality."""

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository.get_nodes_location_history")
    @patch("src.malla.services.traceroute_service.get_traceroute_hops_for_longest_links")
    def test_longest_links_analysis_basic(
        self, mock_get_hops, mock_get_locs, mock_get_names
    ):
        """Test basic longest links analysis functionality."""
        now_ts = datetime.now().timestamp()
        mock_hop = {
            "packet_id": 1,
            "direction": "forward",
            "hop_index": 0,
            "timestamp": now_ts,
            "from_node_id": 100,
            "to_node_id": 200,
            "snr": -5.0,
        }
        mock_get_hops.return_value = [mock_hop]
        mock_get_locs.return_value = {
            100: [
                {
                    "from_node_id": 100,
                    "latitude": 40.0,
                    "longitude": -3.0,
                    "altitude": 100,
                    "timestamp": now_ts,
                }
            ],
            200: [
                {
                    "from_node_id": 200,
                    "latitude": 40.045,
                    "longitude": -3.0,
                    "altitude": 100,
                    "timestamp": now_ts,
                }
            ],
        }
        mock_get_names.return_value = {100: "Node100", 200: "Node200"}

        # Call the method
        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=1.0, min_snr=-10.0, max_results=10
        )

        # Verify structure
        assert "summary" in result
        assert "direct_links" in result
        assert "indirect_links" in result

        # Verify summary
        summary = result["summary"]
        assert summary["total_links"] == 1
        assert summary["direct_links"] == 1
        assert summary["longest_direct"] is not None
        assert summary["longest_path"] is None

        # Verify direct links
        assert len(result["direct_links"]) == 1
        direct_link = result["direct_links"][0]
        assert direct_link["from_node_id"] == 100
        assert direct_link["to_node_id"] == 200
        assert direct_link["distance_km"] > 4.0
        assert direct_link["avg_snr"] == -5.0
        assert direct_link["traceroute_count"] == 1

    @patch("src.malla.services.traceroute_service.get_traceroute_hops_for_longest_links")
    def test_longest_links_analysis_empty_data(self, mock_get_hops):
        """Test analysis with no traceroute data."""
        mock_get_hops.return_value = []

        # Call the method
        result = TracerouteService.get_longest_links_analysis()

        # Should return empty results with proper structure
        assert result["summary"]["total_links"] == 0
        assert result["summary"]["direct_links"] == 0
        assert result["summary"]["longest_direct"] is None
        assert result["summary"]["longest_path"] is None
        assert len(result["direct_links"]) == 0
        assert len(result["indirect_links"]) == 0

    @staticmethod
    def _hop(packet_id, hop_index, from_node, to_node, snr, timestamp):
        return {
            "packet_id": packet_id,
            "direction": "forward",
            "hop_index": hop_index,
            "timestamp": timestamp,
            "from_node_id": from_node,
            "to_node_id": to_node,
            "snr": snr,
        }

    @staticmethod
    def _linear_locations(node_positions, timestamp):
        return {
            node_id: [
                {
                    "from_node_id": node_id,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude": 100,
                    "timestamp": timestamp,
                }
            ]
            for node_id, (lat, lon) in node_positions.items()
        }

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository.get_nodes_location_history")
    @patch("src.malla.services.traceroute_service.get_traceroute_hops_for_longest_links")
    def test_longest_links_broken_path_not_aggregated(
        self, mock_get_hops, mock_get_locs, mock_get_names
    ):
        """A zero-SNR middle hop splits A->B->C->D; segments must not join as A->D."""
        now_ts = datetime.now().timestamp()
        mock_get_hops.return_value = [
            self._hop(1, 0, 100, 200, -5.0, now_ts),
            self._hop(1, 1, 200, 300, 0.0, now_ts),
            self._hop(1, 2, 300, 400, -5.0, now_ts),
        ]
        mock_get_locs.return_value = self._linear_locations(
            {
                100: (40.000, -3.0),
                200: (40.045, -3.0),
                300: (40.090, -3.0),
                400: (40.135, -3.0),
            },
            now_ts,
        )
        mock_get_names.return_value = {nid: f"Node{nid}" for nid in (100, 200, 300, 400)}

        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=1.0, min_snr=-30.0, max_results=10
        )

        direct = {(link["from_node_id"], link["to_node_id"]) for link in result["direct_links"]}
        assert direct == {(100, 200), (300, 400)}
        assert result["indirect_links"] == []
        assert result["summary"]["longest_path"] is None
        assert result["summary"]["longest_direct"] is not None

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository.get_nodes_location_history")
    @patch("src.malla.services.traceroute_service.get_traceroute_hops_for_longest_links")
    def test_longest_links_contiguous_path_aggregated(
        self, mock_get_hops, mock_get_locs, mock_get_names
    ):
        """A fully evidenced A->B->C path still aggregates with correct hops/preview."""
        now_ts = datetime.now().timestamp()
        mock_get_hops.return_value = [
            self._hop(1, 0, 100, 200, -5.0, now_ts),
            self._hop(1, 1, 200, 300, -5.0, now_ts),
        ]
        mock_get_locs.return_value = self._linear_locations(
            {100: (40.000, -3.0), 200: (40.045, -3.0), 300: (40.090, -3.0)},
            now_ts,
        )
        mock_get_names.return_value = {nid: f"Node{nid}" for nid in (100, 200, 300)}

        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=1.0, min_snr=-10.0, max_results=10
        )

        assert len(result["indirect_links"]) == 1
        path = result["indirect_links"][0]
        assert (path["from_node_id"], path["to_node_id"]) == (100, 300)
        assert path["hop_count"] == 2
        assert path["route_preview"] == ["Node100", "Node200", "Node300"]
        assert path["total_distance_km"] > 9.0
        assert path["avg_snr"] == -5.0

    @patch("src.malla.services.traceroute_service.LocationRepository.get_node_locations")
    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.get_traceroute_hops_for_graph")
    def test_network_graph_broken_path_no_indirect(
        self, mock_get_hops, mock_get_names, mock_get_locs
    ):
        """Graph indirect connections require continuity: no fake A->D shortcut."""
        from src.malla.services.traceroute_service import _NETWORK_GRAPH_CACHE

        _NETWORK_GRAPH_CACHE.clear()
        now_ts = datetime.now().timestamp()
        mock_get_hops.return_value = [
            self._hop(1, 0, 100, 200, -5.0, now_ts),
            self._hop(1, 1, 200, 300, 0.0, now_ts),
            self._hop(1, 2, 300, 400, -5.0, now_ts),
        ]
        mock_get_names.return_value = {nid: f"Node{nid}" for nid in (100, 200, 300, 400)}
        mock_get_locs.return_value = []

        try:
            result = TracerouteService.get_network_graph_data(
                hours=24,
                min_snr=-200.0,
                include_indirect=True,
                filters={"start_time": now_ts - 60, "end_time": now_ts + 60},
            )
        finally:
            _NETWORK_GRAPH_CACHE.clear()

        direct = {(link["source"], link["target"]) for link in result["links"]}
        assert direct == {(100, 200), (300, 400)}
        assert result["indirect_connections"] == []
        assert result["stats"]["links_filtered_due_to_snr_0"] == 1

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.get_node_traceroute_statistics")
    def test_node_traceroute_stats(self, mock_get_stats, mock_get_names):
        """Test node traceroute stats delegates to SQL statistics."""
        mock_get_stats.return_value = {
            "node_id": 12345,
            "as_source": {"total": 10, "successful": 8, "success_rate": 80.0},
            "as_destination": {"total": 5, "successful": 4, "success_rate": 80.0},
            "as_intermediate_hop": {"participation_count": 3},
            "total_involvement": 18,
        }
        mock_get_names.return_value = {12345: "TestNode"}

        stats = TracerouteService.get_node_traceroute_stats(12345)
        assert stats["node_id"] == 12345
        assert stats["node_name"] == "TestNode"
        assert stats["total_involvement"] == 18
