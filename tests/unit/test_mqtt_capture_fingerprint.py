"""Capture-daemon integration of firmware fingerprinting (hooks + flush)."""

import sqlite3
import zlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2

from src.malla import mqtt_capture
from src.malla.fingerprint import (
    NODE_FINGERPRINT_TABLE_SQL,
    FirmwareEvidence,
    relay_marker_for,
)

PUBKEY = bytes(range(32, 64))
NODE = zlib.crc32(PUBKEY) & 0xFFFFFFFF  # a 2.8-style, key-derived node number


def _envelope(packet: mesh_pb2.MeshPacket, topic="msh/TW/2/e/MediumFast/!a2e96b40"):
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.channel_id = "MediumFast"
    envelope.gateway_id = "!a2e96b40"
    envelope.packet.CopyFrom(packet)
    return SimpleNamespace(topic=topic, payload=envelope.SerializeToString())


def _packet(
    node=NODE, portnum=portnums_pb2.PortNum.NODEINFO_APP, payload=b"", signed=False
):
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", node)
    packet.to = 0xFFFFFFFF
    packet.id = 42
    packet.hop_start = 3
    packet.hop_limit = 3
    packet.relay_node = relay_marker_for(node)
    data = mesh_pb2.Data()
    data.portnum = portnum
    data.payload = payload
    raw = data.SerializeToString()
    if signed:
        raw += bytes([0x52, 64]) + bytes(64)
    packet.decoded.ParseFromString(raw)
    return packet


@pytest.fixture(autouse=True)
def _isolated_accumulator(monkeypatch):
    monkeypatch.setattr(mqtt_capture, "_fingerprint_pending", {})
    # A fresh "last flush" so on_message never flushes to a real DB mid-test.
    monkeypatch.setattr(mqtt_capture, "_fingerprint_last_flush", float("inf"))
    yield


@patch("src.malla.mqtt_capture.log_packet_to_database")
@patch("src.malla.mqtt_capture.update_node_cache")
def test_on_message_accumulates_nodeinfo_evidence(_cache, _log):
    user = mesh_pb2.User()
    user.id = f"!{NODE:08x}"
    user.long_name = "Signer"
    user.public_key = PUBKEY
    user.is_unmessagable = False
    msg = _envelope(_packet(payload=user.SerializeToString(), signed=True))

    mqtt_capture.on_message(None, None, msg)

    ev = mqtt_capture._fingerprint_pending[NODE]
    assert ev.nodeinfo_count == 1
    assert ev.has_public_key is True
    assert ev.id_from_public_key is True
    assert ev.has_unmessagable_field is True
    assert ev.relay_self_count == 1
    assert ev.xeddsa_signed_count == 1


@patch("src.malla.mqtt_capture.log_packet_to_database")
@patch("src.malla.mqtt_capture.update_node_cache")
def test_on_message_records_map_report_version(_cache, _log):
    report = mqtt_pb2.MapReport()
    report.firmware_version = "2.7.26.54e0d8d"
    msg = _envelope(
        _packet(
            portnum=portnums_pb2.PortNum.MAP_REPORT_APP,
            payload=report.SerializeToString(),
        )
    )

    mqtt_capture.on_message(None, None, msg)

    ev = mqtt_capture._fingerprint_pending[NODE]
    assert ev.firmware_version == "2.7.26.54e0d8d"
    assert ev.firmware_version_at is not None


@patch("src.malla.mqtt_capture.log_packet_to_database")
@patch("src.malla.mqtt_capture.update_node_cache")
def test_encrypted_packets_still_yield_header_evidence(_cache, _log):
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", 0x9EA1F700)  # ends in 0x00 -> relay byte 0xFF
    packet.to = 0xFFFFFFFF
    packet.hop_start = 5
    packet.hop_limit = 5
    packet.relay_node = 0xFF
    packet.encrypted = b"\x01\x02\x03"
    msg = _envelope(packet)

    mqtt_capture.on_message(None, None, msg)

    ev = mqtt_capture._fingerprint_pending[0x9EA1F700]
    assert ev.relay_self_count == 1
    assert ev.xeddsa_signed_count == 0
    assert ev.hop_start_mask == 1 << 5


def test_flush_merges_deltas_into_database(tmp_path, monkeypatch):
    db_path = str(tmp_path / "fp.db")
    conn = sqlite3.connect(db_path)
    conn.execute(NODE_FINGERPRINT_TABLE_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)

    mqtt_capture._fingerprint_pending[NODE] = FirmwareEvidence(
        relay_self_count=2, nodeinfo_count=1
    )
    assert mqtt_capture.flush_fingerprints() == 0  # interval not elapsed
    assert mqtt_capture.flush_fingerprints(force=True) == 1
    assert mqtt_capture._fingerprint_pending == {}

    mqtt_capture._fingerprint_pending[NODE] = FirmwareEvidence(
        relay_self_count=1, xeddsa_signed_count=1
    )
    assert mqtt_capture.flush_fingerprints(force=True) == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM node_fingerprint WHERE node_id = ?", (NODE,)
    ).fetchone()
    conn.close()
    assert row["relay_self_count"] == 3
    assert row["nodeinfo_count"] == 1
    assert row["xeddsa_signed_count"] == 1


