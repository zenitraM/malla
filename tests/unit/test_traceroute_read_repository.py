"""Behavioral tests for PR2's saved-traceroute list reader."""

import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from meshtastic import mesh_pb2

from malla.database.repositories import LocationRepository
from malla.database.traceroute_read_repository import (
    get_node_traceroute_statistics,
    get_route_patterns_data,
    get_traceroute_hops_for_graph,
    get_traceroute_hops_for_longest_links,
    get_traceroute_packets,
)
from malla.database.traceroute_schema import ensure_traceroute_schema
from malla.database.traceroutes import write_traceroute

pytestmark = pytest.mark.unit


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "reader.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                portnum INTEGER,
                portnum_name TEXT,
                mesh_packet_id INTEGER,
                from_node_id INTEGER,
                to_node_id INTEGER,
                gateway_id TEXT,
                channel_id TEXT,
                hop_start INTEGER,
                hop_limit INTEGER,
                rssi REAL,
                snr REAL,
                payload_length INTEGER,
                raw_payload BLOB,
                processed_successfully INTEGER DEFAULT 1
            )
        """)
        ensure_traceroute_schema(conn.cursor())
        conn.commit()
    return path


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _insert(conn, *, packet_id, timestamp, mesh_id, gateway, route=(900,), snr_towards=None):
    if snr_towards is None:
        snr_towards = [-40] * (len(route) + 1)
    raw = mesh_pb2.RouteDiscovery(
        route=route, snr_towards=snr_towards
    ).SerializeToString()
    cursor = conn.execute(
        """
        INSERT INTO packet_history (
            id, timestamp, portnum, portnum_name, mesh_packet_id,
            from_node_id, to_node_id, gateway_id, channel_id,
            hop_start, hop_limit, rssi, snr, payload_length, raw_payload
        ) VALUES (?, ?, 70, 'TRACEROUTE_APP', ?, 100, 200, ?, 'LongFast',
                  5, 3, -80, -10, ?, ?)
        """,
        (packet_id, timestamp, mesh_id, gateway, len(raw), raw),
    )
    packet = dict(
        conn.execute("SELECT * FROM packet_history WHERE id = ?", (cursor.lastrowid,)).fetchone()
    )
    write_traceroute(conn.cursor(), packet)


def test_empty_database_returns_empty_packets(database):
    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        result = get_traceroute_packets()

    assert result["total_count"] == 0
    assert result["packets"] == []


def test_grouping_filters_full_history_before_exact_pagination(database):
    with closing(_connection(database)) as conn:
        # More receptions than the old grouped-reader scan cap, with an older
        # matching route that must remain reachable on a later page.
        for packet_id in range(1, 101):
            _insert(
                conn,
                packet_id=packet_id,
                timestamp=packet_id,
                mesh_id=packet_id,
                gateway="!00000001",
                route=(900 if packet_id == 1 else 901,),
            )
        # A second reception of one mesh packet must change its reception count,
        # not the number of grouped rows.
        _insert(
            conn,
            packet_id=101,
            timestamp=101,
            mesh_id=1,
            gateway="!00000002",
            route=(900,),
        )
        conn.commit()

    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        page = get_traceroute_packets(
            limit=10,
            offset=90,
            filters={"start_time": 0.0, "end_time": 200.0},
            group_packets=True,
        )
        route_match = get_traceroute_packets(
            limit=10,
            filters={"start_time": 0.0, "end_time": 200.0, "route_node": 900},
            group_packets=True,
        )
        gateway_sorted = get_traceroute_packets(
            limit=-1,
            filters={"start_time": 0.0, "end_time": 200.0},
            order_by="gateway_id",
            order_dir="asc",
            group_packets=True,
        )

    assert page["total_count"] == 100
    assert len(page["packets"]) == 10
    assert route_match["total_count"] == 1
    assert route_match["packets"][0]["mesh_packet_id"] == 1
    assert route_match["packets"][0]["reception_count"] == 2
    assert route_match["packets"][0]["gateway_count"] == 2
    assert gateway_sorted["packets"][0]["gateway_count"] == 1
    assert gateway_sorted["packets"][-1]["gateway_count"] == 2


def test_get_traceroute_hops_for_graph_and_longest_links(database):
    with closing(_connection(database)) as conn:
        _insert(conn, packet_id=1, timestamp=10.0, mesh_id=101, gateway="!00000001", route=(901, 902))
        conn.commit()

    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        hops = get_traceroute_hops_for_graph(filters={"start_time": 0.0, "end_time": 20.0})
        longest_hops = get_traceroute_hops_for_longest_links(start_time=0.0, end_time=20.0)

    assert len(hops) == 3
    assert [h["from_node_id"] for h in hops] == [100, 901, 902]
    assert [h["to_node_id"] for h in hops] == [901, 902, 200]
    assert len(longest_hops) == 3


def test_hop_query_preserves_zero_snr_hops_in_path_order(database):
    """A zero-SNR middle hop stays in the sequence so paths keep their structure.

    For A->B->C->D the stored hops are A->B, B->C, C->D. Dropping B->C (SNR 0)
    in SQL would leave two disconnected segments that downstream consumers
    would splice into a bogus two-hop A->D path.
    """
    with closing(_connection(database)) as conn:
        _insert(
            conn,
            packet_id=1,
            timestamp=10.0,
            mesh_id=101,
            gateway="!00000001",
            route=(901, 902),
            snr_towards=[-160, 0, -160],
        )
        conn.commit()

    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        hops = get_traceroute_hops_for_graph(filters={"start_time": 0.0, "end_time": 20.0})
        longest_hops = get_traceroute_hops_for_longest_links(start_time=0.0, end_time=20.0)

    for query_hops in (hops, longest_hops):
        assert [h["from_node_id"] for h in query_hops] == [100, 901, 902]
        assert [h["to_node_id"] for h in query_hops] == [901, 902, 200]
        assert [h["snr"] for h in query_hops] == [-40.0, 0.0, -40.0]


def test_get_route_patterns_data(database):
    with closing(_connection(database)) as conn:
        for pid in range(1, 4):
            _insert(conn, packet_id=pid, timestamp=float(pid), mesh_id=pid, gateway="!00000001", route=(905,))
        conn.commit()

    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        patterns_result = get_route_patterns_data(start_time=0.0, end_time=10.0, limit=5)

    assert patterns_result["total_patterns"] == 1
    assert patterns_result["analyzed_traceroutes"] == 3
    assert len(patterns_result["sorted_patterns"]) == 1
    pattern_key, pattern_data = patterns_result["sorted_patterns"][0]
    assert pattern_data["count"] == 3
    assert pattern_key[1] == (905,)


def test_get_node_traceroute_statistics(database):
    with closing(_connection(database)) as conn:
        _insert(conn, packet_id=1, timestamp=10.0, mesh_id=101, gateway="!00000001", route=(900,))
        conn.commit()

    with patch(
        "malla.database.traceroute_read_repository.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        source_stats = get_node_traceroute_statistics(node_id=100)
        dest_stats = get_node_traceroute_statistics(node_id=200)
        intermediate_stats = get_node_traceroute_statistics(node_id=900)

    assert source_stats["as_source"]["total"] == 1
    assert source_stats["as_source"]["successful"] == 1
    assert dest_stats["as_destination"]["total"] == 1
    assert dest_stats["as_destination"]["successful"] == 1
    assert intermediate_stats["as_intermediate_hop"]["participation_count"] == 1


def test_get_nodes_location_history(database):
    pos = mesh_pb2.Position(latitude_i=400000000, longitude_i=-300000000, altitude=150)
    pos_bytes = pos.SerializeToString()

    with closing(_connection(database)) as conn:
        conn.execute(
            """
            INSERT INTO packet_history (
                id, timestamp, portnum, portnum_name, from_node_id, to_node_id,
                gateway_id, payload_length, raw_payload
            ) VALUES (500, 100.0, 3, 'POSITION_APP', 100, 4294967295, '!00000001', ?, ?)
            """,
            (len(pos_bytes), pos_bytes),
        )
        conn.commit()

    with patch(
        "malla.database.repositories.get_db_connection",
        side_effect=lambda: _connection(database),
    ):
        locs = LocationRepository.get_nodes_location_history([100, 200], limit_per_node=5)

    assert 100 in locs
    assert len(locs[100]) == 1
    assert locs[100][0]["latitude"] == 40.0
    assert locs[100][0]["longitude"] == -30.0
    assert locs[100][0]["altitude"] == 150
    assert 200 in locs
    assert len(locs[200]) == 0

