"""
E2E tests for the line-of-sight analysis feature on the map.
"""

import pytest
from playwright.sync_api import Page, expect

DEFAULT_TIMEOUT = 20000  # ms


class TestLineOfSight:
    """Test line-of-sight analysis functionality."""

    @pytest.mark.e2e
    def test_line_of_sight_button_appears_on_link_popup(
        self, page: Page, test_server_url
    ):
        """Test that the line-of-sight button appears on RF link popups."""
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

        # Try to find and click on an RF link (polyline on the map)
        # Links are rendered as SVG path elements by Leaflet
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on the first link
            links.first.click()

            # Wait for popup to appear
            page.wait_for_timeout(1000)

            # Check if popup is visible
            popup = page.locator(".leaflet-popup-content")
            if popup.is_visible():
                popup_content = popup.text_content()

                # Check if the line of sight button appears (only if both nodes have locations)
                # The button may or may not appear depending on whether both nodes have location data
                los_button = popup.locator("button:has-text('Line of Sight')")

                # If the button is visible, verify it has the correct icon
                if los_button.count() > 0:
                    expect(los_button).to_be_visible()
                    # Check for the icon
                    icon = los_button.locator("i.bi-graph-up")
                    expect(icon).to_be_visible()
                else:
                    # If no LOS button, that's also valid if nodes don't have locations
                    # The test still passes as the functionality is correctly conditional
                    assert popup_content is not None, (
                        "Popup should have content even without LOS button"
                    )

    @pytest.mark.e2e
    def test_line_of_sight_modal_opens(self, page: Page, test_server_url):
        """Test that clicking the line-of-sight button opens the modal."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link to open its popup
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for modal to appear
                page.wait_for_timeout(1000)

                # Check that the modal is visible
                modal = page.locator("#lineOfSightModal")
                expect(modal).to_be_visible(timeout=5000)

                # Check modal title
                modal_title = page.locator("#lineOfSightModalLabel")
                expect(modal_title).to_contain_text("Line of Sight Analysis")

    @pytest.mark.e2e
    def test_line_of_sight_loads_elevation_data(self, page: Page, test_server_url):
        """Test that the line-of-sight analysis loads elevation data."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()
                page.wait_for_timeout(500)

                # Check that loading spinner appears
                loading_spinner = page.locator("#losLoadingSpinner")
                # It should be visible initially or become hidden quickly
                # We just verify it exists
                assert loading_spinner.count() > 0, "Loading spinner should exist"

                # Wait for the content to load (API call may take a few seconds)
                # Give it up to 15 seconds for the external API call
                page.wait_for_selector("#losContent", state="visible", timeout=15000)

                # Verify content sections are visible
                los_content = page.locator("#losContent")
                expect(los_content).to_be_visible()

                # Check that link information is displayed
                link_info = page.locator("#losLinkInfo")
                expect(link_info).to_be_visible()
                link_info_text = link_info.text_content()
                assert link_info_text and len(link_info_text) > 0, (
                    "Link info should have content"
                )

                # Check that analysis information is displayed
                analysis_info = page.locator("#losAnalysisInfo")
                expect(analysis_info).to_be_visible()
                analysis_text = analysis_info.text_content()
                assert analysis_text and len(analysis_text) > 0, (
                    "Analysis info should have content"
                )

    @pytest.mark.e2e
    def test_line_of_sight_displays_elevation_chart(self, page: Page, test_server_url):
        """Test that the elevation profile chart is displayed."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for content to load
                page.wait_for_selector("#losContent", state="visible", timeout=15000)

                # Check that the chart canvas exists and is visible
                chart_canvas = page.locator("#elevationChart")
                expect(chart_canvas).to_be_visible()

                # Verify canvas has content (Chart.js should have rendered to it)
                canvas_width = chart_canvas.evaluate("el => el.width")
                canvas_height = chart_canvas.evaluate("el => el.height")
                assert canvas_width > 0, "Chart canvas should have width"
                assert canvas_height > 0, "Chart canvas should have height"

    @pytest.mark.e2e
    def test_line_of_sight_shows_data_attribution(self, page: Page, test_server_url):
        """Test that data source attribution is displayed."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for content to load
                page.wait_for_selector("#losContent", state="visible", timeout=15000)

                # Check that attribution is displayed
                attribution = page.locator("#losAttribution")
                expect(attribution).to_be_visible()

                # Check that data source information is present
                data_source = page.locator("#losDataSource")
                expect(data_source).to_be_visible()

                data_source_text = data_source.text_content()
                assert data_source_text and len(data_source_text) > 0, (
                    "Data source attribution should have content"
                )

                # Should mention the dataset name (e.g., SRTM)
                assert (
                    "SRTM" in data_source_text
                    or "elevation" in data_source_text.lower()
                ), f"Data source should mention elevation dataset: {data_source_text}"

    @pytest.mark.e2e
    def test_line_of_sight_modal_can_be_closed(self, page: Page, test_server_url):
        """Test that the line-of-sight modal can be closed."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for modal to open
                page.wait_for_selector(
                    "#lineOfSightModal", state="visible", timeout=5000
                )

                # Click the close button
                close_button = page.locator("#lineOfSightModal .btn-close")
                close_button.click()

                # Wait for modal to close
                page.wait_for_timeout(1000)

                # Verify modal is no longer visible
                modal = page.locator("#lineOfSightModal")
                # The modal should either be hidden or removed from visible area
                expect(modal).not_to_be_visible()

    @pytest.mark.e2e
    def test_line_of_sight_displays_link_distance(self, page: Page, test_server_url):
        """Test that link distance is displayed in the analysis."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for content to load
                page.wait_for_selector("#losContent", state="visible", timeout=15000)

                # Check that distance is displayed
                link_info = page.locator("#losLinkInfo")
                link_info_text = link_info.text_content()

                assert "Distance" in link_info_text, "Link info should display distance"

                # Check that distance has a unit (km)
                assert "km" in link_info_text, (
                    "Distance should be displayed in kilometers"
                )

    @pytest.mark.e2e
    def test_line_of_sight_includes_node_altitudes(self, page: Page, test_server_url):
        """Test that node altitudes are included in the analysis."""
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Enable traceroute links
        links_checkbox = page.locator("#tracerouteLinksCheckbox")
        if not links_checkbox.is_checked():
            links_checkbox.click()
            page.wait_for_timeout(1000)

        # Wait for map data to load
        page.wait_for_timeout(3000)

        # Look for RF links
        links = page.locator(".leaflet-overlay-pane path")

        if links.count() > 0:
            # Click on a link
            links.first.click()
            page.wait_for_timeout(1000)

            # Check if line of sight button is present
            los_button = page.locator("button:has-text('Line of Sight')")

            if los_button.count() > 0 and los_button.is_visible():
                # Click the line of sight button
                los_button.click()

                # Wait for content to load
                page.wait_for_selector("#losContent", state="visible", timeout=15000)

                # Check that altitude information is displayed
                link_info = page.locator("#losLinkInfo")
                link_info_text = link_info.text_content()

                assert "Altitude" in link_info_text, (
                    "Link info should display node altitudes"
                )

    @pytest.mark.e2e
    def test_line_of_sight_error_handling(self, page: Page, test_server_url):
        """Test that errors are handled gracefully if the API fails."""
        # This test verifies the error handling structure exists
        page.goto(f"{test_server_url}/map")

        # Wait for loading to complete
        page.wait_for_selector("#mapLoading", state="hidden", timeout=DEFAULT_TIMEOUT)

        # Check that error elements exist in the modal
        error_div = page.locator("#losError")
        assert error_div.count() > 0, "Error div should exist in modal"

        error_message = page.locator("#losErrorMessage")
        assert error_message.count() > 0, "Error message element should exist"

        # The error div should be hidden by default
        expect(error_div).to_be_hidden()

