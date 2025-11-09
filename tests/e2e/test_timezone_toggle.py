"""
E2E tests for timezone toggle functionality
"""

import re

import pytest
from playwright.sync_api import expect


@pytest.mark.e2e
class TestTimezoneToggleE2E:
    """End-to-end tests for timezone toggle feature."""

    def test_timezone_toggle_button_exists(self, page, test_server_url):
        """Test that timezone toggle button exists in navbar."""
        page.goto(f"{test_server_url}/packets")

        # Check for timezone toggle button
        timezone_toggle = page.locator("#timezone-toggle")
        expect(timezone_toggle).to_be_visible()

        # Check for icon
        icon = timezone_toggle.locator("i")
        expect(icon).to_have_class(re.compile(r"bi-(globe|clock-history)"))

    def test_timezone_scripts_loaded(self, page, test_server_url):
        """Test that timezone JavaScript files are loaded."""
        page.goto(f"{test_server_url}/packets")

        # Check that timezone utilities are available
        has_timezone_utils = page.evaluate("""
            typeof formatTimestamp === 'function' &&
            typeof renderTimestampColumn === 'function'
        """)
        assert has_timezone_utils, "Timezone utility functions not loaded"

        # Check that timezone toggle is initialized
        has_timezone_toggle = page.evaluate(
            "typeof window.timezoneToggle !== 'undefined'"
        )
        assert has_timezone_toggle, "Timezone toggle not initialized"

    def test_timezone_toggle_changes_preference(self, page, test_server_url):
        """Test that clicking timezone toggle changes the preference."""
        page.goto(f"{test_server_url}/packets")

        # Get initial preference
        initial_pref = page.evaluate(
            "localStorage.getItem('malla-timezone-preference') || 'local'"
        )

        # Click timezone toggle button
        page.click("#timezone-toggle")

        # Wait for page to reload (the toggle should trigger a reload)
        page.wait_for_load_state("load")

        # Check that preference changed
        new_pref = page.evaluate("localStorage.getItem('malla-timezone-preference')")
        assert new_pref != initial_pref, "Timezone preference should change"
        assert new_pref in ["local", "utc"], f"Invalid timezone preference: {new_pref}"

    def test_timezone_toggle_updates_timestamps_in_table(self, page, test_server_url):
        """Test that timezone toggle updates timestamps in packet table."""
        page.goto(f"{test_server_url}/packets")

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get first timestamp
        first_timestamp = page.locator(
            ".modern-table tbody tr:first-child td:first-child small"
        ).text_content()

        # Should show time with or without UTC suffix depending on current preference
        assert first_timestamp is not None and len(first_timestamp) > 0, (
            "No timestamp found"
        )

        # Click timezone toggle
        page.click("#timezone-toggle")

        # Wait for page reload
        page.wait_for_load_state("load")
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get timestamp after toggle
        new_timestamp = page.locator(
            ".modern-table tbody tr:first-child td:first-child small"
        ).text_content()

        # Toggling the timezone should either change the timestamp value or change format (presence/absence of 'UTC').
        assert new_timestamp != first_timestamp or ("UTC" in new_timestamp) != (
            "UTC" in first_timestamp
        ), "Timestamp should change value or format (UTC suffix) after timezone toggle"

    def test_local_timezone_displays_without_utc_suffix(self, page, test_server_url):
        """Test that local timezone displays timestamps without UTC suffix."""
        # Set preference to local
        page.goto(f"{test_server_url}/packets")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'local')")
        page.reload()

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get first timestamp
        first_timestamp = page.locator(
            ".modern-table tbody tr:first-child td:first-child small"
        ).text_content()

        # Should NOT have UTC suffix in local mode
        assert "UTC" not in first_timestamp, (
            f"Local timezone should not show UTC: {first_timestamp}"
        )

    def test_utc_timezone_displays_with_utc_suffix(self, page, test_server_url):
        """Test that UTC timezone displays timestamps with UTC suffix."""
        # Set preference to UTC
        page.goto(f"{test_server_url}/packets")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'utc')")
        page.reload()

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get first timestamp
        first_timestamp = page.locator(
            ".modern-table tbody tr:first-child td:first-child small"
        ).text_content()

        # Should have UTC suffix in UTC mode
        assert "UTC" in first_timestamp, (
            f"UTC timezone should show UTC: {first_timestamp}"
        )

    def test_timezone_persists_across_page_navigation(self, page, test_server_url):
        """Test that timezone preference persists when navigating to different pages."""
        # Set timezone to UTC
        page.goto(f"{test_server_url}/packets")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'utc')")
        page.reload()

        # Navigate to nodes page
        page.goto(f"{test_server_url}/nodes")
        page.wait_for_load_state("load")

        # Check preference is still UTC
        pref = page.evaluate("localStorage.getItem('malla-timezone-preference')")
        assert pref == "utc", "Timezone preference should persist across pages"

        # Navigate to traceroute page
        page.goto(f"{test_server_url}/traceroute")
        page.wait_for_load_state("load")

        # Check preference is still UTC
        pref = page.evaluate("localStorage.getItem('malla-timezone-preference')")
        assert pref == "utc", "Timezone preference should persist across pages"

    def test_packet_detail_page_respects_timezone(self, page, test_server_url):
        """Test that packet detail page respects timezone setting."""
        # Go to packets page first
        page.goto(f"{test_server_url}/packets")
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Click on first packet to go to detail page
        page.click(".modern-table tbody tr:first-child td:first-child a")
        page.wait_for_load_state("load")

        # Find timestamp in packet detail page
        # It should have data-timestamp attribute
        timestamp_elements = page.locator("[data-timestamp]").all()

        # Should have at least one timestamp element
        assert len(timestamp_elements) > 0, (
            "No timestamp elements found on packet detail page"
        )

        # Get current timezone preference
        pref = page.evaluate(
            "localStorage.getItem('malla-timezone-preference') || 'local'"
        )

        # Check that timestamp is formatted according to preference
        for element in timestamp_elements[:3]:  # Check first 3 timestamps
            text = element.text_content()
            if text and len(text) > 5:  # Skip empty or very short text
                if pref == "utc":
                    assert "UTC" in text, (
                        f"UTC mode should show UTC in timestamp: {text}"
                    )
                else:
                    assert "UTC" not in text, (
                        f"Local mode should not show UTC in timestamp: {text}"
                    )

    def test_nodes_page_respects_timezone(self, page, test_server_url):
        """Test that nodes page respects timezone setting."""
        # Set to local timezone
        page.goto(f"{test_server_url}/nodes")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'local')")
        page.reload()

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Find "Last Seen" timestamps
        last_seen_cells = page.locator(
            ".modern-table tbody td:has(.timestamp-display)"
        ).all()

        if len(last_seen_cells) > 0:
            # Check first timestamp
            text = last_seen_cells[0].text_content()
            if text and "Never" not in text:
                assert "UTC" not in text, f"Local mode should not show UTC: {text}"

    def test_traceroute_page_respects_timezone(self, page, test_server_url):
        """Test that traceroute page respects timezone setting."""
        # Set to UTC timezone
        page.goto(f"{test_server_url}/traceroute")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'utc')")
        page.reload()

        # Wait for table to load
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Get first timestamp
        first_timestamp = page.locator(
            ".modern-table tbody tr:first-child td:first-child small"
        ).text_content()

        if first_timestamp:
            # Should have UTC suffix
            assert "UTC" in first_timestamp, (
                f"UTC mode should show UTC: {first_timestamp}"
            )

    def test_datetime_inputs_work_with_timezone_toggle(self, page, test_server_url):
        """Test that datetime-local inputs work correctly regardless of timezone setting."""
        page.goto(f"{test_server_url}/packets")

        # Open filters sidebar
        page.click("text=Filters")
        page.wait_for_selector("#start_time", timeout=5000)

        # Set a datetime value
        # datetime-local always works in browser's local time
        page.fill("#start_time", "2025-01-01T12:00")

        # The input should accept the value regardless of timezone display setting
        value = page.input_value("#start_time")
        assert value == "2025-01-01T12:00", "Datetime input should work correctly"

        # Toggle timezone
        page.click("#timezone-toggle")
        page.wait_for_load_state("load")

        # Reopen filters and check input still works
        page.click("text=Filters")
        page.wait_for_selector("#start_time", timeout=5000)
        page.fill("#start_time", "2025-01-02T14:30")

        value = page.input_value("#start_time")
        assert value == "2025-01-02T14:30", (
            "Datetime input should work after timezone toggle"
        )

    def test_node_detail_page_respects_timezone(self, page, test_server_url):
        """Test that node detail page timestamps respect timezone setting."""
        # Go to nodes page
        page.goto(f"{test_server_url}/nodes")
        page.wait_for_selector(".modern-table tbody tr", timeout=10000)

        # Click on first node to go to detail page
        page.click(".modern-table tbody tr:first-child td a")
        page.wait_for_load_state("load")

        # Find timestamp elements with data-timestamp attribute
        timestamp_elements = page.locator("[data-timestamp]").all()

        # Should have at least one timestamp element (last_seen)
        assert len(timestamp_elements) > 0, (
            "No timestamp elements found on node detail page"
        )

        # Get current timezone preference
        pref = page.evaluate(
            "localStorage.getItem('malla-timezone-preference') || 'local'"
        )

        # Check that timestamps are formatted according to preference
        for element in timestamp_elements[:2]:  # Check first 2 timestamps
            text = element.text_content()
            if text and len(text) > 5:  # Skip empty or very short text
                if pref == "utc":
                    assert "UTC" in text, (
                        f"UTC mode should show UTC in timestamp: {text}"
                    )
                else:
                    assert "UTC" not in text, (
                        f"Local mode should not show UTC in timestamp: {text}"
                    )

    def test_map_page_link_timestamps_respect_timezone(self, page, test_server_url):
        """Test that map page link popups respect timezone setting."""
        # Set to UTC timezone
        page.goto(f"{test_server_url}/map")
        page.evaluate("localStorage.setItem('malla-timezone-preference', 'utc')")
        page.reload()

        # Wait for map to load
        page.wait_for_selector("#map", timeout=10000)
        page.wait_for_timeout(3000)  # Wait for data to load

        # Check that formatTimestamp function is available
        has_format_function = page.evaluate("typeof formatTimestamp === 'function'")
        assert has_format_function, (
            "formatTimestamp function should be available on map page"
        )
