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

    @pytest.mark.integration
    @pytest.mark.api
    def test_chat_channels_endpoint(self, client):
        """The /api/chat/channels endpoint returns channels list."""
        response = client.get("/api/chat/channels")
        assert response.status_code == 200
        data = response.get_json()
        assert "channels" in data
        assert isinstance(data["channels"], list)

    @pytest.mark.integration
    @pytest.mark.api
    def test_chat_channels_filter_empty(self, client):
        """When chat_hide_empty_channels is True, only channels with text messages are returned."""
        from src.malla.config import AppConfig, _override_config, get_config

        orig_cfg = get_config()
        try:
            # Test with chat_hide_empty_channels = False (all channels)
            cfg_all = AppConfig(
                database_file=orig_cfg.database_file,
                chat_hide_empty_channels=False,
            )
            _override_config(cfg_all)
            res_all = client.get("/api/chat/channels").get_json()

            # Test with chat_hide_empty_channels = True (only with messages)
            cfg_filtered = AppConfig(
                database_file=orig_cfg.database_file,
                chat_hide_empty_channels=True,
            )
            _override_config(cfg_filtered)
            res_filtered = client.get("/api/chat/channels").get_json()

            assert set(res_filtered["channels"]).issubset(set(res_all["channels"]))

            # Test query parameter ?all=true override
            res_override = client.get("/api/chat/channels?all=true").get_json()
            assert res_override["channels"] == res_all["channels"]
        finally:
            _override_config(orig_cfg)

    @pytest.mark.integration
    @pytest.mark.api
    def test_chat_channels_include_and_exclude(self, client):
        """Include and exclude filters properly constrain channels returned to chat."""
        from src.malla.config import AppConfig, _override_config, get_config

        orig_cfg = get_config()
        try:
            # Baseline: get unfiltered channels
            cfg_base = AppConfig(
                database_file=orig_cfg.database_file,
                chat_hide_empty_channels=False,
                chat_include_channels=[],
                chat_exclude_channels=[],
            )
            _override_config(cfg_base)
            base_channels = client.get("/api/chat/channels").get_json()["channels"]

            if len(base_channels) >= 2:
                chan_a = base_channels[0]
                chan_b = base_channels[1]

                # 1. Test chat_include_channels only
                cfg_include = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_include_channels=[chan_a],
                )
                _override_config(cfg_include)
                res_inc = client.get("/api/chat/channels").get_json()["channels"]
                assert res_inc == [chan_a]

                # 2. Test chat_exclude_channels only
                cfg_exclude = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_exclude_channels=[chan_a],
                )
                _override_config(cfg_exclude)
                res_exc = client.get("/api/chat/channels").get_json()["channels"]
                assert chan_a not in res_exc
                assert chan_b in res_exc

                # 3. Test both include and exclude together
                cfg_both = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_include_channels=[chan_a, chan_b],
                    chat_exclude_channels=[chan_a],
                )
                _override_config(cfg_both)
                res_both = client.get("/api/chat/channels").get_json()["channels"]
                assert res_both == [chan_b]
        finally:
            _override_config(orig_cfg)

    @pytest.mark.integration
    @pytest.mark.api
    def test_chat_messages_include_and_exclude(self, client):
        """Streaming chat messages respects chat_include_channels and chat_exclude_channels."""
        from src.malla.config import AppConfig, _override_config, get_config

        orig_cfg = get_config()
        try:
            # Baseline: get messages from all channels
            cfg_base = AppConfig(
                database_file=orig_cfg.database_file,
                chat_hide_empty_channels=False,
                chat_include_channels=[],
                chat_exclude_channels=[],
            )
            _override_config(cfg_base)
            base_data = client.get("/api/chat/messages?limit=100").get_json()
            all_channels = {p["ch"] for p in base_data["packets"] if p.get("ch")}

            if len(all_channels) >= 2:
                chan_list = list(all_channels)
                target_chan = chan_list[0]
                other_chan = chan_list[1]

                # 1. Test chat_include_channels on "All channels" (no ?channel)
                cfg_inc = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_include_channels=[target_chan],
                )
                _override_config(cfg_inc)
                inc_data = client.get("/api/chat/messages?limit=100").get_json()
                for p in inc_data["packets"]:
                    assert p["ch"] == target_chan

                # Direct query for forbidden channel returns empty
                bad_chan_data = client.get(f"/api/chat/messages?channel={other_chan}").get_json()
                assert bad_chan_data["packets"] == []

                # 2. Test chat_exclude_channels on "All channels"
                cfg_exc = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_exclude_channels=[target_chan],
                )
                _override_config(cfg_exc)
                exc_data = client.get("/api/chat/messages?limit=100").get_json()
                for p in exc_data["packets"]:
                    assert p["ch"] != target_chan

                # Direct query for excluded channel returns empty
                exc_direct = client.get(f"/api/chat/messages?channel={target_chan}").get_json()
                assert exc_direct["packets"] == []

                # 3. Test both include and exclude
                cfg_both = AppConfig(
                    database_file=orig_cfg.database_file,
                    chat_include_channels=[target_chan, other_chan],
                    chat_exclude_channels=[target_chan],
                )
                _override_config(cfg_both)
                both_data = client.get("/api/chat/messages?limit=100").get_json()
                for p in both_data["packets"]:
                    assert p["ch"] == other_chan
        finally:
            _override_config(orig_cfg)

    @pytest.mark.integration
    @pytest.mark.api
    def test_chat_messages_deduplication_and_empty_allowed(self, client):
        """Duplicates in include/exclude are deduplicated; empty effective allowed returns empty response."""
        from src.malla.config import AppConfig, _override_config, get_config

        orig_cfg = get_config()
        try:
            # 1. Duplicate channels in include config are handled cleanly
            cfg_dups = AppConfig(
                database_file=orig_cfg.database_file,
                chat_include_channels="ChanA, ChanA, ChanB",
                chat_exclude_channels="ChanA, ChanA",
            )
            assert cfg_dups.get_chat_include_channels() == ["ChanA", "ChanB"]
            assert cfg_dups.get_chat_exclude_channels() == ["ChanA"]
            _override_config(cfg_dups)
            res = client.get("/api/chat/messages?limit=10").get_json()
            assert "packets" in res
            assert "last_id" in res

            # 2. When all included channels are excluded, returns empty response
            cfg_empty = AppConfig(
                database_file=orig_cfg.database_file,
                chat_include_channels="ChanA",
                chat_exclude_channels="ChanA",
            )
            _override_config(cfg_empty)
            res_empty = client.get("/api/chat/messages").get_json()
            assert res_empty["packets"] == []
            assert res_empty["nodes"] == {}
        finally:
            _override_config(orig_cfg)

    @pytest.mark.integration
    def test_get_unique_chat_channels_connection_cleanup(self, monkeypatch):
        """NodeRepository.get_unique_chat_channels closes connection in finally block even if query fails."""
        import sqlite3

        from malla.database import repositories

        real_get_conn = repositories.get_db_connection
        closed = []

        class MockConn:
            def __init__(self, raw_conn):
                self._raw = raw_conn

            def cursor(self):
                raise sqlite3.OperationalError("Simulated database failure")

            def close(self):
                closed.append(True)
                self._raw.close()

        def mock_get_db_connection():
            return MockConn(real_get_conn())

        monkeypatch.setattr(repositories, "get_db_connection", mock_get_db_connection)
        res = repositories.NodeRepository.get_unique_chat_channels(only_with_messages=True)
        assert res == []
        assert len(closed) == 1


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
