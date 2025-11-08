"""
Integration tests for API endpoints.

These tests verify that all API endpoints work correctly with the test database
and return the expected data structures and formats.
"""

import pytest


class TestStatsEndpoint:
    """Test the /api/stats endpoint."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_stats_endpoint_basic(self, client, helpers):
        """Test basic stats endpoint functionality."""
        response = client.get("/api/stats")
        helpers.assert_api_response_structure(
            response,
            [
                "total_packets",
                "total_nodes",
                "active_nodes_24h",
                "recent_packets",
                "avg_rssi",
                "avg_snr",
                "packet_types",
                "success_rate",
            ],
        )

        data = response.get_json()
        assert data["total_packets"] > 0
        assert data["total_nodes"] >= 5  # We have 5 test nodes
        assert isinstance(data["packet_types"], list)
        assert data["success_rate"] >= 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_stats_endpoint_with_gateway_filter(self, client):
        """Test stats endpoint with gateway filter."""
        response = client.get("/api/stats?gateway_id=!12345678")
        assert response.status_code == 200
        data = response.get_json()
        assert "total_packets" in data


class TestPacketsEndpoint:
    """Test the /api/packets endpoint."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_endpoint_basic(self, client, helpers):
        """Test basic packets endpoint functionality."""
        response = client.get("/api/packets")
        helpers.assert_api_response_structure(
            response, ["packets", "total_count", "page", "per_page"]
        )

        data = response.get_json()
        assert len(data["packets"]) > 0
        assert data["total_count"] > 0

        # Check packet structure
        packet = data["packets"][0]
        expected_packet_keys = ["id", "timestamp", "from_node_id", "to_node_id"]
        for key in expected_packet_keys:
            assert key in packet

        # Check for gateway information - could be gateway_id (individual) or gateway_list (grouped)
        assert "gateway_id" in packet or "gateway_list" in packet

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_endpoint_pagination(self, client):
        """Test packets endpoint pagination."""
        # Test first page
        response = client.get("/api/packets?limit=5&page=1")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["packets"]) <= 5
        assert data["page"] == 1
        assert data["per_page"] == 5

        # Test second page
        response = client.get("/api/packets?limit=5&page=2")
        assert response.status_code == 200
        data2 = response.get_json()

        # Packets should be different between pages
        if len(data2["packets"]) > 0:
            packet_ids_page1 = {p["id"] for p in data["packets"]}
            packet_ids_page2 = {p["id"] for p in data2["packets"]}
            assert packet_ids_page1 != packet_ids_page2

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_endpoint_filters(self, client):
        """Test packets endpoint with various filters."""
        # Test gateway filter
        response = client.get("/api/packets?gateway_id=!12345678")
        assert response.status_code == 200
        data = response.get_json()
        for packet in data["packets"]:
            # For grouped packets, check gateway_list; for individual packets, check gateway_id
            if "gateway_list" in packet:
                assert "!12345678" in packet["gateway_list"]
            else:
                assert packet.get("gateway_id") == "!12345678"

        # Test from_node filter
        response = client.get("/api/packets?from_node=305419896")  # 0x12345678
        assert response.status_code == 200
        data = response.get_json()
        for packet in data["packets"]:
            assert packet.get("from_node_id") == 305419896


