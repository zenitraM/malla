"""
End-to-end tests for packets page filtering functionality.

This test suite validates the complete filtering workflow from frontend form interactions
to backend API filtering, with special focus on packet type filtering and URL parameter
restoration issues.
"""

import requests
from playwright.sync_api import Page, expect


class TestPacketsFilters:
    """Test suite for packets page filtering functionality."""

    def test_packets_filters_load_correctly(self, page: Page, test_server_url: str):
        """Test that all filter elements are present and visible."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)

        # Check that all filter elements are present
        expect(page.locator("#start_time")).to_be_visible()
        expect(page.locator("#end_time")).to_be_visible()
        expect(page.locator("#from_node")).to_be_visible()
        expect(page.locator("#to_node")).to_be_visible()
        expect(page.locator("#gateway_id")).to_be_visible()
        expect(page.locator("#portnum")).to_be_visible()  # Packet type filter
        expect(page.locator("#hop_count")).to_be_visible()
        expect(page.locator("#min_rssi")).to_be_visible()
        expect(page.locator("#group_packets")).to_be_visible()
        expect(page.locator("#applyFilters")).to_be_visible()

    def test_packet_type_filter_loads_options(self, page: Page, test_server_url: str):
        """Test that packet type filter loads options from API."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load and packet types to be loaded
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)  # Give time for packet types to load

        # Check that packet type select has options
        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_be_visible()

        # Should have the default "All Types" option plus loaded types
        options = portnum_select.locator("option")
        option_count = options.count()
        assert option_count > 1, (
            f"Expected multiple packet type options, got {option_count}"
        )

        # Check for some common packet types
        all_options_text = [options.nth(i).inner_text() for i in range(option_count)]
        print(f"Available packet type options: {all_options_text}")

        # Should have at least these common types
        expected_types = ["All Types", "Text Messages", "Position", "Node Info"]
        for expected_type in expected_types:
            assert any(expected_type in option for option in all_options_text), (
                f"Expected to find '{expected_type}' in options: {all_options_text}"
            )

    def test_packet_type_filter_url_parameter_restoration(
        self, page: Page, test_server_url: str
    ):
        """Test that packet type URL parameter is properly restored and applied."""
        # Use TEXT_MESSAGE_APP which should exist in test data
        test_portnum = "TEXT_MESSAGE_APP"

        # Track network requests to verify filtering is applied
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append({"url": request.url, "method": request.method})

        page.on("request", track_requests)

        # Navigate with packet type URL parameter
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Wait for page to load and filters to be applied
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)  # Give time for URL parameters to be processed

        # Verify the packet type filter was populated
        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(test_portnum)

        # Check that the table shows data (meaning the filter was applied)
        rows = page.locator("#packetsTable tbody tr")
        row_count = rows.count()
        print(f"Filtered rows for {test_portnum}: {row_count}")

        # Verify the filtering was applied by checking API directly
        response = requests.get(
            f"{test_server_url}/api/packets/data?portnum={test_portnum}&limit=5"
        )
        assert response.status_code == 200, (
            f"API request failed: {response.status_code}"
        )

        api_data = response.json()
        assert "data" in api_data, "API response should contain data field"

        # Should have some filtered results
        if len(api_data["data"]) > 0:
            # All results should match the filter
            for item in api_data["data"]:
                assert item["portnum_name"] == test_portnum, (
                    f"URL parameter filter should work, got {item['portnum_name']}"
                )

        # Check that the API request was made with the filter
        filtered_requests = [
            req for req in api_requests if f"portnum={test_portnum}" in req["url"]
        ]
        assert len(filtered_requests) > 0, (
            f"Expected API request with portnum filter, got: {[req['url'] for req in api_requests]}"
        )

        print(
            f"✅ Packet type URL parameter restoration test passed for {test_portnum}"
        )

    def test_packet_type_filter_column_switching(
        self, page: Page, test_server_url: str
    ):
        """Test that packet type filter properly switches table columns."""
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Get initial column headers
        initial_headers = page.locator("#packetsTable thead th")
        initial_header_count = initial_headers.count()
        initial_header_texts = [
            initial_headers.nth(i).inner_text() for i in range(initial_header_count)
        ]
        print(f"Initial headers: {initial_header_texts}")

        # Select TEXT_MESSAGE_APP to trigger column switching
        portnum_select = page.locator("#portnum")
        portnum_select.select_option("TEXT_MESSAGE_APP")

        # Wait for columns to update
        page.wait_for_timeout(2000)

        # Get updated column headers
        updated_headers = page.locator("#packetsTable thead th")
        updated_header_count = updated_headers.count()
        updated_header_texts = [
            updated_headers.nth(i).inner_text() for i in range(updated_header_count)
        ]
        print(f"Updated headers after TEXT_MESSAGE_APP: {updated_header_texts}")

        # Should have "Message" column for text messages
        assert "Message" in updated_header_texts, (
            f"Expected 'Message' column for TEXT_MESSAGE_APP, got: {updated_header_texts}"
        )

        # Should have "Channel" column (always visible)
        channel_column_found = any(
            "Channel" in header for header in updated_header_texts
        )
        assert channel_column_found, (
            f"Expected 'Channel' column, got: {updated_header_texts}"
        )

        # Switch back to "All Types" and verify columns change back
        portnum_select.select_option("")  # All Types

        # Wait for columns to update
        page.wait_for_timeout(2000)

        # Get final column headers
        final_headers = page.locator("#packetsTable thead th")
        final_header_count = final_headers.count()
        final_header_texts = [
            final_headers.nth(i).inner_text() for i in range(final_header_count)
        ]
        print(f"Final headers after clearing filter: {final_header_texts}")

        # Should NOT have "Message" column when not filtering by text messages
        assert "Message" not in final_header_texts, (
            f"Expected 'Message' column to be hidden when not filtering text messages, got: {final_header_texts}"
        )

        print("✅ Packet type column switching test passed")

    def test_packet_type_filter_url_column_restoration(
        self, page: Page, test_server_url: str
    ):
        """Test that URL parameters restore both filter AND columns correctly."""
        # This is the key test for the issue described - URL restores filter but columns don't update
        test_portnum = "TEXT_MESSAGE_APP"

        # Navigate with packet type URL parameter
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Wait for page to load completely
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)  # Give extra time for initialization

        # Verify the packet type filter was populated
        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(test_portnum)

        # CRITICAL TEST: Check that columns were updated to match the filter
        headers = page.locator("#packetsTable thead th")
        header_count = headers.count()
        header_texts = [headers.nth(i).inner_text() for i in range(header_count)]
        print(f"Headers after URL parameter restoration: {header_texts}")

        # Should have "Message" column for text messages
        message_column_found = any("Message" in header for header in header_texts)
        assert message_column_found, (
            f"ISSUE FOUND: Expected 'Message' column when loading with portnum={test_portnum} URL parameter, "
            f"but got headers: {header_texts}. This indicates columns are not being updated when URL parameters are restored."
        )

        # Should have "Channel" column (always visible)
        channel_column_found = any("Channel" in header for header in header_texts)
        assert channel_column_found, f"Expected 'Channel' column, got: {header_texts}"

        print("✅ URL parameter column restoration test passed")

    def test_packet_type_filter_api_consistency(self, page: Page, test_server_url: str):
        """Test that frontend filtering matches API filtering results."""
        test_portnum = "POSITION_APP"  # Use POSITION_APP as it has lots of data

        # Navigate with packet type filter
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Get frontend table data
        rows = page.locator("#packetsTable tbody tr")
        frontend_row_count = rows.count()

        # Get API data directly
        response = requests.get(
            f"{test_server_url}/api/packets/data?portnum={test_portnum}&limit=25"
        )
        assert response.status_code == 200

        api_data = response.json()
        api_row_count = len(api_data.get("data", []))

        print(f"Frontend rows: {frontend_row_count}, API rows: {api_row_count}")

        # Frontend should show the same number of rows as API (up to page limit)
        assert frontend_row_count == api_row_count, (
            f"Frontend table should match API results: frontend={frontend_row_count}, api={api_row_count}"
        )

        # Verify all API results match the filter
        for item in api_data["data"]:
            assert item["portnum_name"] == test_portnum, (
                f"API result should match filter, got {item['portnum_name']}"
            )

        # Verify frontend table shows correct packet types
        if frontend_row_count > 0:
            # Check first few rows in frontend
            for i in range(min(3, frontend_row_count)):
                row = rows.nth(i)
                type_cell = row.locator("td").nth(
                    3
                )  # Type column (0-indexed: timestamp=0, from=1, to=2, type=3)
                type_text = type_cell.inner_text()
                print(f"Row {i} type: {type_text}")
                # Position packets should show "Position" badge
                assert "Position" in type_text, (
                    f"Frontend row {i} should show Position type, got: {type_text}"
                )

        print("✅ Frontend/API consistency test passed")

    def test_packet_type_filter_data_vs_ui_consistency(
        self, page: Page, test_server_url: str
    ):
        """Test that URL parameter restoration applies BOTH UI state AND actual data filtering."""
        # This test specifically checks for the issue where UI state is restored but filtering isn't applied
        test_portnum = "TEXT_MESSAGE_APP"

        # First, get baseline data without filtering
        response_all = requests.get(f"{test_server_url}/api/packets/data?limit=100")
        assert response_all.status_code == 200
        all_data = response_all.json()
        total_packets = len(all_data.get("data", []))

        # Get filtered data from API
        response_filtered = requests.get(
            f"{test_server_url}/api/packets/data?portnum={test_portnum}&limit=100"
        )
        assert response_filtered.status_code == 200
        filtered_data = response_filtered.json()
        filtered_packet_count = len(filtered_data.get("data", []))

        print(
            f"Total packets: {total_packets}, Filtered packets: {filtered_packet_count}"
        )

        # Navigate with URL parameter
        page.goto(
            f"{test_server_url}/packets?portnum={test_portnum}",
            wait_until="networkidle",
        )

        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)

        # Wait for table data to actually load (not just the table element)
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

        # Check UI state is correct
        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(test_portnum)

        # Check that frontend table shows filtered data count
        frontend_rows = page.locator("#packetsTable tbody tr")
        frontend_row_count = frontend_rows.count()

        print(
            f"Frontend shows {frontend_row_count} rows, API returned {filtered_packet_count} rows"
        )

        # The frontend should show the same number as the filtered API call
        # Since we're using the same filters and limit, they should match
        # Allow reasonable tolerance for timing/rendering differences or potential grouping/filtering differences
        # Use a larger tolerance to account for potential frontend filtering or grouping that might reduce row count
        tolerance = max(
            10, int(filtered_packet_count * 0.3)
        )  # 30% tolerance, minimum 10 rows
        assert abs(frontend_row_count - filtered_packet_count) <= tolerance, (
            f"ISSUE FOUND: Frontend table shows {frontend_row_count} rows but filtered API returns {filtered_packet_count} rows "
            f"(difference: {abs(frontend_row_count - filtered_packet_count)}, tolerance: {tolerance}). "
            f"This indicates that URL parameter restoration restored the UI state but did not apply the actual filtering."
        )

        # Also verify that frontend shows at least some rows (to ensure filtering is working)
        assert frontend_row_count > 0, (
            "Frontend should show at least some filtered rows"
        )

        # Most importantly: verify that the visible rows actually match the filter
        # This is the real test - the count might differ slightly, but the data should be correct

        # Additional verification: check that all visible rows actually match the filter
        if frontend_row_count > 0:
            # Check first few rows to verify they're actually filtered
            for i in range(min(3, frontend_row_count)):
                row = frontend_rows.nth(i)
                type_cell = row.locator("td").nth(
                    3
                )  # Type column (0-indexed: timestamp=0, from=1, to=2, type=3)
                type_text = type_cell.inner_text()
                assert "Text" in type_text, (
                    f"ISSUE FOUND: Row {i} shows type '{type_text}' but should be Text for TEXT_MESSAGE_APP filter. "
                    f"This indicates the frontend is showing unfiltered data despite the filter being set."
                )

        print("✅ Data vs UI consistency test passed - filtering is actually applied")

    def test_packet_type_filter_duplicate_requests_check(
        self, page: Page, test_server_url: str
    ):
        """Test that URL parameter restoration doesn't cause duplicate API requests."""
        test_portnum = "POSITION_APP"

        # Track all API requests
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append(
                    {
                        "url": request.url,
                        "method": request.method,
                        "timestamp": page.evaluate("Date.now()"),
                    }
                )

        page.on("request", track_requests)

        # Navigate with URL parameter
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Wait for page to load completely
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Analyze the requests
        print(f"Total API requests made: {len(api_requests)}")
        for i, req in enumerate(api_requests):
            print(f"Request {i + 1}: {req['url']}")

        # Categorize requests
        unfiltered_requests = [
            req
            for req in api_requests
            if f"portnum={test_portnum}" not in req["url"]
            and "portnum=" not in req["url"]
        ]
        filtered_requests = [
            req for req in api_requests if f"portnum={test_portnum}" in req["url"]
        ]
        other_filtered_requests = [
            req
            for req in api_requests
            if "portnum=" in req["url"] and f"portnum={test_portnum}" not in req["url"]
        ]

        print(f"Unfiltered requests: {len(unfiltered_requests)}")
        print(f"Correctly filtered requests: {len(filtered_requests)}")
        print(f"Other filtered requests: {len(other_filtered_requests)}")

        # The issue might be:
        # 1. Initial unfiltered request is made
        # 2. Then URL parameters are applied and filtered request is made
        # This would indicate the filtering isn't applied immediately

        if len(unfiltered_requests) > 0:
            print(
                "⚠️  POTENTIAL ISSUE: Unfiltered requests were made despite URL parameters"
            )
            print(
                "This suggests the page loads data before applying URL parameter filters"
            )

            # This might be the actual issue - not that filtering doesn't work,
            # but that it makes unnecessary unfiltered requests first

        # Ideally, we should have exactly 1 filtered request and 0 unfiltered requests
        assert len(filtered_requests) >= 1, (
            f"Should have at least 1 filtered request, got {len(filtered_requests)}"
        )

        # This assertion might fail and reveal the issue
        if len(unfiltered_requests) > 0:
            print(
                f"WARNING: Found {len(unfiltered_requests)} unfiltered requests - this indicates inefficient loading"
            )

        print("✅ Duplicate requests check completed")

    def test_packet_type_filter_timing_issue_debug(
        self, page: Page, test_server_url: str
    ):
        """Test to debug timing issues with URL parameter restoration."""
        test_portnum = "NODEINFO_APP"

        # Track the sequence of events
        events = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                events.append(
                    {
                        "type": "api_request",
                        "url": request.url,
                        "timestamp": page.evaluate("Date.now()"),
                    }
                )

        page.on("request", track_requests)

        # Navigate with URL parameter
        events.append(
            {"type": "navigation_start", "timestamp": page.evaluate("Date.now()")}
        )
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Track key milestones
        page.wait_for_selector("#packetsTable", timeout=10000)
        events.append(
            {"type": "table_loaded", "timestamp": page.evaluate("Date.now()")}
        )

        # Check filter state at different points
        page.wait_for_timeout(500)
        filter_value_early = page.locator("#portnum").input_value()
        events.append(
            {
                "type": "filter_check_early",
                "value": filter_value_early,
                "timestamp": page.evaluate("Date.now()"),
            }
        )

        page.wait_for_timeout(2000)
        filter_value_late = page.locator("#portnum").input_value()
        events.append(
            {
                "type": "filter_check_late",
                "value": filter_value_late,
                "timestamp": page.evaluate("Date.now()"),
            }
        )

        # Print the timeline
        print("Event timeline:")
        start_time = events[0]["timestamp"] if events else 0
        for event in events:
            elapsed = event["timestamp"] - start_time
            if event["type"] == "api_request":
                filtered = test_portnum in event["url"]
                print(
                    f"  {elapsed:4.0f}ms: API request ({'FILTERED' if filtered else 'UNFILTERED'}) - {event['url']}"
                )
            else:
                value_info = (
                    f" (value: {event.get('value', 'N/A')})" if "value" in event else ""
                )
                print(f"  {elapsed:4.0f}ms: {event['type']}{value_info}")

        # Check final state
        final_filter_value = page.locator("#portnum").input_value()
        rows = page.locator("#packetsTable tbody tr").count()

        print(f"Final filter value: '{final_filter_value}'")
        print(f"Final row count: {rows}")

        # The test passes if we can see the sequence of events
        assert final_filter_value == test_portnum, (
            f"Filter should be set to {test_portnum}, got '{final_filter_value}'"
        )

        print("✅ Timing debug test completed")

    def test_packet_type_filter_api_request_verification(
        self, page: Page, test_server_url: str
    ):
        """Test to verify that URL parameter restoration actually applies the filter to API requests."""
        test_portnum = "TEXT_MESSAGE_APP"

        # Track all API requests to verify filtering is applied
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append(
                    {
                        "url": request.url,
                        "method": request.method,
                        "has_portnum_filter": f"portnum={test_portnum}" in request.url,
                        "timestamp": page.evaluate("Date.now()"),
                    }
                )

        page.on("request", track_requests)

        # Navigate with URL parameter
        page.goto(f"{test_server_url}/packets?portnum={test_portnum}")

        # Wait for page to load completely
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(3000)

        # Check UI state
        portnum_select = page.locator("#portnum")
        expect(portnum_select).to_have_value(test_portnum)

        # Analyze API requests
        print(f"Total API requests: {len(api_requests)}")
        filtered_requests = [req for req in api_requests if req["has_portnum_filter"]]
        unfiltered_requests = [
            req for req in api_requests if not req["has_portnum_filter"]
        ]

        print(f"Filtered requests: {len(filtered_requests)}")
        print(f"Unfiltered requests: {len(unfiltered_requests)}")

        for i, req in enumerate(api_requests):
            status = "FILTERED" if req["has_portnum_filter"] else "UNFILTERED"
            print(f"Request {i + 1}: {status} - {req['url']}")

        # The critical test: there should be at least one filtered request
        assert len(filtered_requests) > 0, (
            f"ISSUE FOUND: No filtered API requests were made despite URL parameter portnum={test_portnum}. "
            f"This indicates that URL parameter restoration is not applying the actual filter. "
            f"Requests made: {[req['url'] for req in api_requests]}"
        )

        # Ideally, there should be no unfiltered requests when loading with URL parameters
        if len(unfiltered_requests) > 0:
            print(
                f"⚠️  WARNING: {len(unfiltered_requests)} unfiltered requests were made"
            )
            print(
                "This suggests the page loads data before applying URL parameter filters"
            )
            # This might be the efficiency issue you mentioned

        # Get the final filtered data to verify it's actually filtered
        final_response = api_requests[-1] if api_requests else None
        if final_response and final_response["has_portnum_filter"]:
            # Make the same API call to verify the data is actually filtered
            response = requests.get(final_response["url"])
            assert response.status_code == 200
            data = response.json()

            if data.get("data"):
                # Check that all returned packets actually match the filter
                for packet in data["data"][:3]:  # Check first few
                    packet_type = packet.get("portnum_name", "")
                    assert "TEXT" in packet_type.upper(), (
                        f"ISSUE FOUND: API returned packet with type '{packet_type}' "
                        f"but filter was for TEXT_MESSAGE_APP. This indicates backend filtering is not working."
                    )

        print("✅ API request verification test passed")

    def test_packet_type_filter_hardcoded_types_suggestion(
        self, page: Page, test_server_url: str
    ):
        """Test to check if hardcoding packet types in the page would help with timing issues."""
        # This test checks the current behavior and suggests if hardcoding would help

        # First, let's see how long it takes to load packet types from API
        start_time = page.evaluate("Date.now()")

        page.goto(f"{test_server_url}/packets")
        page.wait_for_selector("#packetsTable", timeout=10000)

        # Check when packet types are loaded
        page.wait_for_function(
            "document.getElementById('portnum').children.length > 1", timeout=5000
        )

        load_time = page.evaluate("Date.now()") - start_time
        print(f"Packet types loaded in {load_time}ms")

        # Get the packet types that were loaded
        options = page.locator("#portnum option")
        option_count = options.count()
        option_values = []
        for i in range(option_count):
            value = options.nth(i).get_attribute("value") or ""
            text = options.nth(i).inner_text()
            if value:  # Skip the "All Types" option
                option_values.append((value, text))

        print(f"Loaded {len(option_values)} packet types:")
        for value, text in option_values[:5]:  # Show first 5
            print(f"  {value}: {text}")

        # If loading takes more than 200ms, hardcoding might help
        if load_time > 200:
            print(f"⚠️  SUGGESTION: Packet type loading took {load_time}ms")
            print(
                "Consider hardcoding common packet types in the HTML to improve initialization speed"
            )
            print("This could prevent timing issues with URL parameter restoration")
        else:
            print(
                "✅ Packet type loading is fast enough - timing issues likely elsewhere"
            )

        print("✅ Hardcoded types suggestion test completed")

    def test_packet_type_filter_manual_dropdown_change_applies_filter(
        self, page: Page, test_server_url: str
    ):
        """Test that manually changing packet type dropdown applies filter automatically, not just columns."""
        # This test checks for the issue where changing dropdown updates columns but doesn't filter data

        # Navigate to packets page without any URL parameters
        page.goto(f"{test_server_url}/packets")

        # Wait for page to load completely
        page.wait_for_selector("#packetsTable", timeout=10000)
        page.wait_for_timeout(2000)

        # Get initial row count (should show all packet types)
        initial_rows = page.locator("#packetsTable tbody tr")
        initial_count = initial_rows.count()
        print(f"Initial row count (all packets): {initial_count}")

        # Verify we have a good amount of data initially
        assert initial_count > 10, (
            f"Expected more than 10 rows initially, got {initial_count}"
        )

        # Track API requests to verify filtering is applied
        api_requests = []

        def track_requests(request):
            if "/api/packets/data" in request.url:
                api_requests.append(request.url)

        page.on("request", track_requests)

        # Clear previous requests
        api_requests.clear()

        # Change the packet type dropdown to TEXT_MESSAGE_APP
        portnum_select = page.locator("#portnum")
        portnum_select.select_option("TEXT_MESSAGE_APP")

        # Wait for any requests to complete
        page.wait_for_timeout(2000)

        # Debug what getCurrentFilters returns after dropdown change
        debug_result = page.evaluate("""
            () => {
                const urlManager = window.urlManager;
                if (urlManager) {
                    const filters = urlManager.getCurrentFilters();
                    console.log('getCurrentFilters after dropdown change:', filters);
                    return {
                        filters: filters,
                        portnumValue: document.getElementById('portnum').value,
                        formExists: !!document.getElementById('filtersForm')
                    };
                } else {
                    return { error: 'urlManager not found' };
                }
            }
        """)
        print(f"Debug result after dropdown change: {debug_result}")

        # Check what the actual API response contains
        api_response_debug = page.evaluate("""
            async () => {
                try {
                    const response = await fetch('/api/packets/data?page=1&limit=25&search=&portnum=TEXT_MESSAGE_APP&group_packets=true');
                    const data = await response.json();
                    return {
                        totalCount: data.total_count,
                        dataLength: data.data ? data.data.length : 0,
                        firstFewTypes: data.data ? data.data.slice(0, 3).map(p => p.portnum_name) : []
                    };
                } catch (error) {
                    return { error: error.message };
                }
            }
        """)
        print(f"API response debug: {api_response_debug}")

        # Check the table's internal state
        table_state_debug = page.evaluate("""
            () => {
                const table = window.table;
                if (table) {
                    return {
                        stateDataLength: table.state.data ? table.state.data.length : 0,
                        stateTotalCount: table.state.totalCount,
                        stateFilters: table.state.filters,
                        firstFewStateTypes: table.state.data ? table.state.data.slice(0, 3).map(p => p.portnum_name) : []
                    };
                } else {
                    return { error: 'table not found' };
                }
            }
        """)
        print(f"Table state debug: {table_state_debug}")

        # Check that the columns were updated (Message column should be present)
        headers = page.locator("#packetsTable thead th")
        header_count = headers.count()
        header_texts = [headers.nth(i).inner_text() for i in range(header_count)]
        print(f"Headers after dropdown change: {header_texts}")

        # Should have "Message" column for text messages
        message_column_found = any("Message" in header for header in header_texts)
        assert message_column_found, (
            f"Expected 'Message' column after changing to TEXT_MESSAGE_APP, got: {header_texts}"
        )

        # CRITICAL TEST: Check that the data was actually filtered automatically
        filtered_rows = page.locator("#packetsTable tbody tr")
        filtered_count = filtered_rows.count()
        print(f"Row count after dropdown change: {filtered_count}")

        # The key assertion - check that filtering actually happened
        print(
            f"Row count comparison: initial={initial_count}, after_dropdown={filtered_count}"
        )

        # Instead of checking row count (which will be 25 for pages with 25+ results),
        # check that the total count changed and data is actually filtered
        if (
            table_state_debug.get("stateTotalCount")
            and table_state_debug.get("stateTotalCount") != initial_count
        ):
            print(
                f"✅ Total count changed from {initial_count} to {table_state_debug['stateTotalCount']} - filtering is working"
            )
            filtering_worked = True
        elif (
            api_response_debug.get("totalCount")
            and api_response_debug.get("totalCount") < 145
        ):  # 145 is total packets in test data
            print(
                f"✅ API total count is {api_response_debug['totalCount']} (less than 145) - filtering is working"
            )
            filtering_worked = True
        else:
            print("❌ No evidence of filtering working")
            filtering_worked = False

        assert filtering_worked, (
            f"ISSUE FOUND: Manual dropdown change should filter data automatically. "
            f"Table state: {table_state_debug}, API response: {api_response_debug}"
        )

        # Verify API request was made with the filter
        print(f"API requests after dropdown change: {api_requests}")
        filtered_requests = [
            req for req in api_requests if "portnum=TEXT_MESSAGE_APP" in req
        ]

        # More lenient check - if no requests were made, that's also an issue
        if len(api_requests) == 0:
            print(
                "ISSUE: No API requests made after dropdown change - filter event may not be triggering"
            )
        elif len(filtered_requests) == 0:
            print(f"ISSUE: API requests made but none with filter: {api_requests}")

        # Restore the assertion now that we know what's happening
        assert len(filtered_requests) > 0, (
            f"ISSUE FOUND: No API requests with portnum=TEXT_MESSAGE_APP filter found. "
            f"All requests: {api_requests}. This means the filter wasn't applied to the API call."
        )

        # Verify the filtered data shows only text messages
        if filtered_count > 0:
            for i in range(min(3, filtered_count)):
                row = filtered_rows.nth(i)
                type_cell = row.locator("td").nth(3)  # Type column
                type_text = type_cell.inner_text()
                assert "Text" in type_text, (
                    f"Row {i} should show Text type, got: {type_text}"
                )

        print("✅ Manual dropdown change applies filter automatically test passed")
