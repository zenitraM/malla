"""
Integration tests for traceroute packet grouping and two-stage SQL pagination.

Validates that:
1. Multi-gateway receptions for the same packet are correctly grouped.
2. Pagination returns the exact requested limit across multiple pages without early truncation.
3. total_count reflects the total number of unique packet groups across the entire time window.
4. Ordering by timestamp, gateway_count, etc., operates correctly across groups.
"""

from datetime import datetime, timedelta

import pytest

from src.malla.database.connection import get_db_connection
from src.malla.database.repositories import TracerouteRepository

NODE_SRC = 0x7A111001
NODE_DST = 0x7A111002


def _insert_grouped_test_data(
    cursor, base_time: float, num_packets: int = 15, gateways_per_packet: int = 4
):
    """Insert multiple packets, each received by multiple gateways."""
    for p_idx in range(num_packets):
        mesh_packet_id = 900000 + p_idx
        pkt_time = base_time - (p_idx * 60)  # Each packet 1 minute apart

        for gw_idx in range(gateways_per_packet):
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
                    NODE_SRC,
                    NODE_DST,
                    f"!gw{gw_idx:08x}",
                    -80 - (gw_idx * 5),
                    5.0 - (gw_idx * 2.0),
                    pkt_time - gw_idx,  # Slightly different reception time per gateway
                    3,
                    3,
                    70,
                    "TRACEROUTE_APP",
                    f"msh/2/c/LongFast/!gw{gw_idx:08x}",
                    16,
                    b"test_payload_123",
                    True,
                ),
            )


@pytest.mark.integration
class TestTracerouteGroupingPagination:
    """Test two-stage SQL grouping and pagination."""

    NUM_PACKETS = 15
    GATEWAYS_PER_PACKET = 4

    @pytest.fixture(autouse=True)
    def _seed_packets(self, app):
        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()
            base_time = datetime.now().timestamp()
            _insert_grouped_test_data(
                cursor,
                base_time,
                num_packets=self.NUM_PACKETS,
                gateways_per_packet=self.GATEWAYS_PER_PACKET,
            )
            conn.commit()
            conn.close()
            yield

    def _filters(self) -> dict:
        end = datetime.now()
        start = end - timedelta(days=7)
        return {
            "start_time": start.timestamp(),
            "end_time": end.timestamp(),
            "from_node": NODE_SRC,
            "to_node": NODE_DST,
        }

    def test_grouped_packets_pagination_page_slices(self):
        """Verify that offset 0, 5, 10 return correct slices without premature truncation."""
        filters = self._filters()

        # Page 1: limit=5, offset=0
        page1 = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=0,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="desc",
        )
        assert page1["total_count"] == self.NUM_PACKETS
        assert len(page1["packets"]) == 5

        page1_ids = [p["mesh_packet_id"] for p in page1["packets"]]
        assert len(set(page1_ids)) == 5

        # Page 2: limit=5, offset=5
        page2 = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=5,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="desc",
        )
        assert page2["total_count"] == self.NUM_PACKETS
        assert len(page2["packets"]) == 5

        page2_ids = [p["mesh_packet_id"] for p in page2["packets"]]
        assert len(set(page2_ids)) == 5
        # Ensure disjoint pages
        assert set(page1_ids).isdisjoint(set(page2_ids))

        # Page 3: limit=5, offset=10
        page3 = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=10,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="desc",
        )
        assert page3["total_count"] == self.NUM_PACKETS
        assert len(page3["packets"]) == 5

        page3_ids = [p["mesh_packet_id"] for p in page3["packets"]]
        assert set(page3_ids).isdisjoint(set(page1_ids))
        assert set(page3_ids).isdisjoint(set(page2_ids))

        # Page 4: offset beyond total (offset=15)
        page4 = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=15,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="desc",
        )
        assert page4["total_count"] == self.NUM_PACKETS
        assert len(page4["packets"]) == 0

    def test_grouped_packet_aggregation_details(self):
        """Verify that aggregated packet contains gateway counts and reception stats."""
        filters = self._filters()

        result = TracerouteRepository.get_traceroute_packets(
            limit=1, offset=0, group_packets=True, filters=filters
        )
        assert len(result["packets"]) == 1
        pkt = result["packets"][0]

        assert pkt["is_grouped"] is True
        assert pkt["gateway_count"] == self.GATEWAYS_PER_PACKET
        assert len(pkt["gateway_list"].split(",")) == self.GATEWAYS_PER_PACKET
        assert pkt["from_node_id"] == NODE_SRC
        assert pkt["to_node_id"] == NODE_DST
        assert "min_rssi" in pkt
        assert "max_rssi" in pkt
        assert "min_snr" in pkt
        assert "max_snr" in pkt

    def test_api_endpoint_grouped_pagination(self, client):
        """Test that /api/traceroute/data correctly serves paginated grouped results."""
        resp = client.get(
            f"/api/traceroute/data?page=1&limit=5&group_packets=true&from_node={NODE_SRC}&to_node={NODE_DST}"
        )
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["total_count"] == self.NUM_PACKETS
        assert data["page"] == 1
        assert data["limit"] == 5
        assert len(data["data"]) == 5
        assert all(p.get("is_grouped") is True for p in data["data"])

        # Request page 2
        resp2 = client.get(
            f"/api/traceroute/data?page=2&limit=5&group_packets=true&from_node={NODE_SRC}&to_node={NODE_DST}"
        )
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["total_count"] == self.NUM_PACKETS
        assert data2["page"] == 2
        assert len(data2["data"]) == 5

        page1_ids = {p["id"] for p in data["data"]}
        page2_ids = {p["id"] for p in data2["data"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_empty_results(self):
        """Verify that when no packets match, total_count is 0 and packets is empty list."""
        result = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": 0x99999999},  # Non-existent node
        )
        assert result["total_count"] == 0
        assert result["packets"] == []

    def test_sorting_by_timestamp(self):
        """Verify that timestamp ordering is respected in Stage 1 group selection."""
        filters = self._filters()

        # Descending
        desc_res = TracerouteRepository.get_traceroute_packets(
            limit=self.NUM_PACKETS,
            offset=0,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="desc",
        )
        timestamps_desc = [p["timestamp"] for p in desc_res["packets"]]
        assert timestamps_desc == sorted(timestamps_desc, reverse=True)

        # Ascending
        asc_res = TracerouteRepository.get_traceroute_packets(
            limit=self.NUM_PACKETS,
            offset=0,
            group_packets=True,
            filters=filters,
            order_by="timestamp",
            order_dir="asc",
        )
        timestamps_asc = [p["timestamp"] for p in asc_res["packets"]]
        assert timestamps_asc == sorted(timestamps_asc)

    def test_route_node_fallback_filtering(self):
        """Verify route_node filter path still returns correctly grouped and paginated items."""
        result = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=0,
            group_packets=True,
            filters={"route_node": NODE_SRC},  # Matches from_node_id
        )
        assert result["total_count"] == self.NUM_PACKETS
        assert len(result["packets"]) == 5
        assert all(p["is_grouped"] for p in result["packets"])
