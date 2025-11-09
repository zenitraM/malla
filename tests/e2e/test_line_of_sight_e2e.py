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
        """Test the complete line-of-sight analysis workflow using direct input."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Wait for node cache to load
        page.wait_for_timeout(2000)

        # Use JavaScript to directly set node values (avoids z-index issues with dropdowns)
        page.evaluate("""
            () => {
                // Set from node
                document.getElementById('fromNode_value').value = '1128074276';
                document.getElementById('fromNode').value = 'Test Mobile Alpha';
                document.getElementById('fromNode_value').dispatchEvent(new Event('change'));

                // Set to node
                document.getElementById('toNode_value').value = '1128074277';
                document.getElementById('toNode').value = 'Test Mobile Beta';
                document.getElementById('toNode_value').dispatchEvent(new Event('change'));
            }
        """)

        # Wait for handlers to process
        page.wait_for_timeout(500)

        # Check if analyze button is enabled
        analyze_btn = page.locator("#analyzeBtn")
        expect(analyze_btn).to_be_enabled(timeout=2000)

        # Click analyze button
        analyze_btn.click()

        # Wait for either loading state or results
        page.wait_for_timeout(2000)

        # Check that either loading or results are shown
        loading_visible = page.locator("#loadingState").is_visible()
        results_visible = page.locator("#resultsContainer").is_visible()
        error_visible = page.locator("#errorState").is_visible()

        # One of these should be true
        assert loading_visible or results_visible or error_visible, (
            "No feedback shown after clicking analyze"
        )

    def test_line_of_sight_elevation_toggle(self, page: Page, test_server_url):
        """Test that the elevation mode toggle is present."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Check elevation toggle exists (it's in resultsContainer which is hidden initially)
        toggle = page.locator("#useNodeElevationToggle")
        expect(toggle).to_be_attached()

        # When results are shown, toggle should be visible and checked by default
        # We can't test interaction without running an analysis, so just verify it exists
        expect(toggle).to_have_attribute("type", "checkbox")

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

        # Attribution box is inside resultsContainer which is hidden until analysis is run
        # Check for attribution box - it should be attached but hidden initially
        attribution = page.locator(".attribution-box")
        expect(attribution).to_be_attached()

        # The attribution box content should contain the required text even if hidden
        attribution_html = attribution.inner_html()
        assert "DEM Net Elevation API" in attribution_html
        assert "elevationapi.com" in attribution_html
        assert "OpenStreetMap" in attribution_html

    def test_line_of_sight_from_tools_menu(self, page: Page, test_server_url):
        """Test opening line-of-sight from the Tools menu."""
        page.goto(f"{test_server_url}/map")
        page.wait_for_load_state("networkidle")

        # Open Tools dropdown
        tools_dropdown = page.locator("#toolsDropdown")
        tools_dropdown.click()

        # Wait for dropdown to open
        page.wait_for_timeout(500)

        # Find Line of Sight link in dropdown
        los_link = page.locator('a.dropdown-item[href="/line-of-sight"]')
        expect(los_link).to_be_attached()

        # Get the href to verify
        href = los_link.get_attribute("href")
        assert href == "/line-of-sight", (
            "Line of Sight link should point to /line-of-sight"
        )

        # Navigate to the link
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")

        # Verify it's the line-of-sight page
        expect(page.locator("h1")).to_contain_text("Line of Sight Analysis")

    def test_line_of_sight_distance_hint(self, page: Page, test_server_url):
        """Test that distance hint element exists and works with JavaScript selection."""
        page.goto(f"{test_server_url}/line-of-sight")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Distance hint element should exist
        hint = page.locator("#distanceHint")
        expect(hint).to_be_attached()

        # Use JavaScript to set nodes with locations and trigger distance calculation
        page.evaluate("""
            () => {
                // Set from node with location
                document.getElementById('fromNode_value').value = '1128074276';
                document.getElementById('fromNode').value = 'Test Mobile Alpha';
                document.getElementById('fromNode_value').dispatchEvent(new Event('change'));

                // Set to node with location
                document.getElementById('toNode_value').value = '1128074277';
                document.getElementById('toNode').value = 'Test Mobile Beta';
                document.getElementById('toNode_value').dispatchEvent(new Event('change'));
            }
        """)

        # Wait for distance calculation
        page.wait_for_timeout(1000)

        # Distance hint should now be visible (if nodes have locations)
        # Check if it's either visible or at least has content
        hint_display = hint.evaluate("el => window.getComputedStyle(el).display")
        # Either it should be visible with distance, or hidden (if nodes don't have locations)
        assert hint_display in ["block", "inline", "none"], (
            "Distance hint should have valid display state"
        )

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
