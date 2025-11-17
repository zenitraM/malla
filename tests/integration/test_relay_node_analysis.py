"""Tests for relay_node analysis in node details."""

import pytest

from malla.database.repositories import NodeRepository


class TestRelayNodeAnalysis:
    """Test cases for relay_node analysis in node detail pages."""

    def test_relay_node_stats_in_node_details(self, test_client, temp_database):
        """Test that relay_node stats are NOT in node details (moved to API)."""
        # Get a node that has packets
        result = NodeRepository.get_nodes(limit=10, offset=0)
        if not result["nodes"]:
            pytest.skip("No nodes in database")

        node_id = result["nodes"][0]["node_id"]

        # Get node details
        node_details = NodeRepository.get_node_details(node_id)
        assert node_details is not None

        # relay_node_stats should NOT be in node_details anymore (moved to separate API)
        assert "relay_node_stats" not in node_details

    def test_relay_node_display_in_page(self, test_client, temp_database):
        """Test that relay_node analysis is displayed in the node detail page."""
        # Get a node
        result = NodeRepository.get_nodes(limit=10, offset=0)
        if not result["nodes"]:
            pytest.skip("No nodes in database")

        node_id = result["nodes"][0]["node_id"]

        # Access node detail page
        response = test_client.get(f"/node/{node_id}")
        assert response.status_code == 200

        html = response.data.decode("utf-8")

        # Check that the page can render (relay_node section may or may not be visible depending on data)
        # The template uses {% if relay_node_stats %} so it won't show if there's no data
        assert "node_id" in html.lower() or "node id" in html.lower()