class TestNodesEndpoint:
    """Test the /api/nodes endpoint."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_nodes_endpoint_basic(self, client, helpers):
        """Test basic nodes endpoint functionality."""
        response = client.get("/api/nodes")
        helpers.assert_api_response_structure(
            response, ["nodes", "total_count", "page", "per_page"]
        )

        data = response.get_json()
        assert len(data["nodes"]) >= 5  # We have 5 test nodes
        assert data["total_count"] >= 5

        # Check node structure
        node = data["nodes"][0]
        expected_node_keys = ["node_id", "long_name", "short_name", "hw_model"]
        for key in expected_node_keys:
            assert key in node

    @pytest.mark.integration
    @pytest.mark.api
    def test_nodes_search_endpoint(self, client):
        """Test the nodes search endpoint."""
        # Test with empty query - should return popular nodes
        response = client.get("/api/nodes/search?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert "nodes" in data
        assert "total_count" in data
        assert "is_popular" in data
        assert data["is_popular"]
        assert data["total_count"] >= 0  # May have popular nodes

        # Test with a query
        response = client.get("/api/nodes/search?q=test&limit=5")
        assert response.status_code == 200
        data = response.get_json()
        assert "nodes" in data
        assert "total_count" in data
        assert "query" in data
        assert "is_popular" in data
        assert data["query"] == "test"
        assert not data["is_popular"]
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) <= 5


class TestTracerouteEndpoints:
    """Test the traceroute API endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_endpoint_basic(self, client, helpers):
        """Test basic traceroute endpoint functionality."""
        response = client.get("/api/traceroute")
        helpers.assert_api_response_structure(
            response, ["traceroutes", "total_count", "page", "per_page"]
        )

        data = response.get_json()
        assert data["total_count"] >= 0  # May or may not have traceroutes

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_patterns_endpoint(self, client):
        """Test traceroute patterns endpoint."""
        response = client.get("/api/traceroute/patterns")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_related_nodes_endpoint(self, client):
        """Test traceroute related nodes endpoint."""
        # Test with a known test node ID (305419896 = 0x12345678)
        response = client.get("/api/traceroute/related-nodes/305419896")
        assert response.status_code == 200

        data = response.get_json()
        assert "node_id" in data
        assert "related_nodes" in data
        assert "total_count" in data
        assert data["node_id"] == 305419896
        assert isinstance(data["related_nodes"], list)
        assert isinstance(data["total_count"], int)

        # Check structure of related nodes if any exist
        if data["related_nodes"]:
            node = data["related_nodes"][0]
            expected_keys = [
                "node_id",
                "hex_id",
                "display_name",
                "long_name",
                "short_name",
                "traceroute_count",
            ]
            for key in expected_keys:
                assert key in node

            # Check data types
            assert isinstance(node["node_id"], int)
            assert isinstance(node["hex_id"], str)
            assert isinstance(node["display_name"], str)
            assert isinstance(node["traceroute_count"], int)
            assert node["hex_id"].startswith("!")
            assert node["traceroute_count"] > 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_related_nodes_hex_format(self, client):
        """Test traceroute related nodes endpoint with hex node ID format."""
        # Test with hex format (!12345678)
        response = client.get("/api/traceroute/related-nodes/!12345678")
        assert response.status_code == 200

        data = response.get_json()
        assert data["node_id"] == 305419896  # Should convert to decimal

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_related_nodes_not_found(self, client):
        """Test traceroute related nodes endpoint with non-existent node."""
        # Test with a node ID that doesn't exist
        # Note: "99999999" is now treated as decimal by convert_node_id
        response = client.get("/api/traceroute/related-nodes/99999999")
        assert response.status_code == 200

        data = response.get_json()
        assert data["node_id"] == 99999999  # Decimal value
        assert data["related_nodes"] == []
        assert data["total_count"] == 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_related_nodes_invalid_format(self, client):
        """Test traceroute related nodes endpoint with invalid node ID format."""
        response = client.get("/api/traceroute/related-nodes/invalid_id")
        # Should handle the error gracefully
        assert response.status_code in [400, 500]

    @pytest.mark.integration
    @pytest.mark.api
    def test_traceroute_hops_nodes_endpoint(self, client):
        """Test traceroute hops nodes endpoint."""
        response = client.get("/api/traceroute-hops/nodes")
        assert response.status_code == 200

        data = response.get_json()
        assert "nodes" in data
        assert "total_count" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["total_count"], int)

        # Check structure of nodes if any exist
        if data["nodes"]:
            node = data["nodes"][0]
            expected_keys = [
                "node_id",
                "hex_id",
                "display_name",
                "long_name",
                "short_name",
                "hw_model",
            ]
            for key in expected_keys:
                assert key in node

            # Check data types
            assert isinstance(node["node_id"], int)
            assert isinstance(node["hex_id"], str)
            assert isinstance(node["display_name"], str)
            assert node["hex_id"].startswith("!")

            # Check if location data is included when available
            if "location" in node:
                location = node["location"]
                assert "latitude" in location
                assert "longitude" in location
                assert isinstance(location["latitude"], int | float)
                assert isinstance(location["longitude"], int | float)


