from playwright.sync_api import Page, expect


class TestNodesPrimaryChannelFilter:
    """E2E tests for filtering nodes by primary channel."""

    def test_filter_by_primary_channel(self, page: Page, test_server_url: str):
        """Verify that filtering by primary channel works on Nodes page."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data and channel filter options to load
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#primary_channel option').length > 1",
            timeout=10000,
        )

        # Get current total rows
        initial_rows = page.locator("#nodesTable tbody tr").count()
        assert initial_rows > 0, "Nodes table should have data before filtering"

        # Select the primary channel (fixture uses 'LongFast')
        channel_select = page.locator("#primary_channel")
        expect(channel_select).to_be_visible()
        channel_select.select_option(value="LongFast")

        # Apply filters
        page.locator("#applyFilters").click()

        # Wait for filtering to apply – expect same or fewer rows
        page.wait_for_function(
            "(initial) => document.querySelectorAll('#nodesTable tbody tr').length <= initial",
            timeout=5000,
            arg=initial_rows,
        )

        filtered_rows = page.locator("#nodesTable tbody tr").count()
        assert filtered_rows > 0, (
            "Filtering by primary channel should return some nodes"
        )

        # Each visible row should contain 'LongFast' badge in Channel column
        rows_html = page.locator("#nodesTable tbody").inner_html()
        assert "LongFast" in rows_html, "Filtered rows should display selected channel"
