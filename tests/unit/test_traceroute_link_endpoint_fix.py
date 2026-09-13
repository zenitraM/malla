"""Regression tests for materialized traceroute-link pagination."""

import sqlite3
import time
from unittest.mock import patch

import pytest
from flask import Flask

from src.malla.database.traceroute_read_repository import get_traceroute_link
from src.malla.routes.api_routes import register_api_routes

pytestmark = pytest.mark.unit


class _NonClosingConnection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        pass


def _packet(packet_id, timestamp, gateway_id="!0000012c"):
    return {
        "id": packet_id,
        "timestamp": timestamp,
        "timestamp_str": "2026-09-10 10:00:00",
        "from_node_id": 100,
        "to_node_id": 200,
        "gateway_id": gateway_id,
        "route_nodes_json": "[]",
        "snr_towards_json": "[-16.5]",
        "route_back_json": "[]",
        "snr_back_json": "[]",
        "target_hop_snr": -16.5,
    }


def test_endpoint_paginates_details_but_keeps_full_window_statistics():
    now = time.time()
    link_result = {
        "packets": [_packet(15, now), _packet(14, now - 1)],
        "total_count": 25,
        "total_attempts": 25,
        "forward_count": 13,
        "reverse_count": 12,
        "avg_snr": -11.25,
    }

    app = Flask(__name__)
    register_api_routes(app)
    with (
        patch(
            "src.malla.routes.api_routes.get_traceroute_link",
            return_value=link_result,
        ) as query,
        patch(
            "src.malla.routes.api_routes.NodeRepository.get_bulk_node_names",
            return_value={100: "Node A", 200: "Node B", 300: "Gateway"},
        ) as names,
        app.test_client() as client,
    ):
        response = client.get("/api/traceroute/link/100/200?limit=10&page=2")

    assert response.status_code == 200
    data = response.get_json()
    assert [row["id"] for row in data["traceroutes"]] == [15, 14]
    assert data["page"] == 2
    assert data["limit"] == 10
    assert data["total_count"] == 25
    assert data["total_pages"] == 3
    assert data["total_attempts"] == 25
    assert data["avg_snr"] == -11.25
    assert data["direction_counts"] == {
        "Node A → Node B": 13,
        "Node B → Node A": 12,
    }
    assert data["traceroutes"][0]["complete_path_display"] == "Node A"
    assert data["traceroutes"][0]["gateway_node_name"] == "Gateway"
    assert names.call_count == 1
    assert query.call_args.kwargs["limit"] == 10
    assert query.call_args.kwargs["offset"] == 10


def test_endpoint_returns_empty_paginated_result():
    link_result = {
        "packets": [],
        "total_count": 0,
        "total_attempts": 0,
        "forward_count": 0,
        "reverse_count": 0,
        "avg_snr": None,
    }
    app = Flask(__name__)
    register_api_routes(app)
    with (
        patch(
            "src.malla.routes.api_routes.get_traceroute_link",
            return_value=link_result,
        ),
        patch(
            "src.malla.routes.api_routes.NodeRepository.get_bulk_node_names",
            return_value={},
        ),
        app.test_client() as client,
    ):
        response = client.get("/api/traceroute/link/100/200?limit=10&page=2")

    data = response.get_json()
    assert response.status_code == 200
    assert data["traceroutes"] == []
    assert data["direction_counts"] == {"forward": 0, "reverse": 0}
    assert data["total_count"] == 0
    assert data["total_pages"] == 0


def test_materialized_link_query_aggregates_all_rows_and_pages_packet_details():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE packet_history (
            id INTEGER PRIMARY KEY, gateway_id TEXT, channel_id TEXT,
            hop_start INTEGER, hop_limit INTEGER, rssi REAL, snr REAL,
            payload_length INTEGER, processed_successfully INTEGER
        );
        CREATE TABLE traceroute_routes (
            packet_id INTEGER PRIMARY KEY, timestamp REAL, from_node_id INTEGER,
            to_node_id INTEGER, mesh_packet_id INTEGER, route_nodes_json TEXT,
            snr_towards_json TEXT, route_back_json TEXT, snr_back_json TEXT,
            parse_status TEXT, parser_version INTEGER
        );
        CREATE TABLE traceroute_hops (
            packet_id INTEGER, direction TEXT, hop_index INTEGER, timestamp REAL,
            from_node_id INTEGER, to_node_id INTEGER, snr REAL
        );
        """
    )
    now = time.time()
    for packet_id in range(1, 26):
        from_node_id, to_node_id = (
            (100, 200) if packet_id % 2 else (200, 100)
        )
        connection.execute(
            "INSERT INTO packet_history VALUES (?, ?, '', 5, 4, -80, 1, 10, 1)",
            (packet_id, "!0000012c"),
        )
        connection.execute(
            "INSERT INTO traceroute_routes VALUES (?, ?, 100, 200, ?, '[]', ?, '[]', '[]', 'parsed', 1)",
            (packet_id, now + packet_id, packet_id, "[-10]"),
        )
        connection.execute(
            "INSERT INTO traceroute_hops VALUES (?, 'forward', 0, ?, ?, ?, ?)",
            (packet_id, now + packet_id, from_node_id, to_node_id, -packet_id),
        )
    # Repeated occurrences stay in aggregate hop statistics but must not duplicate
    # the packet in the paginated traceroute details.
    connection.execute(
        "INSERT INTO traceroute_hops VALUES (1, 'return', 1, ?, 200, 100, 5)",
        (now + 1,),
    )
    connection.commit()

    with patch(
        "src.malla.database.traceroute_read_repository.get_db_connection",
        return_value=_NonClosingConnection(connection),
    ):
        result = get_traceroute_link(
            100,
            200,
            start_time=now,
            end_time=now + 30,
            limit=10,
            offset=10,
        )

    assert result["total_count"] == 25
    assert result["total_attempts"] == 25
    assert result["forward_count"] == 13
    assert result["reverse_count"] == 13
    assert result["avg_snr"] == pytest.approx((sum(range(-1, -26, -1)) + 5) / 26)
    assert [packet["id"] for packet in result["packets"]] == list(range(15, 5, -1))
