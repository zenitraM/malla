"""
Test traceroute filtering functionality to ensure all filters work correctly.
"""

from datetime import datetime, timedelta

import pytest


class TestTracerouteFilters:
    """Test traceroute filter functionality."""

    @pytest.mark.integration
    def test_traceroute_data_api_node_filters(self, client):
        """Test that node filters work correctly in the traceroute data API."""
        # Test without filters - should return whatever data exists
        response = client.get("/api/traceroute/data?page=1&limit=10")
        assert response.status_code == 200
        data = response.get_json()
        assert "data" in data
        assert "total_count" in data
        total_without_filters = data["total_count"]

        # Test from_node filter with a non-existent node
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&from_node=999999999"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

        # Test to_node filter with a non-existent node
        response = client.get("/api/traceroute/data?page=1&limit=10&to_node=999999999")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

        # Test route_node filter with a non-existent node
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&route_node=999999999"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

        # Test that invalid node IDs are handled gracefully
        response = client.get("/api/traceroute/data?page=1&limit=10&from_node=invalid")
        assert response.status_code == 200
        data = response.get_json()
        # Should return all data since invalid filter is ignored
        assert data["total_count"] == total_without_filters

    @pytest.mark.integration
    def test_traceroute_data_api_time_filters(self, client):
        """Test that time filters work correctly in the traceroute data API."""
        # Test with future time range - should return no results
        future_start = datetime.now() + timedelta(days=1)
        future_end = datetime.now() + timedelta(days=2)

        response = client.get(
            f"/api/traceroute/data?page=1&limit=10&start_time={future_start.isoformat()}&end_time={future_end.isoformat()}"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

        # Test with past time range
        past_start = datetime.now() - timedelta(days=30)
        past_end = datetime.now() - timedelta(days=29)

        response = client.get(
            f"/api/traceroute/data?page=1&limit=10&start_time={past_start.isoformat()}&end_time={past_end.isoformat()}"
        )
        assert response.status_code == 200
        data = response.get_json()
        # Should return valid response (may or may not have data depending on test database)
        assert "data" in data
        assert "total_count" in data

    @pytest.mark.integration
    def test_traceroute_data_api_gateway_filter(self, client):
        """Test that gateway filter works correctly in the traceroute data API."""
        # Test with non-existent gateway
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&gateway_id=!nonexist"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

    @pytest.mark.integration
    def test_traceroute_data_api_return_path_filter(self, client):
        """Test that return_path_only filter works correctly."""
        # Test return_path_only filter
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&return_path_only=true"
        )
        assert response.status_code == 200
        data = response.get_json()
        # Should return valid response structure
        assert "data" in data
        assert "total_count" in data

    @pytest.mark.integration
    def test_traceroute_data_api_combined_filters(self, client):
        """Test that multiple filters work together."""
        # Test multiple filters combined
        response = client.get(
            "/api/traceroute/data?page=1&limit=10&from_node=999999999&gateway_id=!nonexist&return_path_only=true"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert len(data["data"]) == 0

    @pytest.mark.integration
    def test_traceroute_data_api_response_structure(self, client):
        """Test that the API response has the correct structure."""
        response = client.get("/api/traceroute/data?page=1&limit=5")
        assert response.status_code == 200
        data = response.get_json()

        # Check response structure
        assert "data" in data
        assert "total_count" in data
        assert "page" in data
        assert "limit" in data
        assert "total_pages" in data

        # Check that data is a list
        assert isinstance(data["data"], list)

        # If there's data, check the structure of individual items
        if data["data"]:
            item = data["data"][0]
            expected_fields = [
                "id",
                "timestamp",
                "from_node",
                "from_node_id",
                "to_node",
                "to_node_id",
                "route_nodes",
                "route_names",
                "gateway",
                "rssi",
                "snr",
                "hops",
                "is_grouped",
            ]
            for field in expected_fields:
                assert field in item, f"Missing field: {field}"
