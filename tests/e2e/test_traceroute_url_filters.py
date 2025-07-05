"""
End-to-end tests for traceroute page URL filter behavior.
"""

import requests
from playwright.sync_api import Page, expect


class TestTracerouteURLFilters:
    """Test suite for traceroute page URL filter functionality."""

    def test_traceroute_url_filter_no_duplicate_requests(
        self, page: Page, test_server_url: str
    ):
        """Test that traceroute page with URL filters doesn't make duplicate API requests."""
        # Use a known node ID from test fixtures
        test_from_node = "858993459"  # TSNF from test fixtures

        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/traceroute/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with URL parameters
        page.goto(
            f"{test_server_url}/traceroute?from_node={test_from_node}&group_packets=false"
        )

        # Wait for page to load completely
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(3000)  # Give time for all requests to complete

        # Verify the filter was populated correctly
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value(test_from_node)

        # Verify grouping checkbox was set correctly
        group_checkbox = page.locator("#group_packets")
        expect(group_checkbox).not_to_be_checked()

        # Check that we have table data
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, f"Expected filtered results, but found {row_count} rows"

        # Analyze API requests
        print(f"Total API requests made: {len(api_requests)}")
        for i, req in enumerate(api_requests):
            print(f"Request {i + 1}: {req['url']}")

        # Count unfiltered vs filtered requests
        unfiltered_requests = [
            req
            for req in api_requests
            if f"from_node={test_from_node}" not in req["url"]
        ]
        filtered_requests = [
            req for req in api_requests if f"from_node={test_from_node}" in req["url"]
        ]

        print(f"Unfiltered requests: {len(unfiltered_requests)}")
        print(f"Filtered requests: {len(filtered_requests)}")

        # We should have 0 unfiltered requests when URL has filters
        assert len(unfiltered_requests) == 0, (
            f"Expected 0 unfiltered requests when URL has filters, "
            f"but found {len(unfiltered_requests)} unfiltered requests. "
            f"This indicates the page is making unnecessary API calls."
        )

        # We should have exactly 1 filtered request
        assert len(filtered_requests) == 1, (
            f"Expected exactly 1 filtered request, but found {len(filtered_requests)}"
        )

    def test_traceroute_url_filter_applied_immediately(
        self, page: Page, test_server_url: str
    ):
        """Test that URL filters are applied immediately without needing to click Apply."""
        test_from_node = "858993459"  # TSNF

        # Navigate with URL parameters
        page.goto(f"{test_server_url}/traceroute?from_node={test_from_node}")

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify the filter was populated
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value(test_from_node)

        # Check that the table shows filtered data immediately
        # by verifying we have some data (meaning the filter was applied)
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data immediately"

        # Verify the filtering worked by checking the API directly
        response = requests.get(
            f"{test_server_url}/api/traceroute/data?from_node={test_from_node}&limit=5"
        )
        assert response.status_code == 200
        api_data = response.json()

        assert "data" in api_data
        assert len(api_data["data"]) > 0, "Should have filtered results"

        # All results should match the filter
        for item in api_data["data"]:
            assert item["from_node_id"] == int(test_from_node), (
                f"All traceroutes should be from node {test_from_node}"
            )

    def test_traceroute_url_filter_multiple_parameters(
        self, page: Page, test_server_url: str
    ):
        """Test that multiple URL parameters are applied correctly."""
        test_from_node = "858993459"
        test_to_node = "1128074276"

        # Navigate with multiple URL parameters
        page.goto(
            f"{test_server_url}/traceroute?from_node={test_from_node}&to_node={test_to_node}&group_packets=true"
        )

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify all filters were populated
        from_node_field = page.locator('input[name="from_node"]')
        expect(from_node_field).to_have_value(test_from_node)

        to_node_field = page.locator('input[name="to_node"]')
        expect(to_node_field).to_have_value(test_to_node)

        group_checkbox = page.locator("#group_packets")
        expect(group_checkbox).to_be_checked()

        # Check that we have data
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data"

    def test_traceroute_no_url_parameters_single_request(
        self, page: Page, test_server_url: str
    ):
        """Test that traceroute page without URL parameters makes only one API request."""
        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/traceroute/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate without URL parameters
        page.goto(f"{test_server_url}/traceroute")

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Should have exactly 1 API request
        print(f"API requests made: {len(api_requests)}")
        for req in api_requests:
            print(f"Request: {req['url']}")

        assert len(api_requests) == 1, (
            f"Expected exactly 1 API request for unfiltered page, "
            f"but found {len(api_requests)} requests"
        )

    def test_traceroute_route_node_filter_url(self, page: Page, test_server_url: str):
        """Test that route_node URL parameter is applied correctly."""
        test_route_node = "858993459"

        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/traceroute/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with route_node parameter
        page.goto(f"{test_server_url}/traceroute?route_node={test_route_node}")

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify the route_node filter was populated
        route_node_field = page.locator('input[name="route_node"]')
        expect(route_node_field).to_have_value(test_route_node)

        # Check that we have table data
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data"

        # Should have exactly 1 filtered API request
        filtered_requests = [
            req for req in api_requests if f"route_node={test_route_node}" in req["url"]
        ]
        assert len(filtered_requests) == 1, (
            f"Expected exactly 1 filtered request, but found {len(filtered_requests)}"
        )

    def test_traceroute_gateway_filter_url(self, page: Page, test_server_url: str):
        """Test that gateway_id URL parameter is applied correctly."""
        # Use a known gateway node decimal ID from test fixtures
        test_gateway_id = "1128011076"  # decimal form of !433c1544

        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/traceroute/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with gateway_id parameter
        page.goto(f"{test_server_url}/traceroute?gateway_id={test_gateway_id}")

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify the gateway filter was populated
        gateway_field = page.locator('input[name="gateway_id"]')
        expect(gateway_field).to_have_value(test_gateway_id)

        # Check that we have table data
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data"

        # Should have exactly 1 filtered API request
        filtered_requests = [
            req for req in api_requests if f"gateway_id={test_gateway_id}" in req["url"]
        ]
        assert len(filtered_requests) == 1, (
            f"Expected exactly 1 filtered request, but found {len(filtered_requests)}"
        )

    def test_traceroute_time_range_filter_url(self, page: Page, test_server_url: str):
        """Test that time range URL parameters are applied correctly."""
        start_time = "2025-06-18T10:00"
        end_time = "2025-06-18T12:00"

        # Navigate with time range parameters
        page.goto(
            f"{test_server_url}/traceroute?start_time={start_time}&end_time={end_time}"
        )

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify the time filters were populated
        start_time_field = page.locator('input[name="start_time"]')
        expect(start_time_field).to_have_value(start_time)

        end_time_field = page.locator('input[name="end_time"]')
        expect(end_time_field).to_have_value(end_time)

        # Check that we have table data
        rows = page.locator("#tracerouteTable tbody tr")
        row_count = rows.count()
        # Note: Time range might result in 0 rows if no data in that range, which is valid
        print(f"Filtered rows for time range: {row_count}")
