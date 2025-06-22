"""
Packet-related routes for the Meshtastic Mesh Health Web UI
"""

import logging
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, render_template, request

from ..database.connection import get_db_connection

# Import from the new modular architecture
from ..database.repositories import LocationRepository
from ..models.traceroute import TraceroutePacket
from ..utils.node_utils import (
    get_bulk_node_names,
)
from ..utils.traceroute_graph import build_combined_traceroute_graph

logger = logging.getLogger(__name__)

packet_bp = Blueprint("packet", __name__)


def get_packet_details(packet_id: int) -> dict[str, Any] | None:
    """Get comprehensive details for a specific packet including all receptions."""
    logger.info(f"Getting packet details for packet {packet_id}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get the main packet information
        cursor.execute(
            """
            SELECT
                id, timestamp, from_node_id, to_node_id, portnum, portnum_name,
                gateway_id, channel_id, mesh_packet_id, rssi, snr, hop_limit, hop_start,
                payload_length, processed_successfully, raw_payload,
                via_mqtt, want_ack, priority, delayed, channel_index, rx_time,
                pki_encrypted, next_hop, relay_node, tx_after
            FROM packet_history
            WHERE id = ?
        """,
            (packet_id,),
        )

        packet_row = cursor.fetchone()
        if not packet_row:
            logger.warning(f"Packet {packet_id} not found")
            conn.close()
            return None

        packet = dict(packet_row)

        # Add derived fields
        packet["timestamp_str"] = datetime.fromtimestamp(packet["timestamp"]).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        packet["hop_count"] = (
            (packet["hop_start"] - packet["hop_limit"])
            if packet["hop_start"] is not None and packet["hop_limit"] is not None
            else None
        )
        packet["has_payload"] = packet["payload_length"] > 0
        packet["success"] = packet["processed_successfully"]

        # Ensure mesh_packet_id is an integer for template formatting
        if packet["mesh_packet_id"] is not None:
            try:
                packet["mesh_packet_id"] = int(packet["mesh_packet_id"])
            except (ValueError, TypeError):
                packet["mesh_packet_id"] = None

        # Get node names
        node_ids = [packet["from_node_id"], packet["to_node_id"]]
        node_ids = [nid for nid in node_ids if nid]

        # Also collect gateway IDs that look like node IDs (start with !)
        gateway_ids = set()
        if packet["gateway_id"] and packet["gateway_id"].startswith("!"):
            gateway_ids.add(packet["gateway_id"])

        node_names = get_bulk_node_names(node_ids)
        packet["from_node_name"] = node_names.get(packet["from_node_id"], "Unknown")
        packet["to_node_name"] = node_names.get(packet["to_node_id"], "Unknown")

        # Find all receptions of the same packet using mesh_packet_id (preferred) or fallback to time-based
        receptions = []

        if packet["mesh_packet_id"] is not None:
            # Use mesh_packet_id for accurate correlation
            cursor.execute(
                """
                SELECT
                    id, timestamp, gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, processed_successfully,
                    raw_payload, from_node_id, to_node_id, portnum, portnum_name
                FROM packet_history
                WHERE mesh_packet_id = ?
                AND id != ?
                ORDER BY timestamp ASC
            """,
                (packet["mesh_packet_id"], packet_id),
            )

            logger.info(
                f"Correlating packets using mesh_packet_id: {packet['mesh_packet_id']}"
            )
        else:
            # Fallback to time-based correlation for older packets without mesh_packet_id
            time_window = 2
            cursor.execute(
                """
                SELECT
                    id, timestamp, gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, processed_successfully,
                    raw_payload, from_node_id, to_node_id, portnum, portnum_name
                FROM packet_history
                WHERE from_node_id = ?
                AND timestamp BETWEEN ? AND ?
                AND portnum = ?
                AND id != ?
                ORDER BY timestamp ASC
            """,
                (
                    packet["from_node_id"],
                    packet["timestamp"] - time_window,
                    packet["timestamp"] + time_window,
                    packet["portnum"],
                    packet_id,
                ),
            )

            logger.info(
                f"Correlating packets using time-based fallback (±{time_window}s)"
            )

        for row in cursor.fetchall():
            reception = dict(row)
            reception["timestamp_str"] = datetime.fromtimestamp(
                reception["timestamp"]
            ).strftime("%Y-%m-%d %H:%M:%S")
            reception["hop_count"] = (
                (reception["hop_start"] - reception["hop_limit"])
                if reception["hop_start"] is not None
                and reception["hop_limit"] is not None
                else None
            )
            reception["time_diff"] = reception["timestamp"] - packet["timestamp"]
            receptions.append(reception)

            # Collect gateway IDs for name resolution
            if reception["gateway_id"] and reception["gateway_id"].startswith("!"):
                gateway_ids.add(reception["gateway_id"])

        # Get recent packets from the same node for context
        cursor.execute(
            """
            SELECT
                id, timestamp, portnum_name, to_node_id, gateway_id, rssi, snr,
                hop_limit, hop_start, payload_length, processed_successfully, mesh_packet_id
            FROM packet_history
            WHERE from_node_id = ?
            AND timestamp BETWEEN ? AND ?
            AND id != ?
            ORDER BY timestamp DESC
            LIMIT 20
        """,
            (
                packet["from_node_id"],
                packet["timestamp"] - (3600 * 2),  # 2 hours before
                packet["timestamp"] + (3600 * 2),  # 2 hours after
                packet_id,
            ),
        )

        context_packets = []
        context_node_ids = set()
        for row in cursor.fetchall():
            ctx_packet = dict(row)
            ctx_packet["timestamp_str"] = datetime.fromtimestamp(
                ctx_packet["timestamp"]
            ).strftime("%Y-%m-%d %H:%M:%S")
            ctx_packet["hop_count"] = (
                (ctx_packet["hop_start"] - ctx_packet["hop_limit"])
                if ctx_packet["hop_start"] is not None
                and ctx_packet["hop_limit"] is not None
                else None
            )
            ctx_packet["time_diff"] = ctx_packet["timestamp"] - packet["timestamp"]
            ctx_packet["time_diff_str"] = f"{ctx_packet['time_diff']:+.0f}s"
            context_packets.append(ctx_packet)
            if ctx_packet["to_node_id"]:
                context_node_ids.add(ctx_packet["to_node_id"])
            # Collect gateway IDs for name resolution
            if ctx_packet["gateway_id"] and ctx_packet["gateway_id"].startswith("!"):
                gateway_ids.add(ctx_packet["gateway_id"])

        # Get names for context packet nodes
        context_node_names = get_bulk_node_names(list(context_node_ids))
        for ctx_packet in context_packets:
            ctx_packet["to_node_name"] = context_node_names.get(
                ctx_packet["to_node_id"], "Unknown"
            )

        # Get names for all gateway IDs that are node IDs
        gateway_names = {}
        gateway_node_ids = []
        if gateway_ids:
            # Convert gateway ID strings to integers for name lookup
            for gw_id in gateway_ids:
                if isinstance(gw_id, str) and gw_id.startswith("!"):
                    try:
                        # Convert hex string to integer
                        node_id = int(gw_id[1:], 16)
                        gateway_node_ids.append(node_id)
                    except ValueError:
                        logger.warning(
                            f"Could not convert gateway ID {gw_id} to integer"
                        )
                elif isinstance(gw_id, int):
                    gateway_node_ids.append(gw_id)

            if gateway_node_ids:
                node_names = get_bulk_node_names(gateway_node_ids)
                # Map back to original gateway ID strings
                for gw_id in gateway_ids:
                    if isinstance(gw_id, str) and gw_id.startswith("!"):
                        try:
                            node_id = int(gw_id[1:], 16)
                            gateway_names[gw_id] = node_names.get(node_id)
                        except ValueError:
                            pass
                    elif isinstance(gw_id, int):
                        gateway_names[str(gw_id)] = node_names.get(gw_id)

        # Get location data for all gateway nodes
        gateway_locations = {}
        if gateway_node_ids:
            try:
                # Fetch only the locations we need for the gateway nodes
                all_locations = LocationRepository.get_node_locations(
                    {"node_ids": gateway_node_ids}
                )

                # Filter for our gateway nodes and convert to the expected format
                for location in all_locations:
                    if location["node_id"] in gateway_node_ids:
                        # Map back to gateway ID format
                        gateway_id = f"!{location['node_id']:08x}"
                        gateway_locations[gateway_id] = {
                            "node_id": location["node_id"],
                            "latitude": location["latitude"],
                            "longitude": location["longitude"],
                            "altitude": location["altitude"],
                            "timestamp": location["timestamp"],
                            "timestamp_str": datetime.fromtimestamp(
                                location["timestamp"]
                            ).strftime("%Y-%m-%d %H:%M:%S"),
                            "display_name": location["display_name"],
                            "long_name": location["long_name"],
                            "short_name": location["short_name"],
                            "hw_model": location["hw_model"],
                        }

                logger.info(
                    f"Found location data for {len(gateway_locations)} gateways"
                )
            except Exception as e:
                logger.warning(f"Error getting gateway locations: {e}")

        # ---------------------------------------------------------------------
        # Build combined traceroute graph across all receptions (including main)
        # ---------------------------------------------------------------------
        try:
            graph_packets = [
                packet
            ] + receptions  # Receptions already include raw_payload
            packet_graph_data = build_combined_traceroute_graph(graph_packets)

            # Convert any bytes objects to base64 for JSON serialization
            from ..utils.serialization_utils import convert_bytes_to_base64

            packet_graph_data = convert_bytes_to_base64(packet_graph_data)
        except Exception as e:
            logger.warning(
                f"Failed to build combined traceroute graph for packet {packet_id}: {e}"
            )
            packet_graph_data = {"nodes": [], "edges": [], "paths": []}

        # Add gateway names and locations to packet and receptions
        packet["gateway_name"] = gateway_names.get(packet["gateway_id"], None)
        packet["gateway_location"] = gateway_locations.get(packet["gateway_id"], None)

        for reception in receptions:
            reception["gateway_name"] = gateway_names.get(reception["gateway_id"], None)
            reception["gateway_location"] = gateway_locations.get(
                reception["gateway_id"], None
            )

        for ctx_packet in context_packets:
            ctx_packet["gateway_name"] = gateway_names.get(
                ctx_packet["gateway_id"], None
            )

        # Try to decode payload if available and protobuf is available
        payload_info = None
        if packet["raw_payload"] and packet["payload_length"] > 0:
            payload_info = decode_packet_payload(packet)

        # Always generate raw analysis to show packet structure, even without payload
        raw_analysis = get_raw_packet_analysis(packet)

        conn.close()

        # Convert any remaining bytes objects to base64 for JSON serialization
        from ..utils.serialization_utils import convert_bytes_to_base64

        result = {
            "packet": convert_bytes_to_base64(packet),
            "other_receptions": convert_bytes_to_base64(receptions),
            "context_packets": convert_bytes_to_base64(context_packets),
            "payload_info": convert_bytes_to_base64(payload_info),
            "raw_analysis": convert_bytes_to_base64(raw_analysis),
            "reception_count": len(receptions) + 1,  # +1 for the main packet
            "gateway_count": len(
                set([r["gateway_id"] for r in receptions] + [packet["gateway_id"]])
            ),
            "correlation_method": "mesh_packet_id"
            if packet["mesh_packet_id"] is not None
            else "time_based",
            "gateway_locations": gateway_locations,  # Add location data for template
            "packet_graph_data": packet_graph_data,
        }

        correlation_info = (
            f"mesh_packet_id={packet['mesh_packet_id']}"
            if packet["mesh_packet_id"] is not None
            else "time-based fallback"
        )
        logger.info(
            f"Packet details retrieved: {len(receptions)} other receptions, {len(context_packets)} context packets, {len(gateway_locations)} gateway locations, correlation: {correlation_info}"
        )
        return result

    except Exception as e:
        logger.error(f"Error getting packet details for packet {packet_id}: {e}")
        raise


def decode_packet_payload(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Attempt to decode packet payload based on portnum using the new dynamic discovery system."""
    if not packet["raw_payload"]:
        return None

    try:
        payload_info = {
            "portnum": packet["portnum_name"],
            "size": packet["payload_length"],
            "decoded": False,
            "data": None,
            "text": None,
            "error": None,
        }

        # Use the new generic protobuf decoding system
        decoded_payload = decode_protobuf_payload(packet)

        if decoded_payload is None:
            payload_info["error"] = "No protobuf decoder available"
            payload_info["decoded"] = False
            return payload_info

        # Handle different decode result types
        if decoded_payload.get("type") == "text_message":
            payload_info["text"] = decoded_payload.get("text")
            payload_info["decoded"] = True
            if "decode_error" in decoded_payload:
                payload_info["error"] = decoded_payload["decode_error"]
                payload_info["text"] = decoded_payload.get(
                    "raw_bytes"
                )  # Use hex for invalid UTF-8
                # Keep decoded=True for text messages even with decode errors (backward compatibility)

        elif decoded_payload.get("type") == "protobuf":
            # Convert the generic protobuf decode to the expected format for the template
            payload_info["decoded"] = True

            # Create application-specific data structure based on portnum
            if packet["portnum_name"] == "POSITION_APP":
                # Convert raw protobuf fields to user-friendly format
                raw_data = decoded_payload
                payload_info["data"] = {
                    "latitude": raw_data.get("latitude_i", 0) / 1e7
                    if raw_data.get("latitude_i")
                    else None,
                    "longitude": raw_data.get("longitude_i", 0) / 1e7
                    if raw_data.get("longitude_i")
                    else None,
                    "altitude": raw_data.get("altitude"),
                    "sats_in_view": raw_data.get("sats_in_view"),
                    "precision_bits": raw_data.get("precision_bits"),
                }

            elif packet["portnum_name"] == "NODEINFO_APP":
                # Convert User protobuf to expected format
                raw_data = decoded_payload
                payload_info["data"] = {
                    "id": raw_data.get("id"),
                    "long_name": raw_data.get("long_name"),
                    "short_name": raw_data.get("short_name"),
                    "macaddr": raw_data.get(
                        "macaddr"
                    ),  # Already converted to hex by protobuf_message_to_dict
                    "hw_model": raw_data.get("hw_model"),
                }

            elif packet["portnum_name"] == "TELEMETRY_APP":
                # Convert Telemetry protobuf to expected format
                raw_data = decoded_payload
                data = {"time": raw_data.get("time")}

                if "device_metrics" in raw_data:
                    data["device_metrics"] = raw_data["device_metrics"]

                if "environment_metrics" in raw_data:
                    data["environment_metrics"] = raw_data["environment_metrics"]

                if "air_quality_metrics" in raw_data:
                    data["air_quality_metrics"] = raw_data["air_quality_metrics"]

                if "power_metrics" in raw_data:
                    data["power_metrics"] = raw_data["power_metrics"]

                payload_info["data"] = data

            elif packet["portnum_name"] == "NEIGHBORINFO_APP":
                # Convert NeighborInfo protobuf to expected format with node name resolution
                raw_data = decoded_payload

                # Process neighbor list
                neighbors = []
                neighbor_node_ids = []

                if "neighbors" in raw_data:
                    for neighbor in raw_data["neighbors"]:
                        neighbor_data = {
                            "node_id": neighbor.get("node_id"),
                            "snr": neighbor.get(
                                "snr", 0.0
                            ),  # Default to 0.0 instead of None for backward compatibility
                            "last_rx_time": neighbor.get("last_rx_time")
                            if neighbor.get("last_rx_time", 0) != 0
                            else None,
                            "node_broadcast_interval_secs": neighbor.get(
                                "node_broadcast_interval_secs"
                            )
                            if neighbor.get("node_broadcast_interval_secs", 0) != 0
                            else None,
                        }

                        # Format timestamp if available
                        if neighbor_data["last_rx_time"]:
                            try:
                                from datetime import datetime

                                neighbor_data["last_rx_time_str"] = (
                                    datetime.fromtimestamp(
                                        neighbor_data["last_rx_time"], tz=UTC
                                    ).strftime("%Y-%m-%d %H:%M:%S")
                                )
                            except (ValueError, OSError):
                                neighbor_data["last_rx_time_str"] = "Invalid timestamp"
                        else:
                            neighbor_data["last_rx_time_str"] = "Unknown"

                        neighbors.append(neighbor_data)
                        if neighbor_data["node_id"]:
                            neighbor_node_ids.append(neighbor_data["node_id"])

                # Get node names for all neighbors
                neighbor_node_names = {}
                if neighbor_node_ids:
                    neighbor_node_names = get_bulk_node_names(neighbor_node_ids)

                # Add node names to neighbor data
                for neighbor_data in neighbors:
                    neighbor_data["node_name"] = neighbor_node_names.get(
                        neighbor_data["node_id"],
                        f"Unknown Node ({neighbor_data['node_id']})",
                    )

                # Prepare final data structure
                data = {
                    "node_id": raw_data.get("node_id")
                    if raw_data.get("node_id", 0) != 0
                    else None,
                    "last_sent_by_id": raw_data.get("last_sent_by_id")
                    if raw_data.get("last_sent_by_id", 0) != 0
                    else None,
                    "node_broadcast_interval_secs": raw_data.get(
                        "node_broadcast_interval_secs"
                    )
                    if raw_data.get("node_broadcast_interval_secs", 0) != 0
                    else None,
                    "neighbors": neighbors,
                    "neighbor_count": len(neighbors),
                }

                # Get node names for the reporting node and last_sent_by node
                reporting_node_ids = []
                if data["node_id"]:
                    reporting_node_ids.append(data["node_id"])
                if data["last_sent_by_id"]:
                    reporting_node_ids.append(data["last_sent_by_id"])

                if reporting_node_ids:
                    reporting_node_names = get_bulk_node_names(reporting_node_ids)
                    node_id = data.get("node_id")
                    last_sent_by_id = data.get("last_sent_by_id")
                    if isinstance(node_id, int):
                        data["node_name"] = reporting_node_names.get(
                            node_id, f"Unknown Node ({node_id})"
                        )
                    else:
                        data["node_name"] = "Unknown Node"
                    if isinstance(last_sent_by_id, int):
                        data["last_sent_by_name"] = reporting_node_names.get(
                            last_sent_by_id, f"Unknown Node ({last_sent_by_id})"
                        )
                    else:
                        data["last_sent_by_name"] = "Unknown Node"
                else:
                    data["node_name"] = "Unknown Node"
                    data["last_sent_by_name"] = "Unknown Node"

                payload_info["data"] = data

                logger.info(
                    f"NeighborInfo decode complete for packet {packet['id']}: {len(neighbors)} neighbors reported by node {data['node_id']}"
                )

            elif packet["portnum_name"] == "TRACEROUTE_APP":
                # Use the enhanced TraceroutePacket class for comprehensive analysis
                try:
                    tr_packet = TraceroutePacket(packet, resolve_names=True)

                    # Calculate distances for all hops
                    tr_packet.calculate_hop_distances(calculate_for_all_paths=True)

                    # Get enhanced hop data with distances
                    forward_hops_with_distances = (
                        tr_packet.get_display_hops_with_distances()
                    )
                    return_hops_with_distances = (
                        tr_packet.get_return_hops_with_distances()
                    )

                    # Create enhanced payload data including distance information
                    payload_info["data"] = {
                        # Legacy fields for backward compatibility
                        "route_nodes": tr_packet.route_data["route_nodes"],
                        "snr_towards": tr_packet.route_data["snr_towards"],
                        "route_back": tr_packet.route_data["route_back"],
                        "snr_back": tr_packet.route_data["snr_back"],
                        "route_node_names": {},  # Will be populated below
                        # Enhanced TraceroutePacket data
                        "traceroute_packet": tr_packet,
                        "has_return_path": tr_packet.has_return_path(),
                        "is_complete": tr_packet.is_complete(),
                        "forward_path_display": tr_packet.format_path_display(
                            "display"
                        ),
                        "return_path_display": tr_packet.format_path_display("return")
                        if tr_packet.has_return_path()
                        else None,
                        "actual_rf_path_display": tr_packet.format_path_display(
                            "actual_rf"
                        ),
                        # Enhanced hop data with distances
                        "forward_hops": forward_hops_with_distances,
                        "return_hops": return_hops_with_distances,
                        # Distance summary
                        "total_forward_distance": sum(
                            hop.distance_meters
                            for hop in forward_hops_with_distances
                            if hop.distance_meters is not None
                        )
                        if forward_hops_with_distances
                        else None,
                        "total_return_distance": sum(
                            hop.distance_meters
                            for hop in return_hops_with_distances
                            if hop.distance_meters is not None
                        )
                        if return_hops_with_distances
                        else None,
                    }

                    # Add route node names for backward compatibility
                    all_route_nodes = set()
                    if tr_packet.route_data["route_nodes"]:
                        all_route_nodes.update(tr_packet.route_data["route_nodes"])
                    if tr_packet.route_data["route_back"]:
                        all_route_nodes.update(tr_packet.route_data["route_back"])
                    if packet["from_node_id"]:
                        all_route_nodes.add(packet["from_node_id"])
                    if packet["to_node_id"]:
                        all_route_nodes.add(packet["to_node_id"])

                    if all_route_nodes:
                        route_node_names = get_bulk_node_names(list(all_route_nodes))
                        payload_info["data"]["route_node_names"] = route_node_names

                    logger.info(
                        f"Enhanced traceroute decode complete for packet {packet['id']}: "
                        f"{len(forward_hops_with_distances)} forward hops, "
                        f"{len(return_hops_with_distances)} return hops"
                    )

                except Exception as e:
                    logger.error(
                        f"Enhanced traceroute decode error for packet {packet['id']}: {e}"
                    )
                    # Fallback to basic traceroute parsing
                    try:
                        from ..utils.traceroute_utils import parse_traceroute_payload

                        route_data = parse_traceroute_payload(packet["raw_payload"])

                        # Collect all unique node IDs from the route
                        all_route_nodes = set()
                        if route_data["route_nodes"]:
                            all_route_nodes.update(route_data["route_nodes"])
                        if route_data["route_back"]:
                            all_route_nodes.update(route_data["route_back"])

                        # Also include the packet's from and to nodes since they're part of the complete route
                        if packet["from_node_id"]:
                            all_route_nodes.add(packet["from_node_id"])
                        if packet["to_node_id"]:
                            all_route_nodes.add(packet["to_node_id"])

                        # Get node names for all route nodes
                        route_node_names = {}
                        if all_route_nodes:
                            route_node_names = get_bulk_node_names(
                                list(all_route_nodes)
                            )

                        payload_info["data"] = {
                            "route_nodes": route_data[
                                "route_nodes"
                            ],  # Keep as numeric IDs
                            "snr_towards": route_data["snr_towards"],
                            "route_back": route_data[
                                "route_back"
                            ],  # Keep as numeric IDs
                            "snr_back": route_data["snr_back"],
                            "route_node_names": route_node_names,  # Add node names lookup
                        }
                        payload_info["error"] = (
                            f"Enhanced parsing failed, using basic parsing: {e}"
                        )
                        payload_info["decoded"] = False
                    except Exception as fallback_e:
                        payload_info["error"] = (
                            f"Both enhanced and basic traceroute decode failed: {e}, {fallback_e}"
                        )
                        payload_info["decoded"] = False

            else:
                # For other protobuf types, use the raw decoded data
                payload_info["data"] = decoded_payload

        elif decoded_payload.get("type") == "unknown_or_custom":
            payload_info["text"] = decoded_payload.get("raw_bytes")
            payload_info["error"] = decoded_payload.get("note", "Unknown packet type")
            payload_info["decoded"] = False

        elif decoded_payload.get("type") == "decode_error":
            payload_info["error"] = decoded_payload.get(
                "decode_error", "Unknown decode error"
            )
            payload_info["text"] = decoded_payload.get("raw_bytes")
            payload_info["decoded"] = False

        else:
            # Fallback for any other case
            payload_info["error"] = "Unknown decode result type"
            payload_info["text"] = (
                packet["raw_payload"].hex() if packet["raw_payload"] else None
            )
            payload_info["decoded"] = False

        # Only mark as decoded if we have data and no errors
        if payload_info["data"] and not payload_info["error"]:
            payload_info["decoded"] = True
        elif payload_info["text"] and not payload_info["error"]:
            payload_info["decoded"] = True

        return payload_info

    except Exception as e:
        logger.warning(f"Error decoding payload for packet {packet['id']}: {e}")
        return {
            "portnum": packet["portnum_name"],
            "size": packet["payload_length"],
            "decoded": False,
            "error": str(e),
            "text": packet["raw_payload"].hex() if packet["raw_payload"] else None,
        }


def protobuf_message_to_dict(message: Any) -> dict[str, Any] | None:
    """Convert a protobuf message to a dictionary using reflection."""
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.message import Message

    if not isinstance(message, Message):
        return None

    try:
        # Use protobuf's built-in JSON conversion which handles all field types
        result = MessageToDict(
            message,
            preserving_proto_field_name=True,  # Use original field names
            use_integers_for_enums=False,  # Use enum names instead of numbers
        )
        return result
    except Exception as e:
        # Fallback to manual field extraction if JSON conversion fails
        result = {}
        for field, value in message.ListFields():
            try:
                if field.label == field.LABEL_REPEATED:
                    # Handle repeated fields (lists)
                    if field.type == field.TYPE_MESSAGE:
                        result[field.name] = [
                            protobuf_message_to_dict(item) for item in value
                        ]
                    else:
                        result[field.name] = list(value)
                elif field.type == field.TYPE_MESSAGE:
                    # Handle nested messages
                    result[field.name] = protobuf_message_to_dict(value)
                elif field.type == field.TYPE_BYTES:
                    # Convert bytes to hex string
                    result[field.name] = value.hex()
                else:
                    # Handle primitive types
                    result[field.name] = value
            except Exception as field_error:
                result[field.name] = f"<decode_error: {str(field_error)}>"

        if result:
            result["_conversion_method"] = "manual_fallback"
            result["_original_error"] = str(e)

        return result


def get_all_protobuf_message_classes() -> dict[str, Any]:
    """Dynamically discover all available protobuf message classes from the Meshtastic package."""
    try:
        import inspect

        import meshtastic

        # Get all protobuf modules
        protobuf_modules = [attr for attr in dir(meshtastic) if attr.endswith("_pb2")]

        # Map to store all discovered message classes
        all_message_classes: dict[str, Any] = {}

        for module_name in protobuf_modules:
            try:
                module = getattr(meshtastic, module_name)

                # Find all protobuf message classes in this module
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and hasattr(obj, "DESCRIPTOR"):
                        # Store with module prefix to avoid conflicts
                        full_name = f"{module_name}.{name}"
                        all_message_classes[name] = obj
                        all_message_classes[full_name] = obj

            except Exception as e:
                print(f"Warning: Could not import {module_name}: {e}")
                continue

        return all_message_classes

    except Exception as e:
        print(f"Error discovering protobuf classes: {e}")
        return {}


def get_protobuf_message_class_for_portnum(portnum_name: str) -> Any | None:
    """Get the appropriate protobuf message class for a given portnum using dynamic discovery."""
    try:
        # Get all available message classes
        all_classes = get_all_protobuf_message_classes()

        # Enhanced mapping that uses the dynamically discovered classes
        # This maps portnum names to the most likely message class names
        portnum_to_class_name: dict[str, str | None] = {
            "TEXT_MESSAGE_APP": None,  # Special case - plain text, not protobuf
            "TEXT_MESSAGE_COMPRESSED_APP": "Compressed",  # From mesh_pb2
            "REMOTE_HARDWARE_APP": "HardwareMessage",  # From remote_hardware_pb2
            "POSITION_APP": "Position",  # From mesh_pb2
            "NODEINFO_APP": "User",  # From mesh_pb2
            "ROUTING_APP": "Routing",  # From mesh_pb2
            "ADMIN_APP": "AdminMessage",  # From admin_pb2
            "WAYPOINT_APP": "Waypoint",  # From mesh_pb2
            "AUDIO_APP": None,  # Custom format - no standard protobuf
            "DETECTION_SENSOR_APP": None,  # Custom format
            "REPLY_APP": None,  # Custom format
            "IP_TUNNEL_APP": None,  # Custom format
            "SERIAL_APP": None,  # Custom format
            "STORE_FORWARD_APP": "StoreAndForward",  # From storeforward_pb2
            "RANGE_TEST_APP": None,  # Custom format
            "TELEMETRY_APP": "Telemetry",  # From telemetry_pb2
            "ZPS_APP": None,  # Custom format
            "SIMULATOR_APP": None,  # Custom format
            "TRACEROUTE_APP": "RouteDiscovery",  # From mesh_pb2
            "NEIGHBORINFO_APP": "NeighborInfo",  # From mesh_pb2
            "ATAK_PLUGIN": None,  # Custom format
            "MAP_REPORT_APP": "MapReport",  # From mesh_pb2 (discovered!)
            "POWERSTRESS_APP": "PowerStressMessage",  # From mesh_pb2 (discovered!)
            "ATAK_FORWARDER": None,  # Custom format
            "PAXCOUNTER_APP": "Paxcount",  # From paxcount_pb2
            "PRIVATE_APP": None,  # Custom format
            "RETICULUM_TUNNEL_APP": None,  # Custom format
            "ALERT_APP": None,  # Custom format or not available
            "UNKNOWN_APP": None,
            "MAX": None,
        }

        # Get the class name for this portnum
        class_name = portnum_to_class_name.get(portnum_name)

        if class_name is None:
            return None

        # Try to find the class in our discovered classes
        message_class = all_classes.get(class_name)

        if message_class is None:
            # Try with module prefixes if direct lookup failed
            for full_name, cls in all_classes.items():
                if full_name.endswith(f".{class_name}"):
                    message_class = cls
                    break

        return message_class

    except ImportError as e:
        # Log the import error for debugging
        print(f"Import error in get_protobuf_message_class_for_portnum: {e}")
        return None


def decode_protobuf_payload(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Decode a protobuf payload from a packet."""
    if not packet.get("raw_payload"):
        return None

    # Initialize variables to avoid "possibly unbound" errors
    raw_payload = packet["raw_payload"]
    portnum_name = packet.get("portnum_name", "unknown")
    message_class = None

    try:
        # Ensure portnum_name is a string
        if not isinstance(portnum_name, str):
            return {
                "raw_bytes": raw_payload.hex() if raw_payload else None,
                "type": "unknown_or_custom",
                "portnum": str(portnum_name) if portnum_name else "unknown",
                "note": "Invalid or missing portnum_name",
            }

        # Special case for text messages - they're UTF-8 strings, not protobuf
        if portnum_name == "TEXT_MESSAGE_APP":
            try:
                return {
                    "text": raw_payload.decode("utf-8"),
                    "type": "text_message",
                    "portnum": portnum_name,
                }
            except UnicodeDecodeError:
                return {
                    "raw_bytes": raw_payload.hex(),
                    "type": "text_message",
                    "portnum": portnum_name,
                    "decode_error": "Could not decode as UTF-8",
                }

        # Get the appropriate protobuf message class
        message_class = get_protobuf_message_class_for_portnum(portnum_name)

        if message_class is None:
            # Unknown or non-protobuf message type
            return {
                "raw_bytes": raw_payload.hex(),
                "type": "unknown_or_custom",
                "portnum": portnum_name,
                "note": f"No decoder available for {portnum_name}",
            }

        # Create and parse the protobuf message
        message = message_class()
        message.ParseFromString(raw_payload)

        # Convert to dictionary using generic reflection
        result = protobuf_message_to_dict(message)

        if result is None:
            return {
                "raw_bytes": raw_payload.hex(),
                "type": "protobuf_decode_failed",
                "portnum": portnum_name,
                "message_class": message_class.__name__,
            }

        # Add metadata
        result["type"] = "protobuf"
        result["portnum"] = portnum_name
        result["message_class"] = message_class.__name__

        return result

    except Exception as e:
        return {
            "raw_bytes": raw_payload.hex() if raw_payload else None,
            "type": "decode_error",
            "portnum": portnum_name if "portnum_name" in locals() else "unknown",
            "decode_error": f"{message_class.__name__} decode error: {str(e)}"
            if "message_class" in locals() and message_class
            else str(e),
        }


def get_raw_packet_analysis(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Extract all raw packet fields and analyze MQTT privacy/exposure settings."""
    try:
        from meshtastic import mesh_pb2

        analysis: dict[str, Any] = {
            "service_envelope": {},
            "mesh_packet": {},
            "mqtt_privacy": {},
            "topic_analysis": {},
            "raw_hex": packet["raw_payload"].hex() if packet["raw_payload"] else None,
            "size_bytes": len(packet["raw_payload"]) if packet["raw_payload"] else 0,
            "error": "No payload data - showing packet structure only"
            if not packet["raw_payload"]
            else None,
        }

        # For packets from MQTT, we need to reconstruct or get the ServiceEnvelope
        # Since we only store the decoded MeshPacket payload, we'll work with what we have
        # and create the ServiceEnvelope context from the stored fields

        # ServiceEnvelope-level analysis from stored database fields
        analysis["service_envelope"] = {
            "gateway_id": packet.get("gateway_id"),
            "channel_id": packet.get("channel_id"),
            "topic": packet.get("topic"),
            "description": "MQTT ServiceEnvelope contains the MeshPacket plus routing metadata",
        }

        # Analyze the topic structure for MQTT privacy implications
        topic = packet.get("topic")
        if topic:
            topic_parts = topic.split("/")
            analysis["topic_analysis"] = {
                "full_topic": topic,
                "parts": topic_parts,
                "privacy_implications": [],
            }

            # Standard Meshtastic MQTT topic structure: msh/region/modem_preset/message_type/channel_id
            if len(topic_parts) >= 5:
                analysis["topic_analysis"]["structure"] = {
                    "prefix": topic_parts[0] if len(topic_parts) > 0 else None,
                    "region": topic_parts[1] if len(topic_parts) > 1 else None,
                    "modem_preset": topic_parts[2] if len(topic_parts) > 2 else None,
                    "message_type": topic_parts[3]
                    if len(topic_parts) > 3
                    else None,  # 'e' for encrypted, 'c' for command
                    "channel_id": topic_parts[4] if len(topic_parts) > 4 else None,
                }

                privacy_implications: list[str] = []
                # Analyze message type
                if topic_parts[3] == "e":
                    privacy_implications.append("Encrypted message - content protected")
                elif topic_parts[3] == "c":
                    privacy_implications.append(
                        "Command message - administrative traffic"
                    )
                elif topic_parts[3] == "p":
                    privacy_implications.append(
                        "Position message - location data exposed"
                    )

                # Analyze channel
                if len(topic_parts) >= 5 and topic_parts[4]:
                    channel_name = topic_parts[4]
                    if channel_name == "LongFast":
                        privacy_implications.append(
                            "Default channel - widely monitored"
                        )
                    else:
                        privacy_implications.append(f"Custom channel: {channel_name}")

                analysis["topic_analysis"]["privacy_implications"] = (
                    privacy_implications
                )
        else:
            # No topic available (likely from test database)
            analysis["topic_analysis"] = {
                "full_topic": None,
                "parts": [],
                "privacy_implications": ["Topic information not available"],
            }

        # MeshPacket field analysis
        # We'll reconstruct what we can from the stored packet data
        mesh_packet_data: dict[str, Any] = {
            "from_node_id": packet.get("from_node_id"),
            "to_node_id": packet.get("to_node_id"),
            "portnum": packet.get("portnum"),
            "portnum_name": packet.get("portnum_name"),
            "hop_limit": packet.get("hop_limit"),
            "hop_start": packet.get("hop_start"),
            "rssi": packet.get("rssi"),
            "snr": packet.get("snr"),
            "payload_length": packet.get("payload_length"),
            "timestamp": packet.get("timestamp"),
            "via_mqtt": packet.get("via_mqtt"),
            "want_ack": packet.get("want_ack"),
            "priority": packet.get("priority"),
            "delayed": packet.get("delayed"),
            "channel_index": packet.get("channel_index"),
            "rx_time": packet.get("rx_time"),
            "pki_encrypted": packet.get("pki_encrypted"),
            "next_hop": packet.get("next_hop"),
            "relay_node": packet.get("relay_node"),
            "tx_after": packet.get("tx_after"),
            "description": "Core mesh packet with routing and payload information",
        }

        # Calculate derived fields
        hop_start = packet.get("hop_start")
        hop_limit = packet.get("hop_limit")
        if hop_start is not None and hop_limit is not None:
            mesh_packet_data["hops_taken"] = hop_start - hop_limit
            mesh_packet_data["remaining_hops"] = hop_limit

        analysis["mesh_packet"] = mesh_packet_data

        # MQTT Privacy and Exposure Analysis
        mqtt_privacy: dict[str, Any] = {
            "exposure_level": "Unknown",
            "privacy_features": [],
            "exposure_risks": [],
            "mqtt_specific_fields": {},
        }

        # Use the via_mqtt field directly
        if packet.get("via_mqtt"):
            mqtt_privacy["mqtt_specific_fields"]["via_mqtt"] = True
            mqtt_privacy["exposure_risks"].append(
                "Packet originated from or passed through MQTT"
            )
        else:
            mqtt_privacy["privacy_features"].append(
                "Direct LoRa transmission (not via MQTT)"
            )

        # Use the pki_encrypted field directly
        if packet.get("pki_encrypted"):
            mqtt_privacy["mqtt_specific_fields"]["pki_encrypted"] = True
            mqtt_privacy["privacy_features"].append("PKI encrypted packet")

        # Use the want_ack field
        if packet.get("want_ack"):
            mqtt_privacy["mqtt_specific_fields"]["want_ack"] = True
            mqtt_privacy["privacy_features"].append("Acknowledgment requested")

        # Determine exposure level based on available information
        to_node_id = packet.get("to_node_id")
        if to_node_id is not None and to_node_id not in [0, 0xFFFFFFFF]:
            mqtt_privacy["exposure_level"] = "Direct Message"
            mqtt_privacy["privacy_features"].append("Targeted to specific node")
        else:
            mqtt_privacy["exposure_level"] = "Broadcast"
            mqtt_privacy["exposure_risks"].append("Visible to all nodes on channel")

        # Channel-based privacy analysis
        channel_id = packet.get("channel_id")
        if channel_id:
            if channel_id == "0" or channel_id == "LongFast":
                mqtt_privacy["exposure_risks"].append("Default channel - no encryption")
            else:
                mqtt_privacy["privacy_features"].append(f"Custom channel: {channel_id}")

        # Gateway exposure analysis
        gateway_id = packet.get("gateway_id")
        if gateway_id:
            mqtt_privacy["mqtt_specific_fields"]["gateway_id"] = gateway_id
            if isinstance(gateway_id, str) and gateway_id.startswith("!"):
                mqtt_privacy["privacy_features"].append("Gateway node ID tracked")
            mqtt_privacy["exposure_risks"].append("Packet visible to MQTT subscribers")

        # Position privacy analysis for POSITION_APP
        if packet.get("portnum_name") == "POSITION_APP":
            try:
                position = mesh_pb2.Position()
                position.ParseFromString(packet["raw_payload"])
                if hasattr(position, "precision_bits") and position.precision_bits:
                    # Calculate precision based on Meshtastic documentation
                    # https://meshtastic.org/docs/configuration/radio/channels/#position-precision
                    precision_map = {
                        10: 23300,
                        11: 11700,
                        12: 5800,
                        13: 2900,
                        14: 1500,
                        15: 729,
                        16: 364,
                        17: 182,
                        18: 91,
                        19: 45,
                    }

                    if position.precision_bits >= 32:
                        precision_meters = 1.0
                    elif position.precision_bits in precision_map:
                        precision_meters = float(precision_map[position.precision_bits])
                    elif position.precision_bits < 10:
                        precision_meters = 50000.0
                    elif position.precision_bits > 19:
                        precision_meters = 45.0 / (2 ** (position.precision_bits - 19))
                    else:
                        # Simple interpolation for unknown values
                        precision_meters = 1000.0
                    mqtt_privacy["mqtt_specific_fields"]["position_precision_bits"] = (
                        position.precision_bits
                    )
                    mqtt_privacy["mqtt_specific_fields"][
                        "position_precision_meters"
                    ] = precision_meters
                    if position.precision_bits < 16:
                        mqtt_privacy["privacy_features"].append(
                            f"Reduced position precision: ~{precision_meters}m accuracy"
                        )
                    else:
                        mqtt_privacy["exposure_risks"].append(
                            "Full GPS precision shared"
                        )
            except Exception:
                pass  # Ignore decode errors for this analysis

        # Hop analysis for privacy
        hops_taken = mesh_packet_data.get("hops_taken", 0)
        if hops_taken == 0:
            mqtt_privacy["mqtt_specific_fields"]["zero_hop_policy"] = True
            mqtt_privacy["privacy_features"].append(
                "Zero-hop: direct from source to MQTT gateway"
            )
        else:
            mqtt_privacy["exposure_risks"].append(
                f"Multi-hop path visible ({hops_taken} hops)"
            )

        # Signal strength exposure
        if packet.get("rssi") or packet.get("snr"):
            mqtt_privacy["exposure_risks"].append(
                "RF signal metrics exposed (location inference possible)"
            )
            mqtt_privacy["mqtt_specific_fields"]["signal_metrics"] = {
                "rssi": packet.get("rssi"),
                "snr": packet.get("snr"),
            }

        analysis["mqtt_privacy"] = mqtt_privacy

        # Decode the actual protobuf structures for complete protobuf view
        protobuf_decode: dict[str, Any] = {}

        try:
            # Try to decode the actual ServiceEnvelope and MeshPacket from raw payload
            if packet["raw_payload"]:
                # For now, we'll use the reconstructed data since we don't store the original ServiceEnvelope
                # In a real implementation, you'd decode the actual protobuf bytes here

                # ServiceEnvelope fields (reconstructed from stored data)
                protobuf_decode["service_envelope"] = {
                    "gateway_id": packet.get("gateway_id"),
                    "channel_id": packet.get("channel_id"),
                    "packet": "MeshPacket (see mesh_packet below)",
                }

                # MeshPacket fields (reconstructed from stored data)
                mesh_packet_fields = {
                    "from": packet.get("from_node_id"),
                    "to": packet.get("to_node_id"),
                    "id": packet.get("mesh_packet_id"),
                    "rx_time": packet.get("rx_time"),
                    "rx_snr": packet.get("snr"),
                    "rx_rssi": packet.get("rssi"),
                    "hop_limit": packet.get("hop_limit"),
                    "hop_start": packet.get("hop_start"),
                    "via_mqtt": packet.get("via_mqtt"),
                    "want_ack": packet.get("want_ack"),
                    "priority": packet.get("priority"),
                    "delayed": packet.get("delayed"),
                    "channel_index": packet.get("channel_index"),
                    "pki_encrypted": packet.get("pki_encrypted"),
                    "next_hop": packet.get("next_hop"),
                    "relay_node": packet.get("relay_node"),
                    "tx_after": packet.get("tx_after"),
                }

                # Add decoded payload structure
                if packet.get("portnum") and packet.get("raw_payload"):
                    mesh_packet_fields["decoded"] = {
                        "portnum": packet.get("portnum"),
                        "payload": packet["raw_payload"].hex()
                        if packet["raw_payload"]
                        else None,
                        "want_response": packet.get("want_response"),
                        "dest": packet.get("dest"),
                        "source": packet.get("source"),
                        "request_id": packet.get("request_id"),
                        "reply_id": packet.get("reply_id"),
                        "emoji": packet.get("emoji"),
                    }

                    # Try to decode the actual payload protobuf based on portnum
                    try:
                        decoded_payload = decode_protobuf_payload(packet)
                        if decoded_payload is not None:
                            decoded_dict = mesh_packet_fields.get("decoded")
                            if isinstance(decoded_dict, dict):
                                decoded_dict["parsed_payload"] = decoded_payload
                    except Exception as e:
                        decoded_dict = mesh_packet_fields.get("decoded")
                        if isinstance(decoded_dict, dict):
                            decoded_dict["parse_error"] = str(e)

                protobuf_decode["mesh_packet"] = mesh_packet_fields

        except Exception as e:
            logger.warning(
                f"Error creating protobuf decode for packet {packet['id']}: {e}"
            )
            protobuf_decode = {
                "error": f"Failed to decode protobuf: {str(e)}",
                "service_envelope": analysis["service_envelope"],
                "mesh_packet": analysis["mesh_packet"],
            }

        analysis["protobuf_fields"] = protobuf_decode

        return analysis

    except Exception as e:
        logger.warning(f"Error analyzing raw packet for packet {packet['id']}: {e}")
        return {
            "error": str(e),
            "raw_hex": packet["raw_payload"].hex() if packet["raw_payload"] else None,
            "size_bytes": len(packet["raw_payload"]) if packet["raw_payload"] else 0,
        }


@packet_bp.route("/packets")
def packets() -> str | tuple[str, int]:
    """Packet browser page using modern table interface."""
    logger.info(f"Packets route accessed with args: {request.args}")
    try:
        # Create clean filters dict for template (exclude any pagination parameters)
        template_filters = {}
        for key, value in request.args.items():
            if key not in ["page", "limit", "offset"]:  # Exclude pagination params
                template_filters[key] = value

        logger.info("Packets page rendered")

        return render_template(
            "packets.html",
            filters=template_filters,
        )
    except Exception as e:
        logger.error(f"Error in packets route: {e}")
        return f"Packets error: {e}", 500


@packet_bp.route("/packet/<int:packet_id>")
def packet_detail(packet_id: int) -> str | tuple[str, int]:
    """Packet detail page showing comprehensive information about a specific packet."""
    logger.info(f"Packet detail route accessed for packet {packet_id}")
    try:
        packet_details = get_packet_details(packet_id)
        if packet_details is None:
            return "Packet not found", 404

        logger.info("Packet detail page rendered successfully")
        return render_template("packet_detail.html", **packet_details)
    except Exception as e:
        logger.error(f"Error in packet detail route: {e}")
        return f"Packet detail error: {e}", 500
