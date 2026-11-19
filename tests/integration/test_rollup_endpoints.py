"""Integration: rollup-backed read paths serve real values.

The rewrites (locations latest-position rollup, node hour aggregates, battery
map, longest-links day rollups) must return populated, correctly-shaped
payloads once the capture refresh has run - not merely empty-shell 200s.
"""

import sqlite3
import time

import pytest

from malla import capture_rollups, capture_startup, mqtt_capture
from malla.config import AppConfig
from src.malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures


@pytest.fixture()
def rollup_client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "rollup_endpoints.db")
    monkeypatch.setenv("MALLA_DATABASE_FILE", db_path)
    original_db = mqtt_capture.DATABASE_FILE
    mqtt_capture.DATABASE_FILE = db_path

    DatabaseFixtures().create_test_database(db_path)
    capture_startup.init_database(db_path)  # rollup tables the refresh fills

    # Seed one fresh device-telemetry packet (battery map value) plus a
    # yesterday traceroute and positions, so the completed-day link fold and
    # the latest-state merges all have data.
    from datetime import UTC, datetime, timedelta

    from meshtastic import mesh_pb2, telemetry_pb2

    telemetry = telemetry_pb2.Telemetry()
    telemetry.device_metrics.battery_level = 73
    telemetry_payload = bytes(telemetry.SerializeToString())

    def position(lat, lon):
        position = mesh_pb2.Position()
        position.latitude_i = int(lat * 1e7)
        position.longitude_i = int(lon * 1e7)
        return bytes(position.SerializeToString())

    route = mesh_pb2.RouteDiscovery()
    route.snr_towards.extend([20])  # +5.0 dB direct hop
    traceroute_payload = bytes(route.SerializeToString())

    yesterday = (
        datetime.now(tz=UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        - timedelta(days=1)
    ).timestamp()

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, portnum,"
        " portnum_name, raw_payload) VALUES (?, 't', 1128074276, 67,"
        " 'TELEMETRY_APP', ?)",
        (time.time() - 60, telemetry_payload),
    )
    for node_id, lat, lon in ((1128074276, 52.0, 13.0), (1717986918, 52.4, 13.5)):
        conn.execute(
            "INSERT INTO packet_history (timestamp, topic, from_node_id, portnum,"
            " portnum_name, raw_payload) VALUES (?, 't', ?, 3, 'POSITION_APP', ?)",
            (yesterday, node_id, position(lat, lon)),
        )
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, to_node_id,"
        " portnum, portnum_name, raw_payload) VALUES (?, 't', 1128074276,"
        " 1717986918, 70, 'TRACEROUTE_APP', ?)",
        (yesterday + 60, traceroute_payload),
    )
    conn.commit()
    conn.close()

    capture_rollups.refresh(sqlite3.connect(db_path))

    app = create_app(AppConfig(database_file=db_path))
    try:
        yield app.test_client()
    finally:
        mqtt_capture.DATABASE_FILE = original_db


@pytest.mark.integration
class TestRollupBackedEndpoints:
    def test_locations_returns_rollup_positions(self, rollup_client):
        body = rollup_client.get("/api/locations").get_json()
        assert body["locations"], "expected rollup-backed locations"
        location = body["locations"][0]
        for key in (
            "node_id",
            "latitude",
            "longitude",
            "altitude",
            "precision_bits",
            "precision_meters",
            "sats_in_view",
        ):
            assert key in location
        assert location["latitude"] is not None and location["longitude"] is not None

    def test_v1_nodes_counts_and_battery_from_rollups(self, rollup_client):
        body = rollup_client.get("/api/v1/nodes?page_size=100").get_json()
        rows = body["data"]
        assert rows
        active = [row for row in rows if row["packet_count_24h"] > 0]
        assert active, "expected rollup-backed 24h counters"
        for row in active:
            assert isinstance(row["packet_count_24h"], int)

        # Battery values hydrate on the battery-sorted path (unchanged legacy
        # behaviour); the map itself must come from the rollup.
        battery_rows = rollup_client.get(
            "/api/v1/nodes?sort=battery&page_size=100"
        ).get_json()["data"]
        with_battery = [row for row in battery_rows if row["battery_level"] is not None]
        assert with_battery, "expected rollup-backed battery values"
        assert any(row["battery_level"] == 73 for row in with_battery)

    def test_traceroute_hops_nodes_from_rollups(self, rollup_client):
        body = rollup_client.get("/api/traceroute-hops/nodes").get_json()
        assert body["total_count"] > 0
        located = [n for n in body["nodes"] if "location" in n]
        assert located, "expected rollup-backed locations on the catalog"

    def test_longest_links_from_rollups(self, rollup_client):
        body = rollup_client.get("/api/longest-links?min_snr=-100").get_json()
        assert body["direct_links"], "expected rollup-backed direct links"
        for link in body["direct_links"]:
            assert link["distance_km"] > 0
            assert link["traceroute_count"] >= 1
            assert link["packet_id"] is not None
        assert set(body["summary"]) == {
            "total_links",
            "direct_links",
            "longest_direct",
            "longest_path",
        }