def test_flush_survives_missing_table(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", str(tmp_path / "empty.db"))
    mqtt_capture._fingerprint_pending[NODE] = FirmwareEvidence(nodeinfo_count=1)
    assert mqtt_capture.flush_fingerprints(force=True) == 0
    assert mqtt_capture._fingerprint_pending == {}


DEFAULT_KEY_B64 = "1PG7OiApB1nwvP+rz05pAQ=="
DEFAULT_KEY = bytes.fromhex("d4f1bb3a20290759f0bcffabcf4e6901")


def _aead_encrypt(
    plain: bytes, packet_id: int, sender: int, dest: int, key: bytes = DEFAULT_KEY
) -> bytes:
    """Encrypt like firmware 2.8.1 encryptPacketCCM: 13-byte nonce, 8-byte AAD, 12-byte tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    nonce = packet_id.to_bytes(8, "little") + sender.to_bytes(4, "little") + b"\x00"
    aad = sender.to_bytes(4, "little") + dest.to_bytes(4, "little")
    return AESCCM(key, tag_length=12).encrypt(nonce, plain, aad)


def _encrypted_packet(node, dest=0xFFFFFFFF, packet_id=0x1234ABCD, aead=True):
    user = mesh_pb2.User()
    user.id = f"!{node:08x}"
    user.long_name = "AEAD node"
    user.public_key = PUBKEY
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.NODEINFO_APP
    data.payload = user.SerializeToString()
    plain = data.SerializeToString()
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", node)
    packet.to = dest
    packet.id = packet_id
    packet.hop_start = 3
    packet.hop_limit = 3
    packet.relay_node = relay_marker_for(node)
    if aead:
        packet.encrypted = _aead_encrypt(plain, packet_id, node, dest)
    else:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        nonce = packet_id.to_bytes(8, "little") + node.to_bytes(8, "little")
        enc = Cipher(
            algorithms.AES(DEFAULT_KEY), modes.CTR(nonce), backend=default_backend()
        ).encryptor()
        packet.encrypted = enc.update(plain) + enc.finalize()
    return packet


def test_try_decrypt_handles_aead_and_reports_method(monkeypatch):
    monkeypatch.setattr(mqtt_capture, "DECRYPTION_KEYS", [DEFAULT_KEY_B64])
    info = {}
    packet = _encrypted_packet(NODE)
    assert mqtt_capture.try_decrypt_mesh_packet(packet, info=info) is True
    assert packet.decoded.portnum == portnums_pb2.PortNum.NODEINFO_APP
    assert info["method"] == "ccm"

    info = {}
    packet = _encrypted_packet(NODE, aead=False)
    assert mqtt_capture.try_decrypt_mesh_packet(packet, info=info) is True
    assert info["method"] == "ctr"

    # a tampered tag (or the wrong key) is rejected instead of yielding garbage
    packet = _encrypted_packet(NODE)
    packet.encrypted = packet.encrypted[:-1] + bytes([packet.encrypted[-1] ^ 0xFF])
    assert mqtt_capture.try_decrypt_mesh_packet(packet, info={}) is False


@patch("src.malla.mqtt_capture.log_packet_to_database")
@patch("src.malla.mqtt_capture.update_node_cache")
def test_on_message_counts_aead_channel_as_281_evidence(_cache, _log, monkeypatch):
    monkeypatch.setattr(mqtt_capture, "DECRYPTION_KEYS", [DEFAULT_KEY_B64])
    msg = _envelope(_encrypted_packet(NODE))

    mqtt_capture.on_message(None, None, msg)

    ev = mqtt_capture._fingerprint_pending[NODE]
    assert ev.aead_count == 1
    assert ev.nodeinfo_count == 1  # decrypted NodeInfo was parsed too
    from src.malla.fingerprint import estimate

    assert estimate(ev)["label"] == "≥ 2.8.1"


def test_log_packet_stores_channel_hash(tmp_path, monkeypatch):
    """MeshPacket.channel (the on-air channel hash) lands in channel_index."""
    db_path = str(tmp_path / "log.db")
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
    monkeypatch.setattr(mqtt_capture, "seed_query_planner_stats_async", lambda *_: None)
    mqtt_capture.init_database()

    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", NODE)
    packet.to = 0xFFFFFFFF
    packet.id = 7
    packet.channel = 31  # MediumFast with the default PSK
    packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    packet.decoded.payload = b"hi"
    mqtt_capture.log_packet_to_database("msh/TW/2/e/MediumFast/!a2e96b40", None, packet)

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT channel_index FROM packet_history").fetchone()[0] == 31
    conn.close()
