"""Tests for reception sorting on the packet detail page."""

import pytest

from malla.routes.packet_routes import sort_receptions_for_display

pytestmark = pytest.mark.unit


def test_sort_receptions_for_display_orders_by_hop_then_gateway_then_relay():
    receptions = [
        {
            "id": 3,
            "timestamp": 300.0,
            "hop_count": 2,
            "gateway_id": "!BBBBBBBB",
            "relay_node": 0x12340002,
        },
        {
            "id": 1,
            "timestamp": 100.0,
            "hop_count": 1,
            "gateway_id": "!CCCCCCCC",
            "relay_node": 0x12340003,
        },
        {
            "id": 4,
            "timestamp": 400.0,
            "hop_count": None,
            "gateway_id": "!AAAAAAA0",
            "relay_node": 0x12340004,
        },
        {
            "id": 2,
            "timestamp": 200.0,
            "hop_count": 1,
            "gateway_id": "!BBBBBBBB",
            "relay_node": 0x12340001,
        },
    ]

    sorted_receptions = sort_receptions_for_display(receptions)

    # Expected order:
    # - hop_count 1 first, then 2, then None (unknown)
    # - within hop_count 1: by gateway_id, then relay_node
    assert [r["id"] for r in sorted_receptions] == [2, 1, 3, 4]


def test_sort_receptions_for_display_handles_missing_fields_gracefully():
    receptions = [
        {
            "id": 1,
            "timestamp": None,
            "hop_count": None,
            "gateway_id": None,
            "relay_node": None,
        },
        {
            "id": 2,
            # No timestamp key at all
            "hop_count": 0,
            "gateway_id": "!11111111",
            # No relay_node key at all
        },
    ]

    sorted_receptions = sort_receptions_for_display(receptions)

    # Known hop_count (0) should come before unknown
    assert [r["id"] for r in sorted_receptions] == [2, 1]
