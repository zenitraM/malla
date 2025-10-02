"""
Unit tests for node picker broadcast functionality.

Tests that the node picker correctly includes broadcast options when configured.
"""

import re


class TestNodePickerBroadcast:
    """Test node picker broadcast functionality."""

    def test_from_node_dropdown_includes_broadcast(self, app, client):
        """Test that from_node dropdown includes broadcast option when include_broadcast=true."""
        # Get the packets page which has from_node picker with include_broadcast=true
        response = client.get("/packets")
        assert response.status_code == 200

        content = response.data.decode("utf-8")

        # Look for from_node field with data-include-broadcast="true"
        # Check that from_node exists and has include_broadcast enabled
        assert 'data-include-broadcast="true"' in content, (
            "Should have broadcast-enabled node pickers"
        )
        assert 'name="from_node"' in content, "Should have from_node hidden input field"

    def test_exclude_from_dropdown_includes_broadcast(self, app, client):
        """Test that exclude_from dropdown includes broadcast option when include_broadcast=true."""
        response = client.get("/packets")
        assert response.status_code == 200

        content = response.data.decode("utf-8")

        # Check for exclude_from node picker with broadcast enabled
        assert 'data-include-broadcast="true"' in content, (
            "Should have broadcast-enabled node pickers"
        )
        assert 'name="exclude_from"' in content, (
            "Should have exclude_from hidden input field"
        )

    def test_exclude_to_dropdown_includes_broadcast(self, app, client):
        """Test that exclude_to dropdown includes broadcast option when include_broadcast=true."""
        response = client.get("/packets")
        assert response.status_code == 200

        content = response.data.decode("utf-8")

        # Check for exclude_to node picker with broadcast enabled
        assert 'data-include-broadcast="true"' in content, (
            "Should have broadcast-enabled node pickers"
        )
        assert 'name="exclude_to"' in content, (
            "Should have exclude_to hidden input field"
        )

    def test_node_picker_structure_is_correct(self, app, client):
        """Test that node pickers have the correct HTML structure."""
        response = client.get("/packets")
        assert response.status_code == 200

        content = response.data.decode("utf-8")

        # Check that we have at least 4 node picker containers
        picker_containers = re.findall(
            r'<div[^>]*class="[^"]*node-picker-container[^"]*"', content
        )
        assert len(picker_containers) >= 4, (
            f"Should have at least 4 node picker containers, found {len(picker_containers)}"
        )

        # Check that each exclude field has the correct structure
        for field_name in ["exclude_from", "exclude_to"]:
            # Check for hidden input with correct name
            assert f'name="{field_name}"' in content, (
                f"Should have hidden input for {field_name}"
            )
