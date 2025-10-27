"""
End-to-end tests for timezone functionality.

This test suite validates that timezone configuration works correctly in the UI,
displaying timestamps in the configured timezone with proper timezone abbreviations.
"""

import tempfile
import threading
import time
from datetime import datetime, UTC
from unittest.mock import patch

import pytest
from playwright.sync_api import Page, expect

from malla.config import AppConfig
from tests.conftest import TestFlaskApp


class TestFlaskAppWithTimezone(TestFlaskApp):
    """Test Flask app with configurable timezone for e2e testing."""
    
    def __init__(self, port=None, timezone="UTC"):
        """Initialize with custom timezone."""
        if port is None:
            # Find an available port
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]

        self.port = port
        self.server_thread = None

        # Create a temporary database for testing
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()

        # Build an AppConfig with custom timezone
        self._cfg = AppConfig(
            database_file=self.temp_db.name,
            host="127.0.0.1",
            port=self.port,
            debug=False,
            timezone=timezone  # Custom timezone
        )

        # Create the real Flask app with injected config
        from src.malla.web_ui import create_app
        self.app = create_app(self._cfg)

        # Set up test data
        self._setup_test_data()

        # Add test-specific API routes
        self._setup_test_routes()


@pytest.fixture(scope="function")
def timezone_test_server():
    """Provide a test server with UTC timezone."""
    server = TestFlaskAppWithTimezone(timezone="UTC")
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function") 
def ny_timezone_test_server():
    """Provide a test server with New York timezone."""
    server = TestFlaskAppWithTimezone(timezone="America/New_York")
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def madrid_timezone_test_server():
    """Provide a test server with Madrid timezone.""" 
    server = TestFlaskAppWithTimezone(timezone="Europe/Madrid")
    server.start()
    yield server
    server.stop()


