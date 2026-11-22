"""
Integration tests for packet routes
"""

import pytest


class TestPacketRoutes:
    """Test packet-related routes."""

    def test_packets_page_renders(self, client):
        """Test that the packets page renders successfully."""
        response = client.get("/packets")
        assert response.status_code == 200
        assert b"Packets" in response.data
        assert b"packetsTable" in response.data  # Table container ID

    def test_packet_detail_page_renders(self, client):
        """Test that a packet detail page renders successfully."""
        # First, get a packet ID from the database
        from src.malla.database.repositories import PacketRepository

        # Get the first packet
        result = PacketRepository.get_packets(limit=1, offset=0)
        if result["packets"]:
            packet_id = result["packets"][0]["id"]

            # Test the packet detail page
            response = client.get(f"/packet/{packet_id}")
            assert response.status_code == 200
            assert b"Packet #" in response.data
            assert str(packet_id).encode() in response.data
        else:
            pytest.skip("No packets available for testing")

    def test_packet_detail_not_found(self, client):
        """Test that non-existent packet returns 404."""
        response = client.get("/packet/999999")
        assert response.status_code == 404
        assert b"Packet not found" in response.data

    def test_packet_detail_graph_payload_has_mesh_ids_and_locations(self, client):
        """The packet-page graph payload keeps mesh_packet_id on its paths and
        attaches node locations for hop-distance badges.

        Regression guard for the combined traceroute graph: paths are keyed
        by mesh packet id in the receptions sidebar, and the front-end
        computes hop distances from the locations payload.
        """
        from src.malla.database.connection import get_db_connection
        from src.malla.routes.packet_routes import get_packet_details

        # Tomate Base (1819569748) traceroute: its route nodes all have
        # fixture positions (NYC coordinates).
        conn = get_db_connection()
        row = conn.execute(
            "SELECT id, mesh_packet_id FROM packet_history "
            "WHERE from_node_id = ? AND portnum_name = 'TRACEROUTE_APP' "
            "ORDER BY timestamp DESC LIMIT 1",
            (1819569748,),
        ).fetchone()
        conn.close()

        if row is None:
            pytest.skip("No Tomate Base traceroute in fixture data")

        details = get_packet_details(row["id"])
        assert details is not None

        graph = details["packet_graph_data"]
        node_ids = {node["id"] for node in graph["nodes"]}

        # The route (source -> Epsilon -> destination) is in the graph…
        assert {1819569748, 555666777, 2147483647} <= node_ids

        # …every path keeps the mesh packet id it was correlated under…
        assert graph["paths"]
        assert all(
            path["mesh_packet_id"] == row["mesh_packet_id"] for path in graph["paths"]
        )

        # …and located nodes are exposed for hop-distance badges.
        locations = graph["locations"]
        assert locations[1819569748]["lat"] == pytest.approx(40.7128)
        assert locations[1819569748]["lon"] == pytest.approx(-74.006)
        assert locations[555666777]["lat"] == pytest.approx(40.7831)

    def test_packet_detail_mesh_packet_id_zero_not_correlated(self, client):
        """mesh_packet_id=0 is the "unset" sentinel, not a real packet id.

        Correlating receptions on it would merge every zero-id row into one
        giant reception list (issue #146 reported 100 MiB packet pages for
        databases with tens of thousands of mesh_packet_id=0 rows).
        """
        from src.malla.database.connection import get_db_connection
        from src.malla.routes.packet_routes import get_packet_details

        base_id = 9146000
        rows = [
            # (id, timestamp, from_node_id, portnum, mesh_packet_id)
            (base_id + 1, 1_700_000_000, 111111, 1, 0),  # packet under test
            (
                base_id + 2,
                1_700_000_001,
                111111,
                1,
                0,
            ),  # same sender, +1s: real reception
            (
                base_id + 3,
                1_700_000_500,
                111111,
                1,
                0,
            ),  # same sender, far later: unrelated
            (base_id + 4, 1_700_000_000, 222222, 1, 0),  # different sender: unrelated
            (base_id + 5, 1_700_000_000, 111111, 6, 0),  # different portnum: unrelated
        ]
        conn = get_db_connection()
        try:
            conn.executemany(
                """
                INSERT INTO packet_history
                    (id, timestamp, topic, from_node_id, portnum, portnum_name,
                     gateway_id, mesh_packet_id, payload_length,
                     processed_successfully)
                VALUES (?, ?, 'molla/test', ?, ?, 'TEXT_MESSAGE_APP',
                        '!aabbccdd', ?, 0, 1)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        details = get_packet_details(base_id + 1)
        assert details is not None

        # The zero id is treated as missing: time-based correlation is used.
        assert details["packet"]["mesh_packet_id"] is None
        assert details["correlation_method"] == "time_based"

        # Only the genuinely-matching reception is correlated — never every
        # mesh_packet_id=0 row in the database.
        assert [r["id"] for r in details["other_receptions"]] == [base_id + 2]
