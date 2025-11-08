#!/usr/bin/env python3
"""
Tests for multiple decryption keys functionality.
"""

import base64
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from malla.config import AppConfig
from malla.mqtt_capture import try_decrypt_mesh_packet


class TestMultipleDecryptionKeys:
    """Test multiple decryption keys functionality."""

    def test_config_get_decryption_keys_single_key(self):
        """Test parsing a single decryption key."""
        config = AppConfig(default_channel_key="1PG7OiApB1nwvP+rz05pAQ==")
        keys = config.get_decryption_keys()

        assert len(keys) == 1
        assert keys[0] == "1PG7OiApB1nwvP+rz05pAQ=="

    def test_config_get_decryption_keys_multiple_keys(self):
        """Test parsing multiple comma-separated decryption keys."""
        config = AppConfig(
            default_channel_key="1PG7OiApB1nwvP+rz05pAQ==,AQ4GCAwQFBgcICQoLDA0ODw=,another+key=="
        )
        keys = config.get_decryption_keys()

        assert len(keys) == 3
        assert keys[0] == "1PG7OiApB1nwvP+rz05pAQ=="
        assert keys[1] == "AQ4GCAwQFBgcICQoLDA0ODw="
        assert keys[2] == "another+key=="

    def test_config_get_decryption_keys_with_spaces(self):
        """Test parsing keys with spaces around commas."""
        config = AppConfig(
            default_channel_key="1PG7OiApB1nwvP+rz05pAQ== , AQ4GCAwQFBgcICQoLDA0ODw= , another+key=="
        )
        keys = config.get_decryption_keys()

        assert len(keys) == 3
        assert keys[0] == "1PG7OiApB1nwvP+rz05pAQ=="
        assert keys[1] == "AQ4GCAwQFBgcICQoLDA0ODw="
        assert keys[2] == "another+key=="

    def test_config_get_decryption_keys_empty_string(self):
        """Test parsing empty string returns empty list."""
        config = AppConfig(default_channel_key="")
        keys = config.get_decryption_keys()

        assert len(keys) == 0

    def test_config_get_decryption_keys_filters_empty(self):
        """Test that empty keys are filtered out."""
        config = AppConfig(
            default_channel_key="1PG7OiApB1nwvP+rz05pAQ==,,AQ4GCAwQFBgcICQoLDA0ODw="
        )
        keys = config.get_decryption_keys()

        assert len(keys) == 2
        assert keys[0] == "1PG7OiApB1nwvP+rz05pAQ=="
        assert keys[1] == "AQ4GCAwQFBgcICQoLDA0ODw="

    def test_config_get_decryption_keys_trailing_comma(self):
        """Test parsing keys with trailing comma."""
        config = AppConfig(default_channel_key="1PG7OiApB1nwvP+rz05pAQ==,")
        keys = config.get_decryption_keys()

        assert len(keys) == 1
        assert keys[0] == "1PG7OiApB1nwvP+rz05pAQ=="


