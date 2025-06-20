"""
Traceroute utility functions for Meshtastic Mesh Health Web UI
"""

import logging
import struct
from typing import Any, TypedDict

from meshtastic import mesh_pb2

logger = logging.getLogger(__name__)


class RouteData(TypedDict):
    """Type definition for parsed traceroute route data."""

    route_nodes: list[int]
    snr_towards: list[float]
    route_back: list[int]
    snr_back: list[float]


def parse_traceroute_payload(raw_payload: bytes) -> RouteData:
    """
    Parse traceroute payload from raw bytes.

    Args:
        raw_payload: Raw payload bytes from the packet

    Returns:
        Dictionary containing route data with proper types:
        {
            'route_nodes': List[int],
            'snr_towards': List[float],
            'route_back': List[int],
            'snr_back': List[float]
        }
    """
    logger.debug(f"Parsing traceroute payload of {len(raw_payload)} bytes")

    if not raw_payload:
        return RouteData(route_nodes=[], snr_towards=[], route_back=[], snr_back=[])

    try:
        # Try protobuf parsing first
        route_discovery = mesh_pb2.RouteDiscovery()
        route_discovery.ParseFromString(raw_payload)

        result = RouteData(
            route_nodes=[int(node_id) for node_id in route_discovery.route],
            # Convert SNR from scaled integer to actual dB (divide by 4)
            snr_towards=[float(snr) / 4.0 for snr in route_discovery.snr_towards],
            route_back=[int(node_id) for node_id in route_discovery.route_back],
            # Convert SNR from scaled integer to actual dB (divide by 4)
            snr_back=[float(snr) / 4.0 for snr in route_discovery.snr_back],
        )

        logger.debug(
            f"Protobuf parsing successful: {len(result['route_nodes'])} nodes, "
            f"{len(result['snr_towards'])} SNR values"
        )
        return result

    except Exception as e:
        logger.warning(f"Protobuf parsing failed: {e}, falling back to manual parsing")

    # Fallback to manual parsing
    return parse_traceroute_payload_manual(raw_payload)


def parse_traceroute_payload_manual(raw_payload: bytes) -> RouteData:
    """
    Manually parse traceroute payload when protobuf parsing fails.

    This function handles various payload formats including JSON (for testing)
    and raw protobuf data.
    """
    import json  # Move import to top of function

    result = RouteData(
        route_nodes=[],
        snr_towards=[],
        route_back=[],
        snr_back=[],
    )

    if len(raw_payload) < 1:
        return result

    # Try JSON parsing first (for test data and potential JSON payloads)
    try:
        payload_str = raw_payload.decode("utf-8")
        json_data = json.loads(payload_str)

        if isinstance(json_data, dict):
            # Ensure proper types when parsing from JSON
            route_nodes_raw = json_data.get("route_nodes", [])
            snr_towards_raw = json_data.get("snr_towards", [])
            route_back_raw = json_data.get("route_back", [])
            snr_back_raw = json_data.get("snr_back", [])

            result = RouteData(
                route_nodes=[
                    int(node_id) for node_id in route_nodes_raw if node_id is not None
                ],
                # Convert SNR from scaled integer to actual dB (divide by 4)
                snr_towards=[float(snr) / 4.0 for snr in snr_towards_raw if snr is not None],
                route_back=[
                    int(node_id) for node_id in route_back_raw if node_id is not None
                ],
                # Convert SNR from scaled integer to actual dB (divide by 4)
                snr_back=[float(snr) / 4.0 for snr in snr_back_raw if snr is not None],
            )

            logger.debug(
                f"JSON parsing successful: {len(result['route_nodes'])} nodes, "
                f"{len(result['snr_towards'])} forward SNR"
            )
            return result
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        # Not JSON, continue with protobuf parsing
        pass

    # Fallback to protobuf parsing
    try:
        offset = 0

        # Parse route_nodes (repeated uint32, field 1)
        if offset < len(raw_payload):
            route_nodes, offset = _parse_repeated_uint32(raw_payload, offset, 1)
            result["route_nodes"] = route_nodes

        # Parse snr_towards (repeated float, field 2)
        if offset < len(raw_payload):
            snr_towards, offset = _parse_repeated_float(raw_payload, offset, 2)
            # Convert SNR from scaled integer to actual dB (divide by 4)
            result["snr_towards"] = [snr / 4.0 for snr in snr_towards]

        # Parse route_back (repeated uint32, field 3)
        if offset < len(raw_payload):
            route_back, offset = _parse_repeated_uint32(raw_payload, offset, 3)
            result["route_back"] = route_back

        # Parse snr_back (repeated float, field 4)
        if offset < len(raw_payload):
            snr_back, offset = _parse_repeated_float(raw_payload, offset, 4)
            # Convert SNR from scaled integer to actual dB (divide by 4)
            result["snr_back"] = [snr / 4.0 for snr in snr_back]

        logger.debug(
            f"Manual parsing successful: {len(result['route_nodes'])} nodes, "
            f"{len(result['snr_towards'])} forward SNR, "
            f"{len(result['route_back'])} return nodes, "
            f"{len(result['snr_back'])} return SNR"
        )

    except Exception as e:
        logger.error(f"Error in manual traceroute parsing: {e}")

    return result


