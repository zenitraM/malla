"""The capture must not lose packets published while startup migrations run."""

import sqlite3

import paho.mqtt.client as mqtt
from meshtastic import mqtt_pb2, portnums_pb2

from malla import mqtt_capture

NODE_ID = 1128074276
TOPIC = "msh/ES/2/e/LongFast/!433d0c24"


def _payload() -> bytes:
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.gateway_id = "!433d0c24"
    packet = envelope.packet
    packet.id = 4242
    setattr(packet, "from", NODE_ID)  # type: ignore[arg-type]  # "from" is a keyword
    packet.to = 0xFFFFFFFF
    packet.hop_start = 3
    packet.hop_limit = 3
    packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    packet.decoded.payload = b"hello"
    return envelope.SerializeToString()


def _message() -> mqtt.MQTTMessage:
    # paho stores the topic as bytes and decodes it on read.
    message = mqtt.MQTTMessage(topic=TOPIC.encode())
    message.payload = _payload()
    return message


def _packet_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM packet_history").fetchone()[0]
    finally:
        conn.close()


def _reset_buffer() -> None:
    mqtt_capture.ingest_buffer.stop()
    mqtt_capture.ingest_buffer.drain(lambda _topic, _payload: None)


def test_packets_during_write_locking_migrations_are_replayed(tmp_path, monkeypatch):
    """A packet that arrives while BLOCKING migrations run is stored afterwards."""

    db = str(tmp_path / "capture.db")
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db)
    _reset_buffer()

    mqtt_capture.init_database()  # SCHEMA phase: the ingest path can write
    mqtt_capture.ingest_buffer.start()

    mqtt_capture.on_message(None, None, _message())  # type: ignore[arg-type]
    assert mqtt_capture.ingest_buffer.depth == 1
    assert _packet_count(db) == 0  # buffered, not written

    mqtt_capture.run_write_locking_migrations()
    drained = mqtt_capture.ingest_buffer.drain(mqtt_capture.process_message)

    assert drained == 1
    assert mqtt_capture.ingest_buffer.buffering is False
    assert _packet_count(db) == 1


def test_packets_after_the_drain_are_processed_directly(tmp_path, monkeypatch):
    """Once the drain finishes, later packets take the normal ingest path."""

    db = str(tmp_path / "capture2.db")
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db)
    _reset_buffer()

    mqtt_capture.init_database()
    mqtt_capture.ingest_buffer.start()
    mqtt_capture.run_write_locking_migrations()
    mqtt_capture.ingest_buffer.drain(mqtt_capture.process_message)

    mqtt_capture.on_message(None, None, _message())  # type: ignore[arg-type]

    assert mqtt_capture.ingest_buffer.depth == 0
    assert _packet_count(db) == 1
