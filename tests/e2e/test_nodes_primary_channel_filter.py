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

        # Apply filters. The v1 cutover filters server-side, so wait for the
        # filtered request to complete and for the loading row to clear before
        # asserting row contents.
        with page.expect_response(
            lambda r: "/api/v1/nodes" in r.url and r.status == 200, timeout=15000
        ) as filtered_response:
            page.locator("#applyFilters").click()
        filtered_response.value.finished()

        page.wait_for_function(
            """() => {
                // A row counts only once fully rendered: no loading spinner
                // inside it, and it displays the filtered channel value.
                const rows = document.querySelectorAll('#nodesTable tbody tr');
                for (const row of rows) {
                    if (row.querySelector('.loading-spinner')) continue;
                    if (row.textContent.includes('LongFast')) return true;
                }
                return false;
            }""",
            timeout=15000,
        )

        # The DOM can be mid-refresh (a settled row may be re-rendered with a
        # spinner), so assert the server-side truth from the filtered response
        # and keep the DOM check tolerant.
        body = filtered_response.value.json()
        assert body["data"], "Filtering by primary channel should return some nodes"
        assert all(row.get("primary_channel") == "LongFast" for row in body["data"]), (
            "every returned node must carry the filtered channel"
        )
        page.wait_for_function(
            """() => document.querySelectorAll(
                '#nodesTable tbody tr:not(:has(.loading-spinner))'
            ).length > 0""",
            timeout=15000,
        )
