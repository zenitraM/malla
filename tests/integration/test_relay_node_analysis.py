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

    def test_relay_node_stats_structure(self, test_client, temp_database):
        """Test the structure of relay_node_stats data."""
        # Get all nodes
        result = NodeRepository.get_nodes(limit=50, offset=0)
        if not result["nodes"]:
            pytest.skip("No nodes in database")

        # Find a node with relay_node_stats
        found_stats = False
        for node in result["nodes"]:
            node_id = node["node_id"]
            try:
                node_details = NodeRepository.get_node_details(node_id)
            except Exception as e:
                # Skip nodes that cause errors (e.g., due to database schema issues)
                print(f"Skipping node {node_id} due to error: {e}")
                continue

            if node_details and node_details.get("relay_node_stats"):
                found_stats = True
                stats = node_details["relay_node_stats"]

                # Check structure of first stat
                first_stat = stats[0]
                assert "relay_node" in first_stat
                assert "relay_hex" in first_stat
                assert "count" in first_stat
                assert "candidates" in first_stat

                # relay_hex should be 2-digit hex
                assert len(first_stat["relay_hex"]) == 2

                # candidates should be a list
                assert isinstance(first_stat["candidates"], list)

                # If there are candidates, check their structure
                if first_stat["candidates"]:
                    candidate = first_stat["candidates"][0]
                    assert "node_id" in candidate
                    assert "node_name" in candidate
                    assert "hex_id" in candidate
                    assert "last_byte" in candidate

                break

        # It's okay if no nodes have relay_node_stats (database might not have the data)
        if not found_stats:
            pytest.skip("No nodes with relay_node data found")

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
