"""Tests for the Meshtastic 2.8.x packet-era fields and payload types.

Covers the AES-CCM (``use_aead``) decrypt path, hydration of the newer
MeshPacket header fields from the stored envelope, and decoding of the portnums
that arrived with them (NODE_STATUS_APP, MESH_BEACON_APP, ALERT_APP).
"""

from __future__ import annotations

import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
from meshtastic.protobuf import mesh_beacon_pb2

from malla import mqtt_capture
from malla.database.repositories import PacketRepository
from malla.migrations.structural import (
    PACKET_HISTORY_ADDED_COLUMNS,
    PACKET_HISTORY_TABLE_SQL,
)
from malla.routes.packet_routes import decode_packet_payload
from malla.utils.decryption import try_decrypt_mesh_packet

pytestmark = pytest.mark.unit

KEY = bytes(range(32))
KEY_B64 = base64.b64encode(KEY).decode()


def _data(portnum: int, payload: bytes) -> bytes:
    data = mesh_pb2.Data()
    data.portnum = portnum
    data.payload = payload
    return data.SerializeToString()


def _ccm(packet_id: int, sender: int, dest: int, plaintext: bytes) -> bytes:
    nonce = packet_id.to_bytes(8, "little") + sender.to_bytes(4, "little") + b"\x00"
    aad = sender.to_bytes(4, "little") + dest.to_bytes(4, "little")
    return AESCCM(KEY, tag_length=12).encrypt(nonce, plaintext, aad)


def _ctr(packet_id: int, sender: int, plaintext: bytes) -> bytes:
    nonce = packet_id.to_bytes(8, "little") + sender.to_bytes(8, "little")
    encryptor = Cipher(algorithms.AES(KEY), modes.CTR(nonce)).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def _mesh_packet(packet_id: int, sender: int, dest: int, encrypted: bytes):
    packet = mesh_pb2.MeshPacket(id=packet_id, to=dest, encrypted=encrypted)
    setattr(packet, "from", sender)
    return packet


class TestAeadDecryption:
    def test_ccm_payload_decrypts_and_reports_method(self):
        status = mesh_pb2.StatusMessage(status="on the air").SerializeToString()
        packet = _mesh_packet(
            0x11223344,
            0xAABBCCDD,
            0xFFFFFFFF,
            _ccm(0x11223344, 0xAABBCCDD, 0xFFFFFFFF, _data(36, status)),
        )
        info: dict[str, str] = {}

        assert try_decrypt_mesh_packet(packet, key_base64=KEY_B64, info=info)

        assert info == {"method": "ccm"}
        assert packet.decoded.portnum == portnums_pb2.PortNum.NODE_STATUS_APP
        assert mesh_pb2.StatusMessage.FromString(packet.decoded.payload).status == (
            "on the air"
        )

    def test_wrong_key_fails_and_does_not_fall_back_to_garbage(self):
        status = mesh_pb2.StatusMessage(status="secret").SerializeToString()
        packet = _mesh_packet(
            7,
            8,
            9,
            _ccm(7, 8, 9, _data(portnums_pb2.PortNum.TEXT_MESSAGE_APP, status)),
        )

        assert not try_decrypt_mesh_packet(
            packet, key_base64=base64.b64encode(b"\x01" * 32).decode()
        )
        assert packet.decoded.portnum == portnums_pb2.PortNum.UNKNOWN_APP

    def test_ctr_channel_still_decrypts_after_ccm_miss(self):
        text = b"hello from a CTR channel"
        packet = _mesh_packet(
            42,
            1234,
            0xFFFFFFFF,
            _ctr(42, 1234, _data(portnums_pb2.PortNum.TEXT_MESSAGE_APP, text)),
        )
        info: dict[str, str] = {}

        assert try_decrypt_mesh_packet(packet, key_base64=KEY_B64, info=info)
        assert info == {"method": "ctr"}
        assert packet.decoded.payload == text


