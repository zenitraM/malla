import pytest


def _is_sorted(values, ascending=True):
    """Utility to check if list is sorted, treating None as extreme."""
    # Replace None with extreme values for comparison
    extreme = float("inf") if ascending else float("-inf")
    norm = [v if v is not None else extreme for v in values]
    return all(
        (norm[i] <= norm[i + 1]) if ascending else (norm[i] >= norm[i + 1])
        for i in range(len(norm) - 1)
    )


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.parametrize(
    "sort_by,api_field",
    [
        ("from_node", "from_node_id"),
        ("to_node", "to_node_id"),
        ("hops", "hops"),
    ],
)
def test_packets_sorting(client, sort_by, api_field):
    """Verify that /api/packets/data supports sorting by the given field when ungrouped."""
    for order in ("asc", "desc"):
        resp = client.get(
            f"/api/packets/data?limit=25&sort_by={sort_by}&sort_order={order}&group_packets=false"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        rows = data["data"]
        values = [row.get(api_field) for row in rows]
        if len(values) > 1:
            assert _is_sorted(values, ascending=(order == "asc")), (
                f"Packet sorting failed for {sort_by} {order}"
            )


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.parametrize(
    "sort_by,api_field",
    [
        ("from_node", "from_node_id"),
        ("to_node", "to_node_id"),
        ("hops", "hops"),
    ],
)
def test_traceroute_sorting(client, sort_by, api_field):
    """Verify that /api/traceroute/data supports sorting by the given field when ungrouped."""
    for order in ("asc", "desc"):
        resp = client.get(
            f"/api/traceroute/data?limit=25&sort_by={sort_by}&sort_order={order}&group_packets=false"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        rows = data["data"]
        values = [row.get(api_field) for row in rows]
        if len(values) > 1:
            assert _is_sorted(values, ascending=(order == "asc")), (
                f"Traceroute sorting failed for {sort_by} {order}"
            )
