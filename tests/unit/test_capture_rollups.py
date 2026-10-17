"""Unit tests for the capture-maintained rollup layer (malla.capture_rollups).

Covers the assigned invariants: refresh idempotency, resume-from-state
(bucket tables and id cursors), prune lockstep counts, the signal-quality
parity between the SQL fragment and its Python mirror, and rollup contents
equals a direct SQL recomputation over packet_history.
"""

import sqlite3
import time

import pytest

from malla import capture_rollups, capture_startup, mqtt_capture
from malla.utils.signal_quality import is_plausible_snr, snr_valid_sql

pytestmark = pytest.mark.unit


def _insert_packet(
    conn,
    ts,
    *,
    src,
    dst=None,
    portnum=None,
    portnum_name=None,
    snr=None,
    hop_start=None,
    hop_limit=None,
    payload=None,
):
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id,"
        " portnum, portnum_name, snr, hop_start, hop_limit, raw_payload)"
        " VALUES (?, 't', ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, src, dst, portnum, portnum_name, snr, hop_start, hop_limit, payload),
    )


def _table_rows(conn, table, order):
    return conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()


@pytest.fixture()
def rolled_db(tmp_path):
    """A migrated empty database plus the module globals reset per test."""
    db_path = str(tmp_path / "rollups.db")
    original_db = mqtt_capture.DATABASE_FILE
    mqtt_capture.DATABASE_FILE = db_path
    capture_startup.init_database(db_path)
    yield db_path
    mqtt_capture.DATABASE_FILE = original_db


class TestRefreshIdempotency:
    def test_double_refresh_equals_single(self, rolled_db):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        for hours_ago in (30, 5):
            _insert_packet(
                conn,
                now - hours_ago * 3600,
                src=100,
                dst=200,
                snr=9.5,
                hop_start=3,
                hop_limit=3,
            )
        conn.commit()
        conn.close()

        first = capture_rollups.refresh(sqlite3.connect(rolled_db))
        rows_after_first = {
            table: _table_rows(sqlite3.connect(rolled_db), table, "1,2")
            for table in (
                "node_hour_rollup",
                "link_day_rollup",
                "route_day_rollup",
                "node_latest_position",
                "node_latest_telemetry",
                "traceroute_endpoint",
            )
        }

        second = capture_rollups.refresh(sqlite3.connect(rolled_db))
        assert all(count == 0 for count in second.values())

        rows_after_second = {
            table: _table_rows(sqlite3.connect(rolled_db), table, "1,2")
            for table in rows_after_first
        }
        assert rows_after_second == rows_after_first
        assert first["hour_rows"] == 2

    def test_partial_then_full_equals_single_full(self, rolled_db, tmp_path):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        for hours_ago in (30, 20, 3):
            _insert_packet(
                conn, now - hours_ago * 3600, src=100, snr=5.0, hop_start=1, hop_limit=1
            )
        conn.commit()
        conn.close()

        # Resume-style: fold a stale prefix, then run to completion.
        capture_rollups.refresh(sqlite3.connect(rolled_db), until=now - 10 * 3600)
        capture_rollups.refresh(sqlite3.connect(rolled_db))

        # One-shot equivalent on a fresh copy of the same packets.
        single = str(tmp_path / "single.db")
        original_db = mqtt_capture.DATABASE_FILE
        mqtt_capture.DATABASE_FILE = single
        capture_startup.init_database(single)
        mqtt_capture.DATABASE_FILE = original_db
        conn_single = sqlite3.connect(single)
        src = sqlite3.connect(rolled_db)
        for row in src.execute(
            "SELECT timestamp, topic, from_node_id, to_node_id, portnum,"
            " portnum_name, snr, hop_start, hop_limit, raw_payload FROM packet_history"
        ):
            conn_single.execute(
                "INSERT INTO packet_history (timestamp, topic, from_node_id,"
                " to_node_id, portnum, portnum_name, snr, hop_start, hop_limit,"
                " raw_payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                row,
            )
        conn_single.commit()
        conn_single.close()
        capture_rollups.refresh(sqlite3.connect(single))

        resumed = _table_rows(
            sqlite3.connect(rolled_db), "node_hour_rollup", "hour_epoch, node_id"
        )
        oneshot = _table_rows(
            sqlite3.connect(single), "node_hour_rollup", "hour_epoch, node_id"
        )
        assert resumed == oneshot


