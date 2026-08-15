"""Tests for the MQTT-ingest abuse guards.

Pins the "Harden MQTT ingest against untrusted publishers" guards:

- payloads larger than ``MAX_MQTT_PAYLOAD_BYTES`` are dropped before any
  parsing or persistence (CWE-400/770);
- the in-memory node cache evicts least-recently-updated entries once it
  exceeds ``MAX_NODE_CACHE_SIZE`` (CWE-400/770);
- attacker-controlled values (node names, NODEINFO fields, topics, channel
  names, message text) can never forge extra log lines or inject terminal
  control sequences (CWE-117).
"""

import sqlite3
from types import SimpleNamespace

import pytest
from meshtastic import config_pb2, mesh_pb2, mqtt_pb2, portnums_pb2

from src.malla import mqtt_capture

pytestmark = pytest.mark.unit


def build_nodeinfo_message(long_name: str = "Gabriela") -> SimpleNamespace:
    """Create a minimal MQTT message containing a NODEINFO packet."""
    user = mesh_pb2.User()
    user.id = "!7f6e5d4c"
    user.long_name = long_name
    user.short_name = "GAB"
    user.hw_model = mesh_pb2.HardwareModel.THINKNODE_M3
    user.role = config_pb2.Config.DeviceConfig.Role.CLIENT

    mesh_packet = mesh_pb2.MeshPacket()
    # Generated protobuf field is named "from"; use setattr because "from" is a keyword.
    setattr(mesh_packet, "from", 0x7F6E5D4C)
    mesh_packet.to = 0
    mesh_packet.decoded.portnum = portnums_pb2.PortNum.NODEINFO_APP
    mesh_packet.decoded.payload = user.SerializeToString()

    service_envelope = mqtt_pb2.ServiceEnvelope()
    service_envelope.channel_id = "LongFast"
    service_envelope.packet.CopyFrom(mesh_packet)

    return SimpleNamespace(
        topic="msh/TW/2/e/LongFast/!a2e96b40",
        payload=service_envelope.SerializeToString(),
    )


def build_text_message() -> SimpleNamespace:
    """Create a minimal MQTT message containing a TEXT_MESSAGE packet."""
    mesh_packet = mesh_pb2.MeshPacket()
    setattr(mesh_packet, "from", 123)
    mesh_packet.to = 0  # broadcast
    mesh_packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    mesh_packet.decoded.payload = b"hello"

    service_envelope = mqtt_pb2.ServiceEnvelope()
    service_envelope.channel_id = "LongFast"
    service_envelope.packet.CopyFrom(mesh_packet)

    return SimpleNamespace(
        topic="msh/TW/2/e/LongFast/!abc",
        payload=service_envelope.SerializeToString(),
    )


class TestSanitizeForLog:
    def test_passes_through_plain_text(self):
        assert mqtt_capture._sanitize_for_log("node-42") == "node-42"

    def test_replaces_line_and_control_characters(self):
        out = mqtt_capture._sanitize_for_log("line1\nline2\r\n\x1b[31m\x00end")
        assert "\n" not in out
        assert "\r" not in out
        assert "\x1b" not in out
        assert "\x00" not in out
        assert out == "line1�line2���[31m�end"

    def test_preserves_printable_unicode(self):
        assert mqtt_capture._sanitize_for_log("台北節點") == "台北節點"
        assert mqtt_capture._sanitize_for_log("Node !a2e96b40") == "Node !a2e96b40"

    def test_truncates_at_limit(self):
        out = mqtt_capture._sanitize_for_log("x" * 300, limit=50)
        assert out == "x" * 50 + "…"

    def test_default_limit_is_200(self):
        assert len(mqtt_capture._sanitize_for_log("y" * 500)) == 201

    def test_coerces_non_string_values(self):
        assert mqtt_capture._sanitize_for_log(42) == "42"
        assert mqtt_capture._sanitize_for_log(None) == "None"
        assert mqtt_capture._sanitize_for_log(b"raw") == "b'raw'"


