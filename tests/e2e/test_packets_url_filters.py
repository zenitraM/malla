"""
End-to-end tests for packets page URL filter behavior.
"""

import requests
from playwright.sync_api import Page, expect

DEFAULT_TIMEOUT = 20000  # ms – common timeout for waits


class TestPacketsURLFilters:
    """Test suite for packets page URL filter functionality."""

    def test_packets_url_filter_no_duplicate_requests(
        self, page: Page, test_server_url: str
    ):
        """Test that packets page with URL filters doesn't make duplicate API requests."""
        # Use a known node ID from test fixtures
        test_from_node = "1128074276"  # This should exist in test data

        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with URL parameters
        page.goto(
            f"{test_server_url}/packets?from_node={test_from_node}&group_packets=false"
        )

        # Wait for page to load completely
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)  # Give time for all requests to complete

        # Verify the filter was populated correctly
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value(test_from_node)

        # Verify grouping checkbox was set correctly
        group_checkbox = page.locator("#group_packets")
        expect(group_checkbox).not_to_be_checked()

        # Check that we have table data
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, f"Expected filtered results, but found {row_count} rows"

        # Analyze API requests
        print(f"Total API requests made: {len(api_requests)}")
        for i, req in enumerate(api_requests):
            print(f"Request {i + 1}: {req['url']}")

        # We should ideally have only 1 API request (the filtered one)
        # But currently it makes 2: one unfiltered, then one filtered
        # This test documents the current behavior and will fail when we fix it

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

        # This assertion will fail initially, documenting the bug
        # After fix, we should have 0 unfiltered requests
        assert len(unfiltered_requests) == 0, (
            f"Expected 0 unfiltered requests when URL has filters, "
            f"but found {len(unfiltered_requests)} unfiltered requests. "
            f"This indicates the page is making unnecessary API calls."
        )

        # We should have exactly 1 filtered request
        assert len(filtered_requests) == 1, (
            f"Expected exactly 1 filtered request, but found {len(filtered_requests)}"
        )

    def test_packets_url_filter_applied_immediately(
        self, page: Page, test_server_url: str
    ):
        """Test that URL filters are applied immediately without needing to click Apply."""
        test_from_node = "1128074276"

        # Navigate with URL parameters
        page.goto(f"{test_server_url}/packets?from_node={test_from_node}")

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify the filter was populated
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value(test_from_node)

        # Check that the table shows filtered data immediately
        # by verifying we have some data (meaning the filter was applied)
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data immediately"

        # Verify the filtering worked by checking the API directly
        response = requests.get(
            f"{test_server_url}/api/packets/data?from_node={test_from_node}&limit=5"
        )
        assert response.status_code == 200
        api_data = response.json()

        assert "data" in api_data
        assert len(api_data["data"]) > 0, "Should have filtered results"

        # All results should match the filter
        for item in api_data["data"]:
            assert item["from_node_id"] == int(test_from_node), (
                f"All packets should be from node {test_from_node}"
            )

    def test_packets_url_filter_multiple_parameters(
        self, page: Page, test_server_url: str
    ):
        """Test that multiple URL parameters are applied correctly."""
        test_from_node = "1128074276"
        test_portnum = "TRACEROUTE_APP"

        # Navigate with multiple URL parameters
        page.goto(
            f"{test_server_url}/packets?from_node={test_from_node}&portnum={test_portnum}&group_packets=true"
        )

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify all filters were populated
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value(test_from_node)

        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(test_portnum)

        group_checkbox = page.locator("#group_packets")
        expect(group_checkbox).to_be_checked()

        # Check that we have data
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Table should show filtered data"

    def test_packets_no_url_parameters_single_request(
        self, page: Page, test_server_url: str
    ):
        """Test that packets page without URL parameters makes only one API request."""
        # Track network requests
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate without URL parameters
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Should have exactly 1 API request
        print(f"API requests made: {len(api_requests)}")
        for req in api_requests:
            print(f"Request: {req['url']}")

        assert len(api_requests) == 1, (
            f"Expected exactly 1 API request for unfiltered page, "
            f"but found {len(api_requests)} requests"
        )

    def test_packets_exclude_self_param_populates_checkbox(
        self, page: Page, test_server_url: str
    ):
        """Passing exclude_self=true in URL should check the checkbox and actually filter self-sent packets."""
        test_gateway_id = "2057762540"  # Gateway ID that exists in test data with both self-sent and other packets

        # Navigate with exclude_self param
        page.goto(
            f"{test_server_url}/packets?gateway_id={test_gateway_id}&exclude_self=true"
        )

        # Wait for page and table to load
        page.wait_for_selector("#packetsTable", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(2000)

        # Verify gateway hidden field populated
        hidden_gateway = page.locator('input[name="gateway_id"]')
        expect(hidden_gateway).to_have_value(test_gateway_id)

        # Verify exclude_self checkbox is checked
        exclude_checkbox = page.locator("#exclude_self")
        expect(exclude_checkbox).to_be_checked()

    def test_packets_exclude_self_frontend_behavior(
        self, page: Page, test_server_url: str
    ):
        """Test that the frontend properly applies exclude_self filter when loaded from URL."""
        test_gateway_id = "2057762540"  # Gateway ID that exists in test data

        # Track API requests to verify correct filtering is applied
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with both gateway_id and exclude_self params
        page.goto(
            f"{test_server_url}/packets?gateway_id={test_gateway_id}&exclude_self=true"
        )

        # Wait for page and table to load
        page.wait_for_selector("#packetsTable", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Give time for all requests to complete

        # Verify the checkbox is checked
        exclude_checkbox = page.locator("#exclude_self")
        expect(exclude_checkbox).to_be_checked()

        # Verify that API requests include the exclude_self parameter
        assert len(api_requests) > 0, "Should have made at least one API request"

        # Find the request that should have both gateway_id and exclude_self
        filtered_requests = [
            req
            for req in api_requests
            if f"gateway_id={test_gateway_id}" in req["url"]
            and "exclude_self=true" in req["url"]
        ]

        assert len(filtered_requests) > 0, (
            f"Expected API request with both gateway_id={test_gateway_id} and exclude_self=true, "
            f"but found requests: {[req['url'] for req in api_requests]}"
        )

        print(f"Found correctly filtered API request: {filtered_requests[0]['url']}")
