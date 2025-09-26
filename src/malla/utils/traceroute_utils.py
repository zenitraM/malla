"""
Traceroute utility functions for Meshtastic Mesh Health Web UI
"""

import logging
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
    Parse traceroute payload from raw bytes using protobuf parsing.

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

        Returns empty lists for all fields if the payload cannot be parsed
        as valid protobuf data.
    """
    logger.debug(f"Parsing traceroute payload of {len(raw_payload)} bytes")

    if not raw_payload:
        return RouteData(route_nodes=[], snr_towards=[], route_back=[], snr_back=[])

    try:
        # Try protobuf parsing
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
        logger.debug(f"Protobuf parsing failed: {e}, returning empty result")

    # Return empty result for invalid/malformed packets
    return RouteData(route_nodes=[], snr_towards=[], route_back=[], snr_back=[])


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
