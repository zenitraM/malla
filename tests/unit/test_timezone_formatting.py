"""
Tests for timezone-aware formatting functionality.
"""

import pytest
from datetime import datetime, UTC
from zoneinfo import ZoneInfo

from malla.config import AppConfig, _override_config
from malla.utils.formatting import (
    get_configured_timezone,
    format_datetime_in_timezone,
    get_current_time_in_timezone
)


class TestTimezoneFormatting:
    """Test timezone formatting functions."""

    def test_get_configured_timezone_default(self):
        """Test that default timezone is UTC."""
        config = AppConfig()
        _override_config(config)
        
        tz = get_configured_timezone()
        assert tz.key == "UTC"

    def test_get_configured_timezone_custom(self):
        """Test that custom timezone is used when configured."""
        config = AppConfig(timezone="America/New_York")
        _override_config(config)
        
        tz = get_configured_timezone()
        assert tz.key == "America/New_York"

    def test_get_configured_timezone_invalid_fallback(self):
        """Test that invalid timezone falls back to UTC."""
        config = AppConfig(timezone="Invalid/Timezone")
        _override_config(config)
        
        tz = get_configured_timezone()
        assert tz.key == "UTC"

    def test_format_datetime_in_timezone_utc(self):
        """Test formatting datetime in UTC."""
        config = AppConfig(timezone="UTC")
        _override_config(config)
        
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
        formatted = format_datetime_in_timezone(dt)
        assert "2024-01-15 12:30:00" in formatted
        assert "UTC" in formatted

    def test_format_datetime_in_timezone_est(self):
        """Test formatting datetime in EST."""
        config = AppConfig(timezone="America/New_York")
        _override_config(config)
        
        # Test with winter time (EST)
        dt = datetime(2024, 1, 15, 17, 30, 0, tzinfo=UTC)  # 5:30 PM UTC
        formatted = format_datetime_in_timezone(dt)
        assert "2024-01-15 12:30:00" in formatted  # Should be 12:30 PM EST
        assert "EST" in formatted

    def test_format_datetime_in_timezone_naive(self):
        """Test formatting naive datetime (assumes UTC)."""
        config = AppConfig(timezone="America/New_York")
        _override_config(config)
        
        dt = datetime(2024, 1, 15, 17, 30, 0)  # Naive datetime
        formatted = format_datetime_in_timezone(dt)
        assert "2024-01-15 12:30:00" in formatted  # Should be 12:30 PM EST
        assert "EST" in formatted

    def test_format_datetime_in_timezone_none(self):
        """Test formatting None datetime."""
        result = format_datetime_in_timezone(None)
        assert result == "Never"

    def test_get_current_time_in_timezone(self):
        """Test getting current time in configured timezone."""
        config = AppConfig(timezone="UTC")
        _override_config(config)
        
        current_time = get_current_time_in_timezone()
        
        # Should contain year, time, and timezone
        assert "202" in current_time  # Year
        assert ":" in current_time     # Time separator
        assert "UTC" in current_time   # Timezone

    def test_get_current_time_in_timezone_custom(self):
        """Test getting current time in custom timezone."""
        config = AppConfig(timezone="Europe/Madrid")
        _override_config(config)
        
        current_time = get_current_time_in_timezone()
        
        # Should contain year, time, and timezone
        assert "202" in current_time  # Year
        assert ":" in current_time     # Time separator
        # Could be CET or CEST depending on when test runs
        assert ("CET" in current_time or "CEST" in current_time)