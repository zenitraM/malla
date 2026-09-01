"""
Test that empty-payload TRACEROUTE_APP packets (requests / flood-loop junk)
are excluded from hop/link analysis queries but kept for raw listings.
"""

from datetime import datetime, timedelta

import pytest

JUNK_MESH_PACKET_ID = 2118652877
NODE_A = 0x7A110001
NODE_B = 0x7A110002
NODE_C = 0x7A110003


def _make_route_payload() -> bytes:
    from meshtastic import mesh_pb2

    route = mesh_pb2.RouteDiscovery()
    route.route.extend([NODE_C])
    route.snr_towards.extend([int(-5.0 * 4)])
    return route.SerializeToString()


def _insert_traceroute_rows(cursor, base_time: float) -> None:
    payload = _make_route_payload()

    for i, mesh_packet_id in enumerate((1001, 1002)):
        cursor.execute(
            """
            INSERT INTO packet_history
            (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
             timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
             payload_length, raw_payload, processed_successfully)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                mesh_packet_id,
                NODE_A,
                NODE_B,
                f"!gw{i:08x}",
                -90,
                -5.0,
                base_time - i,
                3,
                3,
                70,
                "TRACEROUTE_APP",
                "msh/2/c/LongFast/!gw",
                len(payload),
                payload,
                True,
            ),
        )

    # Flood-loop junk: same mesh_packet_id redelivered by one gateway,
    # empty payload, hop budget expired.
    for i in range(5):
        cursor.execute(
            """
            INSERT INTO packet_history
            (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
             timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
             payload_length, raw_payload, processed_successfully)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                JUNK_MESH_PACKET_ID,
                NODE_A,
                NODE_B,
                "!9e765708",
                None,
                0.0,
                base_time - 100 - i * 60,
                0,
                3,
                70,
                "TRACEROUTE_APP",
                "msh/2/c/LongFast/!9e765708",
                0,
                b"",
                True,
            ),
        )


class TestTracerouteEmptyPayloadFilter:
    """Test exclusion of empty-payload traceroute packets from analysis paths."""

    @pytest.fixture(autouse=True)
    def _seed_rows(self, app):
        from src.malla.database.connection import get_db_connection

        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()
            base_time = datetime.now().timestamp()
            _insert_traceroute_rows(cursor, base_time)
            cursor.connection.commit()
            conn.close()
            yield

    @staticmethod
    def _filters() -> dict:
        end = datetime.now()
        start = end - timedelta(days=7)
        return {
            "start_time": start.timestamp(),
            "end_time": end.timestamp(),
            "processed_successfully_only": True,
            "from_node": NODE_A,
        }

    @pytest.mark.integration
    def test_repository_excludes_empty_payload_when_requested(self):
        from src.malla.database.repositories import TracerouteRepository

        result = TracerouteRepository.get_traceroute_packets(
            limit=100, filters=self._filters() | {"exclude_empty_payload": True}
        )
        mesh_ids = {p["mesh_packet_id"] for p in result["packets"]}
        assert 1001 in mesh_ids
        assert 1002 in mesh_ids
        assert JUNK_MESH_PACKET_ID not in mesh_ids

    @pytest.mark.integration
    def test_repository_keeps_empty_payload_without_flag(self):
        from src.malla.database.repositories import TracerouteRepository

        result = TracerouteRepository.get_traceroute_packets(
            limit=100, filters=self._filters()
        )
        mesh_ids = {p["mesh_packet_id"] for p in result["packets"]}
        assert JUNK_MESH_PACKET_ID in mesh_ids

    @pytest.mark.integration
    def test_graph_query_excludes_empty_payload_unconditionally(self):
        from src.malla.database.repositories import TracerouteRepository

        rows = TracerouteRepository.get_traceroute_packets_for_graph(
            limit=100, filters=self._filters()
        )
        rows_from_a = [r for r in rows if r["from_node_id"] == NODE_A]
        assert len(rows_from_a) == 2
        assert all(r["raw_payload"] for r in rows_from_a)

    @pytest.mark.integration
    def test_link_endpoint_ignores_junk_rows(self, app):
        with app.test_client() as client:
            response = client.get(f"/api/traceroute/link/{NODE_A}/{NODE_C}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_attempts"] == 2
        assert len(data["traceroutes"]) == 2

    @pytest.mark.integration
    def test_related_nodes_ignores_junk_rows(self, app):
        with app.test_client() as client:
            response = client.get(f"/api/traceroute/related-nodes/{NODE_A}")
        assert response.status_code == 200
        data = response.get_json()
        related_ids = {n["node_id"] for n in data.get("related_nodes", [])}
        assert NODE_C in related_ids