class TestLocationEndpoints:
    """Test the location API endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_locations_endpoint(self, client):
        """Test locations endpoint."""
        response = client.get("/api/locations")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, dict)
        assert "locations" in data
        assert "traceroute_links" in data
        assert "total_count" in data
        assert isinstance(data["locations"], list)
        assert isinstance(data["traceroute_links"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_locations_endpoint_enhanced_fields(self, client):
        """Test that locations endpoint returns all fields expected by the map template."""
        response = client.get("/api/locations")
        assert response.status_code == 200

        data = response.get_json()
        locations = data["locations"]

        if locations:  # Only test if we have location data
            location = locations[0]

            # Test original location fields
            required_fields = [
                "node_id",
                "hex_id",
                "display_name",
                "long_name",
                "short_name",
                "hw_model",
                "latitude",
                "longitude",
                "altitude",
                "timestamp",
            ]
            for field in required_fields:
                assert field in location, f"Missing required field: {field}"

            # Test enhanced fields for map display
            enhanced_fields = [
                "age_hours",
                "timestamp_str",
                "direct_neighbors",
                "neighbors",
                "sats_in_view",
            ]
            for field in enhanced_fields:
                assert field in location, f"Missing enhanced field: {field}"

            # Test field types
            assert isinstance(location["age_hours"], int | float)
            assert isinstance(location["timestamp_str"], str)
            assert isinstance(location["direct_neighbors"], int)
            assert isinstance(location["neighbors"], list)

            # Test neighbor structure if neighbors exist
            if location["neighbors"]:
                neighbor = location["neighbors"][0]
                assert "neighbor_id" in neighbor
                assert "traceroute_count" in neighbor
                assert "packet_count" in neighbor
                # All neighbors should have these fields
                assert isinstance(neighbor["traceroute_count"], int)
                assert isinstance(neighbor["packet_count"], int)
                # SNR should be present (may be None)
                assert "avg_snr" in neighbor
                # RSSI may be present for direct packet neighbors
                if neighbor["packet_count"] > 0:
                    assert "avg_rssi" in neighbor

        # Test traceroute_links structure
        traceroute_links = data["traceroute_links"]
        if traceroute_links:  # Only test if we have link data
            link = traceroute_links[0]

            required_link_fields = [
                "from_node_id",
                "to_node_id",
                "success_rate",
                "avg_snr",
                "age_hours",
                "last_seen_str",
                "is_bidirectional",
                "total_hops_seen",
            ]
            for field in required_link_fields:
                assert field in link, f"Missing required link field: {field}"

            # Test link field types
            assert isinstance(link["from_node_id"], int)
            assert isinstance(link["to_node_id"], int)
            assert isinstance(link["success_rate"], int | float)
            assert isinstance(link["age_hours"], int | float)
            assert isinstance(link["last_seen_str"], str)
            assert isinstance(link["is_bidirectional"], bool)
            assert isinstance(link["total_hops_seen"], int)

    @pytest.mark.integration
    @pytest.mark.api
    def test_location_statistics_endpoint(self, client):
        """Test location statistics endpoint."""
        response = client.get("/api/location/statistics")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_location_hop_distances_endpoint(self, client):
        """Test location hop distances endpoint."""
        response = client.get("/api/location/hop-distances")
        assert response.status_code == 200

        data = response.get_json()
        assert "hop_distances" in data
        assert "total_pairs" in data
        assert isinstance(data["hop_distances"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_locations_endpoint_returns_14_day_data(self, client):
        """Test that locations endpoint returns 14 days of data for client-side filtering."""
        response = client.get("/api/locations")
        assert response.status_code == 200

        data = response.get_json()
        assert "data_period_days" in data
        assert data["data_period_days"] == 14

        # Verify the response structure includes all expected fields
        assert "locations" in data
        assert "traceroute_links" in data
        assert "total_count" in data
        assert "filters_applied" in data

        # Verify that filters_applied includes time range
        filters = data["filters_applied"]
        assert "start_time" in filters
        assert "end_time" in filters

        # Verify the time range is approximately 14 days
        time_diff = filters["end_time"] - filters["start_time"]
        expected_seconds = 14 * 24 * 3600  # 14 days in seconds
        # Allow tolerance for execution time and timing variations (2 hours)
        assert abs(time_diff - expected_seconds) < 7200, (
            f"Time range should be ~14 days, got {time_diff / 3600 / 24:.2f} days"
        )


class TestNodeSpecificEndpoints:
    """Test node-specific API endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_info_endpoint(self, client):
        """Test node info endpoint (optimized for tooltips)."""
        # Test with a known test node ID (1128074276 = 0x43456724)
        response = client.get("/api/node/1128074276/info")
        assert response.status_code == 200

        data = response.get_json()
        assert "node" in data

        node = data["node"]
        # Verify basic tooltip data is present
        assert "node_id" in node
        assert "hex_id" in node
        assert "long_name" in node
        assert "short_name" in node
        assert "packet_count_24h" in node
        assert "gateway_count_24h" in node

        # Verify no heavy data is included (this is now a lightweight endpoint)
        assert "traceroute_stats" not in data
        assert "location_history" not in data
        assert "neighbors" not in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_info_endpoint_not_found(self, client):
        """Test node info endpoint with non-existent node."""
        response = client.get("/api/node/99999999/info")
        assert response.status_code == 404

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_location_history_endpoint(self, client):
        """Test node location history endpoint."""
        # Test with a known test node ID (1128074276 = 0x43456724)
        response = client.get("/api/node/1128074276/location-history")
        assert response.status_code == 200

        data = response.get_json()
        assert "node_id" in data
        assert "location_history" in data
        assert data["node_id"] == 1128074276  # 0x43456724

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_neighbors_endpoint(self, client):
        """Test node neighbors endpoint."""
        # Test with a known test node ID (1128074276 = 0x43456724)
        response = client.get("/api/node/1128074276/neighbors?max_distance=20.0")
        assert response.status_code == 200

        data = response.get_json()
        assert "node_id" in data
        assert "neighbors" in data
        assert "max_distance_km" in data
        assert "neighbor_count" in data
        assert data["max_distance_km"] == 20.0


