"""
Unit tests for the TraceroutePacket class.

These tests verify the complex logic of traceroute path analysis,
including forward/return path interpretation and RF hop analysis.
"""

import json
import time
from unittest.mock import patch

import pytest

from src.malla.models.traceroute import TraceroutePacket


class TestTraceroutePacketBasic:
    """Test basic TraceroutePacket functionality."""

    @pytest.mark.unit
    def test_simple_forward_traceroute(self):
        """Test a simple forward traceroute without return path."""
        packet_data = {
            "id": 1,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops: source->intermediate->destination)
            "raw_payload": json.dumps(
                {
                    "route_nodes": [0x11111111],
                    "snr_towards": [-5.0, -8.0],
                    "route_back": [],
                    "snr_back": [],
                }
            ).encode(),
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            with patch("src.malla.utils.node_utils.get_bulk_node_names") as mock_names:
                mock_names.return_value = {
                    0x12345678: "Alpha",
                    0x87654321: "Beta",
                    0x11111111: "Charlie",
                }

                tr = TraceroutePacket(packet_data)

                # Forward path without return data: from_node + route_nodes (no auto-added destination)
                assert tr.forward_path.node_ids == [0x12345678, 0x11111111]
                assert tr.forward_path.node_names == ["Alpha", "Charlie"]
                assert not tr.has_return_path()
                assert len(tr.forward_path.hops) == 1  # Only one hop: Alpha -> Charlie

    @pytest.mark.unit
    def test_traceroute_with_return_path(self):
        """Test traceroute with return path data."""
        packet_data = {
            "id": 2,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops on forward journey, now returning)
            "raw_payload": json.dumps(
                {
                    "route_nodes": [0x11111111],
                    "snr_towards": [-5.0, -8.0],
                    "route_back": [0x11111111],
                    "snr_back": [-7.0, -6.0],
                }
            ).encode(),
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [0x11111111],
                "snr_back": [-7.0, -6.0],
            }

            with patch("src.malla.utils.node_utils.get_bulk_node_names") as mock_names:
                mock_names.return_value = {
                    0x12345678: "Alpha",
                    0x87654321: "Beta",
                    0x11111111: "Charlie",
                }

                tr = TraceroutePacket(packet_data)

                # With return path, forward display shows: to_node + route_nodes + from_node (return journey)
                assert tr.forward_path.node_ids == [0x87654321, 0x11111111, 0x12345678]
                assert tr.forward_path.node_names == ["Beta", "Charlie", "Alpha"]
                assert tr.has_return_path()
                assert tr.return_path is not None
                # Return path: from_node + route_back
                assert tr.return_path.node_ids == [0x12345678, 0x11111111]

    @pytest.mark.unit
    def test_direct_hop_traceroute(self):
        """Test a direct single-hop traceroute."""
        packet_data = {
            "id": 3,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 2,  # Started with 2 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 1 hop: source->destination)
            "raw_payload": json.dumps(
                {
                    "route_nodes": [],
                    "snr_towards": [-4.0],
                    "route_back": [],
                    "snr_back": [],
                }
            ).encode(),
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [],
                "snr_towards": [-4.0],
                "route_back": [],
                "snr_back": [],
            }

            with patch("src.malla.utils.node_utils.get_bulk_node_names") as mock_names:
                mock_names.return_value = {0x12345678: "Alpha", 0x87654321: "Beta"}

                tr = TraceroutePacket(packet_data)

                # Direct hop without return path: just from_node (no route_nodes, no auto-added destination)
                assert tr.forward_path.node_ids == [0x12345678]
                assert tr.forward_path.node_names == ["Alpha"]
                assert len(tr.forward_path.hops) == 0  # No hops in forward path display

                # But RF path should show the actual direct hop
                rf_hops = tr.get_rf_hops()
                assert len(rf_hops) == 1
                assert rf_hops[0].from_node_id == 0x12345678
                assert rf_hops[0].to_node_id == 0x87654321
                assert rf_hops[0].snr == -4.0


