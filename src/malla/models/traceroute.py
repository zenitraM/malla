"""
Unified TraceroutePacket class for consistent traceroute path analysis.

This class consolidates all traceroute path construction logic that was previously
scattered across templates, APIs, and utility functions. It provides a consistent
interface for analyzing traceroute packets and extracting path information.
"""

import logging
import math
from dataclasses import dataclass
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class RouteData(TypedDict):
    """Type definition for parsed traceroute route data."""

    route_nodes: list[int]
    snr_towards: list[float]
    route_back: list[int]
    snr_back: list[float]


@dataclass
class TracerouteHop:
    """Represents a single hop in a traceroute path."""

    hop_number: int
    from_node_id: int
    to_node_id: int
    from_node_name: str | None = None
    to_node_name: str | None = None
    snr: float | None = None
    direction: str = "forward"  # 'forward', 'return', 'unknown'
    is_target_hop: bool = False  # For specific hop analysis
    # Distance calculation fields
    distance_meters: float | None = None
    from_location_timestamp: float | None = None
    to_location_timestamp: float | None = None
    from_location_age_warning: str | None = None
    to_location_age_warning: str | None = None

    @property
    def distance_km(self) -> float | None:
        """Convert distance_meters to kilometers."""
        if self.distance_meters is None:
            return None
        return self.distance_meters / 1000.0


@dataclass
class TraceroutePath:
    """Represents a complete path (forward or return) with metadata."""

    path_type: str  # 'forward', 'return', 'actual_rf'
    node_ids: list[int]
    node_names: list[str]
    snr_values: list[float]
    hops: list[TracerouteHop]
    is_complete: bool = False
    total_hops: int = 0