class TestUtilityEndpoints:
    """Test utility API endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_gateways_endpoint(self, client):
        """Test gateways endpoint."""
        response = client.get("/api/gateways")
        assert response.status_code == 200

        data = response.get_json()
        assert "gateways" in data
        assert isinstance(data["gateways"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_signal_endpoint(self, client):
        """Test packets signal endpoint."""
        response = client.get("/api/packets/signal")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_gateways_search_endpoint(self, client):
        """Test the gateways search endpoint."""
        # Test with empty query - should return popular gateways
        response = client.get("/api/gateways/search?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert "gateways" in data
        assert "total_count" in data
        assert "is_popular" in data
        assert data["is_popular"]
        assert data["total_count"] >= 0  # May have popular gateways

        # Test with a query
        response = client.get("/api/gateways/search?q=04&limit=5")
        assert response.status_code == 200
        data = response.get_json()
        assert "gateways" in data
        assert "total_count" in data
        assert "query" in data
        assert "is_popular" in data
        assert data["query"] == "04"
        assert not data["is_popular"]
        assert isinstance(data["gateways"], list)
        assert len(data["gateways"]) <= 5


class TestErrorHandling:
    """Test error handling in API endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_invalid_node_id_format(self, client):
        """Test handling of invalid node ID formats."""
        response = client.get("/api/node/invalid_id/info")
        # Should handle the error gracefully
        assert response.status_code in [400, 404, 500]

    @pytest.mark.integration
    @pytest.mark.api
    def test_malformed_api_request(self, client):
        """Test handling of malformed API requests."""
        # Missing required parameters
        response = client.get("/api/packets/data")
        assert response.status_code == 200  # Should return empty result, not error

        result = response.get_json()
        assert "data" in result
        assert "total_count" in result

    @pytest.mark.integration
    @pytest.mark.api
    def test_pagination_edge_cases(self, client):
        """Test pagination edge cases."""
        # Very large page number
        response = client.get("/api/packets?page=9999&limit=10")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["packets"]) == 0  # Should return empty results

        # Zero limit
        response = client.get("/api/packets?page=1&limit=0")
        assert response.status_code == 200