class TestTraceroutePacketRFAnalysis:
    """Test RF path analysis functionality."""

    @pytest.mark.unit
    def test_actual_rf_path_forward(self):
        """Test actual RF path analysis for forward traceroute."""
        packet_data = {
            "id": 4,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,  # Source (Perseo in real example)
            "to_node_id": 0x87654321,  # Destination (Aj0 in real example)
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],  # Intermediate node (Nch in real example)
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # With realistic hop values, is_going_back() returns False
            # So RF path uses forward order: source -> route_nodes -> destination
            rf_hops = tr.get_rf_hops()
            assert len(rf_hops) == 2  # Two SNR values = two RF hops
            assert rf_hops[0].from_node_id == 0x12345678  # Source to intermediate
            assert rf_hops[0].to_node_id == 0x11111111
            assert rf_hops[0].snr == -5.0
            assert rf_hops[1].from_node_id == 0x11111111  # Intermediate to destination
            assert rf_hops[1].to_node_id == 0x87654321
            assert rf_hops[1].snr == -8.0

    @pytest.mark.unit
    def test_actual_rf_path_return(self):
        """Test actual RF path analysis for traceroute with both forward and return data."""
        packet_data = {
            "id": 5,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 4,  # Started with 4 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 3 hops: 2 forward + 1 return so far)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [0x11111111],
                "snr_back": [-7.0, -6.0],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # This packet has both forward and return path data
            # RF hops should include BOTH forward and return RF transmissions
            rf_hops = tr.get_rf_hops()
            assert tr.actual_rf_path.path_type == "combined_rf"
            assert len(rf_hops) == 4  # Two forward SNR values + Two return SNR values

            # Forward RF hops (when has_return_path, shows return journey: to->route->from)
            assert rf_hops[0].direction == "forward_rf"
            assert rf_hops[0].from_node_id == 0x87654321  # to_node first
            assert rf_hops[0].to_node_id == 0x11111111
            assert rf_hops[0].snr == -5.0
            assert rf_hops[1].direction == "forward_rf"
            assert rf_hops[1].from_node_id == 0x11111111
            assert rf_hops[1].to_node_id == 0x12345678  # from_node last
            assert rf_hops[1].snr == -8.0

            # Return RF hops (from->route_back)
            assert rf_hops[2].direction == "return_rf"
            assert rf_hops[2].from_node_id == 0x12345678
            assert rf_hops[2].to_node_id == 0x11111111
            assert rf_hops[2].snr == -7.0
            assert rf_hops[3].direction == "return_rf"
            assert rf_hops[3].snr == -6.0

    @pytest.mark.unit
    def test_actual_rf_path_return_only(self):
        """Test actual RF path analysis for traceroute with only return path data."""
        packet_data = {
            "id": 5,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 4,  # Started with 4 hops
            "hop_limit": 2,  # 2 hops remaining (consumed 2 hops on forward, now returning)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [],  # No forward SNR data
                "route_back": [0x11111111],
                "snr_back": [-7.0, -6.0],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # This packet has only return path RF data
            rf_hops = tr.get_rf_hops()
            assert tr.actual_rf_path.path_type == "combined_rf"
            assert len(rf_hops) == 2  # Only return SNR values

            # Return RF hops only
            assert rf_hops[0].direction == "return_rf"
            assert rf_hops[0].from_node_id == 0x12345678
            assert rf_hops[0].to_node_id == 0x11111111
            assert rf_hops[0].snr == -7.0
            assert rf_hops[1].direction == "return_rf"
            assert rf_hops[1].snr == -6.0

    @pytest.mark.unit
    def test_contains_hop_method(self):
        """Test the contains_hop method for RF link analysis."""
        packet_data = {
            "id": 6,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,  # Source
            "to_node_id": 0x87654321,  # Destination
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # With realistic hop values, is_going_back() returns False
            # RF path uses forward order: source -> route_nodes -> destination
            # So the actual RF hops are: source->intermediate and intermediate->destination
            assert tr.contains_hop(
                0x12345678, 0x11111111
            )  # First hop: source -> intermediate
            assert tr.contains_hop(
                0x11111111, 0x87654321
            )  # Second hop: intermediate -> destination

            # Should work in both directions
            assert tr.contains_hop(0x11111111, 0x12345678)  # Reverse of first hop
            assert tr.contains_hop(0x87654321, 0x11111111)  # Reverse of second hop

            # Should not find non-existent hops
            assert not tr.contains_hop(
                0x12345678, 0x87654321
            )  # Direct hop doesn't exist in this traceroute
            assert not tr.contains_hop(0x99999999, 0x11111111)  # Non-existent node

    @pytest.mark.unit
    def test_get_hop_snr_method(self):
        """Test the get_hop_snr method."""
        packet_data = {
            "id": 7,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,  # Source
            "to_node_id": 0x87654321,  # Destination
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # With realistic hop values, is_going_back() returns False
            # RF path uses forward order: source -> route_nodes -> destination
            # So the actual RF hops are: source->intermediate and intermediate->destination
            assert (
                tr.get_hop_snr(0x12345678, 0x11111111) == -5.0
            )  # First hop: source -> intermediate
            assert (
                tr.get_hop_snr(0x11111111, 0x87654321) == -8.0
            )  # Second hop: intermediate -> destination

            # Should work in both directions
            assert (
                tr.get_hop_snr(0x11111111, 0x12345678) == -5.0
            )  # Reverse of first hop
            assert (
                tr.get_hop_snr(0x87654321, 0x11111111) == -8.0
            )  # Reverse of second hop

            # Should return None for non-existent hops
            assert tr.get_hop_snr(0x12345678, 0x87654321) is None
            assert tr.get_hop_snr(0x99999999, 0x11111111) is None


class TestTraceroutePacketUtilities:
    """Test utility methods and data structures."""

    @pytest.mark.unit
    def test_path_summary(self):
        """Test get_path_summary method."""
        packet_data = {
            "id": 8,
            "timestamp": 1234567890.0,
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)
            summary = tr.get_path_summary()

            assert summary["packet_id"] == 8
            assert summary["from_node_id"] == 0x12345678
            assert summary["to_node_id"] == 0x87654321
            assert summary["timestamp"] == 1234567890.0
            assert summary["gateway_id"] == "!12345678"
            assert not summary["has_return_path"]
            assert summary["forward_hops"] == 1  # Only one hop in forward path display
            assert summary["return_hops"] == 0
            assert summary["total_rf_hops"] == 2  # Two RF hops actually occurred
            assert summary["route_nodes"] == [0x11111111]
            assert summary["snr_towards"] == [-5.0, -8.0]

    @pytest.mark.unit
    def test_format_path_display(self):
        """Test path formatting for display."""
        packet_data = {
            "id": 9,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            with patch("src.malla.utils.node_utils.get_bulk_node_names") as mock_names:
                mock_names.return_value = {
                    0x12345678: "Alpha",
                    0x87654321: "Beta",
                    0x11111111: "Charlie",
                }

                tr = TraceroutePacket(packet_data)

                # Forward path display: from_node + route_nodes (no auto-added destination)
                display = tr.format_path_display("display")
                assert display == "Alpha → Charlie"

                # Test actual RF path - shows the actual hops that occurred
                rf_display = tr.format_path_display("actual_rf")
                # RF path includes all nodes that participated in RF transmission
                assert (
                    "Alpha" in rf_display
                    and "Charlie" in rf_display
                    and "Beta" in rf_display
                )

    @pytest.mark.unit
    def test_template_context(self):
        """Test to_template_context method."""
        packet_data = {
            "id": 10,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 3,  # Started with 3 hops
            "hop_limit": 1,  # 1 hop remaining (consumed 2 hops)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111],
                "snr_towards": [-5.0, -8.0],
                "route_back": [],
                "snr_back": [],
            }

            with patch("src.malla.utils.node_utils.get_bulk_node_names") as mock_names:
                mock_names.return_value = {
                    0x12345678: "Alpha",
                    0x87654321: "Beta",
                    0x11111111: "Charlie",
                }

                tr = TraceroutePacket(packet_data)
                context = tr.to_template_context()

                assert "route_nodes" in context
                assert "route_back" in context
                assert "snr_towards" in context
                assert "snr_back" in context
                assert "has_return_path" in context
                assert "is_complete" in context
                assert "display_path" in context
                assert "return_path" in context
                assert "forward_hops" in context
                assert "return_hops" in context
                assert "route_node_names" in context

                assert not context["has_return_path"]
                assert (
                    len(context["forward_hops"]) == 1
                )  # Only one hop in forward display
                assert len(context["return_hops"]) == 0


class TestTraceroutePacketEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.unit
    def test_empty_payload(self):
        """Test handling of empty or None payload."""
        packet_data = {
            "id": 11,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 2,  # Started with 2 hops
            "hop_limit": 2,  # 2 hops remaining (no hops consumed yet)
            "raw_payload": None,
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [],
                "snr_towards": [],
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # Should handle gracefully - forward path is just from_node (no route_nodes)
            assert tr.forward_path.node_ids == [0x12345678]
            assert len(tr.forward_path.hops) == 0  # No hops in forward display
            assert not tr.has_return_path()
            assert len(tr.get_rf_hops()) == 0  # No SNR data = no RF hops

    @pytest.mark.unit
    def test_malformed_payload(self):
        """Test handling of malformed payload data."""
        packet_data = {
            "id": 12,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 2,  # Started with 2 hops
            "hop_limit": 2,  # 2 hops remaining (no hops consumed yet)
            "raw_payload": b"malformed data",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.side_effect = Exception("Parse error")

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # Should fall back to empty route data
            assert tr.route_data == {
                "route_nodes": [],
                "snr_towards": [],
                "route_back": [],
                "snr_back": [],
            }

    @pytest.mark.unit
    def test_incomplete_traceroute(self):
        """Test handling of incomplete traceroute (didn't reach destination)."""
        packet_data = {
            "id": 13,
            "timestamp": time.time(),
            "from_node_id": 0x12345678,
            "to_node_id": 0x87654321,
            "gateway_id": "!12345678",
            "hop_start": 4,  # Started with 4 hops
            "hop_limit": 2,  # 2 hops remaining (consumed 2 hops, got stuck)
            "raw_payload": b"test",
        }

        with patch(
            "src.malla.utils.traceroute_utils.parse_traceroute_payload"
        ) as mock_parse:
            mock_parse.return_value = {
                "route_nodes": [0x11111111, 0x22222222],  # Doesn't end with to_node_id
                "snr_towards": [-5.0, -8.0],  # Only 2 SNR values for 3 intended hops
                "route_back": [],
                "snr_back": [],
            }

            tr = TraceroutePacket(packet_data, resolve_names=False)

            # Should be marked as incomplete
            assert not tr.is_complete()

            # Forward path shows: from_node + route_nodes (no auto-added destination)
            assert tr.forward_path.node_ids == [0x12345678, 0x11111111, 0x22222222]

            # RF path should only include hops that actually occurred (with SNR data)
            rf_hops = tr.get_rf_hops()
            assert len(rf_hops) == 2  # Only 2 SNR values = 2 actual hops
            assert rf_hops[0].from_node_id == 0x12345678
            assert rf_hops[0].to_node_id == 0x11111111
            assert rf_hops[1].from_node_id == 0x11111111
            assert (
                rf_hops[1].to_node_id == 0x22222222
            )  # Last hop reached 0x22222222, not destination

    @pytest.mark.unit
    def test_snr_conversion_from_scaled_integers(self):
        """Test that SNR values are correctly converted from scaled integers to dB."""
        # Create a test with the actual parse_traceroute_payload function to verify conversion
        with patch("meshtastic.mesh_pb2.RouteDiscovery") as mock_route_discovery_class:
            # Create a mock RouteDiscovery instance
            mock_route_discovery = mock_route_discovery_class.return_value

            # Simulate raw protobuf values that would be scaled integers
            # In Meshtastic, SNR values are often stored as integers that need /4 conversion
            mock_route_discovery.route = [0x11111111]
            mock_route_discovery.snr_towards = [
                -20.0,
                -32.0,
            ]  # These should become -5.0, -8.0
            mock_route_discovery.route_back = [0x22222222]
            mock_route_discovery.snr_back = [-28.0]  # This should become -7.0

            # Import and call the actual function to test the conversion
            from src.malla.utils.traceroute_utils import parse_traceroute_payload

            # Call with dummy payload (protobuf parsing will be mocked)
            result = parse_traceroute_payload(b"dummy_payload")

            # Verify the SNR values were divided by 4
            assert result["snr_towards"] == [-5.0, -8.0]  # -20/4, -32/4
            assert result["snr_back"] == [-7.0]  # -28/4
            assert result["route_nodes"] == [0x11111111]
            assert result["route_back"] == [0x22222222]
