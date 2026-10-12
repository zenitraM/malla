"""The capture must not lose packets published while startup migrations run."""

import socket
import sqlite3

import paho.mqtt.client as mqtt
from meshtastic import mqtt_pb2, portnums_pb2

from malla import capture_startup, mqtt_capture
from malla.migrations import Phase

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

    capture_startup.init_database(db)  # SCHEMA phase: the ingest path can write
    mqtt_capture.ingest_buffer.start()

    mqtt_capture.on_message(None, None, _message())  # type: ignore[arg-type]
    assert mqtt_capture.ingest_buffer.depth == 1
    assert _packet_count(db) == 0  # buffered, not written

    capture_startup.run_write_locking_migrations(db)
    drained = mqtt_capture.ingest_buffer.drain(mqtt_capture.process_message)

    assert drained == 1
    assert mqtt_capture.ingest_buffer.buffering is False
    assert _packet_count(db) == 1


def test_packets_after_the_drain_are_processed_directly(tmp_path, monkeypatch):
    """Once the drain finishes, later packets take the normal ingest path."""

    db = str(tmp_path / "capture2.db")
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db)
    _reset_buffer()

    capture_startup.init_database(db)
    mqtt_capture.ingest_buffer.start()
    capture_startup.run_write_locking_migrations(db)
    mqtt_capture.ingest_buffer.drain(mqtt_capture.process_message)

    mqtt_capture.on_message(None, None, _message())  # type: ignore[arg-type]

    assert mqtt_capture.ingest_buffer.depth == 0
    assert _packet_count(db) == 1


def test_derived_phase_does_not_take_the_migration_lock(tmp_path):
    """DERIVED work is idempotent, so it runs without the runner lock.

    Holding it would let a multi-minute phase be mistaken for a dead holder and
    have the lock stolen; the seeded holder is a dead local pid so a regression
    shows up immediately (the phase would take the row over) instead of after
    the lock timeout.
    """
    db = str(tmp_path / "derived.db")
    capture_startup.init_database(db)

    dead_holder = f"{socket.gethostname()}:999999999"
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES ('migration_lock', ?, ?)",
        (dead_holder, 0.0),
    )
    conn.commit()
    conn.close()

    results = capture_startup.run_phase(db, Phase.DERIVED)

    assert [result.name for result in results]  # the phase ran
    conn = sqlite3.connect(db)
    try:
        holder = conn.execute(
            "SELECT value FROM malla_meta WHERE key = 'migration_lock'"
        ).fetchone()
    finally:
        conn.close()
    assert holder == (dead_holder,)
