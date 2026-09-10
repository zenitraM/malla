"""Behavioral checks for capture, raw-only imports, and resumable preparation."""

import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2

from malla import mqtt_capture
from malla.backfill_traceroutes import main, prepare_traceroutes
from malla.database.schema import ensure_startup_schema
from malla.database.traceroute_schema import ensure_traceroute_schema
from malla.database.traceroutes import (
    PARSER_VERSION,
    decode_traceroute,
    inspect_traceroutes,
    write_traceroute,
)
from malla.models.traceroute import TraceroutePacket

pytestmark = pytest.mark.unit


def payload(route=(), snr=(), back=(), snr_back=()):
    return mesh_pb2.RouteDiscovery(
        route=route, snr_towards=snr, route_back=back, snr_back=snr_back
    ).SerializeToString()


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "history.db"
    monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", str(path))
    monkeypatch.setattr(
        mqtt_capture, "seed_query_planner_stats_async", lambda *_: False
    )
    mqtt_capture.init_database()
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        yield path, conn


def insert_raw(conn, raw, **overrides):
    fields = {
        "timestamp": 1000.0,
        "topic": "msh/test/e/LongFast/!12345678",
        "from_node_id": 100,
        "to_node_id": 200,
        "portnum": 70,
        "portnum_name": "TRACEROUTE_APP",
        "mesh_packet_id": 42,
        "gateway_id": "!12345678",
        "hop_start": 5,
        "hop_limit": 3,
        "raw_payload": raw,
        **overrides,
    }
    cursor = conn.execute(
        f"INSERT INTO packet_history ({', '.join(fields)}) "
        f"VALUES ({', '.join('?' for _ in fields)})",
        list(fields.values()),
    )
    return dict(
        conn.execute(
            "SELECT * FROM packet_history WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    )


def capture(raw, gateway="!12345678"):
    packet = mesh_pb2.MeshPacket(id=42, to=200, hop_start=5, hop_limit=3)
    setattr(packet, "from", 100)
    packet.decoded.portnum = portnums_pb2.PortNum.TRACEROUTE_APP
    packet.decoded.payload = raw
    envelope = mqtt_pb2.ServiceEnvelope(gateway_id=gateway, channel_id="LongFast")
    mqtt_capture.log_packet_to_database("msh/test/e/LongFast", envelope, packet)


@pytest.mark.parametrize(
    "raw",
    [
        payload(snr=[-16]),
        payload(route=[110], snr=[-20]),
        payload(route=[110], snr=[-20, -32], back=[120], snr_back=[4, -12]),
        payload(route=[110, 100, 110], snr=[4, 8, 12, 16]),
        payload(route=[110, 120]),
        payload(snr=[-128]),
        b"",
    ],
)
def test_decoder_preserves_existing_path_rules_without_lookups(raw):
    packet = {
        "from_node_id": 100,
        "to_node_id": 200,
        "hop_start": 5,
        "hop_limit": 3,
        "raw_payload": raw,
    }
    expected = TraceroutePacket(packet, resolve_names=False)
    with patch(
        "malla.models.traceroute.TraceroutePacket._resolve_node_names",
        side_effect=AssertionError("no lookup"),
    ):
        decoded = decode_traceroute(packet)
    assert decoded.route == expected.route_data
    assert decoded.hops == tuple(expected.get_rf_hops())
    assert decoded.forward_complete == expected.is_complete()
    assert decoded.return_complete == expected.is_return_complete()


def test_capture_preserves_repeated_hops_and_gateway_receptions(database):
    _, conn = database
    raw = payload(route=[110, 100, 110], snr=[4, 8, 12, 16])
    capture(raw)
    capture(raw, gateway="!87654321")
    routes = conn.execute(
        "SELECT * FROM traceroute_routes ORDER BY packet_id"
    ).fetchall()
    assert len(routes) == 2
    assert routes[0]["mesh_packet_id"] == routes[1]["mesh_packet_id"] == 42
    for route in routes:
        assert route["parse_status"] == "parsed"
        assert json.loads(route["route_nodes_json"]) == [110, 100, 110]
    hops = conn.execute(
        "SELECT hop_index, from_node_id, to_node_id, snr, reception_count FROM traceroute_hops "
        "WHERE mesh_packet_id = 42 ORDER BY hop_index"
    ).fetchall()
    assert [tuple(hop) for hop in hops] == [
        (0, 200, 110, 1.0, 2),
        (1, 110, 100, 2.0, 2),
        (2, 100, 110, 3.0, 2),
        (3, 110, 100, 4.0, 2),
    ]
    assert conn.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[0] == 4


def test_capture_and_backfill_are_identical(database):
    _, conn = database
    raw = payload(route=[110], snr=[-20, -32], back=[120], snr_back=[4, -128])
    capture(raw)
    before_route = dict(conn.execute("SELECT * FROM traceroute_routes").fetchone())
    before_hops = [
        tuple(row)
        for row in conn.execute(
            "SELECT * FROM traceroute_hops ORDER BY direction, hop_index"
        )
    ]
    with conn:
        conn.execute("DELETE FROM traceroute_routes")
    result = prepare_traceroutes(conn)
    after_route = dict(conn.execute("SELECT * FROM traceroute_routes").fetchone())
    before_route.pop("materialized_at")
    after_route.pop("materialized_at")
    assert before_route == after_route
    assert before_hops == [
        tuple(row)
        for row in conn.execute(
            "SELECT * FROM traceroute_hops ORDER BY direction, hop_index"
        )
    ]
    assert result["complete"]
    assert result["processed_this_run"] == 1


@pytest.mark.parametrize(
    "raw,status", [(b"\xff", "invalid_payload"), (b"", "valid_empty")]
)
def test_capture_keeps_malformed_and_empty_packets_distinct(database, raw, status):
    _, conn = database
    capture(raw)
    assert conn.execute("SELECT raw_payload FROM packet_history").fetchone()[0] == raw
    route = conn.execute("SELECT * FROM traceroute_routes").fetchone()
    assert route["parse_status"] == status
    assert bool(route["parse_error"]) == (status == "invalid_payload")
    assert conn.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[0] == 0
    assert prepare_traceroutes(conn)["processed_this_run"] == 0


def test_capture_storage_failure_rolls_back_raw_and_all_derived_rows(database):
    _, conn = database
    with conn:
        conn.execute("""
            CREATE TRIGGER reject_second_hop BEFORE INSERT ON traceroute_hops
            WHEN NEW.hop_index = 1 BEGIN SELECT RAISE(ABORT, 'test storage failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="test storage failure"):
        capture(payload(route=[110], snr=[4, 8]))
    for table in ("packet_history", "traceroute_routes", "traceroute_hops"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # The failed capture connection was closed and its lock released.
    capture(payload(snr=[4]))
    assert conn.execute("SELECT COUNT(*) FROM traceroute_routes").fetchone()[0] == 1


def test_pending_imports_and_decoder_versions_affect_completeness(database):
    _, conn = database
    assert inspect_traceroutes(conn.cursor())["complete"]
    with conn:
        packet = insert_raw(conn, payload(snr=[4]))
    assert not inspect_traceroutes(conn.cursor())["complete"]
    assert prepare_traceroutes(conn)["complete"]
    assert inspect_traceroutes(conn.cursor())["complete"]
    with conn:
        packet = insert_raw(conn, payload(snr=[4]))
    assert not inspect_traceroutes(conn.cursor())["complete"]
    with conn:
        conn.execute("BEGIN")
        write_traceroute(conn.cursor(), packet)
    assert inspect_traceroutes(conn.cursor())["complete"]
    with patch("malla.database.traceroutes.PARSER_VERSION", PARSER_VERSION + 1):
        assert not inspect_traceroutes(conn.cursor())["complete"]
    capture(payload(snr=[8]))
    assert inspect_traceroutes(conn.cursor())["complete"]


def test_raw_only_updates_and_replacements_remove_stale_hops(database):
    _, conn = database
    capture(payload(route=[110], snr=[4, 8]))
    assert prepare_traceroutes(conn)["complete"]
    with conn:
        conn.execute(
            "UPDATE packet_history SET raw_payload = ?", (payload(route=[120]),)
        )
    assert not inspect_traceroutes(conn.cursor())["complete"]
    assert conn.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[0] == 0
    assert prepare_traceroutes(conn)["complete"]
    assert json.loads(
        conn.execute("SELECT route_nodes_json FROM traceroute_routes").fetchone()[0]
    ) == [120]
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO packet_history (id, timestamp, topic, portnum) VALUES (1, 1000, 'test', 1)"
        )
    assert conn.execute("SELECT COUNT(*) FROM traceroute_routes").fetchone()[0] == 0


@pytest.mark.parametrize("foreign_keys", [True, False])
def test_raw_deletion_cleans_derived_rows_even_for_raw_only_importers(
    database, foreign_keys
):
    _, conn = database
    capture(payload(snr=[4]))
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    with conn:
        conn.execute("DELETE FROM packet_history")
    assert conn.execute("SELECT COUNT(*) FROM traceroute_routes").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[0] == 0


def test_retention_deletes_route_and_hops(database, monkeypatch):
    _, conn = database
    with patch("malla.mqtt_capture.time.time", return_value=1000.0):
        capture(payload(snr=[4]))
    monkeypatch.setattr(mqtt_capture, "DATA_RETENTION_HOURS", 1)
    mqtt_capture.cleanup_old_data()
    for table in ("packet_history", "traceroute_routes", "traceroute_hops"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_backfill_batches_resume_without_retrying_invalid_packets(database):
    _, conn = database
    with conn:
        for raw in (
            payload(snr=[4]),
            b"\xff",
            payload(route=[110]),
            b"",
            payload(snr=[8]),
        ):
            insert_raw(conn, raw)
        insert_raw(conn, b"ordinary text", portnum=1, portnum_name="TEXT_MESSAGE_APP")

    def interrupt(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        prepare_traceroutes(conn, batch_size=2, progress=interrupt)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM traceroute_routes WHERE parser_version = ?",
            (PARSER_VERSION,),
        ).fetchone()[0]
        == 2
    )
    assert not inspect_traceroutes(conn.cursor())["complete"]
    result = prepare_traceroutes(conn, batch_size=2)
    assert result["raw_traceroutes"] == result["routes"] == 5
    assert result["invalid_payload"] == 1
    assert result["processed_this_run"] == 3
    assert result["complete"]
    rows = [
        tuple(row)
        for row in conn.execute("SELECT * FROM traceroute_routes ORDER BY packet_id")
    ]
    assert prepare_traceroutes(conn)["processed_this_run"] == 0
    assert rows == [
        tuple(row)
        for row in conn.execute("SELECT * FROM traceroute_routes ORDER BY packet_id")
    ]


def test_backfill_failed_batch_is_atomic_and_can_resume(database):
    _, conn = database
    with conn:
        for _ in range(3):
            insert_raw(conn, payload(snr=[4]))
        conn.execute("""
            CREATE TRIGGER reject_packet BEFORE INSERT ON traceroute_hops
            WHEN NEW.packet_id = 2 BEGIN SELECT RAISE(ABORT, 'batch failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="batch failure"):
        prepare_traceroutes(conn, batch_size=3)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM traceroute_routes WHERE parse_status = 'pending'"
        ).fetchone()[0]
        == 3
    )
    assert conn.execute("SELECT COUNT(*) FROM traceroute_hops").fetchone()[0] == 0
    with conn:
        conn.execute("DROP TRIGGER reject_packet")
    assert prepare_traceroutes(conn)["complete"]


def test_capture_can_commit_between_backfill_batches(database):
    _, conn = database
    with conn:
        for _ in range(4):
            insert_raw(conn, payload(snr=[4]))
    result = prepare_traceroutes(
        conn, batch_size=2, progress=lambda _: capture(payload(snr=[8]))
    )
    assert result["processed_this_run"] == 4
    assert result["routes"] == result["raw_traceroutes"] == 6
    assert result["complete"]


def test_raw_only_import_during_backfill_cannot_look_complete(database):
    path, conn = database
    with conn:
        insert_raw(conn, payload(snr=[4]))

    def raw_import(_):
        with closing(sqlite3.connect(path)) as other, other:
            other.row_factory = sqlite3.Row
            insert_raw(other, payload(snr=[8]))

    result = prepare_traceroutes(conn, progress=raw_import)
    assert not result["complete"]
    assert result["pending"] == 1
    assert prepare_traceroutes(conn)["complete"]


def test_missing_endpoints_are_not_coerced_and_missing_payload_is_reported(database):
    _, conn = database
    with conn:
        insert_raw(conn, None, mesh_packet_id=None, from_node_id=None, to_node_id=None)
        insert_raw(
            conn,
            payload(route=[110]),
            mesh_packet_id=None,
            from_node_id=None,
            to_node_id=None,
        )
    result = prepare_traceroutes(conn)
    assert result["invalid_payload"] == 1
    assert result["parsed"] == 1
    assert result["hops"] == 0
    for row in conn.execute("SELECT * FROM traceroute_routes"):
        assert row["from_node_id"] is row["to_node_id"] is row["mesh_packet_id"] is None


def test_version_downgrade_is_rejected(database):
    _, conn = database
    capture(payload(snr=[4]))
    with conn:
        conn.execute(
            "UPDATE traceroute_routes SET parser_version = ?", (PARSER_VERSION + 1,)
        )
    with pytest.raises(ValueError, match="newer traceroute decoder"):
        prepare_traceroutes(conn)
    assert not inspect_traceroutes(conn.cursor())["complete"]


def test_cli_requires_explicit_database_and_rejects_missing_path(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    path = tmp_path / "missing.db"
    assert main(["--database", str(path)]) == 1
    assert not path.exists()


def test_cli_check_does_not_create_schema_or_change_history(database, capsys):
    path, conn = database
    with conn:
        for event in ("insert", "update", "delete"):
            conn.execute(f"DROP TRIGGER traceroute_packet_{event}")
        conn.execute("DROP TABLE traceroute_hops")
        conn.execute("DROP TABLE traceroute_routes")
        insert_raw(conn, payload(snr=[4]))
    before = list(conn.iterdump())
    assert main(["--database", str(path), "--check"]) == 1
    assert list(conn.iterdump()) == before
    output = capsys.readouterr().out
    assert str(path.resolve()) in output
    assert '"missing": 1' in output
    # Shared startup creates tables and pending triggers, but does not backfill.
    with conn:
        ensure_startup_schema(conn.cursor())
    assert conn.execute("SELECT COUNT(*) FROM traceroute_routes").fetchone()[0] == 0
    assert not inspect_traceroutes(conn.cursor())["complete"]
    assert main(["--database", str(path), "--batch-size", "1"]) == 0
    assert inspect_traceroutes(conn.cursor())["complete"]


def test_validation_reports_missing_and_orphaned_rows(database):
    _, conn = database
    capture(payload(snr=[4]))
    conn.execute("PRAGMA foreign_keys=OFF")
    with conn:
        conn.execute("DELETE FROM traceroute_routes")
        ensure_traceroute_schema(conn.cursor())
    with conn:
        conn.execute("BEGIN")
        result = inspect_traceroutes(conn.cursor())
    assert result["missing"] == 1
    assert result["orphan_hops"] == 1
    assert not result["complete"]


def test_clearing_derived_history_invalidates_completeness(database):
    _, conn = database
    capture(payload(snr=[4]))
    assert prepare_traceroutes(conn)["complete"]
    with conn:
        conn.execute("DELETE FROM traceroute_routes")
    assert not inspect_traceroutes(conn.cursor())["complete"]
    assert prepare_traceroutes(conn)["complete"]
    with conn:
        conn.execute("DELETE FROM packet_history")
    assert inspect_traceroutes(conn.cursor())["complete"]


def test_backfill_includes_explicit_nonpositive_ids_and_either_port_field(database):
    _, conn = database
    with conn:
        insert_raw(conn, payload(snr=[4]), id=-1, portnum=None)
        insert_raw(conn, payload(snr=[4]), id=0, portnum_name=None)
    result = prepare_traceroutes(conn, batch_size=1)
    assert result["processed_this_run"] == 2
    assert result["complete"]


def test_new_decoder_reprepares_old_records(database, monkeypatch):
    _, conn = database
    capture(payload(snr=[4]))
    assert prepare_traceroutes(conn)["complete"]
    monkeypatch.setattr("malla.database.traceroutes.PARSER_VERSION", PARSER_VERSION + 1)
    monkeypatch.setattr("malla.backfill_traceroutes.PARSER_VERSION", PARSER_VERSION + 1)
    assert not inspect_traceroutes(conn.cursor())["complete"]
    result = prepare_traceroutes(conn)
    assert result["complete"]
    assert result["processed_this_run"] == 1
    assert (
        conn.execute("SELECT parser_version FROM traceroute_routes").fetchone()[0]
        == PARSER_VERSION + 1
    )
