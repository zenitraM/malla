"""
Integration tests for traceroute routes.

Tests the traceroute analysis page and related functionality,
specifically focusing on the node dropdown display fix.
"""

import re
from unittest.mock import patch

import pytest


class TestTracerouteRoutes:
    """Test traceroute route functionality."""

    @pytest.mark.integration
    def test_traceroute_page_loads(self, client):
        """Test that the traceroute page loads successfully."""
        response = client.get("/traceroute")
        assert response.status_code == 200
        assert b"Traceroute Analysis" in response.data
        assert b"Source Node" in response.data
        assert b"Destination Node" in response.data

    @pytest.mark.integration
    def test_traceroute_page_with_filters(self, client):
        """Test traceroute page with query parameters."""
        response = client.get("/traceroute?from_node=305419896&to_node=2271560481")
        assert response.status_code == 200
        assert b"Traceroute Analysis" in response.data

    @pytest.mark.integration
    @patch("src.malla.database.repositories.NodeRepository.get_available_from_nodes")
    @patch("src.malla.database.repositories.PacketRepository.get_unique_gateway_ids")
    def test_traceroute_node_dropdown_format(self, mock_gateways, mock_nodes, client):
        """Test that node dropdowns show proper names and IDs."""
        # Mock the repository data
        mock_nodes.return_value = [
            {
                "node_id": 305419896,  # 0x12345678
                "long_name": "Alpha Gateway",
                "short_name": "Alpha",
                "hex_id": "!12345678",
                "packet_count": 150,
            },
            {
                "node_id": 2271560481,  # 0x87654321
                "long_name": None,
                "short_name": "Beta Repeater",
                "hex_id": "!87654321",
                "packet_count": 75,
            },
            {
                "node_id": 286331153,  # 0x11111111
                "long_name": "",
                "short_name": "",
                "hex_id": "!11111111",
                "packet_count": 25,
            },
        ]
        mock_gateways.return_value = ["!12345678", "!87654321"]

        response = client.get("/traceroute")
        assert response.status_code == 200

        # Check that the response contains the traceroute page elements
        response_text = response.data.decode("utf-8")

        # Should contain the node picker components (JavaScript-based)
        assert "node-picker-input" in response_text
        assert "Source Node" in response_text
        assert "Destination Node" in response_text
        assert "Route Node" in response_text

        # Should contain the JavaScript for node picker functionality
        assert "node-picker.js" in response_text

        # Extract just the node picker sections to check for raw repository keys
        # Find the three node picker containers
        picker_pattern = r'<div class="node-picker-container[^>]*>.*?</div>\s*</div>'
        picker_sections = re.findall(picker_pattern, response_text, re.DOTALL)

        # Check that picker sections don't contain raw repository keys
        for picker_html in picker_sections:
            # These raw keys should not appear in the picker HTML
            assert "long_name" not in picker_html
            assert "short_name" not in picker_html
            # Note: 'node_id' might appear in JavaScript, so we don't check for it here

    @pytest.mark.integration
    @patch("src.malla.database.repositories.NodeRepository.get_available_from_nodes")
    @patch("src.malla.database.repositories.PacketRepository.get_unique_gateway_ids")
    def test_traceroute_node_dropdown_empty_data(
        self, mock_gateways, mock_nodes, client
    ):
        """Test traceroute page with no available nodes."""
        mock_nodes.return_value = []
        mock_gateways.return_value = []

        response = client.get("/traceroute")
        assert response.status_code == 200

        # Should still load the page successfully
        assert b"Traceroute Analysis" in response.data
        # Check for the specific placeholder texts used in traceroute template
        assert b"All source nodes" in response.data
        assert b"All destination nodes" in response.data
        assert b"All route nodes" in response.data

    @pytest.mark.integration
    @patch("src.malla.database.repositories.NodeRepository.get_available_from_nodes")
    @patch("src.malla.database.repositories.PacketRepository.get_unique_gateway_ids")
    def test_traceroute_node_selection_preserved(
        self, mock_gateways, mock_nodes, client
    ):
        """Test that selected node values are preserved in dropdowns."""
        mock_nodes.return_value = [
            {
                "node_id": 305419896,
                "long_name": "Test Node",
                "short_name": "Test",
                "hex_id": "!12345678",
                "packet_count": 100,
            }
        ]
        mock_gateways.return_value = ["!12345678"]

        # Test with from_node filter
        response = client.get("/traceroute?from_node=305419896")
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Should have the from_node filter form field
        assert "from_node" in response_text
        # Modern implementation loads node data dynamically, so we check for the input structure
        assert 'name="from_node"' in response_text

    @pytest.mark.integration
    def test_traceroute_hops_page_loads(self, client):
        """Test that the traceroute hops page loads successfully."""
        response = client.get("/traceroute-hops")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_traceroute_graph_page_loads(self, client):
        """Test that the traceroute graph page loads successfully."""
        response = client.get("/traceroute-graph")
        assert response.status_code == 200

        # Check that the page contains expected elements
        response_text = response.data.decode("utf-8")
        assert "Network Graph" in response_text
        assert "networkGraph" in response_text
        assert "d3js.org" in response_text

    @pytest.mark.integration
    def test_traceroute_graph_with_parameters(self, client):
        """Test that the traceroute graph page accepts filter parameters."""
        response = client.get(
            "/traceroute-graph?hours=72&min_snr=-20&include_indirect=true"
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")
        assert "selected" in response_text  # Should have selected option values


class TestTracerouteRouteErrorHandling:
    """Test error handling in traceroute routes."""

    @pytest.mark.integration
    @patch("src.malla.routes.traceroute_routes.render_template")
    def test_traceroute_handles_repository_error(self, mock_render, client):
        """Test that traceroute page handles template errors gracefully."""
        mock_render.side_effect = Exception("Template error")

        response = client.get("/traceroute")
        assert response.status_code == 500
        assert b"Traceroute error" in response.data

    @pytest.mark.integration
    def test_traceroute_invalid_filter_values(self, client):
        """Test traceroute page with invalid filter values."""
        # Test with invalid node IDs
        response = client.get("/traceroute?from_node=invalid&to_node=also_invalid")
        assert (
            response.status_code == 200
        )  # Should still load, just ignore invalid filters

        # Test with invalid timestamps
        response = client.get(
            "/traceroute?start_time=invalid_date&end_time=also_invalid"
        )
        assert (
            response.status_code == 200
        )  # Should still load, just ignore invalid filters


class TestTracerouteTemplateIntegration:
    """Test integration between routes and templates."""

    @pytest.mark.integration
    @patch("src.malla.database.repositories.NodeRepository.get_available_from_nodes")
    @patch("src.malla.database.repositories.PacketRepository.get_unique_gateway_ids")
    def test_all_dropdown_types_use_correct_format(
        self, mock_gateways, mock_nodes, client
    ):
        """Test that all node dropdowns (from, to, route) use the correct format."""
        mock_nodes.return_value = [
            {
                "node_id": 305419896,
                "long_name": "Test Node Alpha",
                "short_name": "Alpha",
                "hex_id": "!12345678",
                "packet_count": 50,
            }
        ]
        mock_gateways.return_value = ["!12345678"]

        response = client.get("/traceroute")
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # All three node picker components should be present
        # Count how many times the node picker input appears (should be 3: from_node, to_node, route_node)
        node_picker_count = response_text.count("node-picker-input")
        assert node_picker_count == 3, (
            f"Expected 3 node picker inputs, found {node_picker_count}"
        )

        # All three hidden inputs should be present with correct names
        assert 'name="from_node"' in response_text
        assert 'name="to_node"' in response_text
        assert 'name="route_node"' in response_text

        # Should contain the labels for all three dropdowns
        assert "Source Node" in response_text
        assert "Destination Node" in response_text
        assert "Route Node" in response_text


class TestTracerouteRouteNodeFilter:
    """Test the route_node filter functionality."""

    @pytest.mark.integration
    def test_route_node_filter_api_endpoint(self, client):
        """Test that the route_node filter works in the API endpoint."""
        # This test uses the real repository and database
        # We expect that the route_node filter should work correctly
        # Since the test database may not have specific traceroute data, we'll test basic functionality

        # Test without route_node filter - should return whatever traceroute data exists
        response = client.get("/api/traceroute/data?page=1&limit=10")
        assert response.status_code == 200
        data = response.get_json()
        total_packets = data["total_count"]

        # Test with route_node filter for a non-existent node - should return 0 packets
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&route_node=123456789"  # Non-existent node
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

        # Test that the route_node parameter is properly parsed and doesn't cause errors
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&route_node=invalid"  # Invalid node ID
        )
        assert response.status_code == 200  # Should handle gracefully
        data = response.get_json()
        # Should return all packets since invalid filter is ignored
        assert data["total_count"] == total_packets
