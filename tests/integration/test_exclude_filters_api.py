"""
Integration tests for exclude filter API functionality.

Tests the API endpoints that handle exclude_from and exclude_to parameters
using fixture data to ensure filters work correctly.
"""

import pytest


class TestExcludeFiltersAPI:
    """Test exclude filter functionality in API endpoints."""

    @pytest.mark.integration
    def test_exclude_from_filter_api(self, client, test_server_url):
        """Test that exclude_from parameter correctly excludes packets from specified node."""
        # Use known node ID from fixture data
        exclude_node_id = 1128074276  # Test Gateway Alpha

        # First, get all packets to establish baseline (use higher limit to get more data)
        response_all = client.get("/api/packets/data?limit=200")
        assert response_all.status_code == 200
        all_data = response_all.get_json()
        total_packets = len(all_data["data"])
        total_count = all_data["total_count"]

        # Count packets from the node we want to exclude
        packets_from_excluded_node = [
            p for p in all_data["data"] if p["from_node_id"] == exclude_node_id
        ]
        packets_from_excluded_count = len(packets_from_excluded_node)

        print(f"Total packets: {total_packets} (total_count: {total_count})")
        print(f"Packets from node {exclude_node_id}: {packets_from_excluded_count}")

        # Skip test if no packets from this node
        if packets_from_excluded_count == 0:
            pytest.skip(f"No packets from node {exclude_node_id} in test data")

        # Now get packets with exclude_from filter
        response_filtered = client.get(
            f"/api/packets/data?exclude_from={exclude_node_id}&limit=200"
        )
        assert response_filtered.status_code == 200
        filtered_data = response_filtered.get_json()
        filtered_packets = filtered_data["data"]
        filtered_total_count = filtered_data["total_count"]

        # Verify none of the filtered results come from the excluded node
        for packet in filtered_packets:
            assert packet["from_node_id"] != exclude_node_id, (
                f"Found packet {packet['id']} from excluded node {exclude_node_id}"
            )

        # The key test: total_count should be reduced by the number of excluded packets
        expected_total_count = total_count - packets_from_excluded_count
        assert filtered_total_count == expected_total_count, (
            f"Expected total_count {expected_total_count} after excluding from {exclude_node_id}, "
            f"got {filtered_total_count} (original: {total_count}, excluded: {packets_from_excluded_count})"
        )

        print(
            f"✅ Exclude from filter working: {filtered_total_count} total packets, {len(filtered_packets)} returned"
        )

    @pytest.mark.integration
    def test_exclude_to_filter_api(self, client, test_server_url):
        """Test that exclude_to parameter correctly excludes packets to specified node."""
        # Use broadcast node ID (common destination in test data)
        exclude_node_id = 4294967295  # Broadcast

        # First, get all packets to establish baseline (use higher limit)
        response_all = client.get("/api/packets/data?limit=200")
        assert response_all.status_code == 200
        all_data = response_all.get_json()
        total_packets = len(all_data["data"])
        total_count = all_data["total_count"]

        # Count packets to the node we want to exclude
        packets_to_excluded_node = [
            p for p in all_data["data"] if p["to_node_id"] == exclude_node_id
        ]
        packets_to_excluded_count = len(packets_to_excluded_node)

        print(f"Total packets: {total_packets} (total_count: {total_count})")
        print(
            f"Packets to node {exclude_node_id} (broadcast): {packets_to_excluded_count}"
        )

        # Skip test if no packets to this node
        if packets_to_excluded_count == 0:
            pytest.skip(f"No packets to node {exclude_node_id} in test data")

        # Now get packets with exclude_to filter
        response_filtered = client.get(
            f"/api/packets/data?exclude_to={exclude_node_id}&limit=200"
        )
        assert response_filtered.status_code == 200
        filtered_data = response_filtered.get_json()
        filtered_packets = filtered_data["data"]
        filtered_total_count = filtered_data["total_count"]

        # Verify none of the filtered results go to the excluded node
        for packet in filtered_packets:
            assert packet["to_node_id"] != exclude_node_id, (
                f"Found packet {packet['id']} to excluded node {exclude_node_id}"
            )

        # The key test: total_count should be reduced by the number of excluded packets
        expected_total_count = total_count - packets_to_excluded_count
        assert filtered_total_count == expected_total_count, (
            f"Expected total_count {expected_total_count} after excluding to {exclude_node_id}, "
            f"got {filtered_total_count} (original: {total_count}, excluded: {packets_to_excluded_count})"
        )

        print(
            f"✅ Exclude to filter working: {filtered_total_count} total packets, {len(filtered_packets)} returned"
        )

    @pytest.mark.integration
    def test_exclude_broadcast_packets_api(self, client, test_server_url):
        """Test excluding broadcast packets specifically using exclude_to filter."""
        broadcast_node_id = 4294967295

        # Get packets excluding broadcast destinations
        response = client.get(
            f"/api/packets/data?exclude_to={broadcast_node_id}&limit=200"
        )
        assert response.status_code == 200
        data = response.get_json()

        # Verify no packets go to broadcast
        for packet in data["data"]:
            assert packet["to_node_id"] != broadcast_node_id, (
                f"Found broadcast packet {packet['id']} in exclude_to=broadcast results"
            )

        print(
            f"✅ Broadcast exclusion working: {len(data['data'])} non-broadcast packets displayed, {data['total_count']} total"
        )

    @pytest.mark.integration
    def test_combined_exclude_filters_api(self, client, test_server_url):
        """Test using both exclude_from and exclude_to filters together."""
        exclude_from_node = 1128074276  # Test Gateway Alpha
        exclude_to_node = 4294967295  # Broadcast

        # Get all packets first for count verification
        response_all = client.get("/api/packets/data?limit=200")
        assert response_all.status_code == 200

        # Get packets with both exclusions
        response_filtered = client.get(
            f"/api/packets/data?exclude_from={exclude_from_node}&exclude_to={exclude_to_node}&limit=200"
        )
        assert response_filtered.status_code == 200
        filtered_data = response_filtered.get_json()
        filtered_packets = filtered_data["data"]

        # Verify exclusions are applied
        for packet in filtered_packets:
            assert packet["from_node_id"] != exclude_from_node, (
                f"Found packet {packet['id']} from excluded node {exclude_from_node}"
            )
            assert packet["to_node_id"] != exclude_to_node, (
                f"Found packet {packet['id']} to excluded node {exclude_to_node}"
            )

        print(
            f"✅ Combined exclude filters working: {len(filtered_packets)} packets displayed, {filtered_data['total_count']} total"
        )

    @pytest.mark.integration
    def test_exclude_filters_with_other_filters_api(self, client, test_server_url):
        """Test exclude filters work correctly when combined with other filters."""
        exclude_from_node = 1128074276
        portnum_filter = "TEXT_MESSAGE_APP"

        # Get packets with both exclude and portnum filter
        response = client.get(
            f"/api/packets/data?exclude_from={exclude_from_node}&portnum={portnum_filter}&limit=200"
        )
        assert response.status_code == 200
        data = response.get_json()

        # Verify both filters are applied
        for packet in data["data"]:
            assert packet["from_node_id"] != exclude_from_node, (
                f"Found packet {packet['id']} from excluded node despite exclude_from filter"
            )
            assert packet["portnum_name"] == portnum_filter, (
                f"Found packet {packet['id']} with wrong portnum: {packet['portnum_name']}"
            )

        print(
            f"✅ Exclude + portnum filters working: {len(data['data'])} packets displayed, {data['total_count']} total"
        )

    @pytest.mark.integration
    def test_exclude_nonexistent_node_api(self, client, test_server_url):
        """Test that excluding a non-existent node doesn't break the API."""
        nonexistent_node = 999999999

        # This should work without errors and return all packets
        response = client.get(
            f"/api/packets/data?exclude_from={nonexistent_node}&limit=200"
        )
        assert response.status_code == 200
        data = response.get_json()

        # Should have packets (since nothing was actually excluded)
        assert len(data["data"]) > 0, (
            "Should have packets when excluding non-existent node"
        )

        print(
            f"✅ Non-existent node exclusion handled gracefully: {len(data['data'])} packets displayed, {data['total_count']} total"
        )

    @pytest.mark.integration
    def test_exclude_filters_boundary_conditions_api(self, client, test_server_url):
        """Test exclude filters with boundary conditions."""
        # Test with empty string (should be ignored)
        response = client.get("/api/packets/data?exclude_from=&exclude_to=&limit=200")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["data"]) > 0, (
            "Empty exclude filters should not exclude anything"
        )

        # Test with invalid node IDs (should be handled gracefully)
        response = client.get(
            "/api/packets/data?exclude_from=invalid&exclude_to=999999999999&limit=200"
        )
        assert response.status_code == 200  # Should not crash

        print("✅ Boundary conditions handled correctly")

    @pytest.mark.integration
    def test_exclude_filters_performance_api(self, client, test_server_url):
        """Test that exclude filters don't significantly impact performance."""
        import time

        # Time without filters
        start_time = time.time()
        response_no_filter = client.get("/api/packets/data?limit=100")
        no_filter_time = time.time() - start_time
        assert response_no_filter.status_code == 200

        # Time with exclude filters
        start_time = time.time()
        response_with_filter = client.get(
            "/api/packets/data?exclude_from=1128074276&exclude_to=4294967295&limit=100"
        )
        with_filter_time = time.time() - start_time
        assert response_with_filter.status_code == 200

        # Filter should not be significantly slower (allow up to 4x slower for complex queries)
        performance_ratio = (
            with_filter_time / no_filter_time if no_filter_time > 0 else 1
        )
        assert performance_ratio < 4.0, (
            f"Exclude filters too slow: {with_filter_time:.3f}s vs {no_filter_time:.3f}s "
            f"(ratio: {performance_ratio:.2f})"
        )

        print(
            f"✅ Performance acceptable: {no_filter_time:.3f}s -> {with_filter_time:.3f}s"
        )

    @pytest.mark.integration
    def test_exclude_filters_total_count_consistency_api(self, client, test_server_url):
        """Test that total_count is correctly updated when using exclude filters."""
        exclude_from_node = 1128074276

        # Get total count without filters
        response_all = client.get("/api/packets/data?limit=1")
        assert response_all.status_code == 200
        total_without_filter = response_all.get_json()["total_count"]

        # Get total count with exclude filter
        response_filtered = client.get(
            f"/api/packets/data?exclude_from={exclude_from_node}&limit=1"
        )
        assert response_filtered.status_code == 200
        total_with_filter = response_filtered.get_json()["total_count"]

        # Total with filter should be less than or equal to total without filter
        assert total_with_filter <= total_without_filter, (
            f"Total count with filter ({total_with_filter}) should not exceed "
            f"total without filter ({total_without_filter})"
        )

        # If there are packets from the excluded node, total should be different
        response_check = client.get(
            "/api/packets/data?from_node={exclude_from_node}&limit=1"
        )
        packets_from_excluded = response_check.get_json()["total_count"]

        if packets_from_excluded > 0:
            assert total_with_filter < total_without_filter, (
                "Total count should be reduced when excluding node that has packets"
            )

        print(
            f"✅ Total count consistency: {total_without_filter} -> {total_with_filter}"
        )
