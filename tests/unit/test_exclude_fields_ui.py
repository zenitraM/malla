"""Unit tests for exclude fields UI functionality."""

import pytest


@pytest.mark.unit
class TestExcludeFieldsUI:
    """Test that exclude fields are properly included in the UI."""

    def test_exclude_fields_present_in_packets_template(self, client):
        """Test that exclude_from and exclude_to fields are present in packets template."""
        response = client.get("/packets")
        assert response.status_code == 200

        content = response.get_data(as_text=True)

        # Check for exclude_from field
        assert 'name="exclude_from"' in content
        assert 'id="exclude_from"' in content
        assert "Exclude From Node" in content

        # Check for exclude_to field
        assert 'name="exclude_to"' in content
        assert 'id="exclude_to"' in content
        assert "Exclude To Node" in content

        # Check for proper placeholders
        assert 'placeholder="No exclusions"' in content

    def test_exclude_parameters_accepted_by_api(self, client):
        """Test that the API accepts exclude_from and exclude_to parameters."""
        # Test that the API endpoint accepts these parameters without error
        response = client.get(
            "/api/packets/data?exclude_from=123&exclude_to=456&limit=5"
        )

        # Should return 200 (API accepts the parameters)
        assert response.status_code == 200

        data = response.get_json()

        # Should return proper response structure
        assert "data" in data
        assert isinstance(data["data"], list)
        assert "total_count" in data
        assert isinstance(data["total_count"], int)

    def test_exclude_parameters_with_broadcast_node(self, client):
        """Test that exclude parameters work with broadcast node ID."""
        # Test excluding broadcast packets (node ID 4294967295)
        response = client.get(
            "/api/packets/data?exclude_from=4294967295&exclude_to=4294967295&limit=5"
        )

        assert response.status_code == 200
        data = response.get_json()

        # Should handle the request gracefully
        assert "data" in data
        assert isinstance(data["data"], list)
