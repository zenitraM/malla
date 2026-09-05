"""
Unit tests verifying that hops belonging to the same traceroute are only counted once.
"""

from unittest.mock import MagicMock, Mock, patch

from src.malla.models.traceroute import TracerouteHop
from src.malla.services.node_service import NodeService
from src.malla.services.traceroute_service import (
    _NETWORK_GRAPH_CACHE,
    TracerouteService,
)
from src.malla.utils.traceroute_utils import get_packet_traceroute_id


class TestTracerouteHopDeduplication:
    """Tests for deduplicating hops across multiple receptions of the same traceroute."""

    def test_get_packet_traceroute_id(self):
        """Test traceroute ID generation with various packet structures."""
        # 1. Mesh packet ID present and non-zero
        pkt_with_mesh_id = {
            "id": 100,
            "mesh_packet_id": 99999,
            "from_node_id": 10,
            "to_node_id": 20,
        }
        assert get_packet_traceroute_id(pkt_with_mesh_id) == (99999, 10, 20)

        # 2. Mesh packet ID is 0 or None -> fallback to packet id
        pkt_zero_mesh_id = {
            "id": 100,
            "mesh_packet_id": 0,
            "from_node_id": 10,
            "to_node_id": 20,
        }
        assert get_packet_traceroute_id(pkt_zero_mesh_id) == ("packet", 100)

        pkt_no_mesh_id = {
            "id": 101,
            "from_node_id": 10,
            "to_node_id": 20,
        }
        assert get_packet_traceroute_id(pkt_no_mesh_id) == ("packet", 101)

        # 3. Object with packet_data attribute
        obj = Mock()
        obj.packet_data = {
            "id": 102,
            "mesh_packet_id": 88888,
            "from_node_id": 30,
            "to_node_id": 40,
        }
        assert get_packet_traceroute_id(obj) == (88888, 30, 40)

        # 4. Neither mesh_packet_id nor id
        bare_pkt = {"from_node_id": 10, "to_node_id": 20, "timestamp": 12345.0}
        assert get_packet_traceroute_id(bare_pkt) == ("cluster", 10, 20, 12345.0)

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_deduplicates_hops_from_same_traceroute(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """
        Verify that multiple receptions of the same traceroute (same mesh_packet_id)
        only increment hop counts once, but update the last_seen timestamp to the latest.
        """
        _NETWORK_GRAPH_CACHE.clear()
        mock_names.return_value = {10: "Node10", 15: "Node15", 20: "Node20", 18: "Node18"}
        mock_loc_repo.get_node_locations.return_value = []

        # 3 gateway receptions of the same traceroute (mesh_packet_id = 12345)
        packets = [
            {
                "id": 1,
                "mesh_packet_id": 12345,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"pkt1",
            },
            {
                "id": 2,
                "mesh_packet_id": 12345,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1005.0,
                "raw_payload": b"pkt2",
            },
            {
                "id": 3,
                "mesh_packet_id": 12345,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1010.0,
                "raw_payload": b"pkt3",
            },
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        # Packet 1 has hops: 10 -> 15, 15 -> 20
        hop10_15_a = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=15,
            from_node_name="Node10", to_node_name="Node15", snr=5.0
        )
        hop15_20_a = TracerouteHop(
            hop_number=2, from_node_id=15, to_node_id=20,
            from_node_name="Node15", to_node_name="Node20", snr=4.0
        )
        p1 = Mock()
        p1.get_rf_hops.return_value = [hop10_15_a, hop15_20_a]

        # Packet 2 (duplicate route heard by another gateway) has hops: 10 -> 15, 15 -> 20
        hop10_15_b = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=15,
            from_node_name="Node10", to_node_name="Node15", snr=5.0
        )
        hop15_20_b = TracerouteHop(
            hop_number=2, from_node_id=15, to_node_id=20,
            from_node_name="Node15", to_node_name="Node20", snr=4.0
        )
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop10_15_b, hop15_20_b]

        # Packet 3 (different branch of same traceroute) has hops: 10 -> 15, 15 -> 18, 18 -> 20
        hop10_15_c = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=15,
            from_node_name="Node10", to_node_name="Node15", snr=5.0
        )
        hop15_18 = TracerouteHop(
            hop_number=2, from_node_id=15, to_node_id=18,
            from_node_name="Node15", to_node_name="Node18", snr=3.0
        )
        hop18_20 = TracerouteHop(
            hop_number=3, from_node_id=18, to_node_id=20,
            from_node_name="Node18", to_node_name="Node20", snr=2.0
        )
        p3 = Mock()
        p3.get_rf_hops.return_value = [hop10_15_c, hop15_18, hop18_20]

        mock_packet_cls.side_effect = [p1, p2, p3]

        graph = TracerouteService.get_network_graph_data(hours=1, min_snr=-200.0, include_indirect=False)

        link_map = {(link["source"], link["target"]): link for link in graph["links"]}

        # Hop 10 <-> 15 appeared in all 3 receptions, but should only have packet_count == 1
        link_10_15 = link_map[(10, 15)]
        assert link_10_15["packet_count"] == 1
        # last_seen should be updated to packet 3's timestamp (1010.0)
        assert link_10_15["last_seen"] == 1010.0
        assert link_10_15["last_packet_id"] == 3

        # Hop 15 <-> 20 appeared in packets 1 and 2 -> packet_count should be 1
        link_15_20 = link_map[(15, 20)]
        assert link_15_20["packet_count"] == 1
        assert link_15_20["last_seen"] == 1005.0

        # Hop 15 <-> 18 and 18 <-> 20 appeared only in packet 3 -> packet_count should be 1
        assert link_map[(15, 18)]["packet_count"] == 1
        assert link_map[(18, 20)]["packet_count"] == 1

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_counts_round_trip_hops_once_each(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """
        Verify that a round-trip traceroute with forward 10 -> 20 and return 20 -> 10
        counts both directional hops once (packet_count = 2, forward = 1, return = 1),
        even if duplicate receptions are processed.
        """
        _NETWORK_GRAPH_CACHE.clear()
        mock_names.return_value = {10: "Node10", 20: "Node20"}
        mock_loc_repo.get_node_locations.return_value = []

        packets = [
            {
                "id": 1,
                "mesh_packet_id": 7777,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"pkt1",
            },
            {
                "id": 2,
                "mesh_packet_id": 7777,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1002.0,
                "raw_payload": b"pkt2",
            },
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        hop_fwd_1 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="Node10", to_node_name="Node20", snr=7.0
        )
        hop_ret_1 = TracerouteHop(
            hop_number=2, from_node_id=20, to_node_id=10,
            from_node_name="Node20", to_node_name="Node10", snr=-2.0
        )
        p1 = Mock()
        p1.get_rf_hops.return_value = [hop_fwd_1, hop_ret_1]

        hop_fwd_2 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="Node10", to_node_name="Node20", snr=7.0
        )
        hop_ret_2 = TracerouteHop(
            hop_number=2, from_node_id=20, to_node_id=10,
            from_node_name="Node20", to_node_name="Node10", snr=-2.0
        )
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop_fwd_2, hop_ret_2]

        mock_packet_cls.side_effect = [p1, p2]

        graph = TracerouteService.get_network_graph_data(hours=1, min_snr=-200.0, include_indirect=False)

        assert len(graph["links"]) == 1
        link = graph["links"][0]
        assert link["source"] == 10
        assert link["target"] == 20
        assert link["packet_count"] == 2
        assert link["last_seen"] == 1002.0

    @patch("src.malla.services.traceroute_service.get_bulk_node_names")
    @patch("src.malla.services.traceroute_service.LocationRepository")
    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_network_graph_counts_distinct_traceroutes_separately(
        self, mock_repo, mock_packet_cls, mock_loc_repo, mock_names
    ):
        """Verify that distinct traceroutes (different mesh_packet_id) both increment counts."""
        _NETWORK_GRAPH_CACHE.clear()
        mock_names.return_value = {10: "Node10", 20: "Node20"}
        mock_loc_repo.get_node_locations.return_value = []

        packets = [
            {
                "id": 1,
                "mesh_packet_id": 1111,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1000.0,
                "raw_payload": b"pkt1",
            },
            {
                "id": 2,
                "mesh_packet_id": 2222,
                "from_node_id": 10,
                "to_node_id": 20,
                "timestamp": 1050.0,
                "raw_payload": b"pkt2",
            },
        ]
        mock_repo.get_traceroute_packets_for_graph.return_value = packets

        hop1 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="Node10", to_node_name="Node20", snr=5.0
        )
        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]

        hop2 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="Node10", to_node_name="Node20", snr=6.0
        )
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]

        mock_packet_cls.side_effect = [p1, p2]

        graph = TracerouteService.get_network_graph_data(hours=1, min_snr=-200.0, include_indirect=False)

        assert len(graph["links"]) == 1
        link = graph["links"][0]
        assert link["packet_count"] == 2
        assert link["avg_snr"] == 5.5

    def test_api_traceroute_link_deduplicates_same_traceroute(self, client):
        """Verify api_traceroute_link deduplicates hops and traceroutes sharing mesh_packet_id."""
        node1_id = 1000
        node2_id = 2000

        # Two packets from same traceroute (mesh_packet_id 9999) containing hop 1000 -> 2000
        packets = [
            {
                "id": 10,
                "mesh_packet_id": 9999,
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "timestamp": 1000.0,
                "timestamp_str": "2024-01-20 10:00:00",
                "raw_payload": b"pkt1",
            },
            {
                "id": 11,
                "mesh_packet_id": 9999,
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "timestamp": 1002.0,
                "timestamp_str": "2024-01-20 10:02:00",
                "raw_payload": b"pkt2",
            },
        ]

        hop1 = TracerouteHop(
            hop_number=1, from_node_id=node1_id, to_node_id=node2_id,
            from_node_name="Node 1000", to_node_name="Node 2000", snr=6.5,
            direction="forward_rf"
        )
        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]
        p1.from_node_name = "Node 1000"
        p1.to_node_name = "Node 2000"
        p1.gateway_id = 3000
        p1.timestamp = 1000.0
        p1.timestamp_str = "2024-01-20 10:00:00"
        p1.from_node_id = node1_id
        p1.to_node_id = node2_id
        p1.packet_data = packets[0]
        p1.format_path_display.return_value = "1000 -> 2000"

        hop2 = TracerouteHop(
            hop_number=1, from_node_id=node1_id, to_node_id=node2_id,
            from_node_name="Node 1000", to_node_name="Node 2000", snr=6.5,
            direction="forward_rf"
        )
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]
        p2.from_node_name = "Node 1000"
        p2.to_node_name = "Node 2000"
        p2.gateway_id = 3000
        p2.timestamp = 1002.0
        p2.timestamp_str = "2024-01-20 10:02:00"
        p2.from_node_id = node1_id
        p2.to_node_id = node2_id
        p2.packet_data = packets[1]
        p2.format_path_display.return_value = "1000 -> 2000"

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node",
            }
            mock_pkt_cls.side_effect = [p1, p2]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            # Same traceroute seen via two gateway receptions: one direction
            # counted once and a single merged traceroute entry.
            assert sum(data["direction_counts"].values()) == 1
            assert data["total_observations"] == 1
            assert len(data["traceroutes"]) == 1

    def test_api_traceroute_link_counts_round_trip_hops_once_each(self, client):
        """Verify api_traceroute_link counts both forward and return hops of a round-trip traceroute."""
        node1_id = 1000
        node2_id = 2000

        packets = [
            {
                "id": 10,
                "mesh_packet_id": 8888,
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3000,
                "timestamp": 1000.0,
                "timestamp_str": "2024-01-20 10:00:00",
                "raw_payload": b"pkt1",
            },
            {
                "id": 11,
                "mesh_packet_id": 8888,
                "from_node_id": node1_id,
                "to_node_id": node2_id,
                "gateway_id": 3001,
                "timestamp": 1002.0,
                "timestamp_str": "2024-01-20 10:02:00",
                "raw_payload": b"pkt2",
            },
        ]

        hop_fwd = TracerouteHop(
            hop_number=1, from_node_id=node1_id, to_node_id=node2_id,
            from_node_name="Node 1000", to_node_name="Node 2000", snr=8.0,
            direction="forward_rf"
        )
        hop_ret = TracerouteHop(
            hop_number=2, from_node_id=node2_id, to_node_id=node1_id,
            from_node_name="Node 2000", to_node_name="Node 1000", snr=4.0,
            direction="return_rf"
        )

        def make_mock_packet(pkt_data):
            p = Mock()
            p.get_rf_hops.return_value = [hop_fwd, hop_ret]
            p.from_node_name = "Node 1000"
            p.to_node_name = "Node 2000"
            p.gateway_id = pkt_data["gateway_id"]
            p.timestamp = pkt_data["timestamp"]
            p.timestamp_str = pkt_data["timestamp_str"]
            p.from_node_id = node1_id
            p.to_node_id = node2_id
            p.packet_data = pkt_data
            p.format_path_display.return_value = "1000 <-> 2000"
            return p

        p1 = make_mock_packet(packets[0])
        p2 = make_mock_packet(packets[1])

        with (
            patch("src.malla.routes.api_routes.TracerouteRepository") as mock_repo,
            patch("src.malla.routes.api_routes.NodeRepository") as mock_nodes,
            patch("src.malla.routes.api_routes.TraceroutePacket") as mock_pkt_cls,
        ):
            mock_repo.get_traceroute_packets.return_value = {"packets": packets}
            mock_nodes.get_bulk_node_names.return_value = {
                node1_id: "Node 1000",
                node2_id: "Node 2000",
                3000: "Gateway Node 1",
                3001: "Gateway Node 2",
            }
            mock_pkt_cls.side_effect = [p1, p2]

            response = client.get(f"/api/traceroute/link/{node1_id}/{node2_id}")
            assert response.status_code == 200
            data = response.get_json()

            # Two directions observed once each (forward and return), total observations == 2,
            # but single merged traceroute entry.
            assert sum(data["direction_counts"].values()) == 2
            assert data["total_observations"] == 2
            assert len(data["traceroutes"]) == 1
            assert data["traceroutes"][0]["hop_snr"] == 4.0  # Min of plausible matching SNRs (8.0 and 4.0)

    @patch("src.malla.services.traceroute_service.TraceroutePacket")
    @patch("src.malla.services.traceroute_service.TracerouteRepository")
    def test_longest_links_analysis_deduplicates_same_traceroute(
        self, mock_repo, mock_packet_cls
    ):
        """Verify get_longest_links_analysis deduplicates hops from the same traceroute."""
        packets = [
            {
                "id": 1,
                "mesh_packet_id": 4321,
                "from_node_id": 100,
                "to_node_id": 200,
                "timestamp": 1000.0,
                "raw_payload": b"pkt1",
                "gateway_id": "!12345678",
                "processed_successfully": True,
            },
            {
                "id": 2,
                "mesh_packet_id": 4321,
                "from_node_id": 100,
                "to_node_id": 200,
                "timestamp": 1003.0,
                "raw_payload": b"pkt2",
                "gateway_id": "!12345678",
                "processed_successfully": True,
            },
        ]
        mock_repo.get_traceroute_packets.return_value = {"packets": packets}

        hop1 = Mock()
        hop1.from_node_id = 100
        hop1.to_node_id = 200
        hop1.from_node_name = "Node100"
        hop1.to_node_name = "Node200"
        hop1.distance_km = 10.0
        hop1.snr = 4.0

        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]
        p1.calculate_hop_distances = Mock()

        hop2 = Mock()
        hop2.from_node_id = 100
        hop2.to_node_id = 200
        hop2.from_node_name = "Node100"
        hop2.to_node_name = "Node200"
        hop2.distance_km = 10.0
        hop2.snr = 4.0

        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]
        p2.calculate_hop_distances = Mock()

        mock_packet_cls.side_effect = [p1, p2]

        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=1.0, min_snr=-10.0, max_results=10
        )
        links = result.get("direct_links", [])
        assert len(links) == 1
        assert links[0]["traceroute_count"] == 1

    @patch("src.malla.database.get_db_connection")
    @patch("src.malla.models.traceroute.TraceroutePacket")
    def test_node_service_related_nodes_deduplicates_same_traceroute(
        self, mock_packet_cls, mock_conn
    ):
        """Verify NodeService.get_traceroute_related_nodes deduplicates shared hops from same traceroute."""
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.cursor.return_value = mock_cursor

        # Packets returned by cursor
        mock_cursor.fetchall.side_effect = [
            # First query: packet rows
            [
                (1, 1000.0, 10, 20, "!gw1", 0, 3, b"p1", 888),
                (2, 1002.0, 10, 20, "!gw2", 0, 3, b"p2", 888),
            ],
            # Second query: node_info rows
            [
                (20, "Node Twenty", "N20", "!00000014"),
            ],
        ]

        hop1 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="N10", to_node_name="N20", snr=5.0
        )
        p1 = Mock()
        p1.get_rf_hops.return_value = [hop1]

        hop2 = TracerouteHop(
            hop_number=1, from_node_id=10, to_node_id=20,
            from_node_name="N10", to_node_name="N20", snr=5.0
        )
        p2 = Mock()
        p2.get_rf_hops.return_value = [hop2]

        mock_packet_cls.side_effect = [p1, p2]

        result = NodeService.get_traceroute_related_nodes(10)
        related = result["related_nodes"]
        assert len(related) == 1
        # Node 20 should have traceroute_count == 1, not 2
        assert related[0]["node_id"] == 20
        assert related[0]["traceroute_count"] == 1
