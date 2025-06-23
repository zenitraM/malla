"""
End-to-end tests for nodes page search functionality.
"""

from playwright.sync_api import Page, expect


class TestNodesSearch:
    """Test suite for nodes page search functionality."""

    def test_nodes_search_functionality(self, page: Page, test_server_url: str):
        """Test that the search functionality works on the nodes page."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data to load by waiting for any node data
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)

        # Wait for at least some nodes to be loaded (fixture has 17 nodes)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=10000,
        )

        # Get initial row count
        initial_rows = page.locator("#nodesTable tbody tr").count()
        assert initial_rows > 0, "Should have some nodes to test with"

        # Find the search input
        search_input = page.locator("#search")
        expect(search_input).to_be_visible()

        # Search for "Gateway" - should match "Test Gateway Alpha" from fixture data
        search_input.fill("Gateway")

        # Wait for search to be applied by waiting for reduced results
        page.wait_for_function(
            f"() => document.querySelectorAll('#nodesTable tbody tr').length < {initial_rows}",
            timeout=5000,
        )

        # Get filtered row count
        filtered_rows = page.locator("#nodesTable tbody tr").count()

        # Should have fewer results than initial (fixture has 1 node with "Gateway")
        assert filtered_rows < initial_rows, (
            f"Search should reduce row count: {filtered_rows} >= {initial_rows}"
        )

        # Should find exactly 1 result for "Gateway" in fixture data
        assert filtered_rows == 1, f"Expected 1 Gateway node, found {filtered_rows}"

        # Should find the expected node
        expect(page.locator("#nodesTable tbody")).to_contain_text("Test Gateway Alpha")

        # Clear the search
        search_input.clear()

        # Wait for all results to be restored
        page.wait_for_function(
            f"() => document.querySelectorAll('#nodesTable tbody tr').length === {initial_rows}",
            timeout=5000,
        )

        # Verify results are restored
        cleared_rows = page.locator("#nodesTable tbody tr").count()
        assert cleared_rows == initial_rows, (
            f"Clearing search should restore all rows: {cleared_rows} != {initial_rows}"
        )

    def test_nodes_search_with_hardware_filter(self, page: Page, test_server_url: str):
        """Test that search works in combination with hardware filters."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data to load
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=10000,
        )

        # Wait for hardware models to load
        page.wait_for_function(
            "() => document.querySelectorAll('#hw_model option').length > 1",
            timeout=10000,
        )

        # Get initial row count
        initial_rows = page.locator("#nodesTable tbody tr").count()

        # Apply TBEAM hardware filter (from fixture data)
        hw_select = page.locator("#hw_model")
        expect(hw_select).to_be_visible()
        hw_select.select_option(value="TBEAM")

        # Wait for hardware filter to be applied by waiting for reduced results
        page.wait_for_function(
            f"() => document.querySelectorAll('#nodesTable tbody tr').length < {initial_rows}",
            timeout=5000,
        )

        # Get filtered row count
        hw_filtered_rows = page.locator("#nodesTable tbody tr").count()
        assert hw_filtered_rows < initial_rows, "Hardware filter should reduce results"

        # Now apply search on top of hardware filter
        search_input = page.locator("#search")
        search_input.fill("Gateway")  # Search for "Gateway" in the filtered results

        # Wait for combined filter result
        page.wait_for_function(
            f"() => document.querySelectorAll('#nodesTable tbody tr').length <= {hw_filtered_rows}",
            timeout=5000,
        )

        # Get final row count
        final_rows = page.locator("#nodesTable tbody tr").count()

        # Verify the combined filtering works
        assert final_rows <= hw_filtered_rows, "Search should work with hardware filter"

        # Verify the combined filtering works - should have some results
        assert final_rows > 0, "Combined filters should show some results"

    def test_nodes_search_no_results(self, page: Page, test_server_url: str):
        """Test search behavior when no results are found."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data to load
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=10000,
        )

        # Search for something that shouldn't exist in fixture data
        search_input = page.locator("#search")
        search_input.fill("NONEXISTENT_NODE_XYZ123")

        # Wait for the table to show no results (either empty or "No data" message)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length <= 1",
            timeout=5000,
        )

        # Should show no results or empty table
        rows = page.locator("#nodesTable tbody tr").count()
        # Either 0 rows or 1 row with "No data" message
        assert rows <= 1, "Should show no results for non-existent search term"

        # Clear search to restore results
        search_input.clear()

        # Wait for results to be restored
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length > 1",
            timeout=5000,
        )

        # Should have results again
        restored_rows = page.locator("#nodesTable tbody tr").count()
        assert restored_rows > 1, "Should restore results after clearing search"

    def test_nodes_search_case_insensitive(self, page: Page, test_server_url: str):
        """Test that search is case insensitive."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data to load
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=10000,
        )

        search_input = page.locator("#search")

        # Test lowercase search for "gateway" (should match "Test Gateway Alpha")
        search_input.fill("gateway")
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length < 10",
            timeout=5000,
        )
        # Wait for search results to stabilize by checking the content
        page.wait_for_function(
            "() => document.querySelector('#nodesTable tbody tr')?.textContent?.toLowerCase().includes('gateway')",
            timeout=3000,
        )
        lowercase_rows = page.locator("#nodesTable tbody tr").count()

        # Test uppercase search for "GATEWAY"
        search_input.clear()
        # Wait for clear to take effect
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=5000,
        )
        search_input.fill("GATEWAY")
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length < 10",
            timeout=5000,
        )
        # Wait for search results to stabilize by checking the content
        page.wait_for_function(
            "() => document.querySelector('#nodesTable tbody tr')?.textContent?.toLowerCase().includes('gateway')",
            timeout=3000,
        )
        uppercase_rows = page.locator("#nodesTable tbody tr").count()

        # Should return same results (case insensitive)
        assert lowercase_rows == uppercase_rows, "Search should be case insensitive"

        # Should find exactly 1 result for Gateway in fixture data
        assert uppercase_rows == 1, f"Expected 1 Gateway node, found {uppercase_rows}"

    def test_nodes_search_realtime_filtering(self, page: Page, test_server_url: str):
        """Test that search filtering happens in real-time as user types."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table data to load
        page.wait_for_selector("#nodesTable tbody tr", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#nodesTable tbody tr').length >= 10",
            timeout=10000,
        )

        initial_rows = page.locator("#nodesTable tbody tr").count()

        search_input = page.locator("#search")

        # Type "Gateway" character by character to test real-time filtering
        search_input.type("Gateway", delay=200)  # Type with delay

        # Wait for search to be applied by waiting for reduced results
        page.wait_for_function(
            f"() => document.querySelectorAll('#nodesTable tbody tr').length < {initial_rows}",
            timeout=5000,
        )

        # Should have filtered results
        filtered_rows = page.locator("#nodesTable tbody tr").count()

        # Should have fewer results than initial
        assert filtered_rows < initial_rows, "Real-time search should filter results"

        # Should find exactly 1 result for "Gateway" in fixture data
        assert filtered_rows == 1, f"Expected 1 Gateway node, found {filtered_rows}"
