"""Unit tests for the telemetry decode/serve chain.

Covers the real surfaces:
- ``malla.routes.packet_routes.decode_packet_payload`` (the production
  decoder; the TELEMETRY_APP branch -> metric dicts, raw units)
- ``NodeService.get_node_telemetry_history`` series shape via the API route
  contract exercised in ``tests/integration/test_node_telemetry.py``.
"""

import pytest
from meshtastic import mesh_pb2
from meshtastic.protobuf import telemetry_pb2

from malla.routes.packet_routes import decode_packet_payload

pytestmark = pytest.mark.unit


def _device_packet(**overrides):
    t = telemetry_pb2.Telemetry()
    t.time = 1234567890
    t.device_metrics.battery_level = 85
    t.device_metrics.voltage = 4.2  # volts, as the firmware reports it
    t.device_metrics.channel_utilization = 15.5
    t.device_metrics.air_util_tx = 2.3
    t.device_metrics.uptime_seconds = 86400
    packet = {
        "id": 1,
        "portnum_name": "TELEMETRY_APP",
        "payload_length": len(t.SerializeToString()),
        "raw_payload": t.SerializeToString(),
    }
    packet.update(overrides)
    return packet


class TestDecodeTelemetryPayload:
    def test_device_metrics_decoded_raw(self):
        payload = decode_packet_payload(_device_packet())

        assert payload is not None
        result = payload["data"]
        assert payload["decoded"] is True
        assert result["time"] == 1234567890
        device = result["device_metrics"]
        assert device["battery_level"] == 85
        assert device["voltage"] == pytest.approx(4.2, abs=1e-6)
        assert device["channel_utilization"] == 15.5
        assert device["air_util_tx"] == 2.3
        assert device["uptime_seconds"] == 86400

    def test_environment_metrics_decoded(self):
        t = telemetry_pb2.Telemetry()
        t.time = 42
        t.environment_metrics.temperature = 21.5
        t.environment_metrics.relative_humidity = 55
        t.environment_metrics.barometric_pressure = 1013.25
        payload = decode_packet_payload(
            {
                "id": 2,
                "portnum_name": "TELEMETRY_APP",
                "payload_length": len(t.SerializeToString()),
                "raw_payload": t.SerializeToString(),
            }
        )

        assert payload is not None and payload["decoded"] is True
        result = payload["data"]
        env = result["environment_metrics"]
        assert env["temperature"] == 21.5
        assert env["relative_humidity"] == 55
        assert env["barometric_pressure"] == 1013.25
        assert not result.get("device_metrics")

    def test_payload_variant_oneof_last_wins(self):
        # Telemetry.payload_variant is a oneof: setting environment after
        # device replaces it (proto oneof semantics), it does not merge.
        t = telemetry_pb2.Telemetry()
        t.device_metrics.battery_level = 50
        t.environment_metrics.temperature = -3
        payload = decode_packet_payload(
            {
                "id": 3,
                "portnum_name": "TELEMETRY_APP",
                "payload_length": len(t.SerializeToString()),
                "raw_payload": t.SerializeToString(),
            }
        )

        assert payload is not None and payload["decoded"] is True
        result = payload["data"]
        assert "environment_metrics" in result
        assert result["environment_metrics"]["temperature"] == -3
        assert not result.get("device_metrics")

    def test_position_app_uses_generic_protobuf_path(self):
        position = mesh_pb2.Position()
        position.latitude_i = 525000000
        position.longitude_i = 134000000
        raw = position.SerializeToString()
        payload = decode_packet_payload(
            {
                "id": 4,
                "portnum_name": "POSITION_APP",
                "payload_length": len(raw),
                "raw_payload": raw,
            }
        )
        assert payload is not None and payload["decoded"] is True
        assert payload["portnum"] == "POSITION_APP"
        assert payload["data"]["latitude"] == pytest.approx(52.5)
        assert payload["data"]["longitude"] == pytest.approx(13.4)

    def test_empty_payload_returns_none(self):
        assert (
            decode_packet_payload(
                {
                    "id": 5,
                    "portnum_name": "TELEMETRY_APP",
                    "payload_length": 0,
                    "raw_payload": b"",
                }
            )
            is None
        )

    def test_garbage_payload_decode_failure_envelope(self):
        payload = decode_packet_payload(
            {
                "id": 6,
                "portnum_name": "TELEMETRY_APP",
                "payload_length": 3,
                "raw_payload": b"\xff\xfe\xfd",
            }
        )
        assert payload is not None and not payload["decoded"]
        assert payload["error"]

    def test_missing_payload_returns_none(self):
        assert decode_packet_payload({"id": 7, "portnum_name": "TELEMETRY_APP"}) is None


class TestTelemetryServiceContract:
    """The service wraps repository history; the API route shape is pinned in
    tests/integration/test_node_telemetry.py (series/range/start-end). Here we
    pin the decode->series handoff boundary: metrics land in per-metric series
    with units, grouped by facet."""

    def test_metric_registry_covers_device_fields(self):
        from malla.database.repositories import _TELEMETRY_METRICS as TELEMETRY_METRICS

        by_key = {
            (sub_message, field): unit
            for sub_message, field, unit, _group in TELEMETRY_METRICS
        }
        assert by_key[("device_metrics", "battery_level")] == "%"
        assert by_key[("device_metrics", "voltage")] == "V"
        assert by_key[("device_metrics", "channel_utilization")] == "%"
        assert by_key[("environment_metrics", "temperature")] == "°C"

    def test_service_history_envelope(self, tmp_path):
        """Service returns the series envelope via the app's configured DB."""
        from malla.config import AppConfig
        from malla.services.node_service import NodeService
        from malla.web_ui import create_app
        from tests.fixtures.database_fixtures import DatabaseFixtures

        db_path = str(tmp_path / "telemetry.db")
        DatabaseFixtures().create_test_database(db_path)
        app = create_app(AppConfig(database_file=db_path))
        app.config["TESTING"] = True
        with app.app_context():
            result = NodeService.get_node_telemetry_history(999999999, range_key="24h")

        assert "series" in result and isinstance(result["series"], dict)
        assert result.get("count", 0) == 0