class TestTryDecryptMeshPacketMultipleKeys:
    """Test try_decrypt_mesh_packet with multiple keys."""

    def create_mock_mesh_packet(self, encrypted=True, already_decoded=False):
        """Helper to create a mock MeshPacket."""
        mesh_packet = MagicMock()
        mesh_packet.id = 12345
        mesh_packet.encrypted = b"encrypted_data" if encrypted else None

        # Mock the 'from' attribute (Python keyword workaround)
        type(mesh_packet).from_ = 67890
        # Make getattr work for 'from'
        mesh_packet.__getattribute__ = lambda self, name: (
            67890 if name == "from" else MagicMock.__getattribute__(self, name)
        )

        # Set up decoded attribute
        mesh_packet.decoded = MagicMock()
        if already_decoded:
            mesh_packet.decoded.portnum = 1  # TEXT_MESSAGE_APP
        else:
            mesh_packet.decoded.portnum = 0  # UNKNOWN_APP

        return mesh_packet

    def test_try_decrypt_no_keys_configured(self):
        """Test that decryption fails gracefully when no keys are configured."""
        mesh_packet = self.create_mock_mesh_packet()

        # Pass empty list of keys
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=[])

        assert result is False

    def test_try_decrypt_already_decoded_packet(self):
        """Test that already decoded packets are skipped."""
        mesh_packet = self.create_mock_mesh_packet(already_decoded=True)

        with patch("malla.mqtt_capture.portnums_pb2") as mock_portnums:
            mock_portnums.PortNum.UNKNOWN_APP = 0
            result = try_decrypt_mesh_packet(
                mesh_packet, keys_base64=["1PG7OiApB1nwvP+rz05pAQ=="]
            )

        assert result is False

    def test_try_decrypt_no_encrypted_data(self):
        """Test that packets without encrypted data are skipped."""
        mesh_packet = self.create_mock_mesh_packet(encrypted=False)

        result = try_decrypt_mesh_packet(
            mesh_packet, keys_base64=["1PG7OiApB1nwvP+rz05pAQ=="]
        )

        assert result is False

    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_first_key_succeeds(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test successful decryption with the first key."""
        mesh_packet = self.create_mock_mesh_packet()

        # Mock successful decryption
        mock_decrypt.return_value = b"decrypted_payload"
        mock_derive_key.return_value = b"derived_key"

        # Mock protobuf parsing
        mock_data = MagicMock()
        mock_data.portnum = 1  # TEXT_MESSAGE_APP
        mock_mesh_pb2.Data.return_value = mock_data
        mock_portnums.PortNum.UNKNOWN_APP = 0
        mock_portnums.PortNum.Name.return_value = "TEXT_MESSAGE_APP"

        keys = ["key1==", "key2==", "key3=="]
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=keys)

        assert result is True
        # Should only try the first key
        assert mock_decrypt.call_count == 1

    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_second_key_succeeds(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test successful decryption with the second key after first fails."""
        mesh_packet = self.create_mock_mesh_packet()

        # First key fails, second succeeds
        mock_decrypt.side_effect = [b"", b"decrypted_payload"]
        mock_derive_key.return_value = b"derived_key"

        # Mock protobuf parsing
        mock_data = MagicMock()
        mock_data.portnum = 1  # TEXT_MESSAGE_APP
        mock_mesh_pb2.Data.return_value = mock_data
        mock_portnums.PortNum.UNKNOWN_APP = 0
        mock_portnums.PortNum.Name.return_value = "TEXT_MESSAGE_APP"

        keys = ["key1==", "key2==", "key3=="]
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=keys)

        assert result is True
        # Should try first two keys
        assert mock_decrypt.call_count == 2

    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_all_keys_fail(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test that decryption fails when all keys fail."""
        mesh_packet = self.create_mock_mesh_packet()

        # All keys return empty payload
        mock_decrypt.return_value = b""
        mock_derive_key.return_value = b"derived_key"
        mock_portnums.PortNum.UNKNOWN_APP = 0

        keys = ["key1==", "key2==", "key3=="]
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=keys)

        assert result is False
        # Should try all three keys
        assert mock_decrypt.call_count == 3

    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_invalid_protobuf_continues(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test that invalid protobuf with one key tries the next key."""
        mesh_packet = self.create_mock_mesh_packet()

        # Both keys return data, but first produces invalid protobuf
        mock_decrypt.return_value = b"some_data"
        mock_derive_key.return_value = b"derived_key"
        mock_portnums.PortNum.UNKNOWN_APP = 0

        # First parse fails, second succeeds
        mock_data_fail = MagicMock()
        mock_data_fail.ParseFromString.side_effect = Exception("Invalid protobuf")

        mock_data_success = MagicMock()
        mock_data_success.portnum = 1  # TEXT_MESSAGE_APP
        mock_portnums.PortNum.Name.return_value = "TEXT_MESSAGE_APP"

        mock_mesh_pb2.Data.side_effect = [mock_data_fail, mock_data_success]

        keys = ["key1==", "key2=="]
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=keys)

        assert result is True
        # Should try both keys
        assert mock_decrypt.call_count == 2

    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_unknown_app_continues(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test that UNKNOWN_APP portnum with one key tries the next key."""
        mesh_packet = self.create_mock_mesh_packet()

        mock_decrypt.return_value = b"some_data"
        mock_derive_key.return_value = b"derived_key"
        mock_portnums.PortNum.UNKNOWN_APP = 0

        # First parse returns UNKNOWN_APP, second returns valid portnum
        mock_data1 = MagicMock()
        mock_data1.portnum = 0  # UNKNOWN_APP

        mock_data2 = MagicMock()
        mock_data2.portnum = 1  # TEXT_MESSAGE_APP
        mock_portnums.PortNum.Name.return_value = "TEXT_MESSAGE_APP"

        mock_mesh_pb2.Data.side_effect = [mock_data1, mock_data2]

        keys = ["key1==", "key2=="]
        result = try_decrypt_mesh_packet(mesh_packet, keys_base64=keys)

        assert result is True
        # Should try both keys
        assert mock_decrypt.call_count == 2

    @patch("malla.mqtt_capture.DECRYPTION_KEYS", ["global_key1==", "global_key2=="])
    @patch("malla.mqtt_capture.decrypt_packet")
    @patch("malla.mqtt_capture.derive_key_from_channel_name")
    @patch("malla.mqtt_capture.mesh_pb2")
    @patch("malla.mqtt_capture.portnums_pb2")
    def test_try_decrypt_uses_global_keys_when_none_provided(
        self, mock_portnums, mock_mesh_pb2, mock_derive_key, mock_decrypt
    ):
        """Test that global DECRYPTION_KEYS are used when no keys are provided."""
        mesh_packet = self.create_mock_mesh_packet()

        mock_decrypt.return_value = b"decrypted_payload"
        mock_derive_key.return_value = b"derived_key"

        mock_data = MagicMock()
        mock_data.portnum = 1  # TEXT_MESSAGE_APP
        mock_mesh_pb2.Data.return_value = mock_data
        mock_portnums.PortNum.UNKNOWN_APP = 0
        mock_portnums.PortNum.Name.return_value = "TEXT_MESSAGE_APP"

        # Call without specifying keys (should use global DECRYPTION_KEYS)
        result = try_decrypt_mesh_packet(mesh_packet)

        assert result is True
        # Should have tried to decrypt
        assert mock_decrypt.call_count >= 1


class TestIntegrationWithConfig:
    """Integration tests for config and mqtt_capture."""

    def test_config_environment_variable_multiple_keys(self):
        """Test that environment variable correctly sets multiple keys."""
        with patch.dict(
            os.environ,
            {"MALLA_DEFAULT_CHANNEL_KEY": "key1==,key2==,key3=="},
            clear=False,
        ):
            from malla.config import load_config

            config = load_config()
            keys = config.get_decryption_keys()

            assert len(keys) == 3
            assert keys[0] == "key1=="
            assert keys[1] == "key2=="
            assert keys[2] == "key3=="


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
