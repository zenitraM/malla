import json
import time
from unittest.mock import patch

import pytest

from src.malla.utils.traceroute_graph import build_combined_traceroute_graph


@pytest.mark.unit
@patch("src.malla.utils.traceroute_utils.parse_traceroute_payload")
@patch("src.malla.utils.node_utils.get_bulk_node_names")
def test_build_combined_graph_basic(mock_get_names, mock_parse):
    """Ensure that the utility aggregates hops across multiple traceroutes."""
    # Mock node names for readability
    mock_get_names.return_value = {
        0x01: "NodeA",
        0x02: "NodeB",
        0x03: "NodeC",
    }

    # Prepare traceroute payloads (JSON encoded like the DB stores)
    payload1 = json.dumps(
        {
            "route_nodes": [0x02],
            "snr_towards": [5.0, 4.0],
            "route_back": [],
            "snr_back": [],
        }
    ).encode()

    payload2 = json.dumps(
        {
            "route_nodes": [0x02, 0x03],
            "snr_towards": [6.0, 3.5, 2.0],
            "route_back": [],
            "snr_back": [],
        }
    ).encode()

    # Configure mock parse to just load the JSON we encoded
    def parse_side_effect(raw):
        return json.loads(raw.decode())

    mock_parse.side_effect = parse_side_effect

    base_time = int(time.time())
    packet1 = {
        "id": 1,
        "timestamp": base_time,
        "from_node_id": 0x01,
        "to_node_id": 0x03,
        "gateway_id": "!00000001",
        "hop_start": 3,
        "hop_limit": 0,
        "raw_payload": payload1,
        "portnum_name": "TRACEROUTE_APP",
        "payload_length": len(payload1),
    }

    packet2 = {
        "id": 2,
        "timestamp": base_time + 0.5,
        "from_node_id": 0x01,
        "to_node_id": 0x03,
        "gateway_id": "!00000002",
        "hop_start": 4,
        "hop_limit": 0,
        "raw_payload": payload2,
        "portnum_name": "TRACEROUTE_APP",
        "payload_length": len(payload2),
    }

    graph = build_combined_traceroute_graph([packet1, packet2])

    # Expect three unique nodes
    assert len(graph["nodes"]) == 3

    # Expect edges NodeA-NodeB and NodeB-NodeC (undirected)
    edge_ids = {edge["id"] for edge in graph["edges"]}
    # Edge IDs use node names, but in test they fall back to hex format
    # Check for the actual connections: 0x01-0x02 and 0x02-0x03
    assert any("00000001" in edge_id and "00000002" in edge_id for edge_id in edge_ids)
    assert any("00000002" in edge_id and "00000003" in edge_id for edge_id in edge_ids)

    # Edge observation counts should reflect combined occurrences
    # 0x01-0x02 edge appears in both packets (once each) => count 2
    nodeab_edge = next(
        (
            edge
            for edge in graph["edges"]
            if "00000001" in edge["id"] and "00000002" in edge["id"]
        ),
        None,
    )
    assert nodeab_edge is not None
    assert nodeab_edge["value"] == 2
