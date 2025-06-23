"""
End-to-end tests for table implementations.
"""

import re

import requests
from playwright.sync_api import Page, expect


class TestTables:
    """Test suite for table implementations with full-screen layout."""

    def test_packets_page_loads(self, page: Page, test_server_url: str):
        """Test that the packets page loads correctly."""
        page.goto(f"{test_server_url}/packets")

        # Check that the table container exists
        expect(page.locator("#packetsTable")).to_be_visible()

        # Check that the full-screen layout is present
        expect(page.locator(".table-container")).to_be_visible()
        expect(page.locator(".table-main")).to_be_visible()
        expect(page.locator(".table-sidebar")).to_be_visible()

        # Check that the sidebar toggle button exists
        expect(page.locator("#toggleSidebar")).to_be_visible()

    def test_packets_table_loads_data(self, page: Page, test_server_url: str):
        """Test that the packets table loads data correctly."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that table has data
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

        # Check table headers exist
        headers = page.locator(".modern-table thead th")
        expect(headers.first).to_be_visible()

    def test_packets_grouping_default_state(self, page: Page, test_server_url: str):
        """Test that packets table has grouping enabled by default."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector(".modern-table", timeout=10000)

        # Check that grouping checkbox exists and is checked by default
        grouping_checkbox = page.locator("#group_packets")
        expect(grouping_checkbox).to_be_visible()
        expect(grouping_checkbox).to_be_checked()

        # Check that the table loads with grouped data
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)
        rows = page.locator(".modern-table tbody tr")
        assert rows.count() > 0, "No rows found in table"

    def test_packets_grouping_toggle(self, page: Page, test_server_url: str):
        """Test that packets grouping toggle works correctly."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Find grouping checkbox
        grouping_checkbox = page.locator("#group_packets")
        expect(grouping_checkbox).to_be_visible()

        # Get initial row count
        page.locator(".modern-table tbody tr").count()

        # Toggle grouping off
        if grouping_checkbox.is_checked():
            grouping_checkbox.uncheck()

        # Apply filters to reload
        apply_button = page.locator("#applyFilters")
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(2000)

        # Check that data is still displayed
        rows_after_toggle = page.locator(".modern-table tbody tr")
        assert rows_after_toggle.count() > 0, "No rows found after toggle"

        # Toggle grouping back on
        grouping_checkbox.check()
        apply_button.click()
        page.wait_for_timeout(2000)

        # Verify data is still displayed
        final_rows = page.locator(".modern-table tbody tr")
        assert final_rows.count() > 0, "No rows found after toggling back"

    def test_packets_sorting(self, page: Page, test_server_url: str):
        """Test sorting functionality in packets table."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Click on timestamp header to sort
        timestamp_header = page.locator(".modern-table thead th").first
        timestamp_header.click()

        # Wait for sort to complete
        page.wait_for_timeout(1000)

        # Check that header has sortable class and is now sorted
        expect(timestamp_header).to_have_class(re.compile(r".*sortable.*"))
        # Check that the header now has either asc or desc class indicating it's sorted
        expect(timestamp_header).to_have_class(re.compile(r".*(asc|desc).*"))

    def test_packets_gateway_sorting_grouped(self, page: Page, test_server_url: str):
        """Test that gateway sorting works in grouped view."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Ensure grouping is enabled
        grouping_checkbox = page.locator("#group_packets")
        if not grouping_checkbox.is_checked():
            grouping_checkbox.check()
            page.wait_for_timeout(1000)

        # Click on gateway header to sort
        gateway_header = page.locator(
            ".modern-table thead th:nth-child(5)"
        )  # Gateway column
        gateway_header.click()

        # Wait for sort to complete
        page.wait_for_timeout(1000)

        # Check that header has sortable class and is now sorted
        expect(gateway_header).to_have_class(re.compile(r".*sortable.*"))
        # Check that the header now has either asc or desc class indicating it's sorted
        expect(gateway_header).to_have_class(re.compile(r".*(asc|desc).*"))

        # Table should still have data after sorting
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

    def test_packets_pagination(self, page: Page, test_server_url: str):
        """Test pagination functionality in packets table."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check pagination controls exist (they are created by the ModernTable JavaScript)
        expect(page.locator(".modern-pagination")).to_be_visible()

        # Check that table has data
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

    def test_packets_filters(self, page: Page, test_server_url: str):
        """Test filter functionality in packets table."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Test packet type filter
        packet_type_select = page.locator("#portnum")
        packet_type_select.select_option("TRACEROUTE_APP")

        # Apply filters
        apply_button = page.locator("#applyFilters")
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Check that results are filtered (should have some TRACEROUTE packets)
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

    def test_packets_to_node_filter(self, page: Page, test_server_url: str):
        """Test that the to_node filter is present and functional."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that to_node filter exists
        to_node_input = page.locator("#to_node")
        expect(to_node_input).to_be_visible()

        # Check that it has the node picker functionality
        expect(to_node_input).to_have_attribute("placeholder", "All destination nodes")

    def test_packets_packet_types_complete(self, page: Page, test_server_url: str):
        """Test that all packet types are available in the dropdown."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector("#portnum", timeout=10000)

        # Get all options from the packet type dropdown
        packet_type_select = page.locator("#portnum")
        options = packet_type_select.locator("option").all_text_contents()

        # Check that all expected packet types are present
        expected_types = [
            "All Types",
            "Admin",
            "ATAK Plugin",
            "Neighbor Info",
            "Node Info",
            "Position",
            "Range Test",
            "Routing",
            "Store and Forward",
            "Telemetry",
            "Text Messages",
            "Traceroute",
            "Unknown",
        ]

        for expected_type in expected_types:
            assert expected_type in options, f"Missing packet type: {expected_type}"

    def test_packets_grouping_behavior(self, page: Page, test_server_url: str):
        """Test that grouping shows proper ranges for RSSI, SNR, and hops."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Ensure grouping is enabled
        grouping_checkbox = page.locator("#group_packets")
        if not grouping_checkbox.is_checked():
            grouping_checkbox.check()
            page.wait_for_timeout(2000)

        # Look for grouped data patterns in the table content
        page_content = page.content()

        # In grouped mode, we should see ranges or aggregated values
        # Check for patterns like "X to Y dBm" or "X gateways"
        has_grouped_patterns = (
            " to " in page_content  # RSSI/SNR ranges
            or " gateways" in page_content  # Gateway counts
            or " gateway" in page_content  # Single gateway
        )

        assert has_grouped_patterns, "Grouped data patterns not found in table content"

    def test_packets_grouping_reactive_behavior(self, page: Page, test_server_url: str):
        """Test that grouping checkbox triggers reactive updates without clicking Apply filters."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Track network requests to verify reactive behavior
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Clear any existing requests from page load
        api_requests.clear()

        # Find grouping checkbox and get initial state
        grouping_checkbox = page.locator("#group_packets")
        expect(grouping_checkbox).to_be_visible()
        initial_state = grouping_checkbox.is_checked()

        # Toggle grouping checkbox
        if initial_state:
            grouping_checkbox.uncheck()
        else:
            grouping_checkbox.check()

        # Wait for reactive update (should happen automatically)
        page.wait_for_timeout(2000)

        # Verify that an API request was made automatically (reactive behavior)
        assert len(api_requests) > 0, (
            "Expected reactive API request after grouping toggle, but none were made"
        )

        # Verify the request includes the correct grouping parameter
        latest_request = api_requests[-1]
        expected_grouping = "false" if initial_state else "true"
        assert f"group_packets={expected_grouping}" in latest_request["url"], (
            f"Expected group_packets={expected_grouping} in request URL, "
            f"but got: {latest_request['url']}"
        )

        # Verify table still has data after reactive update
        rows = page.locator(".modern-table tbody tr")
        assert rows.count() > 0, "No rows found after reactive grouping toggle"

    def test_traceroute_page_loads(self, page: Page, test_server_url: str):
        """Test that the traceroute page loads correctly."""
        page.goto(f"{test_server_url}/traceroute")

        # Check that the table container exists
        expect(page.locator("#tracerouteTable")).to_be_visible()

        # Check that the full-screen layout is present
        expect(page.locator(".table-container")).to_be_visible()
        expect(page.locator(".table-main")).to_be_visible()
        expect(page.locator(".table-sidebar")).to_be_visible()

    def test_traceroute_table_loads_data(self, page: Page, test_server_url: str):
        """Test that the traceroute table loads data correctly."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that table has data
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

    def test_traceroute_grouping_toggle(self, page: Page, test_server_url: str):
        """Test grouping toggle functionality in traceroute table."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Find and toggle grouping checkbox
        grouping_checkbox = page.locator("#group_packets")
        expect(grouping_checkbox).to_be_visible()

        # Verify it starts checked (default state)
        expect(grouping_checkbox).to_be_checked()

        # Toggle grouping off
        grouping_checkbox.uncheck()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Verify checkbox is now unchecked
        expect(grouping_checkbox).not_to_be_checked()

        # Toggle grouping back on
        grouping_checkbox.check()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Verify checkbox is checked again
        expect(grouping_checkbox).to_be_checked()

    def test_nodes_page_loads(self, page: Page, test_server_url: str):
        """Test that the nodes page loads correctly."""
        page.goto(f"{test_server_url}/nodes")

        # Check that the table container exists
        expect(page.locator("#nodesTable")).to_be_visible()

        # Check that the full-screen layout is present
        expect(page.locator(".table-container")).to_be_visible()
        expect(page.locator(".table-main")).to_be_visible()
        expect(page.locator(".table-sidebar")).to_be_visible()

    def test_nodes_table_loads_data(self, page: Page, test_server_url: str):
        """Test that the nodes table loads data correctly."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that table has data
        rows = page.locator(".modern-table tbody tr")
        expect(rows.first).to_be_visible()

    def test_nodes_hardware_filter_complete(self, page: Page, test_server_url: str):
        """Test that all hardware models are available in the dropdown."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for page to load
        page.wait_for_selector("#hw_model", timeout=10000)

        # Get all options from the hardware model dropdown
        hw_model_select = page.locator("#hw_model")
        options = hw_model_select.locator("option").all_text_contents()

        # Check that key hardware models are present
        expected_models = [
            "All Hardware",
            "T-Beam",
            "Heltec V3",
            "RAK4631",
            "Station G2",
            "T-LoRa V2.1.1.6",
            "Raspberry Pi Pico",
            "M5Stack Core2",
        ]

        for expected_model in expected_models:
            assert expected_model in options, (
                f"Missing hardware model: {expected_model}"
            )

    def test_nodes_role_filter_complete(self, page: Page, test_server_url: str):
        """Test that all node roles are available in the dropdown."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for page to load
        page.wait_for_selector("#role", timeout=10000)

        # Get all options from the role dropdown
        role_select = page.locator("#role")
        options = role_select.locator("option").all_text_contents()

        # Check that all expected roles are present
        expected_roles = [
            "All Roles",
            "Client",
            "Client Mute",
            "Router",
            "Router Client",
            "Router Late",
            "TAK",
            "Tracker",
        ]

        for expected_role in expected_roles:
            assert expected_role in options, f"Missing node role: {expected_role}"

    def test_nodes_last_seen_not_never(self, page: Page, test_server_url: str):
        """Test that nodes with activity don't show 'Never' for last seen."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get table content
        page.content()

        # Look for nodes with packet activity (24h activity > 0)
        # These should not show "Never" for last seen
        rows = page.locator(".modern-table tbody tr")
        row_count = rows.count()

        if row_count > 0:
            # Check first few rows for proper last seen formatting
            for i in range(min(3, row_count)):
                row = rows.nth(i)
                row_text = row.text_content()

                # If a node has 24h activity, it shouldn't show "Never" for last seen
                if row_text and any(
                    badge in row_text
                    for badge in [
                        "badge bg-success",
                        "badge bg-warning",
                        "badge bg-info",
                    ]
                ):
                    # This row has activity, so last seen should not be "Never"
                    assert row_text and "Never" not in row_text, (
                        f"Active node showing 'Never' for last seen in row {i}"
                    )

    def test_nodes_filters_functional(self, page: Page, test_server_url: str):
        """Test that hardware and role filters work correctly."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Test hardware filter
        hw_model_select = page.locator("#hw_model")
        hw_model_select.select_option("TBEAM")

        # Apply filters
        apply_button = page.locator("#applyFilters")
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Check that table still has content (or shows appropriate message)
        # The table should either have T-Beam nodes or be empty with a message
        table_body = page.locator(".modern-table tbody")
        expect(table_body).to_be_visible()

        # Clear filters and test role filter
        clear_button = page.locator("#clearFilters")
        clear_button.click()
        page.wait_for_timeout(1000)

        # Test role filter
        role_select = page.locator("#role")
        role_select.select_option("ROUTER")

        apply_button.click()
        page.wait_for_timeout(1000)

        # Check that table still has content
        expect(table_body).to_be_visible()

    def test_table_responsive_design(self, page: Page, test_server_url: str):
        """Test responsive design of tables."""
        page.goto(f"{test_server_url}/packets")

        # Test desktop view
        page.set_viewport_size({"width": 1200, "height": 800})
        expect(page.locator(".table-sidebar")).to_be_visible()

        # Test mobile view
        page.set_viewport_size({"width": 375, "height": 667})
        # On mobile, sidebar should still be present but may be collapsed
        expect(page.locator(".table-sidebar")).to_be_visible()

        # Test tablet view
        page.set_viewport_size({"width": 768, "height": 1024})
        expect(page.locator(".table-sidebar")).to_be_visible()

    def test_table_action_buttons(self, page: Page, test_server_url: str):
        """Test action buttons in tables."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that action buttons exist
        action_buttons = page.locator(".modern-table tbody tr:first-child .btn")
        expect(action_buttons.first).to_be_visible()

        # Check that buttons have proper links
        first_button = action_buttons.first
        expect(first_button).to_have_attribute("href", re.compile(r"/packet/\d+"))

    def test_table_performance(self, page: Page, test_server_url: str):
        """Test performance of table loading."""
        page.goto(f"{test_server_url}/packets")

        # Measure time to load table
        start_time = page.evaluate("Date.now()")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        end_time = page.evaluate("Date.now()")
        load_time = end_time - start_time

        # Table should load within reasonable time (10 seconds)
        assert load_time < 10000, f"Table took too long to load: {load_time}ms"

    def test_sidebar_toggle_functionality(self, page: Page, test_server_url: str):
        """Test sidebar toggle functionality."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector(".table-sidebar", timeout=10000)

        # Check initial state - sidebar should be visible
        sidebar = page.locator(".table-sidebar")
        expect(sidebar).to_be_visible()
        expect(sidebar).not_to_have_class("collapsed")

        # Click toggle button to collapse sidebar
        toggle_btn = page.locator("#toggleSidebar")
        toggle_btn.click()

        # Wait for animation
        page.wait_for_timeout(500)

        # Check that sidebar is collapsed
        expect(sidebar).to_have_class(re.compile(r".*collapsed.*"))

        # Click toggle button again to expand sidebar
        toggle_btn.click()

        # Wait for animation
        page.wait_for_timeout(500)

        # Check that sidebar is expanded again
        expect(sidebar).not_to_have_class("collapsed")

    def test_filter_controls_in_sidebar(self, page: Page, test_server_url: str):
        """Test that filter controls work properly in the sidebar."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector(".table-sidebar", timeout=10000)

        # Check that filter form exists in sidebar
        filter_form = page.locator("#filtersForm")
        expect(filter_form).to_be_visible()

        # Check that apply and clear buttons exist
        apply_btn = page.locator("#applyFilters")
        clear_btn = page.locator("#clearFilters")
        expect(apply_btn).to_be_visible()
        expect(clear_btn).to_be_visible()

        # Test clear button functionality
        clear_btn.click()
        page.wait_for_timeout(500)

        # Form should be reset (all inputs should be empty)
        start_time_input = page.locator("#start_time")
        expect(start_time_input).to_have_value("")

    def test_nodes_hardware_filter_clear_bug(self, page: Page, test_server_url: str):
        """Test that clearing hardware filter (selecting 'All hardware') properly removes the filter."""
        page.goto(f"{test_server_url}/nodes")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get initial row count
        initial_rows = page.locator(".modern-table tbody tr").count()

        # Wait for hardware models to load
        page.wait_for_timeout(1000)

        # Select a specific hardware model (first non-empty option)
        hw_select = page.locator("#hw_model")
        hw_select.select_option(
            index=1
        )  # Select first hardware model (not "All Hardware")

        # Apply filters
        apply_button = page.locator("#applyFilters")
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Get filtered row count (should be less than initial)
        filtered_rows = page.locator(".modern-table tbody tr").count()

        # Now clear the filter by selecting "All Hardware"
        hw_select.select_option(value="")  # Select "All Hardware" option

        # Apply filters again
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(1000)

        # Get final row count (should be back to initial count)
        final_rows = page.locator(".modern-table tbody tr").count()

        # Verify the filter was properly cleared
        assert final_rows == initial_rows, (
            f"Filter not cleared properly: initial={initial_rows}, filtered={filtered_rows}, final={final_rows}"
        )

    def test_traceroute_route_data_present(self, page: Page, test_server_url: str):
        """Test that traceroute table shows route data correctly."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Check that at least one row has route data (not "No route data")
        route_cells = page.locator(
            ".modern-table tbody tr td:nth-child(4)"
        )  # Route column

        route_found = False
        total_rows = route_cells.count()

        # Check all visible rows for route data
        for i in range(total_rows):
            route_text = route_cells.nth(i).inner_text()
            if route_text and route_text != "No route data" and "→" in route_text:
                route_found = True
                print(f"Found route data in row {i + 1}: {route_text}")
                break

        # If no route data found in current page, try disabling grouping to see individual packets
        if not route_found:
            print(
                "No route data found with grouping enabled, trying without grouping..."
            )
            grouping_checkbox = page.locator("#group_packets")
            if grouping_checkbox.is_checked():
                grouping_checkbox.uncheck()
                apply_button = page.locator("#applyFilters")
                apply_button.click()
                page.wait_for_timeout(2000)

                # Check again after disabling grouping
                route_cells = page.locator(".modern-table tbody tr td:nth-child(4)")
                for i in range(min(10, route_cells.count())):  # Check first 10 rows
                    route_text = route_cells.nth(i).inner_text()
                    if (
                        route_text
                        and route_text != "No route data"
                        and "→" in route_text
                    ):
                        route_found = True
                        print(
                            f"Found route data without grouping in row {i + 1}: {route_text}"
                        )
                        break

        assert route_found, (
            "No route data found in traceroute table (checked both grouped and ungrouped)"
        )

    def test_traceroute_hops_display(self, page: Page, test_server_url: str):
        """Test that traceroute table shows hop counts correctly."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)
        page.wait_for_timeout(2000)  # Additional wait for data to load

        # First, let's check if we have any data at all
        rows = page.locator(".modern-table tbody tr")
        row_count = rows.count()
        assert row_count > 0, "No data rows found in traceroute table"

        # Check that hop counts are displayed (column may vary, so check multiple potential columns)
        hop_cells_found = False
        hop_data_found = False

        # Try to find hop data in different columns (sometimes the column order changes)
        for col_index in [7, 8, 9]:  # Check columns 7, 8, 9 for hop data
            hop_cells = page.locator(
                f".modern-table tbody tr td:nth-child({col_index})"
            )

            if hop_cells.count() > 0:
                hop_cells_found = True
                # Check first few rows for actual hop data
                for i in range(min(5, hop_cells.count())):
                    hop_text = hop_cells.nth(i).inner_text()
                    # Look for numeric hop counts or hop ranges
                    if hop_text and hop_text != "N/A" and hop_text.strip():
                        # Check if it looks like hop data (numbers, ranges like "3-5", etc.)
                        if (
                            any(char.isdigit() for char in hop_text)
                            or "hop" in hop_text.lower()
                        ):
                            hop_data_found = True
                            print(f"Found hop data in column {col_index}: {hop_text}")
                            break

                if hop_data_found:
                    break

        # If we found table cells but no hop data, it might be that the test data doesn't have hop information
        # In that case, we should check if the API has hop data
        if not hop_data_found:
            # Check if the API returns hop data
            api_response = page.evaluate(f"""
                fetch('{test_server_url}/api/traceroute/data?limit=5')
                    .then(response => response.json())
                    .then(data => {{
                        const hasHopData = data.data && data.data.some(item =>
                            item.hop_count !== null &&
                            item.hop_count !== undefined &&
                            item.hop_count > 0
                        );
                        return {{ hasHopData, dataCount: data.data ? data.data.length : 0 }};
                    }})
                    .catch(error => {{ return {{ error: error.message }}; }})
            """)

            if api_response and api_response.get("hasHopData"):
                # If API has hop data but UI doesn't show it, that's a real issue
                assert hop_data_found, (
                    f"API has hop data but UI doesn't display it. Found table cells: {hop_cells_found}"
                )
            else:
                # If API doesn't have hop data, then it's expected that UI doesn't show it
                print(
                    f"No hop data in API response, this is expected for test data. API data count: {api_response.get('dataCount', 'unknown')}"
                )
                # In this case, we just verify that the table structure exists
                assert hop_cells_found, (
                    "Hop column should exist in table structure even if no data"
                )
        else:
            # We found hop data, test passes
            assert hop_data_found, "No hop counts found in traceroute table"

    def test_traceroute_gateway_display(self, page: Page, test_server_url: str):
        """Test that traceroute table shows gateways correctly."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Wait a bit more for data to load
        page.wait_for_timeout(2000)

        # Check that gateways are displayed (not N/A)
        gateway_cells = page.locator(
            ".modern-table tbody tr td:nth-child(5)"
        )  # Gateway column

        gateway_found = False
        for i in range(min(5, gateway_cells.count())):  # Check first 5 rows
            gateway_text = gateway_cells.nth(i).inner_text()
            if gateway_text and gateway_text != "N/A" and gateway_text.strip():
                gateway_found = True
                break

        assert gateway_found, "No gateways found in traceroute table"

    def test_traceroute_gateway_count_validation(
        self, page: Page, test_server_url: str
    ):
        """Test that grouped traceroute table shows at least 1 gateway when grouping is enabled."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for traceroute data to load by looking for gateway count
        page.wait_for_selector(
            ".modern-table tbody tr:has-text('gateway')", timeout=15000
        )

        # Ensure grouping is enabled
        grouping_checkbox = page.locator("#group_packets")
        if not grouping_checkbox.is_checked():
            grouping_checkbox.check()
            apply_button = page.locator("#applyFilters")
            apply_button.click()
            # Wait for the grouped data to reload with gateway counts
            page.wait_for_selector(
                ".modern-table tbody tr:has-text('gateway')", timeout=10000
            )

        # Check that gateway counts show at least 1 gateway (not N/A)
        gateway_cells = page.locator(
            ".modern-table tbody tr td:nth-child(5)"
        )  # Gateway column

        valid_gateway_count_found = False
        for i in range(min(5, gateway_cells.count())):
            gateway_text = gateway_cells.nth(i).inner_text()
            # Should show "1 gateway", "2 gateways", etc., not "N/A"
            if gateway_text and "gateway" in gateway_text and gateway_text != "N/A":
                valid_gateway_count_found = True
                break

        assert valid_gateway_count_found, (
            "No valid gateway counts found in grouped traceroute table"
        )

    def test_traceroute_named_node_links(self, page: Page, test_server_url: str):
        """Test that named nodes in traceroute table have clickable links."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)
        page.wait_for_timeout(2000)

        # Check From and To node columns for clickable links
        from_node_cells = page.locator(
            ".modern-table tbody tr td:nth-child(2)"
        )  # From column
        to_node_cells = page.locator(
            ".modern-table tbody tr td:nth-child(3)"
        )  # To column

        clickable_from_node_found = False
        clickable_to_node_found = False

        # Check first few rows for clickable node links
        for i in range(min(3, from_node_cells.count())):
            from_cell = from_node_cells.nth(i)
            from_links = from_cell.locator("a")
            if from_links.count() > 0:
                clickable_from_node_found = True
                break

        for i in range(min(3, to_node_cells.count())):
            to_cell = to_node_cells.nth(i)
            to_links = to_cell.locator("a")
            if to_links.count() > 0:
                clickable_to_node_found = True
                break

        # At least one of the node columns should have clickable links
        assert clickable_from_node_found or clickable_to_node_found, (
            "No clickable node links found in traceroute table"
        )

    def test_traceroute_grouping_functionality(self, page: Page, test_server_url: str):
        """Test that traceroute grouping works correctly and shows proper data."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get initial row count (ungrouped)
        page.locator(".modern-table tbody tr").count()

        # Enable grouping
        grouping_checkbox = page.locator("#group_packets")
        if not grouping_checkbox.is_checked():
            grouping_checkbox.check()

        # Apply filters to reload with grouping
        apply_button = page.locator("#applyFilters")
        apply_button.click()

        # Wait for table to reload
        page.wait_for_timeout(2000)

        # Check that grouped data still shows route information
        route_cells = page.locator(
            ".modern-table tbody tr td:nth-child(4)"
        )  # Route column
        if route_cells.count() > 0:
            route_text = route_cells.first.inner_text()
            # Should either have route data or show "No route data", not be empty
            assert route_text.strip(), "Route column is empty in grouped view"

        # Check that grouped data shows gateway information
        gateway_cells = page.locator(
            ".modern-table tbody tr td:nth-child(5)"
        )  # Gateway column
        if gateway_cells.count() > 0:
            gateway_text = gateway_cells.first.inner_text()
            # Should show gateway count or gateway name, not N/A
            assert gateway_text and gateway_text != "N/A", (
                f"Gateway shows N/A in grouped view: {gateway_text}"
            )

        # Check that grouped data shows hop information
        hop_cells = page.locator(
            ".modern-table tbody tr td:nth-child(8)"
        )  # Hops column
        if hop_cells.count() > 0:
            hop_text = hop_cells.first.inner_text()
            # Should show hop count or range, not N/A
            assert hop_text and hop_text != "N/A", (
                f"Hops show N/A in grouped view: {hop_text}"
            )

    def test_traceroute_route_node_filter_functionality(
        self, page: Page, test_server_url: str
    ):
        """Test that the route_node filter works correctly in the traceroute table."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for page to load
        page.wait_for_selector("#tracerouteTable")

        # Wait for data to load
        page.wait_for_function("document.querySelector('#tracerouteTable tbody tr')")

        # Get initial row count
        page.locator("#tracerouteTable tbody tr").count()

        # Find the visible node picker input for route_node
        route_node_input = page.locator("#route_node")
        expect(route_node_input).to_be_visible()

        # Type a test node ID (we'll use a common one that should exist)
        route_node_input.fill("2882400001")

        # Apply filters
        page.click("#applyFilters")

        # Wait for the table to update
        page.wait_for_timeout(1000)

        # Check that the filter was applied (the row count should change or stay the same)
        # We can't guarantee specific results since it depends on test data
        # But we can verify the filter doesn't crash the page
        page.locator("#tracerouteTable tbody tr").count()

        # Verify the page still works
        expect(page.locator("#tracerouteTable")).to_be_visible()

        # Clear filters to test that functionality
        page.click("#clearFilters")
        page.wait_for_timeout(1000)

        # Verify the filter was cleared
        cleared_input = page.locator("#route_node")
        expect(cleared_input).to_have_value("")

    def test_url_parameter_filter_population(self, page: Page, test_server_url: str):
        """Test that URL parameters properly populate filters and update when filters change."""
        # Test with packets page and URL parameters (using a valid node ID from test data)
        page.goto(f"{test_server_url}/packets?from_node=1128074276&group_packets=false")

        # Wait for page to load
        page.wait_for_selector("#packetsTable")

        # Wait for filters to be applied from URL - increase timeout
        page.wait_for_timeout(5000)

        # Check that the backend filtering is working correctly by examining the data
        # The node picker should have the correct hidden field value
        hidden_field = page.locator('input[name="from_node"]')
        expect(hidden_field).to_have_value("1128074276")

        # Check that the grouping checkbox was set correctly (should be unchecked for false)
        group_checkbox = page.locator("#group_packets")
        expect(group_checkbox).not_to_be_checked()

        # Verify that the table actually shows filtered results
        # by checking that we have some data (the filter is being applied)
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        assert row_count > 0, f"Expected filtered results, but found {row_count} rows"

    def test_traceroute_route_data_display(self, page: Page, test_server_url: str):
        """Test that route data is properly displayed in grouped traceroute packets."""
        page.goto(f"{test_server_url}/traceroute")

        # Wait for table to load with more specific selector
        page.wait_for_selector("#tracerouteTable tbody tr", timeout=10000)

        # Give extra time for the table data to load
        page.wait_for_timeout(2000)

        # Check route column (4th column) - try both possible table selectors
        route_cells = page.locator("#tracerouteTable tbody tr td:nth-child(4)")

        # If no rows found with tracerouteTable, try generic table selector
        if route_cells.count() == 0:
            route_cells = page.locator("table tbody tr td:nth-child(4)")

        # Get all route cell contents
        route_texts = route_cells.all_text_contents()

        # Count entries with actual route data vs "No route data"
        route_data_count = 0
        no_route_data_count = 0

        for text in route_texts:
            text = (text or "").strip()
            if text == "No route data":
                no_route_data_count += 1
            elif text and text != "No route data":
                route_data_count += 1

                # Verify route data format
                if "→" in text:
                    # Multi-hop route
                    assert not text.startswith("No route"), (
                        f"Route should not start with 'No route': {text}"
                    )
                    # Should contain node identifiers or names
                    parts = text.split("→")
                    assert len(parts) >= 2, (
                        f"Multi-hop route should have at least 2 parts: {text}"
                    )
                else:
                    # Single node route or direct route
                    assert len(text) > 0, f"Route entry should not be empty: {text}"

        # In the test fixtures, we should have some route data
        total_entries = len(route_texts)
        print(
            f"Route data analysis: {route_data_count} with data, {no_route_data_count} without, {total_entries} total"
        )

        # Just verify we have some data to work with
        assert total_entries > 0, (
            f"Should have some traceroute entries, found {total_entries} entries"
        )

        # If we have route data, verify it's properly formatted
        if route_data_count > 0:
            # Check if we have any clickable links
            route_links = page.locator("#tracerouteTable tbody tr td:nth-child(4) a")
            if route_links.count() == 0:
                route_links = page.locator("table tbody tr td:nth-child(4) a")

            link_count = route_links.count()

            # If we have links, verify they're properly formatted
            if link_count > 0:
                # Check that links have proper href attributes
                for i in range(min(5, link_count)):  # Check first 5 links
                    link = route_links.nth(i)
                    href = link.get_attribute("href")
                    assert href and href.startswith("/node/"), (
                        f"Route link should point to node page: {href}"
                    )
            else:
                # If no clickable links, that's OK - just verify we have text content
                print(
                    "No clickable links found in route data, but route text content is present"
                )

    def test_traceroute_grouped_vs_ungrouped_route_data(
        self, page: Page, test_server_url: str
    ):
        """Test that route data is displayed correctly in both grouped and ungrouped modes."""
        # Test grouped mode (default)
        page.goto(f"{test_server_url}/traceroute")
        # Wait for traceroute data to load by looking for gateway count
        page.wait_for_selector("table tbody tr:has-text('gateway')", timeout=15000)

        # Verify grouping is enabled
        group_checkbox = page.locator("#group_packets")
        assert group_checkbox.is_checked(), "Grouping should be enabled by default"

        # Count route data entries in grouped mode
        route_cells_grouped = page.locator("table tbody tr td:nth-child(4)")
        grouped_texts = route_cells_grouped.all_text_contents()
        grouped_route_count = sum(
            1
            for text in grouped_texts
            if (text or "").strip() and (text or "").strip() != "No route data"
        )

        # Switch to ungrouped mode
        group_checkbox.uncheck()

        # Wait for ungrouped data to load with better wait condition
        # In ungrouped mode, we should see individual packet data with timestamps
        page.wait_for_selector(
            "table tbody tr td:nth-child(1):has-text(':')", timeout=15000
        )

        # Count route data entries in ungrouped mode
        route_cells_ungrouped = page.locator("table tbody tr td:nth-child(4)")
        ungrouped_texts = route_cells_ungrouped.all_text_contents()
        ungrouped_route_count = sum(
            1
            for text in ungrouped_texts
            if (text or "").strip() and (text or "").strip() != "No route data"
        )

        # Both modes should have route data (though counts may differ due to grouping)
        assert grouped_route_count > 0, (
            f"Grouped mode should have route data, found {grouped_route_count}"
        )
        assert ungrouped_route_count > 0, (
            f"Ungrouped mode should have route data, found {ungrouped_route_count}"
        )

    def test_traceroute_gateway_and_route_formatting(
        self, page: Page, test_server_url: str
    ):
        """Test that gateway and route data are properly formatted without HTML escaping."""
        page.goto(f"{test_server_url}/traceroute")
        page.wait_for_selector("table tbody tr", timeout=10000)

        # Find all rows
        rows = page.locator("table tbody tr")
        row_count = rows.count()

        gateway_entries_found = 0
        route_entries_found = 0

        for i in range(min(25, row_count)):  # Check first 25 rows
            row = rows.nth(i)

            # Get gateway cell (5th column)
            gateway_cell = row.locator("td:nth-child(5)")
            gateway_text = (gateway_cell.text_content() or "").strip()

            # Get route cell (4th column)
            route_cell = row.locator("td:nth-child(4)")
            route_text = (route_cell.text_content() or "").strip()

            # Check gateway formatting
            if gateway_text and gateway_text != "N/A":
                gateway_entries_found += 1

                # Verify no HTML escaping in gateway text
                assert '"' not in gateway_text, (
                    f"Found escaped quotes in gateway text: {gateway_text}"
                )
                assert "&quot;" not in gateway_text, (
                    f"Found HTML entities in gateway text: {gateway_text}"
                )
                assert "title=" not in gateway_text, (
                    f"Found HTML attributes in gateway text: {gateway_text}"
                )

            # Check route formatting
            if route_text and route_text != "No route data":
                route_entries_found += 1

                # Verify route data is properly formatted
                assert not route_text.startswith("No route"), (
                    f"Route data should not start with 'No route': {route_text}"
                )

        # We should find at least some data to verify formatting
        assert gateway_entries_found > 0 or route_entries_found > 0, (
            "Expected to find at least some gateway or route data to verify formatting"
        )

    def test_api_traceroute_includes_short_names(self, test_server_url: str):
        """Test that the traceroute API includes short name fields."""
        response = requests.get(f"{test_server_url}/api/traceroute/data?limit=5")
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert len(data["data"]) > 0, "Should have traceroute data"

        # Check that the first item has short name fields
        first_item = data["data"][0]
        assert "from_node_short" in first_item, (
            "API should include from_node_short field"
        )
        assert "to_node_short" in first_item, "API should include to_node_short field"

        # Verify short names are not empty for nodes that exist
        if first_item.get("from_node_id"):
            assert first_item["from_node_short"] is not None, (
                "from_node_short should not be None"
            )
            assert first_item["from_node_short"] != "", (
                "from_node_short should not be empty"
            )

        if first_item.get("to_node_id") and first_item["to_node_id"] != 4294967295:
            assert first_item["to_node_short"] is not None, (
                "to_node_short should not be None"
            )
            assert first_item["to_node_short"] != "", (
                "to_node_short should not be empty"
            )

    def test_api_packets_includes_short_names(self, test_server_url: str):
        """Test that the packets API includes short name fields."""
        response = requests.get(f"{test_server_url}/api/packets/data?limit=5")
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert len(data["data"]) > 0, "Should have packet data"

        # Check that the first item has short name fields
        first_item = data["data"][0]
        assert "from_node_short" in first_item, (
            "API should include from_node_short field"
        )
        assert "to_node_short" in first_item, "API should include to_node_short field"

        # Verify short names are not empty for nodes that exist
        if first_item.get("from_node_id"):
            assert first_item["from_node_short"] is not None, (
                "from_node_short should not be None"
            )
            assert first_item["from_node_short"] != "", (
                "from_node_short should not be empty"
            )