def _parse_repeated_uint32(
    data: bytes, offset: int, field_number: int
) -> tuple[list[int], int]:
    """Parse repeated uint32 field from protobuf data."""
    values: list[int] = []

    while offset < len(data):
        # Read field header
        if offset >= len(data):
            break

        try:
            tag_byte = data[offset]
            offset += 1

            # Extract field number and wire type
            field_num = tag_byte >> 3
            wire_type = tag_byte & 0x07

            if field_num != field_number:
                # This isn't our field, skip it or stop
                if field_num > field_number:
                    # We've passed our field
                    offset -= 1
                    break
                else:
                    # Skip this field
                    offset = _skip_field(data, offset - 1, wire_type)
                    continue

            if wire_type == 0:  # Varint
                value, offset = _parse_varint(data, offset)
                values.append(int(value))
            elif wire_type == 2:  # Length-delimited (packed)
                length, offset = _parse_varint(data, offset)
                end_offset = offset + length
                while offset < end_offset:
                    value, offset = _parse_varint(data, offset)
                    values.append(int(value))
                break  # Packed field, we're done
            else:
                # Unexpected wire type for uint32
                break

        except (IndexError, struct.error):
            break

    return values, offset


def _parse_repeated_float(
    data: bytes, offset: int, field_number: int
) -> tuple[list[float], int]:
    """Parse repeated float field from protobuf data."""
    values: list[float] = []

    while offset < len(data):
        if offset >= len(data):
            break

        try:
            tag_byte = data[offset]
            offset += 1

            field_num = tag_byte >> 3
            wire_type = tag_byte & 0x07

            if field_num != field_number:
                if field_num > field_number:
                    # We've passed our field
                    offset -= 1
                    break
                else:
                    # Skip this field
                    offset = _skip_field(data, offset - 1, wire_type)
                    continue

            if wire_type == 5:  # Fixed32 (float)
                if offset + 4 <= len(data):
                    float_bytes = data[offset : offset + 4]
                    float_value = struct.unpack("<f", float_bytes)[0]
                    values.append(float(float_value))
                    offset += 4
                else:
                    break
            elif wire_type == 2:  # Length-delimited (packed floats)
                length, offset = _parse_varint(data, offset)
                end_offset = offset + length
                while offset < end_offset and offset + 4 <= end_offset:
                    float_bytes = data[offset : offset + 4]
                    float_value = struct.unpack("<f", float_bytes)[0]
                    values.append(float(float_value))
                    offset += 4
                break  # Packed field, we're done
            else:
                # Unexpected wire type for float
                break

        except (IndexError, struct.error):
            break

    return values, offset


def _parse_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Parse a varint from protobuf data."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
        if shift >= 64:
            raise ValueError("Varint too long")
    return result, offset


def _skip_field(data: bytes, offset: int, wire_type: int) -> int:
    """Skip a field in protobuf data based on wire type."""
    if wire_type == 0:  # Varint
        _, offset = _parse_varint(data, offset + 1)
    elif wire_type == 1:  # Fixed64
        offset += 9  # 1 byte tag + 8 bytes data
    elif wire_type == 2:  # Length-delimited
        length, offset = _parse_varint(data, offset + 1)
        offset += length
    elif wire_type == 5:  # Fixed32
        offset += 5  # 1 byte tag + 4 bytes data
    else:
        # Unknown wire type, can't skip safely
        raise ValueError(f"Unknown wire type: {wire_type}")
    return offset


def get_node_location_at_timestamp(
    node_id: int, target_timestamp: float
) -> dict[str, Any] | None:
    """
    Get the most recent location for a node at or before the given timestamp.

    This function is a wrapper around LocationRepository.get_node_location_at_timestamp
    to maintain backward compatibility.

    Args:
        node_id: The node ID to get location for
        target_timestamp: The timestamp to get location at (Unix timestamp)

    Returns:
        Dictionary with location data and metadata, or None if no location found
    """
    # Import here to avoid circular dependencies
    from ..database.repositories import LocationRepository

    try:
        return LocationRepository.get_node_location_at_timestamp(
            node_id, target_timestamp
        )
    except Exception as e:
        logger.error(f"Error getting location for node {node_id}: {e}")
        return None