class TestPayloadSizeLimit:
    @staticmethod
    def _msg(topic: str, payload: bytes) -> SimpleNamespace:
        return SimpleNamespace(topic=topic, payload=payload)

    def test_oversized_payload_is_dropped_before_any_processing(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(mqtt_capture, "MAX_MQTT_PAYLOAD_BYTES", 10)

        def _must_not_be_called(*_args, **_kwargs):  # pragma: no cover
            raise AssertionError("processing must not start for oversized payloads")

        monkeypatch.setattr(mqtt_capture, "log_packet_to_database", _must_not_be_called)
        with caplog.at_level("WARNING"):
            mqtt_capture.on_message(
                None, None, self._msg("msh/TW/2/e/LongFast/!abc", b"x" * 11)
            )
        assert "Dropping oversized MQTT payload" in caplog.text

    def test_payload_at_the_limit_is_not_dropped(self, monkeypatch):
        monkeypatch.setattr(mqtt_capture, "MAX_MQTT_PAYLOAD_BYTES", 10)
        stored = []
        monkeypatch.setattr(
            mqtt_capture,
            "log_packet_to_database",
            lambda *args, **kwargs: stored.append(args),
        )
        # Exactly at the limit on a JSON topic: passes the size guard, then is
        # skipped by the JSON check - nothing reaches the store.
        mqtt_capture.on_message(
            None, None, self._msg("msh/TW/2/json/LongFast/!abc", b"x" * 10)
        )
        assert stored == []

    def test_within_limit_protobuf_topic_reaches_store(self, monkeypatch):
        monkeypatch.setattr(mqtt_capture, "MAX_MQTT_PAYLOAD_BYTES", 4096)
        stored = []
        monkeypatch.setattr(
            mqtt_capture,
            "log_packet_to_database",
            lambda *args, **kwargs: stored.append(args),
        )
        # Empty-but-legal ServiceEnvelope: parses, then the missing packet is a
        # parse error - but the raw bytes are still handed to the store (small
        # malformed packets are kept for debugging).
        mqtt_capture.on_message(None, None, self._msg("msh/TW/2/e/LongFast/!abc", b""))
        assert len(stored) == 1
        # The raw (unsanitised) topic is what gets persisted.
        assert stored[0][0] == "msh/TW/2/e/LongFast/!abc"


class TestNodeCacheEviction:
    @staticmethod
    def _entry(ts: float) -> dict:
        return {
            "hex_id": "!deadbeef",
            "long_name": "n",
            "short_name": "n",
            "last_updated": ts,
        }

    def test_evicts_least_recently_updated_when_full(self, monkeypatch):
        monkeypatch.setattr(
            mqtt_capture, "node_cache", {i: self._entry(float(i)) for i in range(10)}
        )
        monkeypatch.setattr(mqtt_capture, "MAX_NODE_CACHE_SIZE", 6)
        monkeypatch.setattr(mqtt_capture, "_NODE_CACHE_EVICT_BATCH", 2)

        mqtt_capture._evict_stale_node_cache_entries()

        assert set(mqtt_capture.node_cache) == {6, 7, 8, 9}

    def test_no_eviction_below_capacity(self, monkeypatch):
        monkeypatch.setattr(
            mqtt_capture, "node_cache", {i: self._entry(float(i)) for i in range(5)}
        )
        monkeypatch.setattr(mqtt_capture, "MAX_NODE_CACHE_SIZE", 10)
        monkeypatch.setattr(mqtt_capture, "_NODE_CACHE_EVICT_BATCH", 1)

        mqtt_capture._evict_stale_node_cache_entries()

        assert set(mqtt_capture.node_cache) == {0, 1, 2, 3, 4}

    def test_eviction_keeps_size_bounded(self, monkeypatch):
        monkeypatch.setattr(
            mqtt_capture, "node_cache", {i: self._entry(float(i)) for i in range(100)}
        )
        monkeypatch.setattr(mqtt_capture, "MAX_NODE_CACHE_SIZE", 10)
        monkeypatch.setattr(mqtt_capture, "_NODE_CACHE_EVICT_BATCH", 3)

        mqtt_capture._evict_stale_node_cache_entries()

        assert set(mqtt_capture.node_cache) == set(range(93, 100))

    def test_update_node_cache_triggers_eviction_when_full(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "capture.db")
        monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
        monkeypatch.setattr(
            mqtt_capture, "node_cache", {i: self._entry(float(i)) for i in range(10)}
        )
        monkeypatch.setattr(mqtt_capture, "MAX_NODE_CACHE_SIZE", 8)
        monkeypatch.setattr(mqtt_capture, "_NODE_CACHE_EVICT_BATCH", 2)

        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE node_info (
                node_id INTEGER PRIMARY KEY,
                hex_id TEXT, long_name TEXT, short_name TEXT,
                hw_model TEXT, role TEXT, primary_channel TEXT,
                is_licensed BOOLEAN, mac_address TEXT,
                first_seen REAL NOT NULL, last_updated REAL NOT NULL
            )"""
        )
        conn.commit()
        conn.close()

        mqtt_capture.update_node_cache(node_id=1000, hex_id="!new0001", long_name="new")

        assert 1000 in mqtt_capture.node_cache
        assert len(mqtt_capture.node_cache) <= 8
        # The four oldest entries were evicted to make room for the newcomer.
        assert all(nid not in mqtt_capture.node_cache for nid in (0, 1, 2, 3))


class TestLogSanitisationEndToEnd:
    """Attacker-controlled values must never produce a second log line."""

    def test_nodeinfo_long_name_cannot_forge_log_lines(self, monkeypatch, caplog):
        monkeypatch.setattr(mqtt_capture, "update_node_cache", lambda **kwargs: None)
        monkeypatch.setattr(
            mqtt_capture, "log_packet_to_database", lambda *args, **kwargs: None
        )

        msg = build_nodeinfo_message(long_name="EVE\nFORGED LOG LINE")

        with caplog.at_level("INFO"):
            mqtt_capture.on_message(None, None, msg)

        # The raw name (with its newline) never appears in the log.
        assert "EVE\nFORGED" not in caplog.text
        # The sanitised name is logged on a single line.
        assert "EVE�FORGED LOG LINE" in caplog.text
        # The forged fragment must not appear as its own line.
        assert not any(
            line.strip().startswith("FORGED LOG LINE")
            for line in caplog.text.splitlines()
        )

    def test_nodeinfo_escape_sequence_cannot_inject_terminal_codes(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(mqtt_capture, "update_node_cache", lambda **kwargs: None)
        monkeypatch.setattr(
            mqtt_capture, "log_packet_to_database", lambda *args, **kwargs: None
        )

        msg = build_nodeinfo_message(long_name="EVE\x1b[31mRED")

        with caplog.at_level("INFO"):
            mqtt_capture.on_message(None, None, msg)

        assert "\x1b" not in caplog.text
        assert "EVE�[31mRED" in caplog.text

    def test_text_message_node_names_cannot_forge_log_lines(self, monkeypatch, caplog):
        monkeypatch.setattr(
            mqtt_capture, "get_node_display_name", lambda nid: "EVE\nFORGED LOG LINE"
        )
        monkeypatch.setattr(
            mqtt_capture, "log_packet_to_database", lambda *args, **kwargs: None
        )

        msg = build_text_message()

        with caplog.at_level("INFO"):
            mqtt_capture.on_message(None, None, msg)

        assert "EVE\nFORGED" not in caplog.text
        assert "EVE�FORGED LOG LINE" in caplog.text
        assert not any(
            line.strip().startswith("FORGED LOG LINE")
            for line in caplog.text.splitlines()
        )

    def test_text_message_content_cannot_forge_log_lines(self, monkeypatch, caplog):
        monkeypatch.setattr(mqtt_capture, "get_node_display_name", lambda nid: "Alice")
        monkeypatch.setattr(
            mqtt_capture, "log_packet_to_database", lambda *args, **kwargs: None
        )

        msg = build_text_message()

        # Rebuild the envelope with hostile text content.
        mesh_packet = mesh_pb2.MeshPacket()
        setattr(mesh_packet, "from", 123)
        mesh_packet.to = 0
        mesh_packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
        mesh_packet.decoded.payload = b"hello\nFORGED LOG LINE"
        service_envelope = mqtt_pb2.ServiceEnvelope()
        service_envelope.channel_id = "LongFast"
        service_envelope.packet.CopyFrom(mesh_packet)
        msg.payload = service_envelope.SerializeToString()

        with caplog.at_level("INFO"):
            mqtt_capture.on_message(None, None, msg)

        assert "hello\nFORGED" not in caplog.text
        assert "hello�FORGED LOG LINE" in caplog.text
        assert not any(
            line.strip().startswith("FORGED LOG LINE")
            for line in caplog.text.splitlines()
        )

    def test_channel_name_cannot_forge_log_lines(self, monkeypatch, caplog):
        """The decrypt-failure debug line sanitises topic-derived channel names."""
        # Force the UNKNOWN_APP decryption path so channel_name is logged.
        mesh_packet = mesh_pb2.MeshPacket()
        setattr(mesh_packet, "from", 123)
        mesh_packet.to = 456
        mesh_packet.id = 7
        mesh_packet.decoded.portnum = portnums_pb2.PortNum.UNKNOWN_APP
        mesh_packet.encrypted = b"\x01\x02\x03"
        service_envelope = mqtt_pb2.ServiceEnvelope()
        service_envelope.channel_id = "LongFast"
        service_envelope.packet.CopyFrom(mesh_packet)
        msg = SimpleNamespace(
            topic="msh/TW/2/e/EVIL\nCHANNEL/!abc",
            payload=service_envelope.SerializeToString(),
        )

        monkeypatch.setattr(
            mqtt_capture, "try_decrypt_mesh_packet", lambda *args, **kwargs: False
        )
        monkeypatch.setattr(
            mqtt_capture, "log_packet_to_database", lambda *args, **kwargs: None
        )

        with caplog.at_level("DEBUG"):
            mqtt_capture.on_message(None, None, msg)

        assert "EVIL\nCHANNEL" not in caplog.text
        assert "EVIL�CHANNEL" in caplog.text
