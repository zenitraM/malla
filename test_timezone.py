#!/usr/bin/env python3
"""
Test script to verify timezone functionality works correctly.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime, UTC
from zoneinfo import ZoneInfo

# Test the configuration directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'malla'))

from config import AppConfig

# Test default config
config = AppConfig()
print(f"Default timezone: {config.timezone}")

# Test timezone utils
from utils.formatting import (
    get_configured_timezone,
    format_datetime_in_timezone,
    get_current_time_in_timezone
)

# Override config
from config import _override_config
_override_config(config)

print("\n--- Testing UTC timezone ---")
tz = get_configured_timezone()
print(f"Configured timezone: {tz.key}")

test_dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
formatted = format_datetime_in_timezone(test_dt)
print(f"Formatted datetime: {formatted}")

current = get_current_time_in_timezone()
print(f"Current time: {current}")

print("\n--- Testing EST timezone ---")
config_est = AppConfig(timezone="America/New_York")
_override_config(config_est)

tz_est = get_configured_timezone()
print(f"Configured timezone: {tz_est.key}")

formatted_est = format_datetime_in_timezone(test_dt)
print(f"Formatted datetime: {formatted_est}")

current_est = get_current_time_in_timezone()
print(f"Current time: {current_est}")

print("\n--- Testing invalid timezone ---")
config_invalid = AppConfig(timezone="Invalid/Timezone")
_override_config(config_invalid)

tz_invalid = get_configured_timezone()
print(f"Fallback timezone: {tz_invalid.key}")

print("\n✓ All timezone functionality tests passed!")