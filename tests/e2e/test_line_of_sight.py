"""
E2E tests for the line-of-sight analysis feature on the map.
"""

import pytest
from playwright.sync_api import Page, expect

DEFAULT_TIMEOUT = 20000  # ms


class TestLineOfSight:
    """Test line-of-sight analysis functionality."""

    @pytest.mark.e2e
    def test_line_of_sight_link_in_popup_template(self, page: Page, test_server_url):
        """Test that the line-of-sight link structure exists in link popups."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links if not already enabled
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Check if Line of Sight link functionality exists by examining the page source
        # This is more reliable than trying to click on map elements
        page_content = page.content()

        # Verify the Line of Sight link template is in the page
        # The showLineOfSight or Line of Sight link should be referenced
        assert (
            "line-of-sight" in page_content.lower() or "Line of Sight" in page_content
        ), "Line of Sight functionality should be available in the map page"

        # Verify the icon class is used
        assert "bi-bezier" in page_content, "Line of Sight icon should be defined"

    @pytest.mark.e2e
    def test_line_of_sight_route_exists(self, page: Page, test_server_url):
        """Test that the line-of-sight route is accessible."""
        # Simply verify the line-of-sight page can be accessed directly
        page.goto(f"{test_server_url}/line-of-sight")

        # Wait for page to load
        page.wait_for_load_state("networkidle")

        # Verify we're on the line-of-sight page
        expect(page.locator("h1")).to_contain_text("Line of Sight Analysis")

        # Verify the route accepts parameters
        page.goto(f"{test_server_url}/line-of-sight?from=123&to=456")
        page.wait_for_load_state("networkidle")

        # Should still load without error
        expect(page.locator("h1")).to_contain_text("Line of Sight Analysis")
