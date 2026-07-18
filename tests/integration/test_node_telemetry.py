"""Tests for the node telemetry history feature (repository, service, API)."""

import os
import sqlite3
import tempfile
import time

import pytest
from meshtastic import telemetry_pb2

from malla.config import AppConfig, _clear_config_cache
from malla.database.repositories import NodeRepository
from malla.services.node_service import NodeService
from malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures

NODE_ID = 0x11223344


def _env_payload(temperature=None, humidity=None, pressure=None):
    t = telemetry_pb2.Telemetry()
    if temperature is not None:
        t.environment_metrics.temperature = temperature
    if humidity is not None:
        t.environment_metrics.relative_humidity = humidity
    if pressure is not None:
        t.environment_metrics.barometric_pressure = pressure
    return t.SerializeToString()


def _device_payload(battery=None, voltage=None):
    t = telemetry_pb2.Telemetry()
    if battery is not None:
        t.device_metrics.battery_level = battery
    if voltage is not None:
        t.device_metrics.voltage = voltage
    return t.SerializeToString()


def _insert_telemetry(db_path, node_id, offset_seconds, raw):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO packet_history
            (timestamp, topic, from_node_id, portnum, portnum_name,
             payload_length, raw_payload, processed_successfully)
        VALUES (?, ?, ?, 67, 'TELEMETRY_APP', ?, ?, 1)
        """,
        (time.time() - offset_seconds, "msh/test", node_id, len(raw), raw),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def telemetry_client():
    """Flask test client backed by a fixture DB seeded with telemetry packets."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    DatabaseFixtures().create_test_database(tmp.name)

    # Recent environment + device telemetry (within 1 day)
    for i in range(4):
        _insert_telemetry(tmp.name, NODE_ID, i * 3600, _env_payload(20 + i, 55 + i))
        _insert_telemetry(tmp.name, NODE_ID, i * 3600, _device_payload(90 - i, 4.1))
    # An old environment sample (~10 days ago) — excluded by 1d/7d ranges
    _insert_telemetry(tmp.name, NODE_ID, 10 * 86400, _env_payload(temperature=5))

    _clear_config_cache()
    app = create_app(AppConfig(database_file=tmp.name))
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        _clear_config_cache()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def test_repository_extracts_metrics(telemetry_client):
    db = os.environ["MALLA_DATABASE_FILE"]
    result = NodeRepository.get_node_telemetry_history(NODE_ID)
    series = result["series"]

    assert set(series) >= {"temperature", "relative_humidity", "battery_level", "voltage"}
    assert series["temperature"]["unit"] == "°C"
    assert series["temperature"]["group"] == "environment"
    assert series["voltage"]["unit"] == "V"
    assert series["voltage"]["group"] == "power"
    # points are [timestamp, value] and ascending in time
    pts = series["temperature"]["points"]
    assert all(len(p) == 2 for p in pts)
    assert pts == sorted(pts, key=lambda p: p[0])
    assert db  # sanity: env override wired by create_app


def test_service_range_filters_old_samples(telemetry_client):
    # The -5°C sample is ~10 days old: present in "all"/30d, absent from 1d/7d.
    all_temps = NodeService.get_node_telemetry_history(NODE_ID, "all")["series"][
        "temperature"
    ]["points"]
    week_temps = NodeService.get_node_telemetry_history(NODE_ID, "7d")["series"][
        "temperature"
    ]["points"]

    assert any(p[1] == 5.0 for p in all_temps)
    assert not any(p[1] == 5.0 for p in week_temps)
    assert len(week_temps) < len(all_temps)


def test_repository_aggregates_with_band(telemetry_client):
    full = NodeRepository.get_node_telemetry_history(NODE_ID)["series"]["temperature"][
        "points"
    ]
    temp = NodeRepository.get_node_telemetry_history(NODE_ID, max_points=3)["series"][
        "temperature"
    ]
    pts = temp["points"]
    band = temp["band"]
    assert "band" in temp and len(band) == len(pts)
    # Aggregated into an averaged line of ~max_points real buckets (break markers
    # excluded), each with a mean ± σ band entry.
    real = [p for p in pts if p[1] is not None]
    assert 0 < len(real) <= 3
    # The ~10-day-old sample is isolated by a gap, so the series is split into two
    # runs joined by a break marker (a None entry) — no line drawn across the gap.
    assert any(p[1] is None for p in pts)
    # The band is mean ± k·σ (clamped to observed values), so the line always
    # stays inside it and never claims a value outside the raw data's range.
    raw_lo = min(p[1] for p in full)
    raw_hi = max(p[1] for p in full)
    for p, b in zip(pts, band, strict=True):
        if p[1] is not None:
            assert b[1] <= p[1] <= b[2]
            assert raw_lo <= b[1] and b[2] <= raw_hi


def test_api_endpoint_returns_series(telemetry_client):
    resp = telemetry_client.get(f"/api/node/{NODE_ID}/telemetry?range=7d")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["range"] == "7d"
    assert data["count"] > 0
    assert "temperature" in data["series"]
    assert data["series"]["battery_level"]["group"] == "power"


def test_api_defaults_and_validates_range(telemetry_client):
    # Unknown range falls back to the 7d default rather than erroring.
    resp = telemetry_client.get(f"/api/node/{NODE_ID}/telemetry?range=bogus")
    assert resp.status_code == 200
    assert resp.get_json()["range"] == "7d"


def test_api_start_end_window(telemetry_client):
    # An explicit start/end window (last day) overrides range and excludes the
    # ~10-day-old sample — this backs the charts' zoom-to-detail refetch.
    now = time.time()
    resp = telemetry_client.get(
        f"/api/node/{NODE_ID}/telemetry?start={now - 86400}&end={now}"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start"] and data["end"]
    assert "decimated" in data
    temps = data["series"].get("temperature", {}).get("points", [])
    assert temps and not any(p[1] == 5.0 for p in temps)


def test_api_empty_for_node_without_telemetry(telemetry_client):
    resp = telemetry_client.get("/api/node/0x99999999/telemetry?range=all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["series"] == {}
    assert data["count"] == 0
