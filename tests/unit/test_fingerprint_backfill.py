"""Backfill of firmware fingerprints from stored history, incl. the auto-run."""

import os
import sqlite3
import tempfile
import time
from unittest.mock import patch

import pytest
from meshtastic import mesh_pb2

from src.malla import mqtt_capture
from src.malla.fingerprint import relay_marker_for
from src.malla.fingerprint_backfill import (
    BACKFILL_MARKER_KEY,
    backfill,
    read_backfill_marker,
)
from tests.fixtures.database_fixtures import DatabaseFixtures

NODE = 0x0400CE8C
PUBKEY = bytes(range(64, 96))


@pytest.fixture()
def db_path():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    DatabaseFixtures().create_test_database(tmp.name)
    yield tmp.name
    try:
        os.unlink(tmp.name)
    except FileNotFoundError:
        pass


def _insert(
    db,
    *,
    ts,
    portnum_name,
    to_node=0xFFFFFFFF,
    hop_start=3,
    hop_limit=3,
    relay=None,
    payload=b"",
):
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO packet_history
            (timestamp, topic, from_node_id, to_node_id, portnum_name, hop_start,
             hop_limit, relay_node, payload_length, raw_payload, processed_successfully)
        VALUES (?, 'msh/test', ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            ts,
            NODE,
            to_node,
            portnum_name,
            hop_start,
            hop_limit,
            relay,
            len(payload),
            payload,
        ),
    )
    conn.commit()
    conn.close()


def _nodeinfo_payload():
    user = mesh_pb2.User()
    user.id = f"!{NODE:08x}"
    user.public_key = PUBKEY
    user.is_unmessagable = False
    return user.SerializeToString()


def test_backfill_writes_evidence_and_marker(db_path):
    now = time.time()
    _insert(
        db_path,
        ts=now - 100,
        portnum_name="NODEINFO_APP",
        relay=relay_marker_for(NODE),
        payload=_nodeinfo_payload(),
    )
    for i in range(3):
        _insert(
            db_path,
            ts=now - 50 - i,
            portnum_name="POSITION_APP",
            relay=relay_marker_for(NODE),
        )
    # after `until`: must be ignored (the live daemon owns it)
    _insert(
        db_path, ts=now + 100, portnum_name="POSITION_APP", relay=relay_marker_for(NODE)
    )

    assert read_backfill_marker(db_path) is None
    stats = backfill(db_path, days=1, until=now + 1, keys=[])
    assert stats["nodes"] >= 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM node_fingerprint WHERE node_id = ?", (NODE,)
    ).fetchone()
    marker = conn.execute(
        "SELECT value FROM malla_meta WHERE key = ?", (BACKFILL_MARKER_KEY,)
    ).fetchone()
    conn.close()
    assert row["nodeinfo_count"] == 1
    assert row["has_public_key"] == 1
    assert row["has_unmessagable_field"] == 1
    assert row["relay_self_count"] == 4  # nodeinfo + 3 positions, not the future one
    assert float(marker[0]) == pytest.approx(now + 1)
    assert read_backfill_marker(db_path) == pytest.approx(now + 1)


def test_dry_run_writes_nothing(db_path):
    now = time.time()
    _insert(
        db_path, ts=now - 10, portnum_name="NODEINFO_APP", payload=_nodeinfo_payload()
    )
    backfill(db_path, days=1, until=now, keys=[], dry_run=True)
    conn = sqlite3.connect(db_path)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    count = (
        conn.execute("SELECT COUNT(*) FROM node_fingerprint").fetchone()[0]
        if "node_fingerprint" in tables
        else 0
    )
    conn.close()
    assert count == 0
    assert read_backfill_marker(db_path) is None


def test_auto_backfill_disabled_by_config(monkeypatch, db_path):
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
    monkeypatch.setattr(mqtt_capture, "FINGERPRINT_BACKFILL_DAYS", 0)
    with patch("src.malla.fingerprint_backfill.backfill") as fake:
        assert mqtt_capture.start_fingerprint_backfill_if_needed() is None
        fake.assert_not_called()


def test_auto_backfill_skipped_once_marker_exists(monkeypatch, db_path):
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
    monkeypatch.setattr(mqtt_capture, "FINGERPRINT_BACKFILL_DAYS", 30)
    backfill(db_path, days=1, until=time.time(), keys=[])  # writes the marker
    with patch("src.malla.fingerprint_backfill.backfill") as fake:
        assert mqtt_capture.start_fingerprint_backfill_if_needed() is None
        fake.assert_not_called()


def test_auto_backfill_runs_once_in_background(monkeypatch, db_path):
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
    monkeypatch.setattr(mqtt_capture, "FINGERPRINT_BACKFILL_DAYS", 30)
    monkeypatch.setattr(mqtt_capture, "DECRYPTION_KEYS", ["1PG7OiApB1nwvP+rz05pAQ=="])
    calls = []

    def fake_backfill(db, **kwargs):
        calls.append((db, kwargs))
        return {"nodes": 0}

    before = time.time()
    with patch("src.malla.fingerprint_backfill.backfill", side_effect=fake_backfill):
        thread = mqtt_capture.start_fingerprint_backfill_if_needed()
        assert thread is not None
        thread.join(timeout=10)
    assert not thread.is_alive()
    ((db, kwargs),) = calls
    assert db == db_path
    assert kwargs["days"] == 30
    assert before <= kwargs["until"] <= time.time()
    assert kwargs["lock"] is mqtt_capture.db_lock
    assert kwargs["keys"] == ["1PG7OiApB1nwvP+rz05pAQ=="]


def test_backfill_decrypts_aead_envelopes(db_path):
    from meshtastic import mqtt_pb2

    from tests.unit.test_mqtt_capture_fingerprint import (
        DEFAULT_KEY_B64,
        _encrypted_packet,
    )

    now = time.time()
    packet = _encrypted_packet(NODE, packet_id=0x0BADCAFE)
    env = mqtt_pb2.ServiceEnvelope()
    env.channel_id = "MediumFast"
    env.gateway_id = "!a2e96b40"
    env.packet.CopyFrom(packet)
    conn = sqlite3.connect(db_path)
    # the test fixture predates this column; the capture daemon adds it on startup
    conn.execute("ALTER TABLE packet_history ADD COLUMN raw_service_envelope BLOB")
    conn.execute(
        """
        INSERT INTO packet_history
            (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name, hop_start,
             hop_limit, relay_node, payload_length, raw_payload, raw_service_envelope, processed_successfully)
        VALUES (?, 'msh/test', ?, ?, 0, 'UNKNOWN_APP', 3, 3, ?, 0, X'', ?, 1)
        """,
        (now - 5, NODE, 0xFFFFFFFF, relay_marker_for(NODE), env.SerializeToString()),
    )
    conn.commit()
    conn.close()

    backfill(db_path, days=1, until=now + 1, keys=[DEFAULT_KEY_B64])
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM node_fingerprint WHERE node_id = ?", (NODE,)
    ).fetchone()
    conn.close()
    assert row["aead_count"] == 1
