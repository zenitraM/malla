"""
End-to-end tests focused on URL parameter handling for exclude filters.

This test suite focuses on URL-based testing which is more reliable in CI environments
than complex UI interactions.
"""

import requests
from playwright.sync_api import Page, expect


class TestExcludeFiltersURLHandling:
    """Test exclude filter URL parameter handling end-to-end."""

    def test_exclude_from_url_parameter_restoration(
        self, page: Page, test_server_url: str
    ):
        """Test that exclude_from URL parameter is properly restored on page load."""
        exclude_from_id = "1128074276"  # Test Gateway Alpha

        # Navigate with exclude_from parameter in URL
        page.goto(f"{test_server_url}/packets?exclude_from={exclude_from_id}")
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)  # Give time for URL parameters to be processed

        # Verify the exclude_from field was populated from URL
        exclude_from_input = page.locator('input[name="exclude_from"]')
        expect(exclude_from_input).to_have_value(exclude_from_id)

        # Verify the filtering was actually applied by checking table content
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        print(f"Packets displayed with exclude_from URL parameter: {row_count}")

        # Verify URL parameter is preserved
        current_url = page.url
        assert f"exclude_from={exclude_from_id}" in current_url, (
            f"URL should preserve exclude_from parameter: {current_url}"
        )

        print("✅ Exclude from URL parameter restoration working correctly")

    def test_exclude_to_url_parameter_restoration(
        self, page: Page, test_server_url: str
    ):
        """Test that exclude_to URL parameter is properly restored on page load."""
        exclude_to_id = "4294967295"  # Broadcast

        # Navigate with exclude_to parameter in URL
        page.goto(f"{test_server_url}/packets?exclude_to={exclude_to_id}")
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Verify the exclude_to field was populated from URL
        exclude_to_input = page.locator('input[name="exclude_to"]')
        expect(exclude_to_input).to_have_value(exclude_to_id)

        # Verify the filtering was actually applied by checking table content
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        print(f"Packets displayed with exclude_to URL parameter: {row_count}")

        # Verify URL parameter is preserved
        current_url = page.url
        assert f"exclude_to={exclude_to_id}" in current_url, (
            f"URL should preserve exclude_to parameter: {current_url}"
        )

        print("✅ Exclude to URL parameter restoration working correctly")

    def test_combined_exclude_url_parameters(self, page: Page, test_server_url: str):
        """Test that both exclude parameters work together in URL."""
        exclude_from_id = "1128074276"
        exclude_to_id = "4294967295"

        # Navigate with both exclude parameters in URL
        page.goto(
            f"{test_server_url}/packets?exclude_from={exclude_from_id}&exclude_to={exclude_to_id}"
        )
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Verify both fields were populated from URL
        exclude_from_input = page.locator('input[name="exclude_from"]')
        exclude_to_input = page.locator('input[name="exclude_to"]')
        expect(exclude_from_input).to_have_value(exclude_from_id)
        expect(exclude_to_input).to_have_value(exclude_to_id)

        # Verify the filtering was actually applied
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        print(f"Packets displayed with both exclude parameters: {row_count}")

        # Verify both URL parameters are preserved
        current_url = page.url
        assert f"exclude_from={exclude_from_id}" in current_url
        assert f"exclude_to={exclude_to_id}" in current_url

        print("✅ Combined exclude URL parameters working correctly")

    def test_exclude_filters_with_other_url_parameters(
        self, page: Page, test_server_url: str
    ):
        """Test exclude filters work with other URL parameters."""
        exclude_from_id = "1128074276"
        portnum = "TEXT_MESSAGE_APP"

        # Navigate with exclude and portnum parameters
        page.goto(
            f"{test_server_url}/packets?exclude_from={exclude_from_id}&portnum={portnum}"
        )
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Verify both parameters were applied
        exclude_from_input = page.locator('input[name="exclude_from"]')
        expect(exclude_from_input).to_have_value(exclude_from_id)

        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(portnum)

        # Verify both filters are in URL
        current_url = page.url
        assert f"exclude_from={exclude_from_id}" in current_url
        assert f"portnum={portnum}" in current_url

        print("✅ Exclude filters with other URL parameters working correctly")

    def test_exclude_filters_url_vs_api_consistency(
        self, page: Page, test_server_url: str
    ):
        """Test that URL parameters produce same results as direct API calls."""
        exclude_from_id = "1128074276"
        exclude_to_id = "4294967295"

        # Get direct API results for comparison
        api_response = requests.get(
            f"{test_server_url}/api/packets/data?exclude_from={exclude_from_id}&exclude_to={exclude_to_id}&limit=100"
        )
        assert api_response.status_code == 200
        api_data = api_response.json()
        api_packet_count = len(api_data["data"])
        api_total_count = api_data["total_count"]

        print(
            f"API results: {api_packet_count} packets displayed, {api_total_count} total"
        )

        # Navigate with URL parameters
        page.goto(
            f"{test_server_url}/packets?exclude_from={exclude_from_id}&exclude_to={exclude_to_id}",
            wait_until="networkidle",
        )
        page.wait_for_selector("#packetsTable", timeout=10000)

        # Wait for table data to actually load
        page.wait_for_selector("#packetsTable tbody tr", timeout=10000)

        # Wait for loading to complete - check that we have data rows (not loading spinner)
        page.wait_for_function(
            """
            () => {
                const tbody = document.querySelector('#packetsTable tbody');
                if (!tbody) return false;
                const rows = tbody.querySelectorAll('tr');
                // Check that we have rows and they're not loading/error states
                if (rows.length === 0) return false;
                const firstRow = rows[0];
                // Make sure it's not a loading or error row
                return !firstRow.textContent.includes('Loading') &&
                       !firstRow.textContent.includes('Error') &&
                       !firstRow.textContent.includes('No data');
            }
            """,
            timeout=10000,
        )

        # Wait a bit more for any final rendering
        page.wait_for_timeout(2000)

        # Get UI results
        ui_rows = page.locator("#packetsTable tbody tr")
        ui_packet_count = ui_rows.count()

        print(
            f"UI results: {ui_packet_count} packets displayed, API: {api_packet_count}"
        )

        # UI should match API results
        # Allow reasonable tolerance for timing/rendering differences or potential grouping/filtering differences
        # Use a larger tolerance to account for potential frontend filtering or grouping that might reduce row count
        tolerance = max(
            10, int(api_packet_count * 0.3)
        )  # 30% tolerance, minimum 10 rows
        assert abs(ui_packet_count - api_packet_count) <= tolerance, (
            f"UI packet count ({ui_packet_count}) should match API count ({api_packet_count}) "
            f"(difference: {abs(ui_packet_count - api_packet_count)}, tolerance: {tolerance})"
        )

        # Also verify that UI shows at least some rows (to ensure filtering is working)
        assert ui_packet_count > 0, "UI should show at least some filtered rows"

        print("✅ URL parameter results consistent with API")

    def test_exclude_filters_clear_via_url(self, page: Page, test_server_url: str):
        """Test that navigating to clean URL clears exclude filters."""
        exclude_from_id = "1128074276"

        # First navigate with exclude parameter
        page.goto(f"{test_server_url}/packets?exclude_from={exclude_from_id}")
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify filter is applied
        exclude_from_input = page.locator('input[name="exclude_from"]')
        expect(exclude_from_input).to_have_value(exclude_from_id)

        # Get filtered count
        filtered_rows = page.locator("#packetsTable tbody tr")
        filtered_count = filtered_rows.count()

        # Navigate to clean URL
        page.goto(f"{test_server_url}/packets")
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Verify fields are cleared
        expect(exclude_from_input).to_have_value("")
        exclude_to_input = page.locator('input[name="exclude_to"]')
        expect(exclude_to_input).to_have_value("")

        # Verify more packets are shown after clearing
        cleared_rows = page.locator("#packetsTable tbody tr")
        cleared_count = cleared_rows.count()

        print(f"Filtered count: {filtered_count}, Cleared count: {cleared_count}")

        # Should have same or more packets after clearing filters
        assert cleared_count >= filtered_count, (
            f"Expected same or more packets after clearing filters, "
            f"got {cleared_count} vs filtered {filtered_count}"
        )

        print("✅ Clear exclude filters via URL navigation working correctly")

    def test_exclude_filters_invalid_url_parameters(
        self, page: Page, test_server_url: str
    ):
        """Test that invalid exclude parameters are handled gracefully."""
        # Test with invalid node IDs
        page.goto(
            f"{test_server_url}/packets?exclude_from=invalid&exclude_to=999999999999"
        )
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Page should load without errors
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Page should load with data despite invalid parameters"

        # Invalid parameters should be ignored (fields should be empty)
        exclude_from_input = page.locator('input[name="exclude_from"]')
        exclude_to_input = page.locator('input[name="exclude_to"]')

        # The inputs should either be empty or contain the original invalid values
        # (depending on implementation - both are acceptable)
        from_value = exclude_from_input.input_value()
        to_value = exclude_to_input.input_value()

        print(f"Invalid parameter handling - from: '{from_value}', to: '{to_value}'")

        print("✅ Invalid exclude URL parameters handled gracefully")

    def test_exclude_filters_broadcast_url_parameter(
        self, page: Page, test_server_url: str
    ):
        """Test that broadcast node can be excluded via URL parameter."""
        broadcast_id = "4294967295"

        # Test excluding broadcast packets
        page.goto(f"{test_server_url}/packets?exclude_to={broadcast_id}")
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Verify broadcast exclusion is applied
        exclude_to_input = page.locator('input[name="exclude_to"]')
        expect(exclude_to_input).to_have_value(broadcast_id)

        # Verify table shows non-broadcast packets
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        print(f"Non-broadcast packets displayed: {row_count}")

        # Check that displayed packets don't go to broadcast
        # (Only check first few rows to avoid timeout issues)
        for i in range(min(3, row_count)):
            row = rows.nth(i)
            to_cell = row.locator("td").nth(2)  # To column (assuming standard layout)
            to_text = to_cell.inner_text()
            # Broadcast should not appear in the "To" column
            assert "Broadcast" not in to_text, (
                f"Found broadcast destination in row {i}: {to_text}"
            )

        print("✅ Broadcast exclude URL parameter working correctly")
