"""UNKNOWN_<n> hardware models get their name once the protobufs know it."""

import sqlite3

from meshtastic import mesh_pb2

from src.malla import mqtt_capture


def test_init_database_names_previously_unknown_hardware(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rename.db")
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)
    monkeypatch.setattr(mqtt_capture, "seed_query_planner_stats_async", lambda *_: None)
    mqtt_capture.init_database()

    known_number = max(
        v.number for v in mesh_pb2.HardwareModel.DESCRIPTOR.values if v.number < 255
    )
    known_name = mesh_pb2.HardwareModel.Name(known_number)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO node_info (node_id, hex_id, hw_model, first_seen, last_updated) VALUES (?, ?, ?, 0, 0)",
        [
            (1, "!00000001", f"UNKNOWN_{known_number}"),
            (2, "!00000002", f"UNKNOWN_{known_number}"),
            (3, "!00000003", "UNKNOWN_999999"),  # still unknown to these protobufs
            (4, "!00000004", "UNKNOWN_0"),  # UNSET stays as it was captured
            (5, "!00000005", "HELTEC_V3"),
        ],
    )
    conn.commit()
    conn.close()

    mqtt_capture.init_database()  # second start after a protobuf upgrade

    conn = sqlite3.connect(db_path)
    rows = dict(
        conn.execute("SELECT node_id, hw_model FROM node_info ORDER BY node_id")
    )
    conn.close()
    assert rows == {
        1: known_name,
        2: known_name,
        3: "UNKNOWN_999999",
        4: "UNKNOWN_0",
        5: "HELTEC_V3",
    }


def test_rename_is_idempotent_and_counts_rows(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE node_info (node_id INTEGER PRIMARY KEY, hex_id TEXT, hw_model TEXT, first_seen REAL, last_updated REAL)"
    )
    conn.execute(
        "INSERT INTO node_info VALUES (1, '!1', 'UNKNOWN_43', 0, 0)"
    )  # 43 = HELTEC_V3
    assert mqtt_capture.rename_unknown_hardware_models(conn.cursor()) == 1
    assert conn.execute("SELECT hw_model FROM node_info").fetchone()[0] == "HELTEC_V3"
    assert mqtt_capture.rename_unknown_hardware_models(conn.cursor()) == 0