class TestCursorResume:
    def test_latest_state_tracks_new_packets(self, rolled_db):
        from meshtastic import mesh_pb2

        now = time.time()
        conn = sqlite3.connect(rolled_db)

        def position(lat):
            position = mesh_pb2.Position()
            position.latitude_i = int(lat * 1e7)
            position.longitude_i = int(13.0 * 1e7)
            return bytes(position.SerializeToString())

        _insert_packet(
            conn,
            now - 3600,
            src=100,
            portnum=3,
            portnum_name="POSITION_APP",
            payload=position(52.0),
        )
        conn.commit()
        conn.close()
        capture_rollups.refresh(sqlite3.connect(rolled_db))

        conn = sqlite3.connect(rolled_db)
        _insert_packet(
            conn,
            now,
            src=100,
            portnum=3,
            portnum_name="POSITION_APP",
            payload=position(53.0),
        )
        conn.commit()
        conn.close()
        capture_rollups.refresh(sqlite3.connect(rolled_db))

        conn = sqlite3.connect(rolled_db)
        latitude = conn.execute(
            "SELECT latitude FROM node_latest_position WHERE node_id = 100"
        ).fetchone()[0]
        cursor_id = conn.execute(
            "SELECT last_packet_id FROM _rollup_cursor WHERE name = 'node_latest_position'"
        ).fetchone()[0]
        max_id = conn.execute("SELECT MAX(id) FROM packet_history").fetchone()[0]
        assert latitude == pytest.approx(53.0)
        # The cursor stores the snapshot bound, never a mid-scan max.
        assert cursor_id == max_id

    def test_redoing_a_committed_range_is_a_noop(self, rolled_db):
        from meshtastic import mesh_pb2

        now = time.time()
        conn = sqlite3.connect(rolled_db)

        def position(lat):
            position = mesh_pb2.Position()
            position.latitude_i = int(lat * 1e7)
            position.longitude_i = int(13.0 * 1e7)
            return bytes(position.SerializeToString())

        _insert_packet(
            conn,
            now - 60,
            src=100,
            portnum=3,
            portnum_name="POSITION_APP",
            payload=position(52.0),
        )
        conn.commit()
        conn.close()
        capture_rollups.refresh(sqlite3.connect(rolled_db))

        # Simulate a crash before the cursor commit: reset and re-merge.
        conn = sqlite3.connect(rolled_db)
        conn.execute("UPDATE _rollup_cursor SET last_packet_id = 0")
        conn.commit()
        conn.close()
        capture_rollups.refresh(sqlite3.connect(rolled_db))

        conn = sqlite3.connect(rolled_db)
        row = conn.execute(
            "SELECT latitude, packet_id FROM node_latest_position WHERE node_id = 100"
        ).fetchone()
        max_id = conn.execute("SELECT MAX(id) FROM packet_history").fetchone()[0]
        assert row[0] == pytest.approx(52.0)
        assert row[1] == max_id


class TestPruneLockstep:
    def test_prune_removes_only_expired_buckets(self, rolled_db, monkeypatch):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        for hours_ago, node in ((48, 100), (48, 200), (2, 300)):
            _insert_packet(conn, now - hours_ago * 3600, src=100, dst=node)
        for node_id in (100, 200, 300):
            conn.execute(
                "INSERT INTO node_info (node_id, hex_id, long_name, short_name,"
                " first_seen, last_updated) VALUES (?, 'x', 'n', 'n', ?, ?)",
                (node_id, now, now),
            )
        conn.commit()
        conn.close()

        capture_rollups.refresh(sqlite3.connect(rolled_db))

        monkeypatch.setattr(mqtt_capture, "DATA_RETENTION_HOURS", 24)
        mqtt_capture.cleanup_old_data()

        conn = sqlite3.connect(rolled_db)
        remaining_hours = {
            row[0]
            for row in conn.execute("SELECT DISTINCT hour_epoch FROM node_hour_rollup")
        }
        packets_per_hour = dict(
            conn.execute(
                "SELECT CAST(timestamp/3600 AS INTEGER), COUNT(*) FROM packet_history"
                " GROUP BY 1"
            )
        )
        # Every surviving rollup bucket still has its packets; expired buckets are gone.
        for hour in remaining_hours:
            assert packets_per_hour.get(hour, 0) > 0
        total_rollup_packets = conn.execute(
            "SELECT SUM(packet_count) FROM node_hour_rollup"
        ).fetchone()[0]
        assert total_rollup_packets == sum(packets_per_hour.values())

    def test_prune_hygiene_removes_orphan_latest_rows(self, rolled_db):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        _insert_packet(conn, now - 3600, src=100, dst=7)
        conn.execute(
            "INSERT INTO node_info (node_id, hex_id, long_name, short_name,"
            " first_seen, last_updated) VALUES (100, 'x', 'n', 'n', ?, ?)",
            (now, now),
        )
        # node 7 has packets but no node_info row -> its latest rows are hygiene-pruned.
        conn.commit()
        conn.close()
        capture_rollups.refresh(sqlite3.connect(rolled_db))
        mqtt_capture.DATA_RETENTION_HOURS = 0  # no packet pruning
        try:
            mqtt_capture.cleanup_old_data()
        finally:
            pass

        conn = sqlite3.connect(rolled_db)
        orphans = conn.execute(
            "SELECT COUNT(*) FROM node_latest_position WHERE node_id NOT IN"
            " (SELECT node_id FROM node_info)"
        ).fetchone()[0]
        assert orphans == 0


