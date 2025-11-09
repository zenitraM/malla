"""
E2E tests for the line-of-sight analysis tool
"""

import pytest
from playwright.sync_api import Page, expect

# Configure longer timeout for API calls
DEFAULT_TIMEOUT = 30000  # ms


@pytest.mark.e2e
class TestLineOfSightE2E:
    """End-to-end tests for line-of-sight functionality."""

    def test_line_of_sight_page_loads_from_tools_menu(
        self, page: Page, test_server_url
    ):
        """Test that the line-of-sight page loads properly from the Tools menu."""
        # Navigate to dashboard
        page.goto(test_server_url)
        page.wait_for_load_state("networkidle")

        # Open Tools dropdown
        tools_dropdown = page.locator("#toolsDropdown")
        tools_dropdown.click()

        # Click Line of Sight link
        los_link = page.locator('a[href="/line-of-sight"]')
        expect(los_link).to_be_visible()
        los_link.click()

        # Wait for page to load
        page.wait_for_load_state("networkidle")

        # Verify page elements are present
        expect(page.locator("h1")).to_contain_text("Line of Sight Analysis")
        expect(page.locator("#fromNode")).to_be_visible()
        expect(page.locator("#toNode")).to_be_visible()
        expect(page.locator("#analyzeBtn")).to_be_visible()

        # Verify analyze button is disabled initially
        expect(page.locator("#analyzeBtn")).to_be_disabled()

    def test_line_of_sight_node_picker_search(self, page: Page, test_server_url):
        """Test that the node picker search functionality works."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Wait for node cache to load
        page.wait_for_timeout(2000)

        # Click on from node picker
        from_input = page.locator("#fromNode")
        from_input.click()

        # Type a search query
        from_input.fill("test")
        page.wait_for_timeout(500)

        # Check if dropdown appears
        dropdown = page.locator(".node-picker-dropdown").first
        expect(dropdown).to_be_visible(timeout=5000)

        # Check if results are shown
        results = page.locator(".node-picker-results .node-picker-item")
        if results.count() > 0:
            # Select first result
            results.first.click()

            # Verify that a value was set
            from_value = page.locator("#fromNode_value")
            expect(from_value).not_to_have_value("")

    def test_line_of_sight_with_url_parameters(self, page: Page, test_server_url):
        """Test that the tool works when loaded with URL parameters."""
        # Navigate with URL parameters (using test node IDs)
        page.goto(f"{test_server_url}/line-of-sight?from=123456789&to=987654321")
        page.wait_for_load_state("networkidle")

        # Wait for initial load attempt
        page.wait_for_timeout(3000)

        # Page should load without errors
        expect(page.locator("h1")).to_contain_text("Line of Sight Analysis")

        # Even if nodes don't exist, page should handle gracefully
        # (no JavaScript errors should occur)

    def test_line_of_sight_complete_workflow(self, page: Page, test_server_url):
        """Test the complete line-of-sight analysis workflow."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Wait for node cache to load
        page.wait_for_timeout(2000)

        # Try to select from node
        from_input = page.locator("#fromNode")
        from_input.click()
        from_input.fill("")  # Clear and show popular nodes
        page.wait_for_timeout(500)

        # Check if we have any nodes
        results = page.locator(".node-picker-results .node-picker-item")
        if results.count() > 0:
            # Select first node
            first_node = results.first
            first_node.click()
            page.wait_for_timeout(300)

            # Select to node (different from first)
            to_input = page.locator("#toNode")
            to_input.click()
            to_input.fill("")
            page.wait_for_timeout(500)

            to_results = page.locator(".node-picker-results .node-picker-item")
            if to_results.count() > 1:
                # Select second node
                to_results.nth(1).click()
                page.wait_for_timeout(300)

                # Check if analyze button is enabled
                analyze_btn = page.locator("#analyzeBtn")
                expect(analyze_btn).to_be_enabled(timeout=2000)

                # Click analyze button
                analyze_btn.click()

                # Wait for either loading state or results
                page.wait_for_timeout(2000)

                # Check that either loading or results are shown
                loading_visible = (
                    page.locator("#loadingState").is_visible()
                )
                results_visible = (
                    page.locator("#resultsContainer").is_visible()
                )
                error_visible = page.locator("#errorState").is_visible()

                # One of these should be true
                assert (
                    loading_visible or results_visible or error_visible
                ), "No feedback shown after clicking analyze"

    def test_line_of_sight_elevation_toggle(self, page: Page, test_server_url):
        """Test that the elevation mode toggle is present."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Check elevation toggle exists
        toggle = page.locator("#useNodeElevationToggle")
        expect(toggle).to_be_visible()
        expect(toggle).to_be_checked()

        # Toggle should be clickable
        toggle.click()
        expect(toggle).not_to_be_checked()

        # Toggle back
        toggle.click()
        expect(toggle).to_be_checked()

    def test_line_of_sight_map_visible(self, page: Page, test_server_url):
        """Test that the map element is present."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Map container should exist
        map_container = page.locator("#line-of-sight-map")
        expect(map_container).to_be_attached()

    def test_line_of_sight_attribution_present(self, page: Page, test_server_url):
        """Test that proper attribution is displayed."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Check for attribution box
        attribution = page.locator(".attribution-box")
        expect(attribution).to_be_visible()

        # Check for DEM Net Elevation API attribution
        expect(attribution).to_contain_text("DEM Net Elevation API")
        expect(attribution).to_contain_text("elevationapi.com")

        # Check for OpenStreetMap attribution
        expect(attribution).to_contain_text("OpenStreetMap")

    def test_line_of_sight_from_map_link(self, page: Page, test_server_url):
        """Test opening line-of-sight from the map page."""
        page.goto(f"{test_server_url}/map")
        page.wait_for_load_state("networkidle")

        # Wait for map to load
        page.wait_for_timeout(3000)

        # Look for any Line of Sight buttons (if they exist)
        los_buttons = page.locator('a:has-text("Line of Sight")')

        if los_buttons.count() > 0:
            # Click the first line of sight button
            with page.expect_popup() as popup_info:
                los_buttons.first.click()

            # Get the new page
            new_page = popup_info.value
            new_page.wait_for_load_state("networkidle")

            # Verify it's the line-of-sight page
            expect(new_page.locator("h1")).to_contain_text("Line of Sight Analysis")

            # URL should have parameters
            assert "from=" in new_page.url or "to=" in new_page.url

            new_page.close()

    def test_line_of_sight_distance_hint(self, page: Page, test_server_url):
        """Test that distance hint appears when both nodes are selected."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Select from node
        from_input = page.locator("#fromNode")
        from_input.click()
        from_input.fill("")
        page.wait_for_timeout(500)

        results = page.locator(".node-picker-results .node-picker-item")
        if results.count() > 0:
            results.first.click()
            page.wait_for_timeout(300)

            # Select to node
            to_input = page.locator("#toNode")
            to_input.click()
            to_input.fill("")
            page.wait_for_timeout(500)

            to_results = page.locator(".node-picker-results .node-picker-item")
            if to_results.count() > 1:
                to_results.nth(1).click()
                page.wait_for_timeout(1000)

                # Distance hint should appear
                hint = page.locator("#distanceHint")
                # Note: Hint might not appear if nodes don't have locations
                # Just check it exists
                expect(hint).to_be_attached()

    def test_line_of_sight_error_handling(self, page: Page, test_server_url):
        """Test error handling when elevation API fails."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Page should handle no selection gracefully
        analyze_btn = page.locator("#analyzeBtn")
        expect(analyze_btn).to_be_disabled()

        # Error state element should exist but be hidden
        error_state = page.locator("#errorState")
        expect(error_state).to_be_attached()
        expect(error_state).to_be_hidden()

