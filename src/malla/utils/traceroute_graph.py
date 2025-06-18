import logging
from collections import defaultdict
from typing import Any

from ..models.traceroute import TraceroutePacket
from .node_utils import get_bulk_node_names

logger = logging.getLogger(__name__)


def _gateway_id_to_int(gateway_id):
    """Convert a gateway_id (which may be a string like '!abcdef12') to an int node id.
    Returns None if it cannot be converted."""
    if gateway_id is None:
        return None

    if isinstance(gateway_id, int):
        return gateway_id

    if isinstance(gateway_id, str) and gateway_id.startswith("!"):
        try:
            return int(gateway_id[1:], 16)
        except ValueError:
            return None

    # Unknown format
    return None


def build_combined_traceroute_graph(packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a combined traceroute graph using hop links from multiple related traceroute packets.

    The resulting structure is suitable for direct JSON serialisation and for visualisation
    on the front-end (e.g. with Vis-Network, D3, etc.).

    Args:
        packets: A list of packet dictionaries (each in the same format as returned by
                 the `packet_history` table queries). The list **must** contain the raw_payload
                 bytes so that TraceroutePacket can parse the hop data.

    Returns:
        dict with keys:
            nodes: List[dict]  – each dict has at least ``id`` (int), ``label`` (str), and ``type`` (str).
            edges: List[dict]  – each dict has ``id``, ``from``, ``to``, ``value`` (#observation),
                                   and ``title`` (tooltip text).
            paths: List[dict]  – each dict represents a unique packet path with color and packet info.
    """
    if not packets:
        return {"nodes": [], "edges": [], "paths": []}

    edge_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "snr_values": [],
            "packet_ids": [],
            "directions": [],
            "paths": set(),
        }
    )
    rf_node_ids_set = set()  # Only nodes that participate in actual RF hops
    gateway_node_ids_set = set()  # Gateway nodes that received packets
    packet_paths = {}  # Track unique paths for each packet

    # Process each packet to extract RF hops and gateway information
    for pkt in packets:
        packet_id = pkt.get("id")
        gateway_id = pkt.get("gateway_id")

        # Add gateway node if it's a node ID
        gateway_node_id = _gateway_id_to_int(gateway_id)
        if gateway_node_id:
            gateway_node_ids_set.add(gateway_node_id)

        try:
            tr = TraceroutePacket(pkt, resolve_names=False)
        except Exception as e:
            logger.debug(
                f"Failed to parse packet {pkt.get('id')} for combined graph: {e}"
            )
            continue

        # Get RF hops and build path for this packet
        rf_hops = tr.get_rf_hops()
        if not rf_hops:
            continue

        # Create path representation for this packet
        path_nodes = []
        for hop in rf_hops:
            if not path_nodes or path_nodes[-1] != hop.from_node_id:
                path_nodes.append(hop.from_node_id)
            path_nodes.append(hop.to_node_id)

        # Store path information
        packet_paths[packet_id] = {
            "nodes": path_nodes,
            "gateway_id": gateway_id,
            "gateway_node_id": gateway_node_id,
            "timestamp": pkt.get("timestamp"),
            "snr_values": [hop.snr for hop in rf_hops if hop.snr is not None],
        }

        # Collect nodes from RF hops only (what physically happened on air)
        for hop in rf_hops:
            n1, n2 = hop.from_node_id, hop.to_node_id
            rf_node_ids_set.update([n1, n2])

            # Keep directional information but also create undirected key for aggregation
            # Use string key instead of tuple to avoid JSON serialization issues
            undirected_key = f"{min(n1, n2)}-{max(n1, n2)}"
            edge_stats[undirected_key]["count"] += 1
            edge_stats[undirected_key]["packet_ids"].append(packet_id)
            edge_stats[undirected_key]["directions"].append([n1, n2])
            edge_stats[undirected_key]["paths"].add(packet_id)
            if hop.snr is not None:
                edge_stats[undirected_key]["snr_values"].append(hop.snr)

    # Get node names for all nodes (RF nodes + gateway nodes)
    all_node_ids = list(rf_node_ids_set | gateway_node_ids_set)
    node_names = get_bulk_node_names(all_node_ids) if all_node_ids else {}

    # Build node list with types
    nodes: list[dict[str, Any]] = []

    # Add RF nodes (nodes that participate in routing)
    for node_id in rf_node_ids_set:
        label = node_names.get(node_id, f"!{node_id:08x}")
        node_type = "gateway" if node_id in gateway_node_ids_set else "router"
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "type": node_type,
                "is_gateway": node_id in gateway_node_ids_set,
            }
        )

    # Add gateway-only nodes (gateways that received packets but didn't route)
    for node_id in gateway_node_ids_set:
        if node_id not in rf_node_ids_set:
            label = node_names.get(node_id, f"!{node_id:08x}")
            nodes.append(
                {"id": node_id, "label": label, "type": "gateway", "is_gateway": True}
            )

    # Build edges list with path information
    edges: list[dict[str, Any]] = []
    for edge_key, stats in edge_stats.items():
        # Parse the edge key back to node IDs
        n1, n2 = map(int, edge_key.split("-"))
        count = stats["count"]
        snr_vals = stats["snr_values"]
        avg_snr = None
        if snr_vals:
            avg_snr = sum(snr_vals) / len(snr_vals)

        # Get node names for edge labeling
        n1_name = node_names.get(n1, f"!{n1:08x}")
        n2_name = node_names.get(n2, f"!{n2:08x}")

        title_parts = [f"Observations: {count}"]
        if avg_snr is not None:
            title_parts.append(f"Avg SNR: {avg_snr:.1f} dB")
        title_parts.append(f"{n1_name} ↔ {n2_name}")
        title = " | ".join(title_parts)

        # Determine primary direction (most common direction for this edge)
        direction_counts: dict[str, int] = {}
        for direction in stats["directions"]:
            direction_key = f"{direction[0]}-{direction[1]}"  # Convert to string key
            direction_counts[direction_key] = direction_counts.get(direction_key, 0) + 1

        if direction_counts:
            primary_direction_key = max(
                direction_counts.keys(), key=lambda d: direction_counts[d]
            )
            primary_direction = list(map(int, primary_direction_key.split("-")))
        else:
            primary_direction = [n1, n2]
        is_bidirectional = len(direction_counts) > 1

        # Generate a color based on the packet IDs involved (for visual distinction)
        packet_ids = stats["packet_ids"]
        color_hash = hash(tuple(sorted(set(packet_ids)))) % 360
        edge_color = f"hsl({color_hash}, 70%, 50%)"

        edges.append(
            {
                "id": f"{n1_name}-{n2_name}",
                "from": primary_direction[0],
                "to": primary_direction[1],
                "value": count,  # For edge width
                "title": title,
                "label": f"{count}x" if count > 1 else "",
                "color": edge_color,
                "is_bidirectional": is_bidirectional,
                "packet_ids": packet_ids,
                "direction_counts": direction_counts,
                "avg_snr": avg_snr,
                "paths": list(
                    stats["paths"]
                ),  # Convert set to list for JSON serialization
            }
        )

    # Build paths list for visualization
    paths: list[dict[str, Any]] = []
    for i, (packet_id, path_info) in enumerate(packet_paths.items()):
        # Generate unique color for this path using better distribution
        # Spread colors across the full spectrum (0-360 degrees)
        path_color_hue = (i * 137) % 360  # Use golden angle for better distribution
        path_color = f"hsl({path_color_hue}, 80%, 60%)"

        avg_snr = None
        if path_info["snr_values"]:
            avg_snr = sum(path_info["snr_values"]) / len(path_info["snr_values"])

        paths.append(
            {
                "packet_id": packet_id,
                "nodes": path_info["nodes"],
                "color": path_color,
                "gateway_id": path_info["gateway_id"],
                "gateway_node_id": path_info["gateway_node_id"],
                "timestamp": path_info["timestamp"],
                "avg_snr": avg_snr,
                "hop_count": len(path_info["nodes"]) - 1 if path_info["nodes"] else 0,
            }
        )

    # Identify source and target nodes for highlighting
    source_nodes = set()
    target_nodes = set()

    # Get the actual packet destination from the first packet (they should all have same from/to)
    if packets:
        first_packet = packets[0]
        actual_source = first_packet.get("from_node_id")
        actual_target = first_packet.get("to_node_id")

        if actual_source:
            source_nodes.add(actual_source)
        if actual_target:
            target_nodes.add(actual_target)

    # Mark nodes with their roles
    for node in nodes:
        node["is_source"] = node["id"] in source_nodes
        node["is_target"] = node["id"] in target_nodes

    return {"nodes": nodes, "edges": edges, "paths": paths}
