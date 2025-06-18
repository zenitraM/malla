"""
Unit tests for the traceroute link endpoint bug fix.

Tests that the endpoint properly handles RF hops without crashing on missing gateway_node_name.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from src.malla.models.traceroute import TracerouteHop, TraceroutePacket


class TestTracerouteLinkEndpointFix:
    """Test the fix for the traceroute link endpoint gateway_node_name bug."""

    @pytest.mark.unit
    def test_endpoint_returns_rf_hops_without_gateway_node_name_error(self):
        """
        Test that the endpoint returns RF hops between nodes without crashing
        on the missing gateway_node_name attribute.

        This is a regression test for the bug where the endpoint tried to access
        tr_packet.gateway_node_name which doesn't exist on TraceroutePacket.
        """

        # Mock TracerouteRepository.get_traceroute_packets
        mock_packets = [
            {
                "id": 12345,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 10:30:00",
                "from_node_id": 2510468508,
                "to_node_id": 1128074276,
                "gateway_id": 3333333333,
                "raw_payload": b"fake_payload",
            }
        ]

        # Mock TraceroutePacket with RF hops between target nodes
        mock_traceroute_packet = MagicMock(spec=TraceroutePacket)
        mock_traceroute_packet.from_node_name = "Test Node A"
        mock_traceroute_packet.to_node_name = "Test Node B"
        mock_traceroute_packet.gateway_id = 3333333333
        # Note: gateway_node_name is intentionally NOT set to test the bug fix
        mock_traceroute_packet.format_path_display.return_value = "A -> B"
        mock_traceroute_packet.get_display_hops.return_value = []

        # Create a mock RF hop between the target nodes
        mock_rf_hop = MagicMock(spec=TracerouteHop)
        mock_rf_hop.from_node_id = 2510468508
        mock_rf_hop.to_node_id = 1128074276
        mock_rf_hop.snr = -16.5
        mock_rf_hop.from_node_name = "Test Node A"
        mock_rf_hop.to_node_name = "Test Node B"
        mock_rf_hop.direction = "forward_rf"

        mock_traceroute_packet.get_rf_hops.return_value = [mock_rf_hop]

        with patch(
            "src.malla.routes.api_routes.TracerouteRepository"
        ) as mock_repo_class:
            mock_repo = mock_repo_class
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}

            with patch("src.malla.routes.api_routes.NodeRepository") as mock_node_repo:
                mock_node_repo.get_bulk_node_names.return_value = {
                    2510468508: "Test Node A",
                    1128074276: "Test Node B",
                    3333333333: "Gateway Node",
                }

                with patch(
                    "src.malla.routes.api_routes.TraceroutePacket"
                ) as mock_traceroute_class:
                    mock_traceroute_class.return_value = mock_traceroute_packet

                    # Import here to use the mocked dependencies
                    from flask import Flask

                    from src.malla.routes.api_routes import register_api_routes

                    app = Flask(__name__)
                    register_api_routes(app)

                    with app.test_client() as client:
                        # Test the endpoint that was previously crashing
                        response = client.get(
                            "/api/traceroute/link/2510468508/1128074276"
                        )

                        # Should not crash and should return valid data
                        assert response.status_code == 200

                        data = json.loads(response.data)

                        # Should have traceroutes (not empty due to the crash)
                        assert "traceroutes" in data
                        assert len(data["traceroutes"]) > 0

                        # Should have proper statistics
                        assert "avg_snr" in data
                        assert data["avg_snr"] == -16.5

                        # Should have direction counts
                        assert "direction_counts" in data

                        # Verify the traceroute entry structure (with gateway_node_name)
                        traceroute = data["traceroutes"][0]
                        expected_fields = {
                            "id",
                            "timestamp",
                            "timestamp_str",
                            "from_node_id",
                            "to_node_id",
                            "from_node_name",
                            "to_node_name",
                            "gateway_id",
                            "gateway_node_name",
                            "hop_snr",
                            "route_hops",
                            "complete_path_display",
                        }

                        for field in expected_fields:
                            assert field in traceroute, f"Missing field: {field}"

                        # Ensure gateway_node_name is properly set
                        assert traceroute["gateway_node_name"] == "Gateway Node"

                        # Verify specific values
                        assert traceroute["from_node_id"] == 2510468508
                        assert traceroute["to_node_id"] == 1128074276
                        assert traceroute["hop_snr"] == -16.5
                        assert traceroute["gateway_id"] == 3333333333

    @pytest.mark.unit
    def test_endpoint_handles_no_rf_hops_gracefully(self):
        """
        Test that the endpoint returns empty results when no RF hops exist between nodes.
        """

        # Mock TracerouteRepository.get_traceroute_packets
        mock_packets = [
            {
                "id": 12346,
                "timestamp": time.time(),
                "timestamp_str": "2024-01-20 10:30:00",
                "from_node_id": 1111111111,
                "to_node_id": 2222222222,
                "gateway_id": 3333333333,
                "raw_payload": b"fake_payload",
            }
        ]

        # Mock TraceroutePacket with NO RF hops between target nodes
        mock_traceroute_packet = MagicMock(spec=TraceroutePacket)
        mock_traceroute_packet.get_rf_hops.return_value = []  # No RF hops
        mock_traceroute_packet.get_display_hops.return_value = []

        with patch(
            "src.malla.routes.api_routes.TracerouteRepository"
        ) as mock_repo_class:
            mock_repo = mock_repo_class
            mock_repo.get_traceroute_packets.return_value = {"packets": mock_packets}

            with patch("src.malla.routes.api_routes.NodeRepository") as mock_node_repo:
                mock_node_repo.get_bulk_node_names.return_value = {
                    1111111111: "Test Node A",
                    2222222222: "Test Node B",
                }

                with patch(
                    "src.malla.routes.api_routes.TraceroutePacket"
                ) as mock_traceroute_class:
                    mock_traceroute_class.return_value = mock_traceroute_packet

                    # Import here to use the mocked dependencies
                    from flask import Flask

                    from src.malla.routes.api_routes import register_api_routes

                    app = Flask(__name__)
                    register_api_routes(app)

                    with app.test_client() as client:
                        # Test with nodes that have no RF hops between them
                        response = client.get(
                            "/api/traceroute/link/9999999999/8888888888"
                        )

                        # Should not crash
                        assert response.status_code == 200

                        data = json.loads(response.data)

                        # Should return empty results
                        assert data["traceroutes"] == []
                        assert data["avg_snr"] is None
                        assert data["direction_counts"] == {"forward": 0, "reverse": 0}
