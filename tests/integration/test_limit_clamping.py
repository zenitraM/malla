"""Regression tests for pagination limit clamping (resource-exhaustion guard).

An unbounded ``?limit=`` is interpolated into SQL ``LIMIT``, where SQLite treats
a negative value as "no limit" (whole table) and a huge value forces an
unbounded result set. Endpoints must clamp it.
"""

import pytest


@pytest.mark.integration
@pytest.mark.api
def test_packets_data_clamps_huge_limit(client):
    resp = client.get(
        "/api/packets/data", query_string={"limit": 99999999, "group_packets": "false"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["limit"] <= 1000


@pytest.mark.integration
@pytest.mark.api
def test_packets_data_negative_limit_falls_back(client):
    # SQLite LIMIT -1 means "no limit"; a negative value must not reach SQL.
    resp = client.get(
        "/api/packets/data", query_string={"limit": -1, "group_packets": "false"}
    )
    assert resp.status_code == 200
    assert 1 <= resp.get_json()["limit"] <= 1000


@pytest.mark.integration
@pytest.mark.api
def test_nodes_data_allows_full_roster_limit(client):
    # The nodes table legitimately loads up to 10000 rows; that must still work.
    resp = client.get("/api/nodes/data", query_string={"limit": 10000})
    assert resp.status_code == 200
    assert resp.get_json()["limit"] == 10000


@pytest.mark.integration
@pytest.mark.api
def test_nodes_data_caps_above_max(client):
    resp = client.get("/api/nodes/data", query_string={"limit": 10_000_000})
    assert resp.status_code == 200
    assert resp.get_json()["limit"] <= 10000


@pytest.mark.integration
@pytest.mark.api
def test_packets_negative_page_does_not_error(client):
    resp = client.get(
        "/api/packets", query_string={"limit": 10, "page": -5}
    )
    assert resp.status_code == 200
    assert resp.get_json()["page"] >= 1
