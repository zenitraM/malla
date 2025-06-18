import pytest


class TestDirectReceptionsE2E:
    """End-to-end tests for direct receptions functionality using existing test data."""

    @pytest.mark.integration
    def test_direct_receptions_api_basic_functionality(self, app, client):
        """Test that the direct receptions API endpoints work correctly."""
        # Test with a node that exists in the test database
        # Using node ID 1128074276 which exists in the test fixtures
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received&limit=100"
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data
        assert "total_packets" in data
        assert "total_count" in data
        assert "direction" in data
        assert data["direction"] == "received"

        # Test transmitted direction
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=transmitted&limit=100"
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data
        assert "total_packets" in data
        assert "total_count" in data
        assert "direction" in data
        assert data["direction"] == "transmitted"

    @pytest.mark.integration
    def test_direct_receptions_api_validation(self, app, client):
        """Test API validation and error handling."""
        # Test invalid direction
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=invalid"
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "Invalid direction" in data["error"]

        # Test non-existent node (should return empty results, not error)
        response = client.get(
            "/api/node/9999999999/direct-receptions?direction=received"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["direct_receptions"] == []
        assert data["total_packets"] == 0
        assert data["total_count"] == 0

    @pytest.mark.integration
    def test_direct_receptions_data_structure(self, app, client):
        """Test that the API returns the correct data structure."""
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received&limit=10"
        )
        assert response.status_code == 200

        data = response.get_json()

        # Check top-level structure
        required_fields = [
            "direct_receptions",
            "total_packets",
            "total_count",
            "direction",
        ]
        for field in required_fields:
            assert field in data

        # If we have data, check the structure of direct reception entries
        if data["direct_receptions"]:
            reception = data["direct_receptions"][0]

            # Check required fields in each reception entry
            reception_fields = [
                "from_node_id",
                "from_node_name",
                "packet_count",
                "rssi_avg",
                "rssi_min",
                "rssi_max",
                "snr_avg",
                "snr_min",
                "snr_max",
                "first_seen",
                "last_seen",
                "packets",
            ]

            for field in reception_fields:
                assert field in reception, f"Missing field: {field}"

            # Check packet structure if packets exist
            if reception["packets"]:
                packet = reception["packets"][0]
                packet_fields = ["packet_id", "timestamp", "rssi", "snr"]
                for field in packet_fields:
                    assert field in packet, f"Missing packet field: {field}"

    @pytest.mark.integration
    def test_direct_receptions_limit_parameter(self, app, client):
        """Test that the limit parameter works correctly."""
        # Test with different limits
        for limit in [1, 5, 10]:
            response = client.get(
                f"/api/node/1128074276/direct-receptions?direction=received&limit={limit}"
            )
            assert response.status_code == 200

            data = response.get_json()
            # The total count of nodes should not exceed the limit
            assert len(data["direct_receptions"]) <= limit

    @pytest.mark.integration
    def test_direct_receptions_self_exclusion_logic(self, app, client):
        """Test that nodes don't appear in their own direct receptions."""
        # Test multiple nodes to ensure self-exclusion works
        test_node_ids = [1128074276, 1128074277, 1128074278]

        for node_id in test_node_ids:
            # Test received direction
            response = client.get(
                f"/api/node/{node_id}/direct-receptions?direction=received"
            )
            assert response.status_code == 200

            data = response.get_json()
            # Check that the node doesn't appear in its own received list
            for reception in data["direct_receptions"]:
                assert reception["from_node_id"] != node_id, (
                    f"Node {node_id} appears in its own received list"
                )

            # Test transmitted direction
            response = client.get(
                f"/api/node/{node_id}/direct-receptions?direction=transmitted"
            )
            assert response.status_code == 200

            data = response.get_json()
            # In transmitted direction, check that the node's hex ID doesn't match gateway IDs
            # This is harder to test without knowing the exact hex ID, but we can check
            # that the logic doesn't break

    @pytest.mark.integration
    def test_direct_receptions_node_detail_page_integration(self, app, client):
        """Test that the node detail page loads and includes direct receptions section."""
        response = client.get("/node/1128074276")
        assert response.status_code == 200

        html_content = response.get_data(as_text=True)

        # Check that the direct receptions section is present
        assert "direct-receptions-card" in html_content
        assert "Direct Receptions" in html_content

        # Check that the JavaScript setup is present
        assert "DirectReceptionsChart" in html_content
        assert "direction-toggle-group" in html_content
        assert "metric-toggle-group" in html_content

    @pytest.mark.integration
    def test_direct_receptions_chart_toggles(self, app, client):
        """Test that the chart toggle elements are properly set up."""
        response = client.get("/node/1128074276")
        assert response.status_code == 200

        html_content = response.get_data(as_text=True)

        # Check direction toggle buttons
        assert 'data-direction="received"' in html_content
        assert 'data-direction="transmitted"' in html_content

        # Check metric toggle buttons
        assert 'data-metric="rssi"' in html_content
        assert 'data-metric="snr"' in html_content

        # Check that the node ID is properly embedded for JavaScript
        assert 'data-node-id="1128074276"' in html_content

    @pytest.mark.integration
    def test_direct_receptions_api_performance(self, app, client):
        """Test that the API responds within reasonable time limits."""
        import time

        start_time = time.time()
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received&limit=1000"
        )
        end_time = time.time()

        assert response.status_code == 200
        # API should respond within 2 seconds even with large limits
        assert (end_time - start_time) < 2.0

    @pytest.mark.integration
    def test_direct_receptions_data_consistency(self, app, client):
        """Test data consistency between different API calls."""
        # Get received data
        received_response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received"
        )
        assert received_response.status_code == 200
        received_data = received_response.get_json()

        # Get transmitted data
        transmitted_response = client.get(
            "/api/node/1128074276/direct-receptions?direction=transmitted"
        )
        assert transmitted_response.status_code == 200
        transmitted_data = transmitted_response.get_json()

        # Both should have the same structure
        for data in [received_data, transmitted_data]:
            assert isinstance(data["direct_receptions"], list)
            assert isinstance(data["total_packets"], int)
            assert isinstance(data["total_count"], int)
            assert data["total_packets"] >= 0
            assert data["total_count"] >= 0
            assert data["total_count"] == len(data["direct_receptions"])

    @pytest.mark.integration
    def test_direct_receptions_hex_node_id_support(self, app, client):
        """Test that the API works with hex node IDs."""
        # Test with hex format node ID
        response = client.get(
            "/api/node/!433d0c24/direct-receptions?direction=received"
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data

        # Should return the same data as decimal format
        decimal_response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received"
        )
        decimal_data = decimal_response.get_json()

        # Compare key metrics (allowing for potential timing differences)
        assert data["total_count"] == decimal_data["total_count"]
        assert len(data["direct_receptions"]) == len(decimal_data["direct_receptions"])
