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

    def test_stage_two_does_not_leak_filtered_out_gateways(self):
        """Verify Stage 2 reapplies gateway_id filter and does not leak other gateways."""
        filters = self._filters()
        target_gw = "!gw00000001"
        filters["gateway_id"] = target_gw

        result = TracerouteRepository.get_traceroute_packets(
            limit=5,
            offset=0,
            group_packets=True,
            filters=filters,
        )

        assert result["total_count"] == self.NUM_PACKETS
        assert len(result["packets"]) == 5
        for pkt in result["packets"]:
            # Gateway count must be 1 (only target_gw, not all 4 gateways)
            assert pkt["gateway_count"] == 1
            assert pkt["gateway_list"] == target_gw
            assert pkt["gateway_id"] == target_gw
            # Signal aggregates must match target_gw (gw_idx=1: rssi=-85, snr=3.0)
            assert pkt["min_rssi"] == -85.0
            assert pkt["max_rssi"] == -85.0
            assert pkt["min_snr"] == 3.0
            assert pkt["max_snr"] == 3.0


@pytest.mark.integration
class TestTraceroutePredicateReapplication:
    """Test that all original predicates and composite keys are reapplied in Stage 2."""

    COLLISION_ID = 888888
    NODE_A = 0x11111111
    NODE_B = 0x22222222
    NODE_C = 0x33333333
    NODE_D = 0x44444444

    @pytest.fixture(autouse=True)
    def _seed_predicates_data(self, app):
        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()
            base_time = datetime.now().timestamp()

            # 1. Composite key collision: two different node pairs sharing mesh_packet_id
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
                 timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
                 payload_length, raw_payload, processed_successfully, channel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.COLLISION_ID,
                    self.NODE_A,
                    self.NODE_B,
                    "!gw_a",
                    -70.0,
                    10.0,
                    base_time - 10,
                    3,
                    3,
                    70,
                    "TRACEROUTE_APP",
                    "msh/2/c/LongFast/!gw_a",
                    16,
                    b"payload_pair_ab",
                    1,
                    0,
                ),
            )
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
                 timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
                 payload_length, raw_payload, processed_successfully, channel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.COLLISION_ID,
                    self.NODE_C,
                    self.NODE_D,
                    "!gw_c",
                    -90.0,
                    0.0,
                    base_time - 15,
                    3,
                    3,
                    70,
                    "TRACEROUTE_APP",
                    "msh/2/c/LongFast/!gw_c",
                    16,
                    b"payload_pair_cd",
                    1,
                    0,
                ),
            )

            # 2. Multi-reception packet with different channels, processing statuses, payloads, and times
            # mesh_packet_id: 777777
            # Reception 1: valid, channel 0, processed 1, payload b"good_payload", recent time
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
                 timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
                 payload_length, raw_payload, processed_successfully, channel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    777777,
                    self.NODE_A,
                    self.NODE_B,
                    "!gw_primary",
                    -65.0,
                    12.0,
                    base_time - 20,
                    3,
                    3,
                    70,
                    "TRACEROUTE_APP",
                    "msh/2/c/LongFast/!gw_primary",
                    12,
                    b"good_payload",
                    1,
                    0,
                ),
            )
            # Reception 2: channel 1, processed 0, empty payload, older time (10 days ago)
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr,
                 timestamp, hop_limit, hop_start, portnum, portnum_name, topic,
                 payload_length, raw_payload, processed_successfully, channel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    777777,
                    self.NODE_A,
                    self.NODE_B,
                    "!gw_secondary",
                    -95.0,
                    -5.0,
                    base_time - (10 * 86400),
                    3,
                    3,
                    70,
                    "TRACEROUTE_APP",
                    "msh/2/c/LongFast/!gw_secondary",
                    0,
                    b"",
                    0,
                    1,
                ),
            )

            conn.commit()
            conn.close()
            yield

    def test_composite_key_does_not_mix_colliding_mesh_packet_ids(self):
        """Receptions from colliding mesh_packet_id on different node pairs must remain separate."""
        res = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A, "to_node": self.NODE_B},
        )
        assert res["total_count"] == 2  # COLLISION_ID and 777777
        ab_packet = next(p for p in res["packets"] if p["mesh_packet_id"] == self.COLLISION_ID)
        assert ab_packet["from_node_id"] == self.NODE_A
        assert ab_packet["to_node_id"] == self.NODE_B
        assert ab_packet["gateway_list"] == "!gw_a"
        assert ab_packet["raw_payload"] == b"payload_pair_ab"

    def test_stage_two_reapplies_primary_channel_filter(self):
        """When filtered by primary_channel, stage 2 only fetches matching receptions."""
        res_ch0 = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A, "primary_channel": "0"},
        )
        pkt_ch0 = next(p for p in res_ch0["packets"] if p["mesh_packet_id"] == 777777)
        assert pkt_ch0["gateway_count"] == 1
        assert pkt_ch0["gateway_list"] == "!gw_primary"
        assert str(pkt_ch0["channel_id"]) == "0"

    def test_stage_two_reapplies_processed_successfully_filter(self):
        """When filtered by processed_successfully_only, failed receptions are excluded from stage 2."""
        res = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A, "processed_successfully_only": True},
        )
        pkt = next(p for p in res["packets"] if p["mesh_packet_id"] == 777777)
        assert pkt["gateway_count"] == 1
        assert pkt["gateway_list"] == "!gw_primary"
        assert pkt["gateway_id"] == "!gw_primary"

    def test_stage_two_reapplies_exclude_empty_payload(self):
        """Receptions with empty payload are excluded from stage 2."""
        res = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A, "exclude_empty_payload": True},
        )
        pkt = next(p for p in res["packets"] if p["mesh_packet_id"] == 777777)
        assert pkt["gateway_count"] == 1
        assert pkt["gateway_list"] == "!gw_primary"
        assert pkt["raw_payload"] == b"good_payload"

    def test_stage_two_reapplies_time_window(self):
        """Default 7-day time window excludes receptions older than 7 days from stage 2."""
        res = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A},
        )
        pkt = next(p for p in res["packets"] if p["mesh_packet_id"] == 777777)
        # The reception from 10 days ago (!gw_secondary) is outside the 7-day window
        assert pkt["gateway_count"] == 1
        assert pkt["gateway_list"] == "!gw_primary"

    def test_stage_two_reapplies_search_filter(self):
        """Search predicate is reapplied in stage 2."""
        res = TracerouteRepository.get_traceroute_packets(
            limit=10,
            offset=0,
            group_packets=True,
            filters={"from_node": self.NODE_A},
            search="!gw_primary",
        )
        assert res["total_count"] == 1
        pkt = res["packets"][0]
        assert pkt["mesh_packet_id"] == 777777
        assert pkt["gateway_list"] == "!gw_primary"
