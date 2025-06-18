"""
Integration tests for node routes.

Tests the node detail endpoint with fixture data to ensure it renders properly.
"""

import pytest


class TestNodeRoutes:
    """Test node-related routes."""

    @pytest.mark.integration
    def test_nodes_page_loads(self, client):
        """Test that the nodes page loads successfully."""
        response = client.get("/nodes")
        assert response.status_code == 200
        assert b"Nodes" in response.data

    @pytest.mark.integration
    def test_node_detail_with_valid_node_id(self, client):
        """Test node detail page with a valid node ID from fixture data."""
        # Use Test Gateway Alpha from fixture data
        node_id = 1128074276  # 0x433d0c24

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        # Check that the page contains expected content from fixture data
        assert b"Test Gateway Alpha" in response.data
        assert b"Node Details" in response.data
        assert b"!433d0c24" in response.data  # Hex ID
        assert b"TBEAM" in response.data  # Hardware model
        assert b"ROUTER" in response.data  # Role

    @pytest.mark.integration
    def test_node_detail_with_hex_node_id(self, client):
        """Test node detail page with a hex node ID."""
        # Use hex format of Test Gateway Alpha
        hex_node_id = "!433d0c24"

        response = client.get(f"/node/{hex_node_id}")
        assert response.status_code == 200

        # Check that the page contains expected content
        assert b"Test Gateway Alpha" in response.data
        assert b"Node Details" in response.data

    @pytest.mark.integration
    def test_node_detail_with_decimal_hex_node_id(self, client):
        """Test node detail page with a decimal hex node ID."""
        # Use decimal hex format
        hex_node_id = "433d0c24"

        response = client.get(f"/node/{hex_node_id}")
        assert response.status_code == 200

        # Check that the page contains expected content
        assert b"Test Gateway Alpha" in response.data
        assert b"Node Details" in response.data

    @pytest.mark.integration
    def test_node_detail_with_mobile_node(self, client):
        """Test node detail page with Test Mobile Beta from fixture data."""
        # Use Test Mobile Beta node
        node_id = 1128074277  # 0x433d0c25

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        # Check that the page contains expected content
        assert b"Test Mobile Beta" in response.data
        assert b"!433d0c25" in response.data
        assert b"HELTEC_V3" in response.data
        assert b"CLIENT" in response.data

    @pytest.mark.integration
    def test_node_detail_with_repeater_node(self, client):
        """Test node detail page with Test Repeater Gamma from fixture data."""
        # Use Test Repeater Gamma node
        node_id = 1128074278  # 0x433d0c26

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        # Check that the page contains expected content
        assert b"Test Repeater Gamma" in response.data
        assert b"!433d0c26" in response.data
        assert b"TBEAM" in response.data
        assert b"REPEATER" in response.data

    @pytest.mark.integration
    def test_node_detail_with_nonexistent_node(self, client):
        """Test node detail page with a non-existent node ID."""
        # Use a node ID that doesn't exist in the fixture data
        node_id = 999999999

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 404
        assert b"Node not found" in response.data

    @pytest.mark.integration
    def test_node_detail_with_invalid_node_id(self, client):
        """Test node detail page with an invalid node ID format."""
        # Use an invalid node ID format
        invalid_node_id = "invalid_id"

        response = client.get(f"/node/{invalid_node_id}")
        assert response.status_code == 400
        assert b"Invalid node ID format" in response.data

    @pytest.mark.integration
    def test_node_detail_contains_required_sections(self, client):
        """Test that node detail page contains all required sections."""
        # Use Test Gateway Alpha which should have packet data in fixtures
        node_id = 1128074276  # Test Gateway Alpha

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        # Check for required sections in the HTML
        response_text = response.data.decode("utf-8")

        # Basic information section
        assert "Node Information" in response_text
        assert "Total Packets" in response_text
        assert "Destinations" in response_text
        assert "Avg RSSI" in response_text

        # Check for node metrics
        assert "metric-value" in response_text

        # Check for breadcrumb navigation
        assert "breadcrumb" in response_text
        assert "Home" in response_text
        assert "Nodes" in response_text

    @pytest.mark.integration
    def test_node_detail_packet_data_display(self, client):
        """Test that node detail page displays packet data correctly."""
        # Use Test Gateway Alpha which should have packet data in fixtures
        node_id = 1128074276  # Test Gateway Alpha

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Should show packet count greater than 0
        assert "Total Packets" in response_text

        # Check for protocol breakdown section if there are packets
        if "Protocol Usage" in response_text:
            assert "Protocol" in response_text
            assert "Count" in response_text

    @pytest.mark.integration
    def test_node_detail_navigation_links(self, client):
        """Test that node detail page contains proper navigation links."""
        node_id = 1128074276  # Test Gateway Alpha

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for quick action links
        assert "View All Packets" in response_text
        assert f"/packets?from_node={node_id}" in response_text

        # Check for traceroute link
        assert "View Traceroutes" in response_text
        assert f"/traceroute?from_node={node_id}" in response_text
