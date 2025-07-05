import pytest


@pytest.mark.integration
@pytest.mark.api
class TestPacketsExcludeSelf:
    """Integration tests for exclude_self filter behavior."""

    GATEWAY_ID = "!11110000"
    GATEWAY_NODE_INT = int(GATEWAY_ID[1:], 16)

    def _assert_no_self_messages(self, packets):
        for pkt in packets:
            # Legacy endpoint returns list of dicts under "packets"
            from_id = pkt.get("from_node_id") or pkt.get("from_node")
            assert from_id != self.GATEWAY_NODE_INT, (
                "Self-reported gateway messages were not excluded as expected"
            )

    def test_legacy_endpoint_exclude_self(self, client):
        """/api/packets should respect exclude_self parameter."""
        # Without exclude_self (baseline)
        resp = client.get(f"/api/packets?gateway_id={self.GATEWAY_ID}&limit=50&page=1")
        assert resp.status_code == 200
        packets_all = resp.get_json()["packets"]
        assert len(packets_all) > 0

        # With exclude_self=true
        resp = client.get(
            f"/api/packets?gateway_id={self.GATEWAY_ID}&exclude_self=true&limit=50&page=1"
        )
        assert resp.status_code == 200
        packets_filtered = resp.get_json()["packets"]
        assert len(packets_filtered) > 0

        # Verify filtered packets have no self messages
        self._assert_no_self_messages(packets_filtered)

        # Filtered list should be <= original
        assert len(packets_filtered) <= len(packets_all)

    def test_modern_endpoint_exclude_self(self, client):
        """/api/packets/data should respect exclude_self parameter."""
        # Without exclude_self
        resp = client.get(
            f"/api/packets/data?gateway_id={self.GATEWAY_ID}&limit=50&page=1&group_packets=false"
        )
        assert resp.status_code == 200
        packets_all = resp.get_json()["data"]
        assert len(packets_all) > 0

        # With exclude_self=true
        resp = client.get(
            f"/api/packets/data?gateway_id={self.GATEWAY_ID}&exclude_self=true&limit=50&page=1&group_packets=false"
        )
        assert resp.status_code == 200
        packets_filtered = resp.get_json()["data"]
        assert len(packets_filtered) > 0

        # Verify no self messages
        self._assert_no_self_messages(packets_filtered)

        assert len(packets_filtered) <= len(packets_all)
