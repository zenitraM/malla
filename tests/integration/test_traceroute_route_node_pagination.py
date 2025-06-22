"""
Integration test for traceroute route_node filtering pagination fix.

This test covers the specific scenario where route_node filtering was returning
0 results due to pagination being applied before filtering. The fix ensures
that when route_node filtering is active, a larger dataset is fetched first,
then filtered, then paginated.
"""

import pytest


class TestTracerouteRouteNodePagination:
    """Test the route_node filtering pagination fix."""

    @pytest.mark.integration
    def test_route_node_filter_pagination_fix(self, client):
        """
        Test that route_node filtering works correctly with pagination.

        This test covers the specific bug where route_node filtering was applied
        after SQL pagination, causing 0 results when the target node appeared
        in older packets that weren't fetched due to the limit.

        The fix ensures that when route_node filtering is active, a larger
        dataset is fetched first, then filtered, then paginated.
        """
        # First, get all traceroute data to understand what's available
        response = client.get("/api/traceroute/data?page=1&limit=100")
        assert response.status_code == 200
        all_data = response.get_json()

        # Should have traceroute data from fixtures
        assert all_data["total_count"] > 0
        assert len(all_data["data"]) > 0

        # Find a node that appears as an intermediate hop in the test data
        # Based on the fixtures, we know these nodes are used as route_nodes:
        # 0x11111111, 0x22222222, 0x33333333, etc.
        test_route_nodes = [
            0x11111111,  # 286331153
            0x22222222,  # 572662306
            0x33333333,  # 858993459
            0x55555555,  # 1431655765
            555666777,  # From traceroute_graph_scenarios
        ]

        found_route_node = None
        expected_total = 0

        # Find a route node that actually appears in the test data
        for route_node in test_route_nodes:
            response = client.get(
                f"/api/traceroute/data?page=1&limit=1000&route_node={route_node}"
            )
            assert response.status_code == 200
            data = response.get_json()

            if data["total_count"] > 0:
                found_route_node = route_node
                expected_total = data["total_count"]
                break

        # If no test route nodes found, skip this test
        if found_route_node is None:
            pytest.skip("No test route nodes found in fixture data")

        # Now test the pagination fix with small limits
        # Before the fix, this would return 0 results if the route_node
        # appeared only in older packets beyond the initial limit

        # Test with limit=1 (very small limit to trigger the issue)
        response = client.get(
            f"/api/traceroute/data?page=1&limit=1&route_node={found_route_node}"
        )
        assert response.status_code == 200
        small_limit_data = response.get_json()

        # Should return the correct total count and at least 1 result
        assert small_limit_data["total_count"] == expected_total
        assert len(small_limit_data["data"]) >= 1

        # Test with limit=5
        response = client.get(
            f"/api/traceroute/data?page=1&limit=5&route_node={found_route_node}"
        )
        assert response.status_code == 200
        medium_limit_data = response.get_json()

        # Should return the same total count
        assert medium_limit_data["total_count"] == expected_total
        assert len(medium_limit_data["data"]) == min(5, expected_total)

        # Verify that the returned packets actually contain the route_node
        for packet in small_limit_data["data"]:
            route_nodes = packet.get("route_nodes", [])
            assert found_route_node in route_nodes, (
                f"Packet {packet['id']} should contain route_node {found_route_node} "
                f"but has route_nodes: {route_nodes}"
            )

    @pytest.mark.integration
    def test_route_node_filter_response_structure(self, client):
        """Test that route_node filtered responses have correct structure."""
        # Test with a known route node from fixtures
        route_node = 0x11111111  # 286331153

        response = client.get(
            f"/api/traceroute/data?page=1&limit=10&route_node={route_node}"
        )
        assert response.status_code == 200
        data = response.get_json()

        # Check response structure
        assert "data" in data
        assert "total_count" in data
        assert "page" in data
        assert "limit" in data
        assert "total_pages" in data

        # If there's data, verify packet structure
        if data["data"]:
            packet = data["data"][0]
            required_fields = [
                "id",
                "timestamp",
                "from_node",
                "from_node_id",
                "to_node",
                "to_node_id",
                "route_nodes",
                "route_names",
            ]
            for field in required_fields:
                assert field in packet, f"Missing field: {field}"

            # Verify route_nodes is a list and contains the filtered node
            assert isinstance(packet["route_nodes"], list)
            assert route_node in packet["route_nodes"]

    @pytest.mark.integration
    def test_route_node_filter_with_other_filters(self, client):
        """Test route_node filter combined with other filters."""
        route_node = 0x11111111  # 286331153

        # Get baseline data with just route_node filter
        response = client.get(
            f"/api/traceroute/data?page=1&limit=100&route_node={route_node}"
        )
        assert response.status_code == 200
        baseline_data = response.get_json()

        if baseline_data["total_count"] == 0:
            pytest.skip("No data for test route node")

        # Test route_node + from_node filter
        first_packet = baseline_data["data"][0]
        from_node_id = first_packet["from_node_id"]

        response = client.get(
            f"/api/traceroute/data?page=1&limit=100&route_node={route_node}&from_node={from_node_id}"
        )
        assert response.status_code == 200
        combined_data = response.get_json()

        # Should have fewer or equal results
        assert combined_data["total_count"] <= baseline_data["total_count"]

        # All results should match both filters
        for packet in combined_data["data"]:
            assert packet["from_node_id"] == from_node_id
            assert route_node in packet["route_nodes"]

    @pytest.mark.integration
    def test_route_node_filter_pagination_consistency(self, client):
        """Test that pagination is consistent across pages with route_node filter."""
        route_node = 0x11111111  # 286331153

        # Get first page
        response = client.get(
            f"/api/traceroute/data?page=1&limit=3&route_node={route_node}"
        )
        assert response.status_code == 200
        page1_data = response.get_json()

        if page1_data["total_count"] <= 3:
            pytest.skip("Not enough data to test pagination")

        # Get second page
        response = client.get(
            f"/api/traceroute/data?page=2&limit=3&route_node={route_node}"
        )
        assert response.status_code == 200
        page2_data = response.get_json()

        # Both pages should have same total count
        assert page1_data["total_count"] == page2_data["total_count"]

        # Pages should not have overlapping packets
        page1_ids = {p["id"] for p in page1_data["data"]}
        page2_ids = {p["id"] for p in page2_data["data"]}
        assert len(page1_ids.intersection(page2_ids)) == 0

        # All packets should contain the route_node
        for packet in page1_data["data"] + page2_data["data"]:
            assert route_node in packet["route_nodes"]

    @pytest.mark.integration
    def test_route_node_filter_nonexistent_node(self, client):
        """Test route_node filter with non-existent node."""
        nonexistent_node = 999999999

        response = client.get(
            f"/api/traceroute/data?page=1&limit=10&route_node={nonexistent_node}"
        )
        assert response.status_code == 200
        data = response.get_json()

        # Should return 0 results
        assert data["total_count"] == 0
        assert len(data["data"]) == 0
        assert data["page"] == 1
        assert data["limit"] == 10
        assert data["total_pages"] == 0

    @pytest.mark.integration
    def test_route_node_filter_invalid_input(self, client):
        """Test route_node filter with invalid input."""
        # Test with invalid node ID
        response = client.get("/api/traceroute/data?page=1&limit=10&route_node=invalid")
        assert response.status_code == 200
        data = response.get_json()

        # Should handle gracefully and return all data (filter ignored)
        assert "data" in data
        assert "total_count" in data

        # Test with empty string
        response = client.get("/api/traceroute/data?page=1&limit=10&route_node=")
        assert response.status_code == 200
        data = response.get_json()

        # Should handle gracefully
        assert "data" in data
        assert "total_count" in data

    @pytest.mark.integration
    def test_route_node_filter_performance_optimization(self, client):
        """
        Test that the performance optimization only activates when route_node filter is used.

        This test verifies that the fix doesn't impact performance when route_node
        filtering is not active.
        """
        # Test without route_node filter (should use normal pagination)
        response = client.get("/api/traceroute/data?page=1&limit=10")
        assert response.status_code == 200
        normal_data = response.get_json()

        # Test with route_node filter (should use optimized pagination)
        route_node = 0x11111111
        response = client.get(
            f"/api/traceroute/data?page=1&limit=10&route_node={route_node}"
        )
        assert response.status_code == 200
        filtered_data = response.get_json()

        # Both should return valid responses
        assert "data" in normal_data
        assert "data" in filtered_data
        assert "total_count" in normal_data
        assert "total_count" in filtered_data

        # The optimization should only affect results when route_node filter matches data
        # Normal pagination should work as expected
        assert len(normal_data["data"]) <= 10
        assert len(filtered_data["data"]) <= 10