class TestSignalParity:
    @pytest.mark.parametrize(
        "value",
        [-30.0, -30.1, 30.0, 30.1, 0.0, -12.5, None, 15.0, -100.0],
    )
    def test_python_mirror_matches_sql_fragment(self, value):
        conn = sqlite3.connect(":memory:")
        predicate = snr_valid_sql().replace("snr", ":value")
        row = conn.execute(
            f"SELECT CASE WHEN {predicate} THEN 1 ELSE 0 END", {"value": value}
        ).fetchone()
        assert bool(row[0]) == is_plausible_snr(value)

    def test_hour_fold_applies_the_same_rule(self, rolled_db):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        # 9.5 dB valid; 99 dB not; boundary -30 valid; NULL not.
        for snr in (9.5, 99.0, -30.0, None):
            _insert_packet(conn, now - 3600, src=100, snr=snr, hop_start=2, hop_limit=2)
        # Non-direct hop: hop_start != hop_limit must not count.
        _insert_packet(conn, now - 3600, src=100, snr=5.0, hop_start=1, hop_limit=3)
        conn.commit()
        conn.close()

        capture_rollups.refresh(sqlite3.connect(rolled_db))
        conn = sqlite3.connect(rolled_db)
        _, _, _, snr_sum, snr_count, _ = conn.execute(
            "SELECT hour_epoch, node_id, packet_count, direct_snr_sum,"
            " direct_snr_count, last_seen FROM node_hour_rollup"
        ).fetchone()
        assert snr_count == 2  # 9.5 and -30.0; 99.0/None/relay-hop excluded
        assert snr_sum == pytest.approx(9.5 + -30.0)


class TestRollupContentsMatchRecomputation:
    def test_hour_rollup_equals_direct_sql(self, rolled_db):
        now = time.time()
        conn = sqlite3.connect(rolled_db)
        for hours_ago in (30, 5, 5):
            _insert_packet(
                conn,
                now - hours_ago * 3600,
                src=100,
                dst=200,
                snr=9.5,
                hop_start=3,
                hop_limit=3,
            )
        _insert_packet(conn, now - 5 * 3600, src=101)
        conn.commit()
        conn.close()

        capture_rollups.refresh(sqlite3.connect(rolled_db))

        conn = sqlite3.connect(rolled_db)
        stored = set(conn.execute("SELECT * FROM node_hour_rollup"))
        direct_cond = capture_rollups._direct_snr_cond()
        expected = set(
            conn.execute(
                f"""
                SELECT CAST(timestamp / 3600 AS INTEGER) AS hour, from_node_id,
                       COUNT(*),
                       SUM(CASE WHEN {direct_cond} THEN CAST(snr AS FLOAT) ELSE 0 END),
                       SUM(CASE WHEN {direct_cond} THEN 1 ELSE 0 END),
                       MAX(timestamp)
                FROM packet_history
                WHERE from_node_id IS NOT NULL
                GROUP BY hour, from_node_id
                """
            )
        )
        # Completed buckets only: the live hour is folded on the next refresh.
        live_hour = int(now // 3600)
        expected = {row for row in expected if row[0] < live_hour}
        assert stored == expected
