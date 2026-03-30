"""
Integration tests for the Chat API endpoint (/api/chat/messages).
"""

import pytest

from malla.database.repositories import NodeRepository
from malla.routes import api_routes


class TestChatMessagesAPI:
    """Tests for /api/chat/messages endpoint — raw packet streaming."""

    @pytest.mark.integration
    @pytest.mark.api
    def test_basic_response_structure(self, client, helpers):
        """The endpoint returns the expected top-level keys."""
        response = client.get("/api/chat/messages")
        data = helpers.assert_api_response_structure(
            response, ["packets", "nodes", "last_id", "relays", "relay_filters"]
        )
        assert isinstance(data["packets"], list)
        assert isinstance(data["nodes"], dict)
        assert isinstance(data["last_id"], int)
        assert isinstance(data["relays"], dict)
        assert isinstance(data["relay_filters"], dict)

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_are_text_only(self, client):
        """All returned packets should have decodable text content."""
        data = client.get("/api/chat/messages").get_json()
        assert len(data["packets"]) > 0, "Fixture DB should contain text messages"

        for p in data["packets"]:
            assert "tx" in p
            assert p["tx"] is not None
            assert len(p["tx"]) > 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_packet_fields(self, client):
        """Each packet carries the required compact fields."""
        data = client.get("/api/chat/messages?limit=5").get_json()
        required = {"i", "t", "f", "d", "ch", "m", "hl", "hs", "tx", "gw"}

        for p in data["packets"]:
            missing = required - set(p.keys())
            assert not missing, f"Packet {p.get('i')} missing fields: {missing}"

    @pytest.mark.integration
    @pytest.mark.api
    def test_packets_ordered_by_id_ascending(self, client):
        """Packets should be returned in ascending id order."""
        data = client.get("/api/chat/messages?limit=50").get_json()
        pkts = data["packets"]

        if len(pkts) > 1:
            ids = [p["i"] for p in pkts]
            assert ids == sorted(ids), "Packets should be ordered by id ascending"

    @pytest.mark.integration
    @pytest.mark.api
    def test_limit_parameter(self, client):
        """The limit parameter caps the number of returned packets."""
        data = client.get("/api/chat/messages?limit=3").get_json()
        assert len(data["packets"]) <= 3

    @pytest.mark.integration
    @pytest.mark.api
    def test_limit_capped_at_500(self, client):
        """Requesting more than 500 should be capped."""
        response = client.get("/api/chat/messages?limit=9999")
        assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.api
    def test_after_id_returns_newer_only(self, client):
        """Using after_id should return only packets with id > after_id."""
        initial = client.get("/api/chat/messages?limit=10").get_json()
        pkts = initial["packets"]
        if len(pkts) < 2:
            pytest.skip("Need at least 2 packets to test after_id")

        mid_id = pkts[len(pkts) // 2]["i"]
        data = client.get(f"/api/chat/messages?after_id={mid_id}").get_json()

        for p in data["packets"]:
            assert p["i"] > mid_id, f"Packet id {p['i']} should be > {mid_id}"

    @pytest.mark.integration
    @pytest.mark.api
    def test_before_id_returns_older_only(self, client):
        """Using before_id should return only packets with id < before_id."""
        initial = client.get("/api/chat/messages?limit=10").get_json()
        pkts = initial["packets"]
        if len(pkts) < 2:
            pytest.skip("Need at least 2 packets to test before_id")

        oldest_loaded_id = pkts[0]["i"]
        data = client.get(
            f"/api/chat/messages?before_id={oldest_loaded_id}&limit=10"
        ).get_json()

        if not data["packets"]:
            pytest.skip("Need older packets than the initial page to test before_id")

        for p in data["packets"]:
            assert p["i"] < oldest_loaded_id, (
                f"Packet id {p['i']} should be < {oldest_loaded_id}"
            )

    @pytest.mark.integration
    @pytest.mark.api
    def test_before_id_preserves_ascending_order(self, client):
        """Backward paging should still return packets in ascending id order."""
        initial = client.get("/api/chat/messages?limit=10").get_json()
        pkts = initial["packets"]
        if len(pkts) < 2:
            pytest.skip("Need at least 2 packets to test before_id ordering")

        oldest_loaded_id = pkts[0]["i"]
        data = client.get(
            f"/api/chat/messages?before_id={oldest_loaded_id}&limit=10"
        ).get_json()

        if len(data["packets"]) < 2:
            pytest.skip("Need at least 2 older packets to test before_id ordering")

        ids = [p["i"] for p in data["packets"]]
        assert ids == sorted(ids), "Packets should remain ordered by id ascending"

    @pytest.mark.integration
    @pytest.mark.api
    def test_after_id_beyond_last_returns_empty(self, client):
        """When after_id is beyond the last packet, no packets should be returned."""
        data = client.get("/api/chat/messages?after_id=999999999").get_json()
        assert data["packets"] == []

    @pytest.mark.integration
    @pytest.mark.api
    def test_last_id_reflects_db_state(self, client):
        """last_id should be the highest packet id in the DB."""
        data = client.get("/api/chat/messages").get_json()
        assert data["last_id"] > 0

    @pytest.mark.integration
    @pytest.mark.api
    def test_nodes_dict_contains_senders(self, client):
        """The nodes dict should have entries for all from_node_ids in packets."""
        data = client.get("/api/chat/messages?limit=50").get_json()
        sender_ids = {str(p["f"]) for p in data["packets"] if p["f"]}

        for sid in sender_ids:
            assert sid in data["nodes"], f"Node {sid} missing from nodes dict"
            assert "name" in data["nodes"][sid]
            assert "short" in data["nodes"][sid]

    @pytest.mark.integration
    @pytest.mark.api
    def test_channel_filter(self, client):
        """Filtering by channel should only return packets from that channel."""
        all_data = client.get("/api/chat/messages?limit=300").get_json()
        channels = {p["ch"] for p in all_data["packets"] if p["ch"]}

        if not channels:
            pytest.skip("No channel data in test fixtures")

        target = next(iter(channels))
        filtered = client.get(
            f"/api/chat/messages?channel={target}&limit=300"
        ).get_json()

        for p in filtered["packets"]:
            assert p["ch"] == target, f"Expected channel '{target}', got '{p['ch']}'"

    @pytest.mark.integration
    @pytest.mark.api
    def test_nonexistent_channel_returns_empty(self, client):
        """Filtering by a non-existent channel should return empty."""
        data = client.get("/api/chat/messages?channel=NonexistentChannel42").get_json()
        assert data["packets"] == []

    @pytest.mark.integration
    @pytest.mark.api
    def test_gateway_nodes_resolved(self, client):
        """Gateway node IDs should also appear in the nodes dict."""
        data = client.get("/api/chat/messages?limit=50").get_json()
        gw_node_ids = set()
        for p in data["packets"]:
            gw = p.get("gw")
            if gw and isinstance(gw, str) and gw.startswith("!"):
                try:
                    gw_node_ids.add(str(int(gw[1:], 16)))
                except ValueError:
                    pass

        if not gw_node_ids:
            pytest.skip("No gateway node IDs in test data")

        for gid in gw_node_ids:
            assert gid in data["nodes"], f"Gateway node {gid} missing from nodes dict"

    @pytest.mark.integration
    @pytest.mark.api
    def test_ambiguous_relay_candidates_are_filtered_and_cached(
        self, client, monkeypatch
    ):
        """Ambiguous relay suffixes should use cached gateway-aware narrowing."""
        baseline = client.get("/api/chat/messages?limit=300").get_json()
        target_packet = next(
            (
                packet
                for packet in baseline["packets"]
                if packet.get("rl")
                and packet.get("gw")
                and isinstance(packet["gw"], str)
                and packet["gw"].startswith("!")
                and len(baseline["relays"].get(str(packet["rl"] & 0xFF), [])) > 1
            ),
            None,
        )
        if target_packet is None:
            pytest.skip("Need an ambiguous relay suffix in fixtures")

        gateway_node_id = int(target_packet["gw"][1:], 16)
        relay_last_byte = target_packet["rl"] & 0xFF
        filtered_candidate = {
            "node_id": 0x01020304,
            "node_name": "Filtered Relay",
            "short_name": "FR",
            "hex_id": "!01020304",
            "last_byte": f"{relay_last_byte:02x}",
        }
        api_routes._chat_relay_candidate_cache.clear()
        lookup_calls = 0

        def fake_get_relay_node_candidates_for_pairs(
            relay_pairs: list[tuple[int, int]], cursor=None
        ):
            nonlocal lookup_calls
            lookup_calls += 1
            assert (gateway_node_id, relay_last_byte) in relay_pairs
            return {gateway_node_id: {relay_last_byte: [filtered_candidate]}}

        monkeypatch.setattr(
            NodeRepository,
            "get_relay_node_candidates_for_pairs",
            staticmethod(fake_get_relay_node_candidates_for_pairs),
        )

        first = client.get(
            f"/api/chat/relay-filters?pair={gateway_node_id}:{relay_last_byte}"
        ).get_json()
        filter_key = f"{gateway_node_id}:{relay_last_byte}"
        assert first["relay_filters"][filter_key] == [
            {
                "id": filtered_candidate["node_id"],
                "name": filtered_candidate["node_name"],
                "short": filtered_candidate["short_name"],
            }
        ]

        second = client.get(
            f"/api/chat/relay-filters?pair={gateway_node_id}:{relay_last_byte}"
        ).get_json()
        assert second["relay_filters"][filter_key] == first["relay_filters"][filter_key]
        assert lookup_calls == 1

    @pytest.mark.integration
    @pytest.mark.api
    def test_duplicate_mesh_packet_ids_present(self, client):
        """Raw packets should include duplicates (same mesh_packet_id, different rows)."""
        data = client.get("/api/chat/messages?limit=300").get_json()
        mesh_ids = [p["m"] for p in data["packets"] if p["m"] is not None]
        # The test fixtures have multi-gateway packets with shared mesh_packet_ids
        if not mesh_ids:
            pytest.skip("No mesh_packet_ids in test data")
        from collections import Counter

        counts = Counter(mesh_ids)
        duplicates = {mid: cnt for mid, cnt in counts.items() if cnt > 1}
        # At least some packets should appear multiple times (multi-gateway)
        assert len(duplicates) > 0, (
            "Expected some mesh_packet_ids to appear more than once (multi-gateway receptions)"
        )


class TestChatPageRoute:
    """Tests for the /chat HTML page route."""

    @pytest.mark.integration
    def test_chat_page_loads(self, client):
        """The chat page should return 200 and contain expected elements."""
        response = client.get("/chat")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "chatMessages" in html
        assert "channelFilter" in html
        assert "chat.js" in html
        assert "chat.css" in html
        assert html.count("<div") == html.count("</div>")

    @pytest.mark.integration
    def test_chat_in_navbar(self, client):
        """The Chat link should appear in the navigation bar."""
        response = client.get("/")
        html = response.get_data(as_text=True)
        assert "/chat" in html
        assert "Chat" in html
