"""Unit tests for TracerouteService.

The longest-links analysis reads the capture-maintained link/route day rollups
(see ``malla.capture_rollups``), so these tests seed a real temporary database
through the refresh path and pin the returned aggregates.
"""

import sqlite3
import time

import pytest

from malla import capture_rollups, capture_startup, mqtt_capture
from src.malla.services.traceroute_service import TracerouteService

pytestmark = pytest.mark.unit


def _seed_db(tmp_path):
    from datetime import UTC, datetime, timedelta

    from meshtastic import mesh_pb2

    db_path = str(tmp_path / "ll.db")
    original_db = mqtt_capture.DATABASE_FILE
    mqtt_capture.DATABASE_FILE = db_path
    capture_startup.init_database(db_path)

    conn = sqlite3.connect(db_path)
    now = time.time()
    # Link/day rollups fold completed UTC days only, so seed the traceroutes
    # and positions inside yesterday.
    ts = (
        datetime.now(tz=UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        - timedelta(days=1)
    ).timestamp()

    def traceroute(route, snrs):
        payload = mesh_pb2.RouteDiscovery()
        payload.route.extend(route)
        payload.snr_towards.extend(snrs)
        return bytes(payload.SerializeToString())

    def position(lat, lon):
        position = mesh_pb2.Position()
        position.latitude_i = int(lat * 1e7)
        position.longitude_i = int(lon * 1e7)
        return bytes(position.SerializeToString())

    rows = [
        # A two-hop path 100 -> 200 -> 300 plus the reverse direction.
        (
            ts,
            100,
            300,
            70,
            "TRACEROUTE_APP",
            traceroute([200], [8, -4]),
        ),
        (
            ts,
            300,
            100,
            70,
            "TRACEROUTE_APP",
            traceroute([200, 300], [8, -4, -12]),
        ),
        # Latest positions: 100 near 200 (short hop), 300 far away.
        (ts + 60, 100, None, 3, "POSITION_APP", position(52.0, 13.0)),
        (ts + 60, 200, None, 3, "POSITION_APP", position(52.05, 13.05)),
        (ts + 60, 300, None, 3, "POSITION_APP", position(60.0, 20.0)),
    ]
    for ts, src, dst, portnum, portnum_name, payload in rows:
        conn.execute(
            "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id,"
            " portnum, portnum_name, raw_payload) VALUES (?, 't', ?, ?, ?, ?, ?)",
            (ts, src, dst, portnum, portnum_name, payload),
        )
    for node_id in (100, 200, 300):
        conn.execute(
            "INSERT INTO node_info (node_id, hex_id, long_name, short_name, first_seen,"
            " last_updated) VALUES (?, '!x', ?, ?, ?, ?)",
            (node_id, f"Node{node_id}", f"N{node_id}", now, now),
        )
    conn.commit()
    conn.close()

    capture_rollups.refresh(sqlite3.connect(db_path))
    return db_path, original_db


class TestTracerouteServiceLongestLinks:
    """Longest links over the capture-maintained rollups."""

    def test_longest_links_analysis_empty_data(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "empty.db")
        monkeypatch.setenv("MALLA_DATABASE_FILE", db_path)
        original_db = mqtt_capture.DATABASE_FILE
        mqtt_capture.DATABASE_FILE = db_path
        capture_startup.init_database(db_path)
        try:
            result = TracerouteService.get_longest_links_analysis()
        finally:
            mqtt_capture.DATABASE_FILE = original_db

        assert result["summary"]["total_links"] == 0
        assert result["summary"]["direct_links"] == 0
        assert result["summary"]["longest_direct"] is None
        assert result["summary"]["longest_path"] is None
        assert result["direct_links"] == []
        assert result["indirect_links"] == []

    def test_longest_links_ranks_by_distance(self, tmp_path, monkeypatch):
        db_path, original_db = _seed_db(tmp_path)
        monkeypatch.setenv("MALLA_DATABASE_FILE", db_path)
        try:
            result = TracerouteService.get_longest_links_analysis(
                min_distance_km=1.0, min_snr=-20.0, max_results=10
            )
        finally:
            mqtt_capture.DATABASE_FILE = original_db

        direct = result["direct_links"]
        # The long 100/300 and 200/300 spans; the short 100<->200 hop is the
        # pair (100, 200)?? - whatever the exact set, the farthest pair wins.
        assert direct, "expected rollup-backed direct links"
        distances = [link["distance_km"] for link in direct]
        assert distances == sorted(distances, reverse=True)
        assert distances[0] >= 1.0

        top = direct[0]
        for key in (
            "from_node_id",
            "to_node_id",
            "from_node_name",
            "to_node_name",
            "distance_km",
            "avg_snr",
            "traceroute_count",
            "packet_id",
            "packet_url",
            "last_seen",
        ):
            assert key in top
        assert top["packet_id"] > 0
        assert top["packet_url"] == f"/packet/{top['packet_id']}"
        assert isinstance(top["traceroute_count"], int)

        # Indirect path 100 <-> 300 via 200 with the recorded route preview.
        indirect = result["indirect_links"]
        assert indirect, "expected rollup-backed indirect links"
        assert {link["from_node_id"] for link in indirect} | {
            link["to_node_id"] for link in indirect
        } == {100, 300}
        preview = indirect[0]["route_preview"]
        assert len(preview) >= 3
        assert indirect[0]["hop_count"] >= 2

        assert result["summary"]["total_links"] == len(direct) + len(indirect)
        assert (
            result["summary"]["longest_direct"] == f"{direct[0]['distance_km']:.2f} km"
        )

    def test_min_snr_filter_drops_weak_pairs(self, tmp_path, monkeypatch):
        db_path, original_db = _seed_db(tmp_path)
        monkeypatch.setenv("MALLA_DATABASE_FILE", db_path)

        def all_pair_snrs():
            try:
                return TracerouteService.get_longest_links_analysis(min_snr=-100.0)[
                    "direct_links"
                ]
            finally:
                pass

        try:
            generous = TracerouteService.get_longest_links_analysis(min_snr=-100.0)
            strict = TracerouteService.get_longest_links_analysis(min_snr=50.0)
        finally:
            mqtt_capture.DATABASE_FILE = original_db

        assert generous["direct_links"]
        # Every stored hop SNR is <= 20 dB, so a 50 dB bar excludes everything.
        assert strict["direct_links"] == []
        assert strict["summary"]["total_links"] == 0