def _create_packet_table(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(PACKET_HISTORY_TABLE_SQL)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(packet_history)")}
    for name, decl in PACKET_HISTORY_ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE packet_history ADD COLUMN {name} {decl}")
    conn.commit()
    conn.close()


class TestPacketHeaderHydration:
    def test_new_meshpacket_fields_hydrate_from_envelope(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "packets.db")
        _create_packet_table(db_path)
        monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)

        packet = _mesh_packet(99, 0x12345678, 0xFFFFFFFF, b"")
        packet.channel = 4
        packet.transport_mechanism = (
            mesh_pb2.MeshPacket.TransportMechanism.TRANSPORT_LORA
        )
        packet.xeddsa_signed = True
        packet.ack_proof_status = mesh_pb2.MeshPacket.AckProofStatus.ACK_PROOF_VALID
        packet.decoded.portnum = portnums_pb2.PortNum.NODE_STATUS_APP
        packet.decoded.payload = mesh_pb2.StatusMessage(
            status="lled mesh"
        ).SerializeToString()

        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.packet.CopyFrom(packet)
        mqtt_capture.log_packet_to_database(
            "msh/TW/2/e/LongFast/!deadbeef",
            envelope,
            packet,
            raw_service_envelope_data=envelope.SerializeToString(),
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT channel_index, portnum_name, raw_service_envelope "
            "FROM packet_history"
        ).fetchone()
        conn.close()

        packet_row = dict(row)
        PacketRepository.hydrate_packet_envelope(packet_row)

        # Encrypted packets put a channel hash in MeshPacket.channel; that is
        # not a sender-local channel index, so the column stays NULL.
        assert packet_row["channel_index"] is None
        assert packet_row["transport_mechanism"] == (
            mesh_pb2.MeshPacket.TransportMechanism.TRANSPORT_LORA
        )
        assert packet_row["xeddsa_signed"] == 1
        assert packet_row["ack_proof_status"] != 0
        assert packet_row["portnum_name"] == "NODE_STATUS_APP"


def _packet(portnum_name: str, payload: bytes) -> dict:
    return {
        "id": 1,
        "raw_payload": payload,
        "payload_length": len(payload),
        "portnum_name": portnum_name,
        "from_node_id": 0x12345678,
        "to_node_id": 0xFFFFFFFF,
    }


class TestNewPortnumPayloads:
    def test_node_status_decodes_status_string(self):
        payload = mesh_pb2.StatusMessage(status="seaside node").SerializeToString()
        info = decode_packet_payload(_packet("NODE_STATUS_APP", payload))

        assert info is not None
        assert info["decoded"] is True
        assert info["data"]["status"] == "seaside node"

    def test_mesh_beacon_decodes_message(self):
        payload = mesh_beacon_pb2.MeshBeacon(
            message="join this mesh"
        ).SerializeToString()
        info = decode_packet_payload(_packet("MESH_BEACON_APP", payload))

        assert info is not None
        assert info["decoded"] is True
        assert info["data"]["message"] == "join this mesh"

    @pytest.mark.parametrize("portnum_name", ["ALERT_APP", "REPLY_APP"])
    def test_text_portnums_decode_as_text(self, portnum_name):
        info = decode_packet_payload(_packet(portnum_name, b"ack, see you"))

        assert info is not None
        assert info["decoded"] is True
        assert info["text"] == "ack, see you"


class TestStoredPortnumNames:
    def test_backfill_names_previously_unknown_portnums(self, tmp_path):
        from malla.migrations.derived import (
            _apply_portnum_names,
            _pending_portnum_names,
        )

        conn = sqlite3.connect(tmp_path / "names.db")
        conn.execute(PACKET_HISTORY_TABLE_SQL)
        conn.executemany(
            "INSERT INTO packet_history (timestamp, topic, portnum, portnum_name) "
            "VALUES (0, 't', ?, ?)",
            [
                (13, "UNKNOWN_13"),
                (37, "UNKNOWN_37"),
                (99, "UNKNOWN_99"),  # still genuinely unknown
            ],
        )
        conn.commit()

        assert _pending_portnum_names(conn, None)
        _apply_portnum_names(conn, None)
        conn.commit()

        names = dict(
            conn.execute(
                "SELECT portnum, portnum_name FROM packet_history ORDER BY portnum"
            )
        )
        assert names[13] == "REMOTE_SHELL_APP"
        assert names[37] == "MESH_BEACON_APP"
        assert names[99] == "UNKNOWN_99"
        assert not _pending_portnum_names(conn, None)
        conn.close()
