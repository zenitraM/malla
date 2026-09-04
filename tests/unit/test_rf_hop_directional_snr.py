"""
Unit tests for directional RF hop average SNR analysis.
"""

import time
from unittest.mock import MagicMock, Mock, patch

from src.malla.models.traceroute import TracerouteHop, TraceroutePacket
from src.malla.services.location_service import LocationService
from src.malla.services.traceroute_service import (
    _NETWORK_GRAPH_CACHE,
    TracerouteService,
)
from src.malla.utils.signal_quality import TRACEROUTE_UNKNOWN_SNR


class TestRFHopDirectionalSNR:
    """Test directional SNR separation in network graph, location service, and API."""

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_separates_forward_and_return_snr(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """Test that get_network_graph_data separates forward vs return SNR."""
        mock_names.return_value = {10: "Node10", 20: "Node20"}
        mock_loc_repo.get_node_locations.return_value = []

        # Two packets: packet 1 has hop 10 -> 20 (SNR = 5.0), packet 2 has hop 20 -> 10 (SNR = -3.0)
        packets = [
            {
                "id": 1,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"dummy1",
            },
            {
                "id": 2,
                "from_node_id": 20,
                "to_node_id": 10,
                "timestamp": 1010.0,
                "raw_payload": b"dummy2",
            },
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        hop1 = Mock()
        hop1.from_node_id = 10
        hop1.to_node_id = 20
        hop1.from_node_name = "Node10"
        hop1.to_node_name = "Node20"
        hop1.snr = 5.0

        hop2 = Mock()
        hop2.from_node_id = 20
        hop2.to_node_id = 10
        hop2.from_node_name = "Node20"
        hop2.to_node_name = "Node10"
        hop2.snr = -3.0

        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]

        mock_packet_cls.side_effect = [p1, p2]

        # Use unique hours or clear cache
        graph = TracerouteService.get_network_graph_data(
            hours=99, min_snr=-200.0, include_indirect=False
        )

        assert len(graph["links"]) == 1
        link = graph["links"][0]
        assert link["source"] == 10
        assert link["target"] == 20
        # Combined avg SNR = (5.0 + -3.0) / 2 = 1.0
        assert link["avg_snr"] == 1.0
        # Forward: 10 -> 20: 5.0
        assert link["forward_avg_snr"] == 5.0
        assert link["forward_count"] == 1
        # Return: 20 -> 10: -3.0
        assert link["return_avg_snr"] == -3.0
        assert link["return_count"] == 1
        assert link["worst_snr"] == -3.0
        assert link["overall_quality"] in ("good", "fair", "marginal")
        assert link["link_balance"] in ("balanced", "asymmetric_marginal")
        assert link["estimated_reliability"] is not None
        # Strength is decoupled: packet_count=2 -> 1.5 + 2.5 * log10(2) ~= 2.3
        assert 1.5 <= link["strength"] <= 8.0

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_excludes_unknown_snr_sentinel_from_directional_avg(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """A -32.0 sentinel must not drag directional averages down.

        Firmware encodes "SNR unknown" as -32.0; it passes
        is_plausible_traceroute_snr so the hop stays visible. Forward
        readings of [8.0, -32.0] must average 8.0, not -12.0.
        """
        _NETWORK_GRAPH_CACHE.clear()
        mock_names.return_value = {10: "Node10", 20: "Node20"}
        mock_loc_repo.get_node_locations.return_value = []

        packets = [
            {
                "id": 1,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"dummy1",
            },
            {
                "id": 2,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1010.0,
                "raw_payload": b"dummy2",
            },
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        hop1 = Mock()
        hop1.from_node_id = 10
        hop1.to_node_id = 20
        hop1.from_node_name = "Node10"
        hop1.to_node_name = "Node20"
        hop1.snr = 8.0

        hop2 = Mock()
        hop2.from_node_id = 10
        hop2.to_node_id = 20
        hop2.from_node_name = "Node10"
        hop2.to_node_name = "Node20"
        hop2.snr = TRACEROUTE_UNKNOWN_SNR

        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]

        mock_packet_cls.side_effect = [p1, p2]

        graph = TracerouteService.get_network_graph_data(
            hours=98, min_snr=-200.0, include_indirect=False
        )

        assert len(graph["links"]) == 1
        link = graph["links"][0]
        assert link["forward_avg_snr"] == 8.0
        assert link["forward_count"] == 1
        assert link["return_avg_snr"] is None
        assert link["return_count"] == 0
        # The sentinel hop is still an observation of the link
        assert link["packet_count"] == 2
        assert link["worst_snr"] == 8.0
        assert link["overall_quality"] != "unknown"
        assert link["link_balance"] == "unidirectional"

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_sentinel_only_direction_has_no_directional_avg(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """A direction observed only via the -32.0 sentinel reports no SNR, not -32.0."""
        _NETWORK_GRAPH_CACHE.clear()
        mock_names.return_value = {10: "Node10", 20: "Node20"}
        mock_loc_repo.get_node_locations.return_value = []

        packets = [
            {
                "id": 1,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"dummy1",
            }
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        hop1 = Mock()
        hop1.from_node_id = 10
        hop1.to_node_id = 20
        hop1.from_node_name = "Node10"
        hop1.to_node_name = "Node20"
        hop1.snr = TRACEROUTE_UNKNOWN_SNR

        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]

        mock_packet_cls.side_effect = [p1]

        graph = TracerouteService.get_network_graph_data(
            hours=97, min_snr=-200.0, include_indirect=False
        )

        assert len(graph["links"]) == 1
        link = graph["links"][0]
        assert link["forward_avg_snr"] is None
        assert link["forward_count"] == 0
        assert link["return_avg_snr"] is None
        assert link["worst_snr"] is None
        assert link["packet_count"] == 1
        assert link["overall_quality"] == "unknown"
        assert link["estimated_reliability"] is None

    def test_location_service_get_traceroute_links_exposes_directional_snr(self):
        """Test that get_traceroute_links includes forward_avg_snr and return_avg_snr."""
        network_data = {
            "links": [
                {
                    "source": 10,
                    "target": 20,
                    "packet_count": 4,
                    "last_seen": 1000.0,
                    "avg_snr": 1.0,
                    "forward_avg_snr": 5.0,
                    "return_avg_snr": -3.0,
                    "forward_count": 2,
                    "return_count": 2,
                    "last_packet_id": 42,
                }
            ]
        }
        links = LocationService.get_traceroute_links(network_data=network_data)
        assert len(links) == 1
        link = links[0]
        assert link["from_node_id"] == 10
        assert link["to_node_id"] == 20
        assert link["avg_snr"] == 1.0
        assert link["forward_avg_snr"] == 5.0
        assert link["return_avg_snr"] == -3.0
        assert link["forward_count"] == 2
        assert link["return_count"] == 2
        assert link["worst_snr"] == -3.0
        assert link["is_bidirectional"] is True
        assert link["estimated_reliability"] is not None
        assert link["link_balance"] in ("balanced", "asymmetric_marginal")
        assert link["total_observations"] == 4

    @patch("src.malla.database.connection.get_db_connection")
    def test_location_service_get_packet_links_directional_snr(self, mock_db_conn):
        """Test that get_packet_links computes forward and return SNR for bidirectional packet links."""
        from src.malla.services.location_service import _PACKET_LINKS_CACHE

        _PACKET_LINKS_CACHE.clear()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Two rows: node 10 -> gateway 20, and node 20 -> gateway 10
        mock_cursor.fetchall.return_value = [
            {
                "from_node_id": 10,
                "gateway_id": "!00000014",  # 20 in hex
                "packet_count": 5,
                "avg_rssi": -90.0,
                "avg_snr": 6.0,
                "last_seen": 1000.0,
            },
            {
                "from_node_id": 20,
                "gateway_id": "!0000000a",  # 10 in hex
                "packet_count": 3,
                "avg_rssi": -100.0,
                "avg_snr": -2.0,
                "last_seen": 1020.0,
            },
        ]
        mock_db_conn.return_value = mock_conn

        links = LocationService.get_packet_links()
        assert len(links) == 1
        link = links[0]
        assert link["from_node_id"] == 10
        assert link["to_node_id"] == 20
        assert link["is_bidirectional"] is True
        assert link["forward_avg_snr"] == 6.0
        assert link["return_avg_snr"] == -2.0
        assert link["worst_snr"] == -2.0
        assert link["estimated_reliability"] is not None
        assert link["total_observations"] == 8
        assert link["forward_count"] == 5
        assert link["return_count"] == 3
        assert link["forward_avg_rssi"] == -90.0
        assert link["return_avg_rssi"] == -100.0

    def test_api_traceroute_link_directional_snr(self, client):
        """Test that /api/traceroute/link returns separated forward and return SNRs."""
        node1_id = 1000
        node2_id = 2000

        mock_packets = [
            {
                "id": 101,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 10:30:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake1",
            },
            {
                "id": 102,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 10:32:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake2",
            },
            {
                "id": 103,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 10:35:00",
                "from_node_id": node2_id,
                "to_node_id": node1_id,
                "gateway_id": 3000,
                "raw_payload": b"fake3",
            },
        ]

        p1 = MagicMock(spec=TraceroutePacket)
        p1.from_node_name = "Node 1000"
        p1.to_node_name = "Node 2000"
        p1.gateway_id = 3000
        p1.format_path_display.return_value = "1000 -> 2000"
        hop1 = MagicMock(spec=TracerouteHop)
        hop1.from_node_id = node1_id
        hop1.to_node_id = node2_id
        hop1.from_node_name = "Node 1000"
        hop1.to_node_name = "Node 2000"
        hop1.snr = 8.0
        hop1.direction = "forward_rf"
        p1.get_rf_hops.return_value = [hop1]

        p2 = MagicMock(spec=TraceroutePacket)
        p2.from_node_name = "Node 1000"
        p2.to_node_name = "Node 2000"
        p2.gateway_id = 3000
        p2.format_path_display.return_value = "1000 -> 2000"
        hop2 = MagicMock(spec=TracerouteHop)
        hop2.from_node_id = node1_id
        hop2.to_node_id = node2_id
        hop2.from_node_name = "Node 1000"
        hop2.to_node_name = "Node 2000"
        hop2.snr = 5.0
        hop2.direction = "forward_rf"
        p2.get_rf_hops.return_value = [hop2]

        p3 = MagicMock(spec=TraceroutePacket)
        p3.from_node_name = "Node 2000"
        p3.to_node_name = "Node 1000"
        p3.gateway_id = 3000
        p3.format_path_display.return_value = "2000 -> 1000"
        hop3 = MagicMock(spec=TracerouteHop)
        hop3.from_node_id = node2_id
        hop3.to_node_id = node1_id
        hop3.from_node_name = "Node 2000"
        hop3.to_node_name = "Node 1000"
        hop3.snr = 1.0
        hop3.direction = "return_rf"
        p3.get_rf_hops.return_value = [hop3]

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node",
            }
            mock_pkt_cls.side_effect = [p1, p2, p3]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            assert data["forward_avg_snr"] == 6.5
            assert data["return_avg_snr"] == 1.0
            assert data["forward_count"] == 2
            assert data["return_count"] == 1
            # (8.0 + 5.0 + 1.0) / 3 = 4.6666... rounded to 1 decimal is 4.7
            assert data["avg_snr"] == 4.7

    def test_api_traceroute_link_excludes_unknown_snr_sentinel_from_directional_avg(
        self, client
    ):
        """A -32.0 sentinel must not skew /api/traceroute/link directional averages."""
        node1_id = 1000
        node2_id = 2000

        mock_packets = [
            {
                "id": 201,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 11:30:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake1",
            },
            {
                "id": 202,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 11:32:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake2",
            },
        ]

        p1 = MagicMock(spec=TraceroutePacket)
        p1.from_node_name = "Node 1000"
        p1.to_node_name = "Node 2000"
        p1.gateway_id = 3000
        p1.format_path_display.return_value = "1000 -> 2000"
        hop1 = MagicMock(spec=TracerouteHop)
        hop1.from_node_id = node1_id
        hop1.to_node_id = node2_id
        hop1.from_node_name = "Node 1000"
        hop1.to_node_name = "Node 2000"
        hop1.snr = 8.0
        hop1.direction = "forward_rf"
        p1.get_rf_hops.return_value = [hop1]

        p2 = MagicMock(spec=TraceroutePacket)
        p2.from_node_name = "Node 1000"
        p2.to_node_name = "Node 2000"
        p2.gateway_id = 3000
        p2.format_path_display.return_value = "1000 -> 2000"
        hop2 = MagicMock(spec=TracerouteHop)
        hop2.from_node_id = node1_id
        hop2.to_node_id = node2_id
        hop2.from_node_name = "Node 1000"
        hop2.to_node_name = "Node 2000"
        hop2.snr = TRACEROUTE_UNKNOWN_SNR
        hop2.direction = "forward_rf"
        p2.get_rf_hops.return_value = [hop2]

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node",
            }
            mock_pkt_cls.side_effect = [p1, p2]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            assert data["forward_avg_snr"] == 8.0
            assert data["forward_count"] == 1
            assert data["return_avg_snr"] is None
            assert data["return_count"] == 0
            assert data["total_observations"] == 1
            assert data["worst_snr"] == 8.0
            assert data["link_balance"] == "unidirectional"

    def test_api_traceroute_link_aggregates_both_hops_in_single_packet(
        self, client
    ):
        """A single traceroute packet containing both forward (8 dB) and return (-16 dB) hops
        must aggregate both directional metrics while keeping one history entry per packet.
        """
        node1_id = 1000
        node2_id = 2000

        mock_packets = [
            {
                "id": 301,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 12:30:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake_bidirectional",
            }
        ]

        p = MagicMock(spec=TraceroutePacket)
        p.from_node_name = "Node 1000"
        p.to_node_name = "Node 2000"
        p.gateway_id = 3000
        p.format_path_display.return_value = "1000 <-> 2000"

        hop_fwd = MagicMock(spec=TracerouteHop)
        hop_fwd.from_node_id = node1_id
        hop_fwd.to_node_id = node2_id
        hop_fwd.from_node_name = "Node 1000"
        hop_fwd.to_node_name = "Node 2000"
        hop_fwd.snr = 8.0
        hop_fwd.direction = "forward_rf"

        hop_ret = MagicMock(spec=TracerouteHop)
        hop_ret.from_node_id = node2_id
        hop_ret.to_node_id = node1_id
        hop_ret.from_node_name = "Node 2000"
        hop_ret.to_node_name = "Node 1000"
        hop_ret.snr = -16.0
        hop_ret.direction = "return_rf"

        p.get_rf_hops.return_value = [hop_fwd, hop_ret]

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node",
            }
            mock_pkt_cls.side_effect = [p]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            # Directional metrics must capture both hops
            assert data["forward_avg_snr"] == 8.0
            assert data["forward_count"] == 1
            assert data["return_avg_snr"] == -16.0
            assert data["return_count"] == 1
            assert data["total_observations"] == 2

            # Reliability calculated from the minimum value (-16.0 dB), not the first value (8.0 dB)
            assert data["worst_snr"] == -16.0
            assert data["estimated_reliability"] < 50.0
            assert data["forward_reliability"] > 99.0
            assert data["return_reliability"] < 50.0
            assert data["link_balance"] == "asymmetric_marginal"

            # Exactly one history entry per packet, with hop_snr reflecting the bottleneck (-16.0 dB)
            assert data["total_attempts"] == 1
            assert len(data["traceroutes"]) == 1
            assert data["traceroutes"][0]["hop_snr"] == -16.0

            # Direction counts record both observed directions
            assert data["direction_counts"]["Node 1000 → Node 2000"] == 1
            assert data["direction_counts"]["Node 2000 → Node 1000"] == 1

    def test_api_traceroute_link_single_packet_with_sentinel_and_real_hop(
        self, client
    ):
        """When a packet has one real hop and one -32.0 sentinel hop, the sentinel
        must be excluded from directional SNR, avg_snr, and hop_snr."""
        node1_id = 1000
        node2_id = 2000

        mock_packets = [
            {
                "id": 302,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 12:35:00",
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "raw_payload": b"fake_sentinel",
            }
        ]

        p = MagicMock(spec=TraceroutePacket)
        p.from_node_name = "Node 1000"
        p.to_node_name = "Node 2000"
        p.gateway_id = 3000
        p.format_path_display.return_value = "1000 <-> 2000"

        hop_fwd = MagicMock(spec=TracerouteHop)
        hop_fwd.from_node_id = node1_id
        hop_fwd.to_node_id = node2_id
        hop_fwd.from_node_name = "Node 1000"
        hop_fwd.to_node_name = "Node 2000"
        hop_fwd.snr = 8.0
        hop_fwd.direction = "forward_rf"

        hop_ret = MagicMock(spec=TracerouteHop)
        hop_ret.from_node_id = node2_id
        hop_ret.to_node_id = node1_id
        hop_ret.from_node_name = "Node 2000"
        hop_ret.to_node_name = "Node 1000"
        hop_ret.snr = TRACEROUTE_UNKNOWN_SNR
        hop_ret.direction = "return_rf"

        p.get_rf_hops.return_value = [hop_fwd, hop_ret]

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node",
            }
            mock_pkt_cls.side_effect = [p]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            assert data["forward_avg_snr"] == 8.0
            assert data["forward_count"] == 1
            assert data["return_avg_snr"] is None
            assert data["return_count"] == 0
            assert data["total_observations"] == 1
            assert data["worst_snr"] == 8.0
            assert data["avg_snr"] == 8.0
            assert data["traceroutes"][0]["hop_snr"] == 8.0
            assert data["total_attempts"] == 1
            assert data["direction_counts"]["Node 1000 → Node 2000"] == 1
            assert data["direction_counts"]["Node 2000 → Node 1000"] == 1

    def test_dynamic_per_link_spreading_factor_resolution(self):
        """Test that get_traceroute_links uses the link's channel_id to determine SF thresholds."""
        # For SNR = -5.0 dB:
        # On SFNarrow (SF7, demod limit -7.5 dB): margin is +2.5 dB (< 4 dB) -> marginal
        # On LongFast (SF11, demod limit -17.5 dB): margin is +12.5 dB (>= 10 dB) -> good
        network_data = {
            "links": [
                {
                    "source": 100,
                    "target": 200,
                    "channel_id": "SFNarrow",
                    "packet_count": 2,
                    "last_seen": 1000.0,
                    "avg_snr": -5.0,
                    "forward_avg_snr": -5.0,
                    "return_avg_snr": None,
                    "forward_count": 2,
                    "return_count": 0,
                    "last_packet_id": 1,
                },
                {
                    "source": 300,
                    "target": 400,
                    "channel_id": "LongFast",
                    "packet_count": 2,
                    "last_seen": 1000.0,
                    "avg_snr": -5.0,
                    "forward_avg_snr": -5.0,
                    "return_avg_snr": None,
                    "forward_count": 2,
                    "return_count": 0,
                    "last_packet_id": 2,
                },
            ]
        }

        tr_links = LocationService.get_traceroute_links(network_data=network_data)
        assert len(tr_links) == 2

        sfnarrow_link = next(lnk for lnk in tr_links if lnk["channel_id"] == "SFNarrow")
        longfast_link = next(lnk for lnk in tr_links if lnk["channel_id"] == "LongFast")

        # Under SFNarrow (SF7), -5.0 dB is marginal
        assert sfnarrow_link["forward_quality"] == "marginal"
        assert sfnarrow_link["overall_quality"] == "marginal"
        assert sfnarrow_link["estimated_reliability"] == 50.0

        # Under LongFast (SF11), -5.0 dB is good
        assert longfast_link["forward_quality"] == "good"
        assert longfast_link["overall_quality"] == "good"
        assert longfast_link["estimated_reliability"] > 95.0
