#!/usr/bin/env python3
"""
Tests for MQTT capture reconnection functionality.
"""

import os
import socket

# Import the module we're testing
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from malla.mqtt_capture import on_disconnect


class TestMQTTReconnection:
    """Test MQTT reconnection functionality."""

    def test_on_disconnect_callback_signature(self):
        """Test that on_disconnect accepts the correct number of parameters."""
        # Create mock client
        mock_client = MagicMock()

        # Test that the function can be called with all expected parameters
        # This should not raise a TypeError
        try:
            on_disconnect(
                client=mock_client, userdata=None, flags=None, rc=0, properties=None
            )
        except TypeError as e:
            pytest.fail(f"on_disconnect callback has incorrect signature: {e}")

    def test_clean_disconnect_no_retry(self):
        """Test that clean disconnection (rc=0) doesn't trigger retry logic."""
        mock_client = MagicMock()

        with patch("malla.mqtt_capture.logging") as mock_logging:
            on_disconnect(mock_client, None, None, 0, None)

            # Should log clean disconnection
            mock_logging.info.assert_called_with("Clean disconnection from MQTT broker")

            # Should not attempt reconnection
            mock_client.reconnect.assert_not_called()

    @patch("malla.mqtt_capture.time.sleep")
    def test_unexpected_disconnect_triggers_retry(self, mock_sleep):
        """Test that unexpected disconnection triggers retry logic."""
        mock_client = MagicMock()

        # Make reconnect succeed on first attempt
        mock_client.reconnect.return_value = None

        with patch("malla.mqtt_capture.logging") as mock_logging:
            on_disconnect(
                mock_client, None, None, 1, None
            )  # rc=1 indicates unexpected disconnect

            # Should log unexpected disconnection
            mock_logging.error.assert_called_with(
                "Unexpected MQTT disconnection. Will attempt to reconnect."
            )

            # Should attempt reconnection
            mock_client.reconnect.assert_called_once()

            # Should log successful reconnection
            mock_logging.info.assert_any_call("Successfully reconnected to MQTT broker")

            # Should sleep before retry attempt
            mock_sleep.assert_called_once_with(1)  # First retry delay is 1 second

    @patch("malla.mqtt_capture.time.sleep")
    def test_reconnection_exponential_backoff(self, mock_sleep):
        """Test that reconnection uses exponential backoff."""
        mock_client = MagicMock()

        # Make reconnect fail multiple times, then succeed
        mock_client.reconnect.side_effect = [
            ConnectionRefusedError("Connection refused"),
            socket.gaierror("Name resolution failed"),
            Exception("Generic error"),
            None,  # Success on 4th attempt
        ]

        with patch("malla.mqtt_capture.logging") as mock_logging:
            on_disconnect(mock_client, None, None, 1, None)

            # Should attempt reconnection 4 times
            assert mock_client.reconnect.call_count == 4

            # Should use exponential backoff: 1, 2, 4, 8 seconds
            expected_delays = [1, 2, 4, 8]
            actual_delays = [call_args[0][0] for call_args in mock_sleep.call_args_list]
            assert actual_delays == expected_delays

            # Should log successful reconnection
            mock_logging.info.assert_any_call("Successfully reconnected to MQTT broker")

    @patch("malla.mqtt_capture.time.sleep")
    def test_reconnection_max_delay_cap(self, mock_sleep):
        """Test that reconnection delay is capped at max_delay."""
        mock_client = MagicMock()

        # Make reconnect fail many times to test delay cap
        mock_client.reconnect.side_effect = [
            ConnectionRefusedError("Connection refused")
        ] * 10

        with patch("malla.mqtt_capture.logging") as mock_logging:
            on_disconnect(mock_client, None, None, 1, None)

            # Should attempt reconnection 10 times (max_retries)
            assert mock_client.reconnect.call_count == 10

            # Check that delays are capped at 60 seconds
            actual_delays = [call_args[0][0] for call_args in mock_sleep.call_args_list]

            # First few should follow exponential backoff: 1, 2, 4, 8, 16, 32, 60, 60, 60, 60
            expected_delays = [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]
            assert actual_delays == expected_delays

            # Should log failure after max retries
            mock_logging.error.assert_called_with(
                "Failed to reconnect after 10 attempts. Giving up."
            )

    @patch("malla.mqtt_capture.time.sleep")
    def test_reconnection_different_error_types(self, mock_sleep):
        """Test that different connection errors are handled appropriately."""
        mock_client = MagicMock()

        # Test different error types
        mock_client.reconnect.side_effect = [
            ConnectionRefusedError("Connection refused"),
            socket.gaierror("Name resolution failed"),
            Exception("Generic error"),
            None,  # Success
        ]

        with patch("malla.mqtt_capture.logging") as mock_logging:
            on_disconnect(mock_client, None, None, 1, None)

            # Should log specific error types
            warning_calls = [
                call.args[0] for call in mock_logging.warning.call_args_list
            ]

            assert any("Connection refused" in msg for msg in warning_calls)
            assert any("Cannot resolve hostname" in msg for msg in warning_calls)
            assert any("Generic error" in msg for msg in warning_calls)

    @patch("malla.mqtt_capture.time.sleep")
    def test_reconnection_with_mqtt_broker_config(self, mock_sleep):
        """Test that reconnection uses the configured MQTT broker settings."""
        mock_client = MagicMock()
        mock_client.reconnect.return_value = None

        # Mock the global configuration
        with (
            patch("malla.mqtt_capture.MQTT_BROKER_ADDRESS", "127.0.0.1"),
            patch("malla.mqtt_capture.MQTT_PORT", 1883),
            patch("malla.mqtt_capture.logging") as mock_logging,
        ):
            on_disconnect(mock_client, None, None, 1, None)

            # Should log the broker address and port in reconnection attempt
            info_calls = [call.args[0] for call in mock_logging.info.call_args_list]
            assert any("127.0.0.1:1883" in msg for msg in info_calls)


if __name__ == "__main__":
    pytest.main([__file__])
