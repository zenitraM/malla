"""Integration tests for exclude_self API functionality."""

import pytest


@pytest.mark.integration
@pytest.mark.api
class TestExcludeSelfAPI:
    """Integration tests for exclude_self filter behavior."""

    def test_exclude_self_filter_works(self, client):
        """Test that exclude_self filter actually excludes self-sent packets."""
        # Find a gateway that has both self-sent and other packets
        response = client.get("/api/packets/data?limit=100")
        assert response.status_code == 200
        data = response.get_json()

        # Find gateway with both self-sent and other packets
        gateway_stats = {}
        for packet in data.get("data", []):
            gw_node_id = packet.get("gateway_node_id")
            from_node_id = packet.get("from_node_id")
            if gw_node_id:
                if gw_node_id not in gateway_stats:
                    gateway_stats[gw_node_id] = {"self": 0, "others": 0}
                if from_node_id == gw_node_id:
                    gateway_stats[gw_node_id]["self"] += 1
                else:
                    gateway_stats[gw_node_id]["others"] += 1

        # Find a suitable gateway for testing
        test_gateway_id = None
        for gw_id, stats in gateway_stats.items():
            if stats["self"] > 0 and stats["others"] > 0:
                test_gateway_id = gw_id
                break

        if not test_gateway_id:
            pytest.skip("No gateway found with both self-sent and other packets")

        # Test without exclude_self
        response = client.get(
            f"/api/packets/data?gateway_id={test_gateway_id}&limit=20"
        )
        assert response.status_code == 200
        data_without_filter = response.get_json()
        packets_without_filter = data_without_filter.get("data", [])

        # Count self-sent packets
        self_sent_count = sum(
            1
            for p in packets_without_filter
            if p.get("from_node_id") == test_gateway_id
        )
        assert self_sent_count > 0, "Should have self-sent packets without filter"

        # Test with exclude_self=true
        response = client.get(
            f"/api/packets/data?gateway_id={test_gateway_id}&exclude_self=true&limit=20"
        )
        assert response.status_code == 200
        data_with_filter = response.get_json()
        packets_with_filter = data_with_filter.get("data", [])

        # Verify no self-sent packets
        self_sent_count_filtered = sum(
            1 for p in packets_with_filter if p.get("from_node_id") == test_gateway_id
        )
        assert self_sent_count_filtered == 0, (
            "Should have no self-sent packets with exclude_self=true"
        )

        # Verify we still have other packets
        assert len(packets_with_filter) > 0, "Should still have non-self packets"

        # Verify all remaining packets are from other nodes
        for packet in packets_with_filter:
            from_node_id = packet.get("from_node_id")
            assert from_node_id != test_gateway_id, (
                f"Found self-sent packet {packet['id']} when exclude_self=true"
            )

    def test_exclude_self_with_no_gateway_filter(self, client):
        """Test that exclude_self without gateway_id has no effect."""
        # Without gateway filter, exclude_self should have no effect
        response1 = client.get("/api/packets/data?limit=10")
        response2 = client.get("/api/packets/data?exclude_self=true&limit=10")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.get_json()
        data2 = response2.get_json()

        # Should return same results when no gateway filter is applied
        assert len(data1.get("data", [])) == len(data2.get("data", []))

    def test_exclude_self_false_includes_self_packets(self, client):
        """Test that exclude_self=false includes self-sent packets."""
        # Find a gateway with self-sent packets
        response = client.get("/api/packets/data?limit=100")
        assert response.status_code == 200
        data = response.get_json()

        test_gateway_id = None
        for packet in data.get("data", []):
            gw_node_id = packet.get("gateway_node_id")
            from_node_id = packet.get("from_node_id")
            if gw_node_id and from_node_id == gw_node_id:
                test_gateway_id = gw_node_id
                break

        if not test_gateway_id:
            pytest.skip("No gateway found with self-sent packets")

        # Test with exclude_self=false (explicit)
        response = client.get(
            f"/api/packets/data?gateway_id={test_gateway_id}&exclude_self=false&limit=20"
        )
        assert response.status_code == 200
        data = response.get_json()
        packets = data.get("data", [])

        # Should include self-sent packets
        self_sent_count = sum(
            1 for p in packets if p.get("from_node_id") == test_gateway_id
        )
        assert self_sent_count > 0, (
            "Should include self-sent packets when exclude_self=false"
        )
