"""
E2E tests for map filtering functionality.
"""

import pytest
from playwright.sync_api import Page, expect

DEFAULT_TIMEOUT = 20000  # ms – allow extra time for map data to load


class TestMapFilters:
    """Test map filtering functionality."""

    @pytest.mark.e2e
    def test_role_filter_options_available(self, page: Page, test_server_url):
        """Test that all role filter options are available."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Check that role filter exists
        role_filter = page.locator("#roleFilter")
        expect(role_filter).to_be_visible()

        # Check that all expected options are present
        expected_options = [
            "",
            "CLIENT",
            "ROUTER",
            "REPEATER",
            "CLIENT_MUTE",
            "ROUTER_CLIENT",
            "SENSOR",
            "UNKNOWN",
        ]

        for option_value in expected_options:
            option = role_filter.locator(f"option[value='{option_value}']")
            expect(option).to_be_attached()

    @pytest.mark.e2e
    def test_age_filter_options_available(self, page: Page, test_server_url):
        """Test that all age filter options are available."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Check that age filter exists
        age_filter = page.locator("#maxAge")
        expect(age_filter).to_be_visible()

        # Check that all expected options are present
        expected_options = ["", "1", "6", "24", "72", "168"]

        for option_value in expected_options:
            option = age_filter.locator(f"option[value='{option_value}']")
            expect(option).to_be_attached()

    @pytest.mark.e2e
    def test_client_side_role_filtering(self, page: Page, test_server_url):
        """Test that role filtering works on client-side without server requests."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Monitor network requests
        requests = []
        page.on("request", lambda request: requests.append(request.url))

        # Clear previous requests
        requests.clear()

        # Apply role filter
        role_filter = page.locator("#roleFilter")
        role_filter.select_option("ROUTER")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()

        # Wait for filtering to complete
        page.wait_for_timeout(2000)

        # Check that no new API requests were made to /api/locations
        location_requests = [req for req in requests if "/api/locations" in req]
        assert len(location_requests) == 0, "Role filtering should be client-side only"

    @pytest.mark.e2e
    def test_client_side_age_filtering(self, page: Page, test_server_url):
        """Test that age filtering works on client-side without server requests."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Monitor network requests
        requests = []
        page.on("request", lambda request: requests.append(request.url))

        # Get initial node count
        initial_count = page.locator("#nodeCount").text_content()
        initial_count_int = int(initial_count) if initial_count else 0

        # Clear previous requests
        requests.clear()

        # Apply age filter (1 hour - should filter out most nodes)
        age_filter = page.locator("#maxAge")
        age_filter.select_option("1")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()

        # Wait for filtering to complete
        page.wait_for_timeout(2000)

        # Check that no new API requests were made to /api/locations
        location_requests = [req for req in requests if "/api/locations" in req]
        assert len(location_requests) == 0, "Age filtering should be client-side only"

        # Verify filtering worked
        filtered_count = page.locator("#nodeCount").text_content()
        filtered_count_int = int(filtered_count) if filtered_count else 0

        # Should have fewer nodes after 1-hour filter
        assert filtered_count_int <= initial_count_int

    @pytest.mark.e2e
    def test_filter_reset_functionality(self, page: Page, test_server_url):
        """Test that filters can be reset to show all data."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Get initial counts
        initial_node_count = page.locator("#nodeCount").text_content()
        initial_link_count = page.locator("#statsLinks").text_content()

        # Apply filters
        age_filter = page.locator("#maxAge")
        age_filter.select_option("1")

        role_filter = page.locator("#roleFilter")
        role_filter.select_option("CLIENT")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()
        page.wait_for_timeout(2000)

        # Reset filters
        age_filter.select_option("")
        role_filter.select_option("")
        apply_button.click()
        page.wait_for_timeout(2000)

        # Verify counts return to initial values
        final_node_count = page.locator("#nodeCount").text_content()
        final_link_count = page.locator("#statsLinks").text_content()

        assert final_node_count == initial_node_count, (
            "Node count should return to initial value"
        )
        assert final_link_count == initial_link_count, (
            "Link count should return to initial value"
        )

    @pytest.mark.e2e
    def test_filter_affects_node_list(self, page: Page, test_server_url):
        """Test that filters affect the node list display."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Get initial node list items
        initial_items = page.locator("#nodeList .node-list-item").count()

        # Apply role filter
        role_filter = page.locator("#roleFilter")
        role_filter.select_option("ROUTER")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()
        page.wait_for_timeout(2000)

        # Check that node list items changed
        filtered_items = page.locator("#nodeList .node-list-item").count()

        # Should have fewer or equal items
        assert filtered_items <= initial_items

    @pytest.mark.e2e
    def test_filter_affects_map_markers(self, page: Page, test_server_url):
        """Test that filters affect the map markers."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Wait for markers to load

        # Count initial markers
        initial_markers = page.locator(".node-marker-container").count()

        # Apply restrictive age filter
        age_filter = page.locator("#maxAge")
        age_filter.select_option("1")  # 1 hour

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()
        page.wait_for_timeout(3000)  # Wait for map to update

        # Count filtered markers
        filtered_markers = page.locator(".node-marker-container").count()

        # Should have fewer or equal markers
        assert filtered_markers <= initial_markers

    @pytest.mark.e2e
    def test_search_respects_active_filters(self, page: Page, test_server_url):
        """Test that node search respects active filters."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Apply a role filter first
        role_filter = page.locator("#roleFilter")
        role_filter.select_option("ROUTER")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()
        page.wait_for_timeout(2000)

        # Now search
        search_input = page.locator("#nodeSearch")
        search_input.fill("Test")
        page.wait_for_timeout(1000)

        # Search results should only show nodes that match both the filter and search
        search_results = page.locator("#nodeList .node-list-item")

        # All visible results should be from the filtered set
        # (This is more of a smoke test - specific validation would require knowing test data)
        if search_results.count() > 0:
            # At least verify no errors occurred
            expect(search_results.first).to_be_visible()

    @pytest.mark.e2e
    def test_unknown_role_filtering(self, page: Page, test_server_url):
        """Test filtering for nodes with unknown/null roles."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Apply unknown role filter
        role_filter = page.locator("#roleFilter")
        role_filter.select_option("UNKNOWN")

        apply_button = page.locator("#locationFilterForm button[type='submit']")
        apply_button.click()
        page.wait_for_timeout(2000)

        # Check that filtering completed without errors
        node_count = page.locator("#nodeCount").text_content()
        node_count_int = int(node_count) if node_count else 0

        # Should be a valid count (could be 0)
        assert node_count_int >= 0

    @pytest.mark.e2e
    def test_multiple_filter_combinations(self, page: Page, test_server_url):
        """Test various combinations of filters."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Get references to form elements
        age_filter = page.locator("#maxAge")
        role_filter = page.locator("#roleFilter")
        apply_button = page.locator("#locationFilterForm button[type='submit']")

        combinations = [
            ("24", "CLIENT"),
            ("168", "ROUTER"),
            ("6", "REPEATER"),
            ("72", "UNKNOWN"),
        ]

        for age_value, role_value in combinations:
            # Apply combination
            age_filter.select_option(age_value)
            role_filter.select_option(role_value)
            apply_button.click()
            page.wait_for_timeout(2000)

            # Verify no errors
            node_count = page.locator("#nodeCount").text_content()
            assert node_count is not None, (
                f"Filter combination {age_value}h + {role_value} should work"
            )

            link_count = page.locator("#statsLinks").text_content()
            assert link_count is not None, (
                f"Link count should be available for {age_value}h + {role_value}"
            )

        # Reset filters
        age_filter.select_option("")
        role_filter.select_option("")
        apply_button.click()
        page.wait_for_timeout(2000)
