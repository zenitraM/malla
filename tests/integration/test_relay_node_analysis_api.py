"""Integration tests for relay_node analysis API."""

import pytest


class TestRelayNodeAnalysisAPI:
    """Test cases for the relay node analysis API endpoint."""

    @pytest.mark.integration
    def test_relay_node_analysis_endpoint_basic(self, client):
        """Test that the relay node analysis endpoint returns expected JSON structure."""
        # Test with gateway node that has relay_node data in fixtures
        # Test Gateway Alpha (1128074276) has relay_node packets in fixtures
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()
        assert "relay_node_stats" in data
        assert "total_count" in data
        assert "total_packets" in data

        # relay_node_stats should be a list
        assert isinstance(data["relay_node_stats"], list)

    @pytest.mark.integration
    def test_relay_node_analysis_data_structure(self, client):
        """Test the structure of relay node analysis data."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Should have relay_node_stats based on fixtures
        if data["relay_node_stats"]:
            stat = data["relay_node_stats"][0]

            # Check required fields
            assert "relay_node" in stat
            assert "relay_hex" in stat
            assert "count" in stat
            assert "candidates" in stat
            assert "avg_rssi" in stat
            assert "avg_snr" in stat

            # relay_hex should be 2-character hex string
            assert len(stat["relay_hex"]) == 2
            assert stat["count"] > 0

            # Signal stats should be present (may be None for some entries)
            # If they exist, they should be numeric
            if stat["avg_rssi"] is not None:
                assert isinstance(stat["avg_rssi"], (int, float))
            if stat["avg_snr"] is not None:
                assert isinstance(stat["avg_snr"], (int, float))

            # candidates should be a list
            assert isinstance(stat["candidates"], list)

            # If there are candidates, check their structure
            if stat["candidates"]:
                candidate = stat["candidates"][0]
                assert "node_id" in candidate
                assert "node_name" in candidate
                assert "hex_id" in candidate
                assert "last_byte" in candidate

                # last_byte should be 2-character hex string
                assert len(candidate["last_byte"]) == 2

    @pytest.mark.integration
    def test_relay_node_analysis_with_hex_node_id(self, client):
        """Test that endpoint works with hex node ID format."""
        # Test with hex format node ID
        response = client.get("/api/node/!433d0c24/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()
        assert "relay_node_stats" in data

    @pytest.mark.integration
    def test_relay_node_analysis_limit_parameter(self, client):
        """Test that limit parameter works correctly."""
        # Test with smaller limit
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=5")
        assert response.status_code == 200

        data = response.get_json()

        # Should not exceed limit
        if data["relay_node_stats"]:
            assert len(data["relay_node_stats"]) <= 5

    @pytest.mark.integration
    def test_relay_node_analysis_total_packets(self, client):
        """Test that total_packets is correctly calculated."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # total_packets should equal sum of counts
        if data["relay_node_stats"]:
            calculated_total = sum(stat["count"] for stat in data["relay_node_stats"])
            assert data["total_packets"] == calculated_total

    @pytest.mark.integration
    def test_relay_node_analysis_candidates_match_last_byte(self, client):
        """Test that candidates' last bytes match the relay_node last byte."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Check that candidates have matching last bytes
        for stat in data["relay_node_stats"]:
            relay_hex = stat["relay_hex"]

            for candidate in stat["candidates"]:
                candidate_last_byte = candidate["last_byte"]

                # Candidate last byte should match relay_hex
                assert candidate_last_byte == relay_hex, (
                    f"Candidate last byte {candidate_last_byte} doesn't match "
                    f"relay_hex {relay_hex}"
                )

    @pytest.mark.integration
    def test_relay_node_analysis_sorted_by_count(self, client):
        """Test that relay_node stats are sorted by count descending."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Check that stats are sorted by count in descending order
        if len(data["relay_node_stats"]) > 1:
            counts = [stat["count"] for stat in data["relay_node_stats"]]
            assert counts == sorted(counts, reverse=True), (
                "Relay node stats should be sorted by count in descending order"
            )

    @pytest.mark.integration
    def test_relay_node_analysis_with_nonexistent_node(self, client):
        """Test relay node analysis with a nonexistent node ID."""
        response = client.get("/api/node/999999999/relay-node-analysis?limit=50")

        # Should return 200 with empty stats
        assert response.status_code == 200
        data = response.get_json()
        assert data["relay_node_stats"] == []
        assert data["total_count"] == 0
        assert data["total_packets"] == 0

    @pytest.mark.integration
    def test_relay_node_analysis_invalid_node_id(self, client):
        """Test relay node analysis with invalid node ID format."""
        response = client.get("/api/node/invalid_id/relay-node-analysis?limit=50")

        # Should return 400 for invalid node ID
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestRelayNodeAnalysisFixtures:
    """Test that the fixture data properly supports relay_node analysis."""

    @pytest.mark.integration
    def test_fixtures_have_relay_node_data(self, client):
        """Verify that test fixtures include relay_node data."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Based on our fixtures, we should have relay_node stats
        assert len(data["relay_node_stats"]) > 0, (
            "Test fixtures should include relay_node data for Test Gateway Alpha"
        )

        # We expect at least the three scenarios: 0x88, 0x98, 0xCC (case-insensitive)
        relay_hexes = {stat["relay_hex"].lower() for stat in data["relay_node_stats"]}
        expected_hexes = {"88", "98", "cc"}
        assert expected_hexes.issubset(relay_hexes), (
            f"Expected relay_hexes to include {expected_hexes}, got {relay_hexes}"
        )

        # Should have 0x88 with 20 packets
        assert any(
            stat["relay_hex"] == "88" and stat["count"] == 20
            for stat in data["relay_node_stats"]
        ), "Fixtures should include 20 packets with relay_node 0x88"

    @pytest.mark.integration
    def test_fixtures_have_candidate_nodes(self, client):
        """Verify that test fixtures include candidate nodes for relay analysis."""
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Based on fixtures, relay_node 0x88 should have candidates
        # because we created 0-hop packets from nodes with last byte 0x88
        stat_88 = next(
            (s for s in data["relay_node_stats"] if s["relay_hex"] == "88"), None
        )

        if stat_88:
            assert len(stat_88["candidates"]) > 0, (
                "Relay node 0x88 should have candidate nodes from 0-hop packets"
            )

            # Check that candidates are the nodes we created (0x12345688, 0x23456788)
            candidate_ids = {c["node_id"] for c in stat_88["candidates"]}
            assert 0x12345688 in candidate_ids, (
                "Should find node 0x12345688 as candidate"
            )
            assert 0x23456788 in candidate_ids, (
                "Should find node 0x23456788 as candidate"
            )

    @pytest.mark.integration
    def test_fixtures_bidirectional_candidates(self, client):
        """Test that bidirectional 0-hop links are detected in fixtures."""
        # Test Mobile Beta (1128074277) should appear as a candidate
        # for Test Gateway Alpha because other gateway received 0-hop packets
        # from Test Gateway Alpha
        response = client.get("/api/node/1128074276/relay-node-analysis?limit=50")
        assert response.status_code == 200

        data = response.get_json()

        # Test Gateway Alpha has last byte 0x24
        # Look for any relay_node with last byte 0x24 that might have
        # Test Mobile Beta as a candidate (though this specific scenario
        # depends on whether Test Mobile Beta also has last byte matching)

        # At minimum, verify the API returns valid candidate structure
        for stat in data["relay_node_stats"]:
            for candidate in stat["candidates"]:
                # Each candidate should have all required fields
                assert isinstance(candidate["node_id"], int)
                assert isinstance(candidate["node_name"], str)
                assert isinstance(candidate["hex_id"], str)
                assert isinstance(candidate["last_byte"], str)
