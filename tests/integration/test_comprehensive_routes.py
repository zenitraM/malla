"""
Comprehensive integration tests for all API endpoints and web routes.

This test suite ensures that every single endpoint in the application works correctly
with the test database and returns the expected data structures and HTTP status codes.
"""

import time

import pytest


class TestMainRoutes:
    """Test main application routes."""

    @pytest.mark.integration
    def test_dashboard_route(self, client):
        """Test the main dashboard route."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Dashboard" in response.data
        assert b"Total Messages" in response.data
        assert b"Total Nodes" in response.data
        assert b"Active Nodes" in response.data

    @pytest.mark.integration
    def test_map_route(self, client):
        """Test the map view route."""
        response = client.get("/map")
        assert response.status_code == 200
        assert b"Node Map" in response.data or b"Map" in response.data
        # Check for map-related elements
        assert b"leaflet" in response.data or b"map" in response.data.lower()

    @pytest.mark.integration
    def test_longest_links_route(self, client):
        """Test the longest links analysis route."""
        response = client.get("/longest-links")
        assert response.status_code == 200
        assert b"Longest Links" in response.data


class TestPacketRoutes:
    """Test packet-related routes."""

    @pytest.mark.integration
    def test_packets_list_route(self, client):
        """Test the packets list page."""
        response = client.get("/packets")
        assert response.status_code == 200
        assert b"Packets" in response.data
        assert b"packetsTable" in response.data  # Table container ID

    @pytest.mark.integration
    def test_packet_detail_route(self, client):
        """Test packet detail page with valid packet ID."""
        # Get a packet ID from the database
        from src.malla.database.repositories import PacketRepository

        result = PacketRepository.get_packets(limit=1, offset=0)
        if result["packets"]:
            packet_id = result["packets"][0]["id"]

            response = client.get(f"/packet/{packet_id}")
            assert response.status_code == 200
            assert b"Packet #" in response.data
            assert str(packet_id).encode() in response.data
        else:
            pytest.skip("No packets available for testing")

    @pytest.mark.integration
    def test_packet_detail_not_found(self, client):
        """Test packet detail page with non-existent packet ID."""
        response = client.get("/packet/999999")
        assert response.status_code == 404


class TestNodeRoutes:
    """Test node-related routes."""

    @pytest.mark.integration
    def test_nodes_list_route(self, client):
        """Test the nodes list page."""
        response = client.get("/nodes")
        assert response.status_code == 200
        assert b"Nodes" in response.data

    @pytest.mark.integration
    def test_node_detail_route(self, client):
        """Test node detail page with valid node ID."""
        # Use Test Gateway Alpha from fixture data
        node_id = 1128074276  # 0x433d0c24

        response = client.get(f"/node/{node_id}")
        assert response.status_code == 200
        assert b"Test Gateway Alpha" in response.data
        assert b"Node Details" in response.data
        assert b"!433d0c24" in response.data

    @pytest.mark.integration
    def test_node_detail_hex_format(self, client):
        """Test node detail with hex format node ID."""
        hex_node_id = "!433d0c24"

        response = client.get(f"/node/{hex_node_id}")
        assert response.status_code == 200
        assert b"Test Gateway Alpha" in response.data

    @pytest.mark.integration
    def test_node_detail_not_found(self, client):
        """Test node detail with non-existent node ID."""
        response = client.get("/node/999999999")
        assert response.status_code == 404
        assert b"Node not found" in response.data

    @pytest.mark.integration
    def test_node_detail_invalid_format(self, client):
        """Test node detail with invalid node ID format."""
        response = client.get("/node/invalid_id")
        assert response.status_code == 400
        assert b"Invalid node ID format" in response.data


class TestTracerouteRoutes:
    """Test traceroute-related routes."""

    @pytest.mark.integration
    def test_traceroute_route(self, client):
        """Test the traceroute analysis page."""
        response = client.get("/traceroute")
        assert response.status_code == 200
        assert b"Traceroute" in response.data

    @pytest.mark.integration
    def test_traceroute_hops_route(self, client):
        """Test the traceroute hops visualization page."""
        response = client.get("/traceroute-hops")
        assert response.status_code == 200
        assert b"Traceroute" in response.data or b"Hops" in response.data

    @pytest.mark.integration
    def test_traceroute_with_filters(self, client):
        """Test traceroute page with filter parameters."""
        response = client.get("/traceroute?gateway_id=!12345678&from_node=305419896")
        assert response.status_code == 200
        assert b"Traceroute" in response.data


class TestUtilityRoutes:
    """Test utility routes defined in main.py."""

    @pytest.mark.integration
    def test_health_endpoint(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "meshtastic-mesh-health-ui"
        assert data["version"] == "2.0.0"

    @pytest.mark.integration
    def test_info_endpoint(self, client):
        """Test the application info endpoint."""
        response = client.get("/info")
        assert response.status_code == 200

        data = response.get_json()
        assert data["name"] == "Meshtastic Mesh Health Web UI"
        assert data["version"] == "2.0.0"
        assert "components" in data
        assert "database" in data["components"]


class TestAPIStatsEndpoints:
    """Test API stats endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_stats_endpoint(self, client, helpers):
        """Test /api/stats endpoint."""
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
        assert data["total_packets"] >= 0
        assert data["total_nodes"] >= 0
        assert isinstance(data["packet_types"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_stats_with_gateway_filter(self, client):
        """Test /api/stats with gateway filter."""
        response = client.get("/api/stats?gateway_id=!12345678")
        assert response.status_code == 200
        data = response.get_json()
        assert "total_packets" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_analytics_endpoint(self, client):
        """Test /api/analytics endpoint."""
        response = client.get("/api/analytics")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_analytics_with_filters(self, client):
        """Test /api/analytics with filters."""
        response = client.get(
            "/api/analytics?gateway_id=!12345678&from_node=305419896&hop_count=2"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)


class TestAPIPacketEndpoints:
    """Test API packet endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_packets_endpoint(self, client, helpers):
        """Test /api/packets endpoint."""
        response = client.get("/api/packets")
        helpers.assert_api_response_structure(
            response, ["packets", "total_count", "page", "per_page"]
        )

        data = response.get_json()
        assert data["total_count"] >= 0
        assert isinstance(data["packets"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_packets_pagination(self, client):
        """Test /api/packets pagination."""
        response = client.get("/api/packets?limit=5&page=1")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["packets"]) <= 5
        assert data["page"] == 1
        assert data["per_page"] == 5

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_packets_filters(self, client):
        """Test /api/packets with filters."""
        response = client.get(
            "/api/packets?gateway_id=!12345678&from_node=305419896&portnum=TEXT_MESSAGE_APP"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data["packets"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_packets_signal_endpoint(self, client):
        """Test /api/packets/signal endpoint."""
        response = client.get("/api/packets/signal")
        assert response.status_code == 200
        data = response.get_json()
        assert "signal_data" in data
        assert "total_count" in data


class TestAPINodeEndpoints:
    """Test API node endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_nodes_endpoint(self, client, helpers):
        """Test /api/nodes endpoint."""
        response = client.get("/api/nodes")
        helpers.assert_api_response_structure(
            response, ["nodes", "total_count", "page", "per_page"]
        )

        data = response.get_json()
        assert data["total_count"] >= 0
        assert isinstance(data["nodes"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_node_info_endpoint(self, client):
        """Test /api/node/<node_id>/info endpoint."""
        node_id = 1128074276  # Test Gateway Alpha

        response = client.get(f"/api/node/{node_id}/info")
        assert response.status_code == 200
        data = response.get_json()
        assert "node" in data
        assert "long_name" in data["node"]
        assert "short_name" in data["node"]
        assert "gateway_count_24h" in data["node"]
        assert "packet_count_24h" in data["node"]

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_node_info_hex_format(self, client):
        """Test /api/node/<node_id>/info with hex format."""
        hex_node_id = "!433d0c24"  # Test Gateway Alpha

        response = client.get(f"/api/node/{hex_node_id}/info")
        assert response.status_code == 200
        data = response.get_json()
        assert "node" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_node_info_not_found(self, client):
        """Test /api/node/<node_id>/info with non-existent node."""
        response = client.get("/api/node/999999999/info")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_node_location_history(self, client):
        """Test /api/node/<node_id>/location-history endpoint."""
        node_id = 1128074276  # Test Gateway Alpha

        response = client.get(f"/api/node/{node_id}/location-history")
        assert response.status_code == 200
        data = response.get_json()
        assert "node_id" in data
        assert "location_history" in data
        assert data["node_id"] == node_id

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_node_location_history_with_limit(self, client):
        """Test /api/node/<node_id>/location-history with limit parameter."""
        node_id = 1128074276

        response = client.get(f"/api/node/{node_id}/location-history?limit=5")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["location_history"]) <= 5


class TestAPITracerouteEndpoints:
    """Test API traceroute endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_endpoint(self, client):
        """Test /api/traceroute endpoint."""
        response = client.get("/api/traceroute")
        assert response.status_code == 200
        data = response.get_json()
        assert "traceroutes" in data
        assert "total_count" in data
        assert "page" in data
        assert "per_page" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_pagination(self, client):
        """Test /api/traceroute pagination."""
        response = client.get("/api/traceroute?page=1&per_page=5")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 5
        assert len(data["traceroutes"]) <= 5

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_filters(self, client):
        """Test /api/traceroute with filters."""
        response = client.get(
            "/api/traceroute?gateway_id=!12345678&from_node=305419896&to_node=305419897"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "traceroutes" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_analytics(self, client):
        """Test /api/traceroute/analytics endpoint."""
        response = client.get("/api/traceroute/analytics")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_analytics_with_hours(self, client):
        """Test /api/traceroute/analytics with hours parameter."""
        response = client.get("/api/traceroute/analytics?hours=12")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_details(self, client):
        """Test /api/traceroute/<packet_id> endpoint."""
        # Get a traceroute packet ID from the database
        from src.malla.database.repositories import TracerouteRepository

        result = TracerouteRepository.get_traceroute_packets(limit=1)
        if result["packets"]:
            packet_id = result["packets"][0]["id"]

            response = client.get(f"/api/traceroute/{packet_id}")
            assert response.status_code == 200
            data = response.get_json()
            assert "id" in data
            assert data["id"] == packet_id
        else:
            pytest.skip("No traceroute packets available for testing")

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_details_not_found(self, client):
        """Test /api/traceroute/<packet_id> with non-existent packet."""
        response = client.get("/api/traceroute/999999")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_patterns(self, client):
        """Test /api/traceroute/patterns endpoint."""
        response = client.get("/api/traceroute/patterns")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_traceroute_hops_nodes(self, client):
        """Test /api/traceroute-hops/nodes endpoint."""
        response = client.get("/api/traceroute-hops/nodes")
        assert response.status_code == 200
        data = response.get_json()
        assert "nodes" in data
        assert "total_count" in data
        assert isinstance(data["nodes"], list)


class TestAPILocationEndpoints:
    """Test API location endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_locations_endpoint(self, client):
        """Test /api/locations endpoint."""
        response = client.get("/api/locations")
        assert response.status_code == 200
        data = response.get_json()
        assert "locations" in data
        assert "total_count" in data
        assert isinstance(data["locations"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_location_statistics(self, client):
        """Test /api/location/statistics endpoint."""
        response = client.get("/api/location/statistics")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_location_hop_distances(self, client):
        """Test /api/location/hop-distances endpoint."""
        response = client.get("/api/location/hop-distances")
        assert response.status_code == 200
        data = response.get_json()
        assert "hop_distances" in data
        assert "total_pairs" in data
        assert isinstance(data["hop_distances"], list)


class TestAPIUtilityEndpoints:
    """Test API utility endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_gateways_endpoint(self, client):
        """Test /api/gateways endpoint."""
        response = client.get("/api/gateways")
        assert response.status_code == 200
        data = response.get_json()
        assert "gateways" in data
        assert isinstance(data["gateways"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_longest_links_endpoint(self, client):
        """Test /api/longest-links endpoint."""
        response = client.get("/api/longest-links")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_longest_links_with_filters(self, client):
        """Test /api/longest-links with filter parameters."""
        response = client.get(
            "/api/longest-links?min_distance=1.0&min_snr=-20.0&max_results=50"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)


class TestErrorHandling:
    """Test error handling across all endpoints."""

    @pytest.mark.integration
    def test_404_for_nonexistent_routes(self, client):
        """Test that non-existent routes return 404."""
        response = client.get("/nonexistent-route")
        assert response.status_code == 404

    @pytest.mark.integration
    @pytest.mark.api
    def test_api_error_handling(self, client):
        """Test API error handling with invalid parameters."""
        # Test with invalid node ID format
        response = client.get("/api/node/invalid_node_id/info")
        assert response.status_code in [400, 500]  # Should handle gracefully

        # Test with malformed request parameters
        response = client.get("/api/packets/data?invalid_param=invalid_value")
        assert response.status_code == 200  # Should handle gracefully with defaults

    @pytest.mark.integration
    def test_route_parameter_validation(self, client):
        """Test route parameter validation."""
        # Test packet detail with invalid packet ID
        response = client.get("/packet/invalid_id")
        assert response.status_code == 404

        # Test node detail with invalid node ID
        response = client.get("/node/invalid_node_id")
        assert response.status_code == 400


class TestDataConsistency:
    """Test data consistency across different endpoints."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_node_count_consistency(self, client):
        """Test that node counts are consistent across endpoints."""
        # Get node count from stats
        stats_response = client.get("/api/stats")
        stats_data = stats_response.get_json()
        stats_node_count = stats_data["total_nodes"]

        # Get node count from nodes endpoint
        nodes_response = client.get("/api/nodes")
        nodes_data = nodes_response.get_json()
        nodes_count = nodes_data["total_count"]

        # They should be consistent
        assert stats_node_count == nodes_count

    @pytest.mark.integration
    @pytest.mark.api
    def test_packet_count_consistency(self, client):
        """Test that packet counts are consistent across endpoints."""
        # Get packet count from stats
        stats_response = client.get("/api/stats")
        stats_data = stats_response.get_json()
        stats_packet_count = stats_data["total_packets"]

        # Get packet count from packets endpoint
        packets_response = client.get("/api/packets")
        packets_data = packets_response.get_json()
        packets_count = packets_data["total_count"]

        # They should be consistent
        assert stats_packet_count == packets_count


class TestPerformance:
    """Test performance characteristics of endpoints."""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_endpoint_response_times(self, client):
        """Test that all endpoints respond within reasonable time limits."""
        endpoints = [
            "/",
            "/nodes",
            "/packets",
            "/traceroute",
            "/map",
            "/api/stats",
            "/api/nodes",
            "/api/packets",
            "/api/traceroute",
            "/api/locations",
            "/health",
            "/info",
        ]

        for endpoint in endpoints:
            start_time = time.time()
            response = client.get(endpoint)
            end_time = time.time()

            # All endpoints should respond within 5 seconds
            response_time = end_time - start_time
            assert response_time < 5.0, (
                f"Endpoint {endpoint} took {response_time:.2f}s to respond"
            )

            # All endpoints should return successful status codes
            assert response.status_code in [200, 302], (
                f"Endpoint {endpoint} returned status {response.status_code}"
            )


class TestContentTypes:
    """Test that endpoints return correct content types."""

    @pytest.mark.integration
    def test_html_endpoints_content_type(self, client):
        """Test that HTML endpoints return correct content type."""
        html_endpoints = [
            "/",
            "/nodes",
            "/packets",
            "/traceroute",
            "/traceroute-hops",
            "/map",
            "/longest-links",
        ]

        for endpoint in html_endpoints:
            response = client.get(endpoint)
            if response.status_code == 200:
                assert "text/html" in response.headers.get("Content-Type", "")

    @pytest.mark.integration
    @pytest.mark.api
    def test_json_endpoints_content_type(self, client):
        """Test that JSON API endpoints return correct content type."""
        json_endpoints = [
            "/api/stats",
            "/api/nodes",
            "/api/packets",
            "/api/traceroute",
            "/api/locations",
            "/api/gateways",
            "/health",
            "/info",
        ]

        for endpoint in json_endpoints:
            response = client.get(endpoint)
            if response.status_code == 200:
                assert "application/json" in response.headers.get("Content-Type", "")