class TestDataConsistency:
    """Test data consistency across different endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_count_consistency(self, client):
        """Test that node counts are consistent across endpoints."""
        # Get stats
        stats_response = client.get("/api/stats")
        stats_data = stats_response.get_json()

        # Get nodes
        nodes_response = client.get("/api/nodes?limit=1000")
        nodes_data = nodes_response.get_json()

        # Node counts should be consistent
        assert stats_data["total_nodes"] == nodes_data["total_count"]

    @pytest.mark.integration
    @pytest.mark.api
    def test_packet_count_consistency(self, client):
        """Test that packet counts are consistent across endpoints."""
        # Get stats
        stats_response = client.get("/api/stats")
        stats_data = stats_response.get_json()

        # Get packets with high limit
        packets_response = client.get("/api/packets?limit=10000")
        packets_data = packets_response.get_json()

        # Total packet count should match
        assert stats_data["total_packets"] == packets_data["total_count"]

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_data_consistency(self, client):
        """Test that node data is consistent between node list and node info."""
        # Get a node from the list
        nodes_response = client.get("/api/nodes?limit=1")
        nodes_data = nodes_response.get_json()

        if nodes_data["nodes"]:
            node_id = nodes_data["nodes"][0]["node_id"]

            # Get detailed info for the same node
            info_response = client.get(f"/api/node/{node_id}/info")
            info_data = info_response.get_json()

            # Verify the response structure
            assert "node" in info_data
            node_info = info_data["node"]

            # Check that basic fields match
            assert node_info["node_id"] == node_id
            assert "hex_id" in node_info
            assert "long_name" in node_info or "short_name" in node_info

            # Verify this is the lightweight endpoint (no heavy data)
            assert "packet_count_24h" in node_info
            assert "gateway_count_24h" in node_info
            assert "traceroute_stats" not in info_data
            assert "location_history" not in info_data
            assert "neighbors" not in info_data
        else:
            pytest.skip("No nodes available for testing")


class TestLongestLinksEndpoint:
    """Test the longest links API endpoint."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_basic(self, client):
        """Test basic longest links endpoint functionality."""
        response = client.get("/api/longest-links")
        assert response.status_code == 200

        data = response.get_json()
        assert "summary" in data
        assert "direct_links" in data
        assert "indirect_links" in data

        # Check summary structure
        summary = data["summary"]
        assert "total_links" in summary
        assert "direct_links" in summary
        assert "longest_direct" in summary
        assert "longest_path" in summary

        # Check that data is lists
        assert isinstance(data["direct_links"], list)
        assert isinstance(data["indirect_links"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_with_filters(self, client):
        """Test longest links endpoint with various filters."""
        # Test with minimum distance filter
        response = client.get("/api/longest-links?min_distance=5.0")
        assert response.status_code == 200
        data = response.get_json()

        # All direct links should have distance >= 5.0 km
        for link in data["direct_links"]:
            assert link["distance_km"] >= 5.0

        # All indirect links should have total distance >= 5.0 km
        for link in data["indirect_links"]:
            assert link["total_distance_km"] >= 5.0

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_with_snr_filter(self, client):
        """Test longest links endpoint with SNR filter."""
        response = client.get("/api/longest-links?min_snr=-10.0")
        assert response.status_code == 200
        data = response.get_json()

        # All links should have SNR >= -10.0 dB (if SNR is not None)
        for link in data["direct_links"]:
            if link["avg_snr"] is not None:
                assert link["avg_snr"] >= -10.0

        for link in data["indirect_links"]:
            if link["avg_snr"] is not None:
                assert link["avg_snr"] >= -10.0

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_with_max_results(self, client):
        """Test longest links endpoint with max results limit."""
        response = client.get("/api/longest-links?max_results=5")
        assert response.status_code == 200
        data = response.get_json()

        # Should not exceed max results
        assert len(data["direct_links"]) <= 5
        assert len(data["indirect_links"]) <= 5

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_direct_link_structure(self, client):
        """Test that direct links have the expected structure."""
        response = client.get("/api/longest-links?max_results=10")
        assert response.status_code == 200
        data = response.get_json()

        if data["direct_links"]:
            link = data["direct_links"][0]
            expected_keys = [
                "from_node_id",
                "to_node_id",
                "from_node_name",
                "to_node_name",
                "distance_km",
                "avg_snr",
                "traceroute_count",
                "packet_id",
                "packet_url",
                "last_seen",
            ]
            for key in expected_keys:
                assert key in link

            # Check data types
            assert isinstance(link["from_node_id"], int)
            assert isinstance(link["to_node_id"], int)
            assert isinstance(link["distance_km"], int | float)
            assert isinstance(link["traceroute_count"], int)
            assert isinstance(link["packet_id"], int)
            assert isinstance(link["packet_url"], str)
            assert isinstance(link["last_seen"], int | float)

            # Check that packet URL is properly formatted
            assert link["packet_url"].startswith("/packet/")
            assert str(link["packet_id"]) in link["packet_url"]

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_indirect_link_structure(self, client):
        """Test that indirect links have the expected structure."""
        response = client.get("/api/longest-links?max_results=10")
        assert response.status_code == 200
        data = response.get_json()

        if data["indirect_links"]:
            link = data["indirect_links"][0]
            expected_keys = [
                "from_node_id",
                "to_node_id",
                "from_node_name",
                "to_node_name",
                "total_distance_km",
                "hop_count",
                "avg_snr",
                "route_preview",
                "packet_id",
                "packet_url",
                "last_seen",
            ]
            for key in expected_keys:
                assert key in link

            # Check data types
            assert isinstance(link["from_node_id"], int)
            assert isinstance(link["to_node_id"], int)
            assert isinstance(link["total_distance_km"], int | float)
            assert isinstance(link["hop_count"], int)
            assert isinstance(link["route_preview"], list)
            assert isinstance(link["packet_id"], int)
            assert isinstance(link["packet_url"], str)
            assert isinstance(link["last_seen"], int | float)

            # Check that hop count is reasonable (> 1 for indirect links)
            assert link["hop_count"] > 1

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_sorting(self, client):
        """Test that longest links are properly sorted by distance."""
        response = client.get("/api/longest-links?max_results=20")
        assert response.status_code == 200
        data = response.get_json()

        # Direct links should be sorted by distance (descending)
        if len(data["direct_links"]) > 1:
            for i in range(len(data["direct_links"]) - 1):
                current_distance = data["direct_links"][i]["distance_km"]
                next_distance = data["direct_links"][i + 1]["distance_km"]
                assert current_distance >= next_distance

        # Indirect links should be sorted by total distance (descending)
        if len(data["indirect_links"]) > 1:
            for i in range(len(data["indirect_links"]) - 1):
                current_distance = data["indirect_links"][i]["total_distance_km"]
                next_distance = data["indirect_links"][i + 1]["total_distance_km"]
                assert current_distance >= next_distance

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_error_handling(self, client):
        """Test error handling for invalid parameters."""
        # Test with invalid min_distance
        response = client.get("/api/longest-links?min_distance=invalid")
        assert response.status_code == 200  # Should handle gracefully with default

        # Test with invalid min_snr
        response = client.get("/api/longest-links?min_snr=invalid")
        assert response.status_code == 200  # Should handle gracefully with default

        # Test with invalid max_results
        response = client.get("/api/longest-links?max_results=invalid")
        assert response.status_code == 200  # Should handle gracefully with default

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_empty_results(self, client):
        """Test longest links with filters that return no results."""
        # Use very restrictive filters that should return no results
        response = client.get("/api/longest-links?min_distance=1000&min_snr=50")
        assert response.status_code == 200

        data = response.get_json()
        assert "summary" in data
        assert "direct_links" in data
        assert "indirect_links" in data

        # Should return empty lists but valid structure
        assert isinstance(data["direct_links"], list)
        assert isinstance(data["indirect_links"], list)
        assert len(data["direct_links"]) == 0
        assert len(data["indirect_links"]) == 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_longest_links_summary_accuracy(self, client):
        """Test that summary statistics are accurate."""
        response = client.get("/api/longest-links?max_results=100")
        assert response.status_code == 200
        data = response.get_json()

        summary = data["summary"]

        # Total links should be sum of direct and indirect
        expected_total = len(data["direct_links"]) + len(data["indirect_links"])
        # Note: summary.total_links might be higher than returned results due to max_results limit
        assert summary["total_links"] >= expected_total

        # Direct links count should match
        assert summary["direct_links"] >= len(data["direct_links"])

        # If we have direct links, longest_direct should be the max distance
        if data["direct_links"]:
            max_direct_distance = max(
                link["distance_km"] for link in data["direct_links"]
            )
            if summary["longest_direct"]:
                # Extract numeric value from "X.XX km" format
                longest_direct_value = float(summary["longest_direct"].split()[0])
                assert longest_direct_value >= max_direct_distance

        # If we have indirect links, longest_path should be the max total distance
        if data["indirect_links"]:
            max_indirect_distance = max(
                link["total_distance_km"] for link in data["indirect_links"]
            )
            if summary["longest_path"]:
                # Extract numeric value from "X.XX km" format
                longest_path_value = float(summary["longest_path"].split()[0])
                assert longest_path_value >= max_indirect_distance
