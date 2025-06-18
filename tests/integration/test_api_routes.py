import pytest


class TestAPIRoutes:
    @pytest.mark.integration
    def test_api_traceroute_endpoint(self, client):
        """Test the API traceroute endpoint returns expected structure."""
        response = client.get("/api/traceroute")
        assert response.status_code == 200

        data = response.get_json()
        assert "traceroutes" in data
        assert "total_count" in data
        assert "page" in data
        assert "per_page" in data

    @pytest.mark.integration
    def test_api_traceroute_graph_endpoint(self, client):
        """Test the API traceroute graph endpoint returns expected structure."""
        response = client.get("/api/traceroute/graph")
        assert response.status_code == 200

        data = response.get_json()
        assert "nodes" in data
        assert "links" in data
        assert "stats" in data
        assert "filters" in data

        # Check that nodes and links are lists
        assert isinstance(data["nodes"], list)
        assert isinstance(data["links"], list)

        # Check stats structure
        stats = data["stats"]
        assert "packets_analyzed" in stats
        assert "links_found" in stats

        # Check filters structure
        filters = data["filters"]
        assert "hours" in filters
        assert "min_snr" in filters
        assert "include_indirect" in filters

    @pytest.mark.integration
    def test_api_traceroute_graph_location_data(self, client):
        """Test that the traceroute graph endpoint includes location data for nodes."""
        response = client.get("/api/traceroute/graph")
        assert response.status_code == 200

        data = response.get_json()
        nodes = data["nodes"]

        if nodes:  # Only test if we have nodes
            # Check node structure includes expected fields
            node = nodes[0]
            required_fields = [
                "id",
                "name",
                "packet_count",
                "connections",
                "last_seen",
                "size",
            ]
            for field in required_fields:
                assert field in node, f"Missing required field: {field}"

            # Check if any nodes have location data
            nodes_with_location = [n for n in nodes if "location" in n]

            # If we have nodes with location data, verify the structure
            if nodes_with_location:
                location_node = nodes_with_location[0]
                location = location_node["location"]

                # Verify location structure
                assert "latitude" in location
                assert "longitude" in location
                assert isinstance(location["latitude"], int | float)
                assert isinstance(location["longitude"], int | float)

                # Altitude is optional
                if "altitude" in location:
                    assert isinstance(location["altitude"], int | float | type(None))

                print(
                    f"Found {len(nodes_with_location)} nodes with location data out of {len(nodes)} total nodes"
                )
            else:
                print("No nodes with location data found in graph response")

    @pytest.mark.integration
    def test_api_traceroute_graph_with_filters(self, client):
        """Test the traceroute graph endpoint with various filters."""
        # Test with different time periods
        response = client.get("/api/traceroute/graph?hours=6")
        assert response.status_code == 200
        data = response.get_json()
        assert data["filters"]["hours"] == 6

        # Test with SNR filter
        response = client.get("/api/traceroute/graph?min_snr=-20")
        assert response.status_code == 200
        data = response.get_json()
        assert data["filters"]["min_snr"] == -20.0

        # Test with indirect connections
        response = client.get("/api/traceroute/graph?include_indirect=true")
        assert response.status_code == 200
        data = response.get_json()
        assert data["filters"]["include_indirect"] is True
