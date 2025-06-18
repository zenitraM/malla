"""
Unit tests for the traceroute link endpoint functionality.

Tests the API endpoint that finds direct RF links between two specific nodes.
"""

import json
import time
from unittest.mock import patch

import pytest

from src.malla.models.traceroute import TraceroutePacket


class TestTracerouteLinkEndpoint:
    """Test the traceroute link endpoint behavior."""

    @pytest.mark.unit
    def test_no_direct_rf_hops_returns_zero_traceroutes(self):
        """
        Test that the endpoint returns 0 traceroutes when nodes are involved in traceroutes
        but have no direct RF hops between them.

        This validates the actual behavior observed with nodes 2224740660 and 3665029580.
        """
        node1_id = 2224740660  # !849ad934 - Meshlasaña 📡
        node2_id = 3665029580  # !da73e9cc - JAV - Malasaña 2
        intermediate_node = 1128074276  # Node that both connect to, but not each other

        # Create traceroute packets where both target nodes are involved,
        # but they don't have direct RF hops between each other
        mock_packets = [
            # Packet 1: node2 -> intermediate_node (node1 not involved in RF path)
            {
                "id": 1,
                "timestamp": time.time(),
                "from_node_id": node2_id,
                "to_node_id": 12345,  # Some other destination
                "gateway_id": f"!{node2_id:08x}",
                "raw_payload": json.dumps(
                    {
                        "route_nodes": [intermediate_node],
                        "snr_towards": [25.0],
                        "route_back": [],
                        "snr_back": [],
                    }
                ).encode(),
                "processed_successfully": True,
                "timestamp_str": "2024-01-01 12:00:00",
            },
            # Packet 2: intermediate_node -> node2 (return path, but still no node1)
            {
                "id": 2,
                "timestamp": time.time(),
                "from_node_id": 54321,  # Some other source
                "to_node_id": node2_id,
                "gateway_id": f"!{54321:08x}",
                "raw_payload": json.dumps(
                    {
                        "route_nodes": [intermediate_node],
                        "snr_towards": [25.0, -41.0],
                        "route_back": [intermediate_node],
                        "snr_back": [-47.0],
                    }
                ).encode(),
                "processed_successfully": True,
                "timestamp_str": "2024-01-01 12:01:00",
            },
            # Packet 3: node1 -> some_other_node (node1 involved but not with node2)
            {
                "id": 3,
                "timestamp": time.time(),
                "from_node_id": node1_id,
                "to_node_id": 67890,
                "gateway_id": f"!{node1_id:08x}",
                "raw_payload": json.dumps(
                    {
                        "route_nodes": [99999],  # Different intermediate node
                        "snr_towards": [-10.0],
                        "route_back": [],
                        "snr_back": [],
                    }
                ).encode(),
                "processed_successfully": True,
                "timestamp_str": "2024-01-01 12:02:00",
            },
        ]

        # Mock the repository to return these packets
        with patch("src.malla.database.repositories.TracerouteRepository") as mock_repo:
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}

            with patch(
                "src.malla.database.repositories.NodeRepository"
            ) as mock_node_repo:
                mock_node_repo.get_bulk_node_names.return_value = {
                    node1_id: "Meshlasaña 📡",
                    node2_id: "JAV - Malasaña 2",
                }

                with patch(
                    "src.malla.utils.traceroute_utils.parse_traceroute_payload"
                ) as mock_parse:

                    def parse_side_effect(payload):
                        return json.loads(payload.decode())

                    mock_parse.side_effect = parse_side_effect

                    # Test each packet individually to verify RF hop analysis
                    for i, packet_data in enumerate(mock_packets):
                        tr_packet = TraceroutePacket(
                            packet_data=packet_data, resolve_names=False
                        )
                        rf_hops = tr_packet.get_rf_hops()

                        print(f"Packet {i + 1}: {len(rf_hops)} RF hops")
                        for hop in rf_hops:
                            print(f"  {hop.from_node_id} -> {hop.to_node_id}")

                        # Verify no direct hop between target nodes
                        has_direct_hop = any(
                            (
                                hop.from_node_id == node1_id
                                and hop.to_node_id == node2_id
                            )
                            or (
                                hop.from_node_id == node2_id
                                and hop.to_node_id == node1_id
                            )
                            for hop in rf_hops
                        )
                        assert not has_direct_hop, (
                            f"Packet {i + 1} should not have direct hop between target nodes"
                        )

    @pytest.mark.unit
    def test_direct_rf_hop_returns_traceroutes(self):
        """
        Test that the endpoint returns traceroutes when there IS a direct RF hop
        between the two target nodes.
        """
        node1_id = 2224740660
        node2_id = 3665029580

        # Create a traceroute packet with a direct RF hop between the target nodes
        mock_packet = {
            "id": 100,
            "timestamp": time.time(),
            "from_node_id": node1_id,
            "to_node_id": node2_id,
            "gateway_id": f"!{node1_id:08x}",
            "hop_start": 4,
            "hop_limit": 4,
            "raw_payload": json.dumps(
                {
                    "route_nodes": [],  # Direct hop, no intermediate nodes
                    "snr_towards": [-15.5],  # SNR for the direct hop
                    "route_back": [],
                    "snr_back": [],
                }
            ).encode(),
            "processed_successfully": True,
            "timestamp_str": "2024-01-01 12:00:00",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [],
                "snr_towards": [-15.5],
                "route_back": [],
                "snr_back": [],
            }

            # Create TraceroutePacket and verify it has the direct hop
            tr_packet = TraceroutePacket(packet_data=mock_packet, resolve_names=False)
            rf_hops = tr_packet.get_rf_hops()

            # Should have exactly one RF hop
            assert len(rf_hops) == 1
            hop = rf_hops[0]

            # Should be a direct hop between our target nodes
            assert hop.from_node_id == node1_id
            assert hop.to_node_id == node2_id
            assert hop.snr == -15.5

            # Verify the contains_hop method works
            assert tr_packet.contains_hop(node1_id, node2_id)
            assert tr_packet.contains_hop(
                node2_id, node1_id
            )  # Should work bidirectionally

            # Verify get_hop_snr method works
            assert tr_packet.get_hop_snr(node1_id, node2_id) == -15.5
            assert (
                tr_packet.get_hop_snr(node2_id, node1_id) == -15.5
            )  # Should work bidirectionally

    @pytest.mark.unit
    def test_multi_hop_traceroute_with_target_hop_in_middle(self):
        """
        Test a multi-hop traceroute where the target nodes appear as an intermediate hop.
        """
        node1_id = 2224740660
        node2_id = 3665029580
        source_node = 11111111
        dest_node = 22222222

        # Create a traceroute: source -> node1 -> node2 -> dest
        mock_packet = {
            "id": 200,
            "timestamp": time.time(),
            "from_node_id": source_node,
            "to_node_id": dest_node,
            "gateway_id": f"!{source_node:08x}",
            "hop_start": 4,
            "hop_limit": 4,
            "raw_payload": json.dumps(
                {
                    "route_nodes": [node1_id, node2_id],
                    "snr_towards": [
                        -10.0,
                        -12.0,
                        -8.0,
                    ],  # source->node1, node1->node2, node2->dest
                    "route_back": [],
                    "snr_back": [],
                }
            ).encode(),
            "processed_successfully": True,
            "timestamp_str": "2024-01-01 12:00:00",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [node1_id, node2_id],
                "snr_towards": [-10.0, -12.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            # Create TraceroutePacket and verify it finds the target hop
            tr_packet = TraceroutePacket(packet_data=mock_packet, resolve_names=False)
            rf_hops = tr_packet.get_rf_hops()

            # Should have 3 RF hops total
            assert len(rf_hops) == 3

            # Find the hop between our target nodes
            target_hop = None
            for hop in rf_hops:
                if (hop.from_node_id == node1_id and hop.to_node_id == node2_id) or (
                    hop.from_node_id == node2_id and hop.to_node_id == node1_id
                ):
                    target_hop = hop
                    break

            # Should find the target hop
            assert target_hop is not None
            assert target_hop.from_node_id == node1_id
            assert target_hop.to_node_id == node2_id
            assert target_hop.snr == -12.0

            # Verify the helper methods work
            assert tr_packet.contains_hop(node1_id, node2_id)
            assert tr_packet.get_hop_snr(node1_id, node2_id) == -12.0

    @pytest.mark.unit
    def test_traceroute_packet_actual_rf_path_analysis(self):
        """
        Test that the actual RF path analysis correctly identifies which hops actually occurred.

        This tests the core logic that the endpoint relies on to determine RF hops.
        """
        node1_id = 2224740660
        node2_id = 3665029580
        intermediate_node = 1128074276

        # Test case 1: Forward traceroute that didn't complete (common case)
        incomplete_packet = {
            "id": 300,
            "timestamp": time.time(),
            "from_node_id": node1_id,
            "to_node_id": node2_id,
            "gateway_id": f"!{node1_id:08x}",
            "hop_start": 4,
            "hop_limit": 4,
            "raw_payload": json.dumps(
                {
                    "route_nodes": [
                        intermediate_node
                    ],  # Intended to go through intermediate, then to node2
                    "snr_towards": [
                        -15.0
                    ],  # But only one SNR value = only reached intermediate
                    "route_back": [],
                    "snr_back": [],
                }
            ).encode(),
            "processed_successfully": True,
            "timestamp_str": "2024-01-01 12:00:00",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [intermediate_node],
                "snr_towards": [-15.0],
                "route_back": [],
                "snr_back": [],
            }

            # Create TraceroutePacket
            tr_packet = TraceroutePacket(
                packet_data=incomplete_packet, resolve_names=False
            )

            # Display path shows intended route: node1 -> intermediate -> node2
            display_hops = tr_packet.get_display_hops()
            assert len(display_hops) == 1
            assert display_hops[0].from_node_id == node1_id
            assert display_hops[0].to_node_id == intermediate_node

            # But actual RF path only shows what happened: node1 -> intermediate
            rf_hops = tr_packet.get_rf_hops()
            assert len(rf_hops) == 1  # Only one SNR value = only one RF hop occurred
            assert rf_hops[0].from_node_id == node1_id
            assert rf_hops[0].to_node_id == intermediate_node
            assert rf_hops[0].snr == -15.0

            # Should NOT find a hop between node1 and node2 because it didn't actually happen
            assert not tr_packet.contains_hop(node1_id, node2_id)
            assert tr_packet.get_hop_snr(node1_id, node2_id) is None

    @pytest.mark.unit
    def test_endpoint_integration_scenario(self):
        """
        Test the complete scenario that matches the real-world case:
        Nodes are involved in traceroutes but have no direct RF hops between them.
        """
        node1_id = 2224740660  # Meshlasaña 📡
        node2_id = 3665029580  # JAV - Malasaña 2
        intermediate_node = 1128074276  # The node they both connect through

        # Simulate the actual packets from the debug output
        real_world_packets = [
            # Packet where node2 is source, goes through intermediate
            {
                "id": 11882,
                "timestamp": time.time(),
                "from_node_id": node2_id,
                "to_node_id": 1128205244,
                "gateway_id": f"!{node2_id:08x}",
                "raw_payload": json.dumps(
                    {
                        "route_nodes": [intermediate_node],
                        "snr_towards": [25],
                        "route_back": [],
                        "snr_back": [],
                    }
                ).encode(),
                "processed_successfully": True,
                "timestamp_str": "2024-01-01 12:00:00",
            },
            # Packet with return path, node2 as destination
            {
                "id": 11883,
                "timestamp": time.time(),
                "from_node_id": 1128205244,
                "to_node_id": node2_id,
                "gateway_id": f"!{1128205244:08x}",
                "raw_payload": json.dumps(
                    {
                        "route_nodes": [intermediate_node],
                        "snr_towards": [25, -41],
                        "route_back": [intermediate_node],
                        "snr_back": [-47],
                    }
                ).encode(),
                "processed_successfully": True,
                "timestamp_str": "2024-01-01 12:01:00",
            },
        ]

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:

            def parse_side_effect(payload):
                return json.loads(payload.decode())

            mock_parse.side_effect = parse_side_effect

            # Process packets as the endpoint would
            found_target_hops = 0

            for packet in real_world_packets:
                tr_packet = TraceroutePacket(packet_data=packet, resolve_names=False)
                rf_hops = tr_packet.get_rf_hops()

                # Look for RF hop between target nodes (as endpoint does)
                for hop in rf_hops:
                    if (
                        hop.from_node_id == node1_id and hop.to_node_id == node2_id
                    ) or (hop.from_node_id == node2_id and hop.to_node_id == node1_id):
                        found_target_hops += 1

            # Should find 0 hops between the target nodes, explaining the endpoint result
            assert found_target_hops == 0, (
                "No direct RF hops should exist between these nodes in the test data"
            )

            # Verify that the packets DO contain the nodes, just not as direct hops
            packet1 = TraceroutePacket(
                packet_data=real_world_packets[0], resolve_names=False
            )
            packet2 = TraceroutePacket(
                packet_data=real_world_packets[1], resolve_names=False
            )

            # Packet 1: node2 -> intermediate (node2 is involved)
            assert packet1.from_node_id == node2_id
            rf_hops_1 = packet1.get_rf_hops()
            assert len(rf_hops_1) == 1
            assert rf_hops_1[0].from_node_id == node2_id
            assert rf_hops_1[0].to_node_id == intermediate_node

            # Packet 2: has return path, actual RF shows both forward and return RF hops
            rf_hops_2 = packet2.get_rf_hops()
            assert (
                len(rf_hops_2) == 3
            )  # 2 forward SNR values + 1 return SNR value = 3 RF hops

            # Check that we have both forward and return RF hops
            forward_hops = [hop for hop in rf_hops_2 if hop.direction == "forward_rf"]
            return_hops = [hop for hop in rf_hops_2 if hop.direction == "return_rf"]
            assert len(forward_hops) == 2  # 2 forward SNR values
            assert len(return_hops) == 1  # 1 return SNR value