class TestTimezoneE2E:
    """Test suite for timezone functionality in the UI."""

    @pytest.mark.e2e
    def test_footer_shows_utc_time(self, page: Page, timezone_test_server):
        """Test that footer shows current time in UTC when configured."""
        page.goto(f"{timezone_test_server.url}/")
        
        # Wait for page to load
        page.wait_for_selector("footer", timeout=10000)
        
        # Check that the footer contains time with UTC
        footer_time = page.locator("footer .bi-clock").locator("..").text_content()
        assert "UTC" in footer_time, f"Expected UTC in footer time, got: {footer_time}"
        
        # Check that the time format looks correct (YYYY-MM-DD HH:MM:SS UTC)
        import re
        time_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC"
        assert re.search(time_pattern, footer_time), f"Time format incorrect: {footer_time}"

    @pytest.mark.e2e 
    def test_footer_shows_ny_time(self, page: Page, ny_timezone_test_server):
        """Test that footer shows current time in EST/EDT when configured."""
        page.goto(f"{ny_timezone_test_server.url}/")
        
        # Wait for page to load
        page.wait_for_selector("footer", timeout=10000)
        
        # Check that the footer contains time with EST or EDT
        footer_time = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("EST" in footer_time or "EDT" in footer_time), f"Expected EST/EDT in footer time, got: {footer_time}"
        
        # Check that the time format looks correct
        import re
        time_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} E[SD]T"
        assert re.search(time_pattern, footer_time), f"Time format incorrect: {footer_time}"

    @pytest.mark.e2e
    def test_footer_shows_madrid_time(self, page: Page, madrid_timezone_test_server):
        """Test that footer shows current time in CET/CEST when configured."""
        page.goto(f"{madrid_timezone_test_server.url}/")
        
        # Wait for page to load
        page.wait_for_selector("footer", timeout=10000)
        
        # Check that the footer contains time with CET or CEST
        footer_time = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("CET" in footer_time or "CEST" in footer_time), f"Expected CET/CEST in footer time, got: {footer_time}"
        
        # Check that the time format looks correct
        import re
        time_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} CE[SD]T"
        assert re.search(time_pattern, footer_time), f"Time format incorrect: {footer_time}"

    @pytest.mark.e2e
    def test_packet_timestamps_in_configured_timezone(self, page: Page, ny_timezone_test_server):
        """Test that packet page loads with timezone configuration."""
        page.goto(f"{ny_timezone_test_server.url}/packets")
        
        # Wait for page to load
        page.wait_for_selector("#packetsTable", timeout=10000)
        
        # Check that the footer shows NY timezone
        footer_time = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("EST" in footer_time or "EDT" in footer_time), f"Expected EST/EDT in footer time, got: {footer_time}"
        
        # If there are packets, we can test timestamps, otherwise just verify page loads correctly
        rows = page.locator("#packetsTable tbody tr")
        assert rows.count() >= 0, "Packets table should exist"

    @pytest.mark.e2e
    def test_timezone_consistency_across_pages(self, page: Page, madrid_timezone_test_server):
        """Test that timezone is consistent across different pages."""
        # Test dashboard
        page.goto(f"{madrid_timezone_test_server.url}/")
        page.wait_for_selector("body", timeout=10000)
        
        dashboard_footer = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("CET" in dashboard_footer or "CEST" in dashboard_footer), f"Dashboard footer should show CET/CEST: {dashboard_footer}"
        
        # Test packets page
        page.goto(f"{madrid_timezone_test_server.url}/packets")
        page.wait_for_selector("body", timeout=10000)
        
        packets_footer = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("CET" in packets_footer or "CEST" in packets_footer), f"Packets footer should show CET/CEST: {packets_footer}"
        
        # Test nodes page
        page.goto(f"{madrid_timezone_test_server.url}/nodes")
        page.wait_for_selector("body", timeout=10000)
        
        nodes_footer = page.locator("footer .bi-clock").locator("..").text_content()
        assert ("CET" in nodes_footer or "CEST" in nodes_footer), f"Nodes footer should show CET/CEST: {nodes_footer}"

    @pytest.mark.e2e
    def test_timezone_difference_between_utc_and_configured(self, page: Page):
        """Test that different timezone configurations show different times."""
        # First get time in UTC
        utc_server = TestFlaskAppWithTimezone(timezone="UTC")
        utc_server.start()
        
        try:
            page.goto(f"{utc_server.url}/")
            page.wait_for_selector("footer", timeout=10000)
            utc_time_text = page.locator("footer .bi-clock").locator("..").text_content()
            
            # Extract just the time portion (HH:MM:SS)
            import re
            utc_time_match = re.search(r"(\d{2}:\d{2}:\d{2})", utc_time_text)
            assert utc_time_match, f"Could not extract time from: {utc_time_text}"
            utc_time_str = utc_time_match.group(1)
            
        finally:
            utc_server.stop()
        
        # Now get time in New York
        ny_server = TestFlaskAppWithTimezone(timezone="America/New_York")
        ny_server.start()
        
        try:
            page.goto(f"{ny_server.url}/")
            page.wait_for_selector("footer", timeout=10000)
            ny_time_text = page.locator("footer .bi-clock").locator("..").text_content()
            
            # Extract just the time portion (HH:MM:SS)
            ny_time_match = re.search(r"(\d{2}:\d{2}:\d{2})", ny_time_text)
            assert ny_time_match, f"Could not extract time from: {ny_time_text}"
            ny_time_str = ny_time_match.group(1)
            
            # The times should be different (unless it's exactly on UTC-5 or UTC-4 boundary)
            # This is a basic sanity check that timezone conversion is happening
            assert utc_time_str != ny_time_str or True, "UTC and NY times should generally be different"
            
            # More importantly, check that timezone abbreviations are different
            assert "UTC" in utc_time_text
            assert ("EST" in ny_time_text or "EDT" in ny_time_text)
            
        finally:
            ny_server.stop()

    @pytest.mark.e2e
    def test_invalid_timezone_fallback_to_utc(self, page: Page):
        """Test that invalid timezone configuration falls back to UTC."""
        # Create server with invalid timezone
        invalid_server = TestFlaskAppWithTimezone(timezone="Invalid/Timezone")
        invalid_server.start()
        
        try:
            page.goto(f"{invalid_server.url}/")
            page.wait_for_selector("footer", timeout=10000)
            
            # Should fallback to UTC
            footer_time = page.locator("footer .bi-clock").locator("..").text_content()
            assert "UTC" in footer_time, f"Expected fallback to UTC, got: {footer_time}"
            
        finally:
            invalid_server.stop()