#!/usr/bin/env python3
"""
Tests for MQTT client ID configuration functionality.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from malla.config import AppConfig, _clear_config_cache, load_config


class TestMQTTClientIdConfig:
    """Test MQTT client ID configuration."""

    def test_default_client_id_is_none(self):
        """Default mqtt_client_id should be None (random client ID)."""
        config = AppConfig()
        assert config.mqtt_client_id is None

    def test_client_id_can_be_set(self):
        """mqtt_client_id can be set to a specific string."""
        config = AppConfig(mqtt_client_id="my-malla-client")
        assert config.mqtt_client_id == "my-malla-client"

    def test_client_id_loaded_from_yaml(self, tmp_path, monkeypatch):
        """mqtt_client_id is loaded from YAML configuration."""
        _clear_config_cache()
        monkeypatch.delenv("MALLA_MQTT_CLIENT_ID", raising=False)

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("mqtt_client_id: my-custom-client\n")

        cfg = load_config(config_path=yaml_file)
        assert cfg.mqtt_client_id == "my-custom-client"

    def test_client_id_loaded_from_env(self, monkeypatch):
        """mqtt_client_id is overridden by MALLA_MQTT_CLIENT_ID environment variable."""
        _clear_config_cache()
        monkeypatch.setenv("MALLA_MQTT_CLIENT_ID", "env-client-id")

        cfg = load_config(config_path=None)
        assert cfg.mqtt_client_id == "env-client-id"

    def test_client_id_env_overrides_yaml(self, tmp_path, monkeypatch):
        """Environment variable overrides YAML value for mqtt_client_id."""
        _clear_config_cache()
        monkeypatch.setenv("MALLA_MQTT_CLIENT_ID", "from-env")

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("mqtt_client_id: from-yaml\n")

        cfg = load_config(config_path=yaml_file)
        assert cfg.mqtt_client_id == "from-env"


class TestMQTTClientIdUsage:
    """Test that the MQTT client ID is passed correctly to the MQTT client."""

    @patch("malla.mqtt_capture.mqtt.Client")
    @patch("malla.mqtt_capture.init_database")
    @patch("malla.mqtt_capture.load_node_cache")
    @patch("malla.mqtt_capture.get_node_statistics")
    def test_main_uses_configured_client_id(
        self,
        mock_stats,
        mock_load_cache,
        mock_init_db,
        mock_mqtt_client_class,
    ):
        """main() passes the configured client ID to mqtt.Client."""
        from paho.mqtt.client import CallbackAPIVersion

        mock_stats.return_value = {
            "total_nodes": 0,
            "total_packets": 0,
            "active_nodes_24h": 0,
        }
        mock_client = MagicMock()
        mock_mqtt_client_class.return_value = mock_client
        mock_client.connect.return_value = None
        mock_client.loop_start.return_value = None

        with (
            patch("malla.mqtt_capture.MQTT_CLIENT_ID", "test-client-id"),
            patch("malla.mqtt_capture.MQTT_USERNAME", None),
            patch("malla.mqtt_capture.cleanup_thread", None),
        ):
            from malla.mqtt_capture import main

            main()

        mock_mqtt_client_class.assert_called_once_with(
            CallbackAPIVersion.VERSION2, client_id="test-client-id"
        )

    @patch("malla.mqtt_capture.mqtt.Client")
    @patch("malla.mqtt_capture.init_database")
    @patch("malla.mqtt_capture.load_node_cache")
    @patch("malla.mqtt_capture.get_node_statistics")
    def test_main_uses_empty_string_when_no_client_id(
        self,
        mock_stats,
        mock_load_cache,
        mock_init_db,
        mock_mqtt_client_class,
    ):
        """main() passes empty string to mqtt.Client when no client ID is configured (random)."""
        from paho.mqtt.client import CallbackAPIVersion

        mock_stats.return_value = {
            "total_nodes": 0,
            "total_packets": 0,
            "active_nodes_24h": 0,
        }
        mock_client = MagicMock()
        mock_mqtt_client_class.return_value = mock_client
        mock_client.connect.return_value = None
        mock_client.loop_start.return_value = None

        with (
            patch("malla.mqtt_capture.MQTT_CLIENT_ID", None),
            patch("malla.mqtt_capture.MQTT_USERNAME", None),
            patch("malla.mqtt_capture.cleanup_thread", None),
        ):
            from malla.mqtt_capture import main

            main()

        mock_mqtt_client_class.assert_called_once_with(
            CallbackAPIVersion.VERSION2, client_id=""
        )