class TraceroutePacket:
    """
    Unified class for analyzing traceroute packets and extracting path information.

    This class handles the complex logic of interpreting Meshtastic traceroute data,
    including the special case where route_back changes the interpretation of the
    forward path display.
    """

    def __init__(
        self,
        packet_data: dict[str, Any],
        resolve_names: bool = True,
        pre_parsed_route_data: RouteData | None = None,
    ):
        """
        Initialize a TraceroutePacket from raw packet data.

        Args:
            packet_data: Dictionary containing packet information including:
                - id, from_node_id, to_node_id, raw_payload, etc.
            resolve_names: Whether to resolve node IDs to names
            pre_parsed_route_data: Optional pre-parsed route data to skip extra parsing
        """
        self.packet_data = packet_data.copy()
        self.resolve_names = resolve_names

        # Extract basic packet info
        self.packet_id = packet_data.get("id")
        self.from_node_id: int | None = packet_data.get("from_node_id")
        self.to_node_id: int | None = packet_data.get("to_node_id")
        self.timestamp = packet_data.get("timestamp")
        self.gateway_id = packet_data.get("gateway_id")
        self.raw_payload = packet_data.get("raw_payload")
        self.hop_limit = packet_data.get("hop_limit")
        self.hop_start = packet_data.get("hop_start")

        # Initialize node names
        self.from_node_name: str | None = None
        self.to_node_name: str | None = None

        # Parse (or accept pre-parsed) traceroute payload
        if pre_parsed_route_data is not None:
            self.route_data = pre_parsed_route_data
        else:
            self.route_data = self._parse_payload()

        # Build paths
        self.forward_path = self._build_forward_path()
        self.return_path = self._build_return_path()
        self.actual_rf_path = self._determine_actual_rf_path()

        # Resolve node names if requested
        if resolve_names:
            self._resolve_node_names()

    def _parse_payload(self) -> RouteData:
        """Parse the raw traceroute payload to extract route data."""
        if not self.raw_payload:
            return RouteData(
                route_nodes=[],
                snr_towards=[],
                route_back=[],
                snr_back=[],
            )

        try:
            # Import here to avoid circular dependencies
            from ..utils.traceroute_utils import parse_traceroute_payload

            parsed_data = parse_traceroute_payload(self.raw_payload)

            # Ensure all values are the correct types
            return RouteData(
                route_nodes=[
                    int(node_id)
                    for node_id in parsed_data.get("route_nodes", [])
                    if node_id is not None
                ],
                snr_towards=[
                    float(snr)
                    for snr in parsed_data.get("snr_towards", [])
                    if snr is not None
                ],
                route_back=[
                    int(node_id)
                    for node_id in parsed_data.get("route_back", [])
                    if node_id is not None
                ],
                snr_back=[
                    float(snr)
                    for snr in parsed_data.get("snr_back", [])
                    if snr is not None
                ],
            )
        except Exception as e:
            logger.warning(
                f"Failed to parse traceroute payload for packet {self.packet_id}: {e}"
            )
            return RouteData(
                route_nodes=[],
                snr_towards=[],
                route_back=[],
                snr_back=[],
            )

    def _build_forward_path(self) -> TraceroutePath:
        """
        Build the forward path based on Meshtastic traceroute logic.

        The key insight: when route_back exists, the packet display logic
        shows: to_node_id + route_nodes + from_node_id
        This reflects that packets with return data traveled on the return journey.
        """
        if self.from_node_id is None or self.to_node_id is None:
            return TraceroutePath(
                path_type="forward",
                node_ids=[],
                node_names=[],
                snr_values=[],
                hops=[],
                is_complete=False,
                total_hops=0,
            )

        if self.has_return_path():
            # When return path exists, display shows the "forward" as to->route->from
            node_ids = (
                [self.to_node_id] + self.route_data["route_nodes"] + [self.from_node_id]
            )
            snr_values = self.route_data["snr_towards"]
            path_type = "forward_with_return"
        else:
            # Normal forward path: from->route->to
            node_ids = [self.from_node_id] + self.route_data["route_nodes"]
            snr_values = self.route_data["snr_towards"]
            path_type = "forward"

        # Check if the FORWARD traceroute is complete (reached destination)
        # The forward path is complete if:
        # 1. The last route node matches the destination, OR
        # 2. We have more SNR values than route nodes (indicating final hop reached destination)
        is_complete = (
            self.route_data["route_nodes"]
            and self.route_data["route_nodes"][-1] == self.to_node_id
        )

        # Build hops
        hops = []
        for i in range(len(node_ids) - 1):
            hop = TracerouteHop(
                hop_number=i + 1,
                from_node_id=node_ids[i],
                to_node_id=node_ids[i + 1],
                snr=snr_values[i] if i < len(snr_values) else None,
                direction="forward",
            )
            hops.append(hop)

        return TraceroutePath(
            path_type=path_type,
            node_ids=node_ids,
            node_names=[],  # Will be filled by _resolve_node_names
            snr_values=snr_values,
            hops=hops,
            is_complete=bool(is_complete),
            total_hops=len(hops),
        )

    def _build_return_path(self) -> TraceroutePath | None:
        """Build the return path if available."""
        if (
            not self.has_return_path()
            or self.from_node_id is None
            or self.to_node_id is None
        ):
            return None

        # Return path: from_node_id + route_back + to_node_id
        node_ids = [self.from_node_id] + self.route_data["route_back"]
        snr_values = self.route_data["snr_back"]

        # Check if the return path is complete
        # The return path is complete if the last route_back node matches the original source (from_node_id)
        # OR if we have SNR data for the final hop back to the originator
        is_complete = (
            self.route_data["route_back"]
            and self.route_data["route_back"][-1] == self.from_node_id
        )

        if is_complete:
            node_ids = node_ids + [self.to_node_id]

        # Build hops
        hops = []
        for i in range(len(node_ids) - 1):
            hop = TracerouteHop(
                hop_number=i + 1,
                from_node_id=node_ids[i],
                to_node_id=node_ids[i + 1],
                snr=snr_values[i] if i < len(snr_values) else None,
                direction="return",
            )
            hops.append(hop)

        return TraceroutePath(
            path_type="return",
            node_ids=node_ids,
            node_names=[],  # Will be filled by _resolve_node_names
            snr_values=snr_values,
            hops=hops,
            is_complete=bool(is_complete),
            total_hops=len(hops),
        )

    def _determine_actual_rf_path(self) -> TraceroutePath:
        """
        Determine the actual RF hops that occurred based on the traceroute data.

        This method analyzes both forward and return path data to build a comprehensive
        view of the actual radio transmissions that occurred during the traceroute.

        The traceroute protocol works as follows:
        - Forward path: packet travels from source to destination, collecting SNR data
        - Return path (if present): packet travels back from destination to source

        When route_back exists, it means the packet has completed its forward journey
        and is now on its return journey. The SNR data reflects the actual RF hops
        that occurred during transmission.

        Returns:
            TraceroutePath containing all actual RF hops with SNR data
        """
        if self.from_node_id is None or self.to_node_id is None:
            return TraceroutePath(
                path_type="forward_rf",
                node_ids=[],
                node_names=[],
                snr_values=[],
                hops=[],
                is_complete=False,
                total_hops=0,
            )

        all_hops: list[TracerouteHop] = []
        all_snr_values: list[float] = []

        # Process forward path RF hops
        forward_snr_values = self.route_data["snr_towards"]
        if forward_snr_values:
            # Build forward path nodes based on whether this is a return journey packet
            if self.has_return_path() or self.is_going_back():
                forward_node_ids = (
                    [self.to_node_id]
                    + self.route_data["route_nodes"]
                    + [self.from_node_id]
                )
            else:
                forward_node_ids = (
                    [self.from_node_id]
                    + self.route_data["route_nodes"]
                    + [self.to_node_id]
                )

            # Handle direct hop case (no intermediate route nodes)
            if len(self.route_data["route_nodes"]) == 0 and len(forward_snr_values) > 0:
                if not self.has_return_path():
                    # Direct hop on forward journey: source -> destination
                    forward_node_ids = [self.from_node_id, self.to_node_id]
                else:
                    # Direct hop on return journey: destination -> source
                    # (The SNR data represents the original forward hop, but the packet
                    # is now traveling in the reverse direction)
                    forward_node_ids = [self.to_node_id, self.from_node_id]

            # Build forward RF hops
            for i in range(len(forward_node_ids) - 1):
                if i < len(forward_snr_values):
                    hop = TracerouteHop(
                        hop_number=len(all_hops) + 1,
                        from_node_id=forward_node_ids[i],
                        to_node_id=forward_node_ids[i + 1],
                        snr=forward_snr_values[i],
                        direction="forward_rf",
                    )
                    all_hops.append(hop)
                    all_snr_values.append(forward_snr_values[i])

        # Process return path RF hops (if they exist)
        if self.has_return_path():
            return_snr_values = self.route_data["snr_back"]
            if return_snr_values:
                # Build return path nodes: from_node -> route_back nodes -> to_node
                # This represents the actual return journey RF hops
                return_node_ids = [self.from_node_id] + self.route_data["route_back"]

                # Only include hops that actually have SNR data
                actual_return_hops = min(
                    len(self.route_data["route_back"]), len(return_snr_values)
                )

                if actual_return_hops > 0:
                    return_node_ids = [self.from_node_id] + self.route_data[
                        "route_back"
                    ][:actual_return_hops]
                    # Add the final destination if we have SNR data for the final hop
                    if len(return_snr_values) > actual_return_hops:
                        return_node_ids.append(self.to_node_id)
                else:
                    # No actual hops occurred
                    return_node_ids = [self.from_node_id]

                # Build return hops
                for i in range(len(return_node_ids) - 1):
                    if i < len(return_snr_values):
                        hop = TracerouteHop(
                            hop_number=len(all_hops) + 1,
                            from_node_id=return_node_ids[i],
                            to_node_id=return_node_ids[i + 1],
                            snr=return_snr_values[i],
                            direction="return_rf",
                        )
                        all_hops.append(hop)
                        all_snr_values.append(return_snr_values[i])

        # Determine path type and completeness
        if self.has_return_path():
            path_type = "combined_rf"
            # Complete if both forward and return paths have all their SNR data
            forward_complete = len(forward_snr_values) > len(
                self.route_data["route_nodes"]
            )
            return_complete = len(self.route_data["snr_back"]) > len(
                self.route_data["route_back"]
            )
            is_complete = forward_complete and return_complete
        else:
            path_type = "forward_rf"
            is_complete = len(forward_snr_values) > len(self.route_data["route_nodes"])

        # Build combined node IDs list (all unique nodes in order)
        combined_node_ids = []
        for hop in all_hops:
            if hop.from_node_id not in combined_node_ids:
                combined_node_ids.append(hop.from_node_id)
            if hop.to_node_id not in combined_node_ids:
                combined_node_ids.append(hop.to_node_id)

        return TraceroutePath(
            path_type=path_type,
            node_ids=combined_node_ids,
            node_names=[],  # Will be filled by _resolve_node_names
            snr_values=all_snr_values,
            hops=all_hops,
            is_complete=is_complete,
            total_hops=len(all_hops),
        )

    def _resolve_node_names(self):
        """Resolve node IDs to names for all paths."""
        if not self.resolve_names:
            return

        # Import here to avoid circular dependencies
        from ..utils.node_utils import get_bulk_node_names

        # Collect all unique node IDs
        all_node_ids = set()
        all_node_ids.update(self.forward_path.node_ids)
        if self.return_path:
            all_node_ids.update(self.return_path.node_ids)
        all_node_ids.update(self.actual_rf_path.node_ids)

        # Get names in bulk
        node_names = get_bulk_node_names(list(all_node_ids))

        # Resolve packet-level node names with Optional safety
        if self.from_node_id is not None:
            self.from_node_name = node_names.get(
                self.from_node_id, f"!{self.from_node_id:08x}"
            )
        else:
            self.from_node_name = None

        if self.to_node_id is not None:
            self.to_node_name = node_names.get(
                self.to_node_id, f"!{self.to_node_id:08x}"
            )
        else:
            self.to_node_name = None

        # Update paths with names
        for path in [self.forward_path, self.return_path, self.actual_rf_path]:
            if path is None:
                continue

            # Update node names list
            path.node_names = [
                node_names.get(node_id, f"!{node_id:08x}") for node_id in path.node_ids
            ]

            # Update hop names
            for hop in path.hops:
                hop.from_node_name = node_names.get(
                    hop.from_node_id, f"!{hop.from_node_id:08x}"
                )
                hop.to_node_name = node_names.get(
                    hop.to_node_id, f"!{hop.to_node_id:08x}"
                )

    def _calculate_distance_meters(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """
        Calculate the great circle distance between two points using the Haversine formula.

        Returns distance in meters.
        """
        # Earth's radius in meters
        R = 6371000.0

        # Convert decimal degrees to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Haversine formula
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        distance = R * c
        return distance

    def calculate_hop_distances(
        self, calculate_for_all_paths: bool = True, location_cache: dict | None = None
    ):
        """
        Calculate distances for all hops in this traceroute using timestamp-aware location lookups.

        This method uses the most recent location info that existed at the moment of the traceroute
        for both nodes, falling back to future location data if no recent data exists.

        Args:
            calculate_for_all_paths: If True, calculate for forward, return, and RF paths.
                                   If False, only calculate for the display path.
            location_cache: Optional cache dict to store location lookups and avoid repeated DB queries.
                          Format: {(node_id, timestamp): location_data}
        """
        if not self.timestamp:
            logger.warning(
                f"No timestamp available for packet {self.packet_id}, cannot calculate distances"
            )
            return

        # Import here to avoid circular dependencies
        from ..utils.traceroute_utils import get_node_location_at_timestamp

        logger.debug(
            f"Calculating hop distances for packet {self.packet_id} at timestamp {self.timestamp}"
        )

        # Use provided cache or create a local one
        if location_cache is None:
            location_cache = {}

        def get_cached_location(
            node_id: int, timestamp: float
        ) -> dict[str, Any] | None:
            """Get location with caching to avoid repeated DB queries."""
            cache_key = (node_id, timestamp)
            if cache_key not in location_cache:
                location_cache[cache_key] = get_node_location_at_timestamp(
                    node_id, timestamp
                )
            return location_cache[cache_key]

        # Determine which paths to calculate distances for
        paths_to_calculate = [self.forward_path]
        if calculate_for_all_paths:
            if self.return_path:
                paths_to_calculate.append(self.return_path)
            paths_to_calculate.append(self.actual_rf_path)

        for path in paths_to_calculate:
            if not path or not path.hops:
                continue

            logger.debug(
                f"Calculating distances for {len(path.hops)} hops in {path.path_type} path"
            )

            for hop in path.hops:
                # Get location data for both nodes at the traceroute timestamp using cache
                from_location = get_cached_location(hop.from_node_id, self.timestamp)
                to_location = get_cached_location(hop.to_node_id, self.timestamp)

                if from_location and to_location:
                    # Calculate distance
                    distance_meters = self._calculate_distance_meters(
                        from_location["latitude"],
                        from_location["longitude"],
                        to_location["latitude"],
                        to_location["longitude"],
                    )

                    # Store distance and location metadata in the hop
                    hop.distance_meters = distance_meters
                    hop.from_location_timestamp = from_location["timestamp"]
                    hop.to_location_timestamp = to_location["timestamp"]
                    hop.from_location_age_warning = from_location["age_warning"]
                    hop.to_location_age_warning = to_location["age_warning"]

                    logger.debug(
                        f"Hop {hop.from_node_id} -> {hop.to_node_id}: {distance_meters:.0f}m "
                        f"(from: {from_location['age_warning']}, to: {to_location['age_warning']})"
                    )
                else:
                    # Missing location data
                    if not from_location:
                        logger.debug(
                            f"No location data found for from_node {hop.from_node_id}"
                        )
                    if not to_location:
                        logger.debug(
                            f"No location data found for to_node {hop.to_node_id}"
                        )

                    hop.distance_meters = None
                    hop.from_location_timestamp = None
                    hop.to_location_timestamp = None
                    hop.from_location_age_warning = "No location data available"
                    hop.to_location_age_warning = "No location data available"

    def format_distance(self, distance_meters: float | None) -> str:
        """
        Format distance in appropriate units for display.

        Args:
            distance_meters: Distance in meters

        Returns:
            Formatted distance string
        """
        if distance_meters is None:
            return "Unknown"

        if distance_meters < 1000:
            return f"{distance_meters:.0f} m"
        else:
            return f"{distance_meters / 1000:.2f} km"

    def get_display_hops_with_distances(
        self, location_cache: dict | None = None
    ) -> list[TracerouteHop]:
        """
        Get display hops with distance calculations performed.
        This is a convenience method for templates that need distance data.

        Args:
            location_cache: Optional cache dict to store location lookups and avoid repeated DB queries.
        """
        # Calculate distances if not already done
        if self.forward_path.hops and self.forward_path.hops[0].distance_meters is None:
            self.calculate_hop_distances(
                calculate_for_all_paths=False, location_cache=location_cache
            )

        return self.forward_path.hops

    def get_return_hops_with_distances(
        self, location_cache: dict | None = None
    ) -> list[TracerouteHop]:
        """
        Get return path hops with distance calculations performed.
        This is a convenience method for templates that need distance data.

        Args:
            location_cache: Optional cache dict to store location lookups and avoid repeated DB queries.
        """
        if not self.return_path:
            return []

        # Calculate distances if not already done
        if self.return_path.hops and self.return_path.hops[0].distance_meters is None:
            self.calculate_hop_distances(
                calculate_for_all_paths=True, location_cache=location_cache
            )

        return self.return_path.hops

    # Public interface methods

    def is_going_back(self) -> bool:
        """Check if this traceroute is going back."""
        # Handle None values for hop_start and hop_limit
        hop_start = self.hop_start or 0
        hop_limit = self.hop_limit or 0

        return (
            len(self.route_data["snr_towards"]) > len(self.route_data["route_nodes"])
        ) and len(self.route_data["route_nodes"]) > (hop_start - hop_limit)

    def has_return_path(self) -> bool:
        """Check if this traceroute has return path data."""
        return bool(self.route_data["route_back"])

    def is_complete(self) -> bool:
        """Check if the forward traceroute reached its destination."""
        return self.forward_path.is_complete or self.is_going_back()

    def is_return_complete(self) -> bool:
        """Check if the return path completed back to the originator."""
        return self.return_path.is_complete if self.return_path else False

    def get_completion_status(self) -> str:
        """Get a human-readable completion status."""
        if not self.has_return_path():
            return (
                "Complete"
                if self.is_complete()
                else "Incomplete - Final destination not reached"
            )
        else:
            forward_status = (
                "Forward complete" if self.is_complete() else "Forward incomplete"
            )
            return_status = (
                "Return complete" if self.is_return_complete() else "Return in progress"
            )
            return f"{forward_status}, {return_status}"

    def get_display_path(self) -> TraceroutePath:
        """
        Get the path for template display purposes.
        This matches the current template logic.
        """
        return self.forward_path

    def get_rf_hops(self) -> list[TracerouteHop]:
        """
        Get all direct RF hops from this packet for link analysis.
        Returns hops from the actual RF path this packet took.
        """
        return self.actual_rf_path.hops

    def get_all_hops(self) -> list[TracerouteHop]:
        """Get all hops from both forward and return paths."""
        all_hops = self.forward_path.hops.copy()
        if self.return_path:
            all_hops.extend(self.return_path.hops)
        return all_hops

    def contains_hop(self, from_node_id: int, to_node_id: int) -> bool:
        """
        Check if this traceroute contains a specific hop (in either direction).

        IMPORTANT: This method is used for RF link analysis, so it only checks
        actual RF hops that occurred, not display hops that show intended destinations
        but were never reached in incomplete traceroutes.
        """
        # Only check actual RF hops that occurred on the radio
        for hop in self.get_rf_hops():
            if (hop.from_node_id == from_node_id and hop.to_node_id == to_node_id) or (
                hop.from_node_id == to_node_id and hop.to_node_id == from_node_id
            ):
                return True
        return False

    def get_hop_snr(self, from_node_id: int, to_node_id: int) -> float | None:
        """
        Get the SNR for a specific hop if it exists in this traceroute.

        IMPORTANT: This method is used for RF link analysis, so it only checks
        actual RF hops that occurred, not display hops.
        """
        # Only check actual RF hops that occurred on the radio
        for hop in self.get_rf_hops():
            if (hop.from_node_id == from_node_id and hop.to_node_id == to_node_id) or (
                hop.from_node_id == to_node_id and hop.to_node_id == from_node_id
            ):
                return hop.snr
        return None

    def get_display_hops(self) -> list[TracerouteHop]:
        """
        Get hops from the display/forward path.
        This represents what users see in the traceroute display.
        """
        return self.forward_path.hops

    def get_all_analysis_hops(self) -> list[TracerouteHop]:
        """
        Get all hops for comprehensive analysis, including both display and RF paths.
        This is useful for link analysis where we want to understand all possible hops.
        """
        all_hops = []

        # Add display path hops (marked as 'display')
        for hop in self.get_display_hops():
            hop_copy = TracerouteHop(
                hop_number=hop.hop_number,
                from_node_id=hop.from_node_id,
                to_node_id=hop.to_node_id,
                from_node_name=hop.from_node_name,
                to_node_name=hop.to_node_name,
                snr=hop.snr,
                direction="display",
                is_target_hop=hop.is_target_hop,
            )
            all_hops.append(hop_copy)

        # Add actual RF path hops (marked as 'actual_rf')
        for hop in self.get_rf_hops():
            hop_copy = TracerouteHop(
                hop_number=hop.hop_number,
                from_node_id=hop.from_node_id,
                to_node_id=hop.to_node_id,
                from_node_name=hop.from_node_name,
                to_node_name=hop.to_node_name,
                snr=hop.snr,
                direction="actual_rf",
                is_target_hop=hop.is_target_hop,
            )
            all_hops.append(hop_copy)

        return all_hops

    def get_path_summary(self) -> dict[str, Any]:
        """Get a summary of this traceroute for display/API purposes."""
        return {
            "packet_id": self.packet_id,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "from_node_name": self.forward_path.node_names[0]
            if self.forward_path.node_names
            else None,
            "to_node_name": self.forward_path.node_names[-1]
            if self.forward_path.node_names
            else None,
            "timestamp": self.timestamp,
            "gateway_id": self.gateway_id,
            "has_return_path": self.has_return_path(),
            "is_complete": self.is_complete(),
            "forward_hops": self.forward_path.total_hops,
            "return_hops": self.return_path.total_hops if self.return_path else 0,
            "total_rf_hops": len(self.get_rf_hops()),
            "route_nodes": self.route_data["route_nodes"],
            "route_back": self.route_data["route_back"],
            "snr_towards": self.route_data["snr_towards"],
            "snr_back": self.route_data["snr_back"],
        }

    def format_path_display(self, path_type: str = "display") -> str:
        """
        Format a path for display.

        Args:
            path_type: 'display' (template display), 'forward', 'return', 'actual_rf'
        """
        # Prepare variable that may be Optional initially
        path: TraceroutePath | None
        if path_type == "display":
            path = self.forward_path
        elif path_type == "forward":
            path = self.forward_path
        elif path_type == "return":
            path = self.return_path
        elif path_type == "actual_rf":
            path = self.actual_rf_path
        else:
            raise ValueError(f"Unknown path_type: {path_type}")

        if path is None or not path.node_names:
            return "No path data"

        return " → ".join(path.node_names)

    def to_template_context(self) -> dict[str, Any]:
        """
        Convert to context suitable for template rendering.
        This replaces the current template logic.
        """
        display_path = self.get_display_path()

        context = {
            "route_nodes": self.route_data["route_nodes"],
            "route_back": self.route_data["route_back"],
            "snr_towards": self.route_data["snr_towards"],
            "snr_back": self.route_data["snr_back"],
            "has_return_path": self.has_return_path(),
            "is_complete": self.is_complete(),
            "display_path": display_path,
            "return_path": self.return_path,
            "forward_hops": display_path.hops,
            "return_hops": self.return_path.hops if self.return_path else [],
            "route_node_names": {},
        }

        # Add node names lookup for template compatibility
        all_node_ids = set(
            self.route_data["route_nodes"] + self.route_data["route_back"]
        )
        if self.from_node_id is not None:
            all_node_ids.add(self.from_node_id)
        if self.to_node_id is not None:
            all_node_ids.add(self.to_node_id)

        if self.resolve_names and all_node_ids:
            from ..utils.node_utils import get_bulk_node_names

            node_names = get_bulk_node_names(list(all_node_ids))
            context["route_node_names"] = node_names

        return context
