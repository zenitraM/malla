"""Integration tests for route_node filtering when group_packets=true.

These tests ensure that traceroute queries with the `route_node` filter applied
return only packets that include the specified node anywhere in the route, even
when aggregated (`group_packets=true`).
"""

import pytest


@pytest.mark.integration
class TestTracerouteRouteNodeGrouped:
    """Tests for route_node filter with grouped traceroute queries."""

    ROUTE_NODE_CANDIDATES = [
        0x11111111,  # 286331153 – used in fixtures
        0x22222222,  # 572662306
        0x33333333,  # 858993459
        0x55555555,  # 1431655765
        555666777,  # From traceroute_graph_data fixture
    ]

    def _find_route_node_with_results(self, client):
        """Return first route_node candidate that yields results when grouped."""
        for node in self.ROUTE_NODE_CANDIDATES:
            resp = client.get(
                f"/api/traceroute/data?page=1&limit=5&group_packets=true&route_node={node}"
            )
            assert resp.status_code == 200
            data = resp.get_json()
            if data["total_count"] > 0:
                return node, data["total_count"]
        return None, 0

    def test_grouped_route_node_filter_returns_correct_packets(self, client):
        """Verify that grouped queries honour the route_node filter."""
        route_node, total_cnt = self._find_route_node_with_results(client)
        if route_node is None:
            pytest.skip("No suitable route_node found in fixture data for grouped test")

        # Fetch a page of grouped results
        resp = client.get(
            f"/api/traceroute/data?page=1&limit=25&group_packets=true&route_node={route_node}"
        )
        assert resp.status_code == 200
        payload = resp.get_json()

        # Basic response checks
        assert payload["total_count"] == total_cnt
        assert payload["page"] == 1
        assert payload["limit"] == 25
        assert isinstance(payload["data"], list)
        assert payload["data"], "Expected at least one packet in response"

        # All returned packets should be grouped and include the route_node
        for pkt in payload["data"]:
            assert pkt["is_grouped"] is True
            route_nodes = pkt.get("route_nodes", [])
            from_node = pkt.get("from_node_id")
            to_node = pkt.get("to_node_id")
            assert (
                route_node in route_nodes
                or route_node == from_node
                or route_node == to_node
            ), (
                f"Packet {pkt['id']} does not contain route_node {route_node}. "
                f"route_nodes={route_nodes}, from_node={from_node}, to_node={to_node}"
            )
