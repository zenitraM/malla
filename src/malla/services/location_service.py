"""
Location service for Meshtastic Mesh Health Web UI
"""

import logging
import math
import time
from datetime import UTC, datetime
from typing import Any

from ..database.repositories import LocationRepository

logger = logging.getLogger(__name__)


class LocationService:
    """Service for location-related operations and calculations."""

    @staticmethod
    def get_node_locations(
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all node locations with formatted display information and network topology data.

        Args:
            filters: Optional filters to apply (start_time, end_time, gateway_id, node_ids, etc.)

        Returns:
            List of location dictionaries with additional display fields and network analysis
        """
        if filters is None:
            filters = {}

        service_start = time.time()
        timing_breakdown = {}

        logger.info(f"Getting node locations with filters: {filters}")

        # Get basic location data with filters
        repo_start = time.time()
        locations = LocationRepository.get_node_locations(filters)
        timing_breakdown["repository_call"] = time.time() - repo_start

        if not locations:
            return []

        # Apply age filtering if specified
        age_filter_start = time.time()
        current_time = datetime.now().timestamp()
        if filters.get("max_age_hours"):
            max_age_seconds = filters["max_age_hours"] * 3600
            cutoff_time = current_time - max_age_seconds
            locations = [loc for loc in locations if loc["timestamp"] >= cutoff_time]
            logger.info(
                f"Applied max_age_hours filter: {len(locations)} locations remain after filtering"
            )

        if filters.get("min_age_hours"):
            min_age_seconds = filters["min_age_hours"] * 3600
            cutoff_time = current_time - min_age_seconds
            locations = [loc for loc in locations if loc["timestamp"] <= cutoff_time]
            logger.info(
                f"Applied min_age_hours filter: {len(locations)} locations remain after filtering"
            )
        timing_breakdown["age_filtering"] = time.time() - age_filter_start

        if not locations:
            return []

        # Get network topology data from traceroute analysis
        network_start = time.time()
        try:
            from ..services.traceroute_service import TracerouteService

            # Extract time parameters from filters for network analysis
            hours = 24  # Default to 24 hours – sufficient for map neighbour analysis
            if filters.get("start_time") and filters.get("end_time"):
                # Calculate hours from time range
                time_diff = filters["end_time"] - filters["start_time"]
                hours = max(
                    1, min(168, int(time_diff / 3600))
                )  # Between 1 and 168 hours
            elif filters.get("max_age_hours"):
                hours = min(168, filters["max_age_hours"])

            # Pass the same filters to network analysis for consistency
            network_filters = {}
            if filters.get("start_time"):
                network_filters["start_time"] = filters["start_time"]
            if filters.get("end_time"):
                network_filters["end_time"] = filters["end_time"]
            if filters.get("gateway_id"):
                network_filters["gateway_id"] = filters["gateway_id"]

            network_data = TracerouteService.get_network_graph_data(
                hours=hours,
                include_indirect=False,
                filters=network_filters,
                limit_packets=2000,
            )
        except Exception as e:
            logger.warning(f"Failed to get network topology data: {e}")
            network_data = {"nodes": [], "links": []}
        timing_breakdown["network_topology"] = time.time() - network_start

        # Create lookup maps for network data
        network_processing_start = time.time()
        network_nodes = {node["id"]: node for node in network_data.get("nodes", [])}

        # Create neighbor and gateway count maps
        neighbor_counts = {}
        gateway_counts = {}
        min_hops_to_gateway = {}
        neighbor_details: dict[int, list[dict[str, Any]]] = {}

        # Process network links to build neighbor relationships
        for link in network_data.get("links", []):
            source_id = link["source"]
            target_id = link["target"]

            # Track neighbors
            if source_id not in neighbor_counts:
                neighbor_counts[source_id] = 0
                neighbor_details[source_id] = []
            if target_id not in neighbor_counts:
                neighbor_counts[target_id] = 0
                neighbor_details[target_id] = []

            neighbor_counts[source_id] += 1
            neighbor_counts[target_id] += 1

            # Add neighbor details (using SNR as proxy for RSSI)
            avg_rssi = (
                link.get("avg_snr", 0) - 10 if link.get("avg_snr") else None
            )  # Rough SNR to RSSI conversion
            neighbor_details[source_id].append(
                {"neighbor_id": target_id, "avg_rssi": avg_rssi}
            )
            neighbor_details[target_id].append(
                {"neighbor_id": source_id, "avg_rssi": avg_rssi}
            )
        timing_breakdown["neighbor_processing"] = time.time() - network_processing_start

        # Get gateway information and calculate hop counts
        gateway_start = time.time()

        try:
            from ..database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            # Build time filter for gateway analysis
            gateway_time_filter = ""
            gateway_params = []

            if filters.get("start_time"):
                gateway_time_filter = "AND timestamp >= ?"
                gateway_params.append(filters["start_time"])
            elif not filters.get("end_time"):
                # Default to last 3 hours if no time filters specified (faster, still accurate)
                gateway_time_filter = "AND timestamp > ?"
                gateway_params.append(datetime.now().timestamp() - 3 * 3600)

            if filters.get("end_time"):
                gateway_time_filter += " AND timestamp <= ?"
                gateway_params.append(filters["end_time"])

            cursor.execute(
                f"""
                SELECT
                    gateway_id,
                    COUNT(DISTINCT from_node_id) as unique_sources
                FROM packet_history
                WHERE gateway_id IS NOT NULL
                {gateway_time_filter}
                GROUP BY gateway_id
                HAVING unique_sources >= 3
                ORDER BY unique_sources DESC
            """,
                gateway_params,
            )

            gateway_nodes = {row["gateway_id"] for row in cursor.fetchall()}

            # Count how many gateways heard each node
            cursor.execute(
                f"""
                SELECT from_node_id, COUNT(DISTINCT gateway_id) as gateway_count
                FROM packet_history
                WHERE gateway_id IS NOT NULL
                {gateway_time_filter}
                GROUP BY from_node_id
            """,
                gateway_params,
            )

            gateway_counts = {}
            for row in cursor.fetchall():
                gateway_counts[row["from_node_id"]] = row["gateway_count"]

            conn.close()

            # Calculate minimum hops to gateways in a single multi-source BFS for efficiency
            hop_calc_start = time.time()
            min_hops_to_gateway = LocationService._calculate_all_min_hops_to_gateway(
                gateway_nodes, neighbor_details
            )

            # Ensure every node has a value (use 999 if unreachable)
            for n_id in [loc["node_id"] for loc in locations]:
                if n_id not in min_hops_to_gateway:
                    min_hops_to_gateway[n_id] = 0 if n_id in gateway_nodes else 999
            timing_breakdown["hop_calculation"] = time.time() - hop_calc_start

        except Exception as e:
            logger.warning(f"Failed to calculate gateway information: {e}")
        timing_breakdown["gateway_analysis"] = time.time() - gateway_start

        # Enhance location data with network topology information
        enhancement_start = time.time()
        # current_time already calculated above for age filtering
        enhanced_locations = []

        for location in locations:
            node_id = location["node_id"]

            # Calculate age in hours
            age_hours = (current_time - location["timestamp"]) / 3600

            # Format timestamp string
            timestamp_dt = datetime.fromtimestamp(location["timestamp"])
            timestamp_str = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")

            # Get network data for this node
            network_node = network_nodes.get(node_id, {})
            direct_neighbors = neighbor_counts.get(node_id, 0)
            neighbors = neighbor_details.get(node_id, [])

            enhanced_location = {
                # Original location data
                "node_id": location["node_id"],
                "hex_id": location["hex_id"],
                "display_name": location["display_name"],
                "long_name": location["long_name"],
                "short_name": location["short_name"],
                "hw_model": location["hw_model"],
                "role": location["role"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "altitude": location["altitude"],
                "timestamp": location["timestamp"],
                # Enhanced fields for map display
                "age_hours": round(age_hours, 2),
                "timestamp_str": timestamp_str,
                "min_hops_to_gateway": min_hops_to_gateway.get(node_id),
                "direct_neighbors": direct_neighbors,
                "gateway_count": gateway_counts.get(node_id, 0),
                "neighbors": neighbors,
                "sats_in_view": location.get("sats_in_view"),
                "precision_bits": location.get("precision_bits"),
                "precision_meters": location.get("precision_meters"),
                # Network analysis data
                "packet_count": network_node.get("packet_count", 0),
                "avg_snr": network_node.get("avg_snr"),
                "last_seen_network": network_node.get("last_seen"),
            }

            enhanced_locations.append(enhanced_location)
        timing_breakdown["enhancement"] = time.time() - enhancement_start

        total_service_time = time.time() - service_start
        timing_breakdown["total_service"] = total_service_time

        logger.info(
            f"Enhanced {len(enhanced_locations)} locations with network topology data "
            f"in {total_service_time:.3f}s "
            f"(Repo: {timing_breakdown['repository_call']:.3f}s, "
            f"Network: {timing_breakdown['network_topology']:.3f}s, "
            f"Gateway: {timing_breakdown['gateway_analysis']:.3f}s, "
            f"Enhancement: {timing_breakdown['enhancement']:.3f}s)"
        )
        return enhanced_locations

    @staticmethod
    def _calculate_min_hops_to_gateway(
        start_node_id: int,
        gateway_nodes: set,
        neighbor_details: dict,
        max_hops: int = 10,
    ) -> int | None:
        """
        Calculate minimum hops to reach any gateway using BFS.

        Args:
            start_node_id: Starting node ID
            gateway_nodes: Set of gateway node IDs
            neighbor_details: Dictionary mapping node_id to list of neighbors
            max_hops: Maximum hops to search

        Returns:
            Minimum hops to gateway, or None if unreachable
        """
        if start_node_id in gateway_nodes:
            return 0

        if start_node_id not in neighbor_details:
            return None

        visited = {start_node_id}
        queue = [(start_node_id, 0)]  # (node_id, hops)

        while queue:
            current_node, hops = queue.pop(0)

            if hops >= max_hops:
                continue

            # Check neighbors
            for neighbor in neighbor_details.get(current_node, []):
                neighbor_id = neighbor["neighbor_id"]

                if neighbor_id in gateway_nodes:
                    return hops + 1

                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, hops + 1))

        return None  # No path found

    @staticmethod
    def _calculate_all_min_hops_to_gateway(
        gateway_nodes: set[int],
        neighbor_details: dict[int, list[dict[str, Any]]],
        max_hops: int = 10,
    ) -> dict[int, int]:
        """Calculate minimum hops to reach any gateway for **all** nodes simultaneously.

        This uses a multi-source BFS starting from all gateway nodes, which
        visits every reachable node at most once.  It is drastically faster
        than running a separate BFS from each node.

        Args:
            gateway_nodes: Set of gateway node IDs.
            neighbor_details: Mapping of node_id -> list[{neighbor_id, ...}].
            max_hops: Optional maximum hop search depth.

        Returns:
            Dictionary mapping node_id -> min hops to the nearest gateway.
            Nodes that are unreachable will be *omitted* from the dictionary.
        """

        from collections import deque

        if not gateway_nodes:
            return {}

        # Prepare BFS queue with all gateways as starting points
        queue: deque[tuple[int, int]] = deque()
        distance: dict[int, int] = {}

        for g in gateway_nodes:
            distance[g] = 0
            queue.append((g, 0))

        while queue:
            current, hops = queue.popleft()
            if hops >= max_hops:
                continue

            for nbr in neighbor_details.get(current, []):
                nbr_id = nbr["neighbor_id"]
                if nbr_id not in distance:
                    distance[nbr_id] = hops + 1
                    queue.append((nbr_id, hops + 1))

        return distance

    @staticmethod
    def get_traceroute_links(
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get traceroute links data for map visualization.

        Args:
            filters: Optional filters to apply (same as get_node_locations)

        Returns:
            List of traceroute link dictionaries
        """
        if filters is None:
            filters = {}
        logger.info(
            f"Getting traceroute links for map visualization with filters: {filters}"
        )

        try:
            from ..services.traceroute_service import TracerouteService

            # Extract time parameters from filters for network analysis
            hours = 24  # Default to 24 hours for links
            if filters.get("start_time") and filters.get("end_time"):
                # Calculate hours from time range
                time_diff = filters["end_time"] - filters["start_time"]
                hours = max(
                    1, min(168, int(time_diff / 3600))
                )  # Between 1 and 168 hours
            elif filters.get("max_age_hours"):
                hours = min(168, filters["max_age_hours"])

            # Pass the same filters to network analysis for consistency
            network_filters = {}
            if filters.get("start_time"):
                network_filters["start_time"] = filters["start_time"]
            if filters.get("end_time"):
                network_filters["end_time"] = filters["end_time"]
            if filters.get("gateway_id"):
                network_filters["gateway_id"] = filters["gateway_id"]

            network_data = TracerouteService.get_network_graph_data(
                hours=hours,
                include_indirect=False,
                filters=network_filters,
                limit_packets=2000,
            )

            # Convert network links to map-compatible format
            traceroute_links = []
            current_time = datetime.now().timestamp()

            for link in network_data.get("links", []):
                # Calculate age in hours
                age_hours = (current_time - link["last_seen"]) / 3600

                # Format last seen string
                last_seen_dt = datetime.fromtimestamp(link["last_seen"])
                last_seen_str = last_seen_dt.strftime("%Y-%m-%d %H:%M:%S")

                # Calculate success rate (using packet count as proxy)
                # Higher packet count suggests more reliable link
                success_rate = min(100, max(10, link["packet_count"] * 10))

                traceroute_link = {
                    "from_node_id": link["source"],
                    "to_node_id": link["target"],
                    "success_rate": success_rate,
                    "avg_snr": link.get("avg_snr"),
                    "avg_rssi": link.get("avg_snr", 0) - 10
                    if link.get("avg_snr")
                    else None,  # Rough conversion
                    "age_hours": round(age_hours, 2),
                    "last_seen_str": last_seen_str,
                    "is_bidirectional": True,  # Network graph links are bidirectional by design
                    "total_hops_seen": link["packet_count"],
                    "last_packet_id": link.get("last_packet_id"),
                }

                traceroute_links.append(traceroute_link)

            logger.info(f"Generated {len(traceroute_links)} traceroute links")
            return traceroute_links

        except Exception as e:
            logger.error(f"Error getting traceroute links: {e}")
            return []

    @staticmethod
    def get_node_location_history(
        node_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get location history for a specific node.

        Args:
            node_id: Node ID to get history for
            limit: Maximum number of records to return

        Returns:
            List of location history records with formatted timestamps
        """
        logger.info(f"Getting location history for node {node_id}, limit={limit}")
        return LocationRepository.get_node_location_history(node_id, limit)

    @staticmethod
    def get_location_statistics(
        locations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Get comprehensive location statistics.

        Returns:
            Dictionary containing location statistics and analysis
        """
        logger.info("Calculating location statistics")

        try:
            # Use provided locations list if available to avoid duplicate heavy queries
            if locations is None:
                locations = LocationRepository.get_node_locations()

            if not locations:
                return {
                    "total_nodes_with_location": 0,
                    "nodes_with_location": 0,  # Alias for template compatibility
                    "recent_nodes_with_location": 0,
                    "total_position_packets": 0,
                    "recent_position_packets": 0,
                    "coverage_area": None,
                    "geographic_center": None,
                    "location_freshness": {},
                    "elevation_stats": {},
                }

            # Basic counts
            total_with_location = len(locations)

            # Count recent nodes (last 24 hours)
            current_time = datetime.now().timestamp()
            twenty_four_hours_ago = current_time - (24 * 3600)
            recent_nodes = [
                loc for loc in locations if loc["timestamp"] >= twenty_four_hours_ago
            ]
            recent_nodes_count = len(recent_nodes)

            # Get position packet statistics from database
            from ..database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            # Total position packets
            cursor.execute("""
                SELECT COUNT(*) as total_count
                FROM packet_history
                WHERE portnum = 3  -- POSITION_APP
                AND raw_payload IS NOT NULL
            """)
            total_position_packets = cursor.fetchone()["total_count"]

            # Recent position packets (last 24 hours)
            cursor.execute(
                """
                SELECT COUNT(*) as recent_count
                FROM packet_history
                WHERE portnum = 3  -- POSITION_APP
                AND raw_payload IS NOT NULL
                AND timestamp > ?
            """,
                (twenty_four_hours_ago,),
            )
            recent_position_packets = cursor.fetchone()["recent_count"]

            conn.close()

            # Calculate geographic boundaries and center
            lats = [loc["latitude"] for loc in locations]
            lons = [loc["longitude"] for loc in locations]
            alts = [
                loc["altitude"] for loc in locations if loc.get("altitude") is not None
            ]

            min_lat, max_lat = min(lats), max(lats)
            min_lon, max_lon = min(lons), max(lons)
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2

            # Calculate coverage area using bounding box approximation
            coverage_area_km2 = LocationService._calculate_coverage_area(
                min_lat, max_lat, min_lon, max_lon
            )

            # Location freshness analysis
            now = datetime.now(UTC).timestamp()
            freshness_stats = LocationService._analyze_location_freshness(
                locations, now
            )

            # Elevation statistics
            elevation_stats = {}
            if alts:
                elevation_stats = {
                    "min_elevation": min(alts),
                    "max_elevation": max(alts),
                    "avg_elevation": sum(alts) / len(alts),
                    "nodes_with_elevation": len(alts),
                    "elevation_range": max(alts) - min(alts),
                }

            # Calculate distances between nodes for density analysis
            density_stats = LocationService._calculate_density_statistics(locations)

            result = {
                "total_nodes_with_location": total_with_location,
                "nodes_with_location": total_with_location,  # Alias for template compatibility
                "recent_nodes_with_location": recent_nodes_count,
                "total_position_packets": total_position_packets,
                "recent_position_packets": recent_position_packets,
                "coverage_area": {
                    "bounding_box": {
                        "min_lat": min_lat,
                        "max_lat": max_lat,
                        "min_lon": min_lon,
                        "max_lon": max_lon,
                    },
                    "center": {"latitude": center_lat, "longitude": center_lon},
                    "area_km2": round(coverage_area_km2, 2),
                },
                "location_freshness": freshness_stats,
                "elevation_stats": elevation_stats,
                "density_stats": density_stats,
            }

            logger.info(
                f"Location statistics calculated for {total_with_location} nodes ({recent_nodes_count} recent)"
            )
            return result

        except Exception as e:
            logger.error(f"Error calculating location statistics: {e}")
            raise

    @staticmethod
    def get_node_hop_distances() -> list[dict[str, Any]]:
        """
        Calculate distances between neighboring nodes based on location data.

        Returns:
            List of node pairs with calculated distances
        """
        logger.info("Calculating hop distances between nodes")

        try:
            locations = LocationService.get_node_locations()

            if len(locations) < 2:
                return []

            # Calculate distances between all pairs
            distances = []

            for i, loc1 in enumerate(locations):
                for _j, loc2 in enumerate(locations[i + 1 :], i + 1):
                    distance_km = LocationService.calculate_haversine_distance(
                        loc1["latitude"],
                        loc1["longitude"],
                        loc2["latitude"],
                        loc2["longitude"],
                    )

                    # Only include reasonable hop distances (< 50km for mesh networks)
                    if distance_km <= 50:
                        distances.append(
                            {
                                "node1_id": loc1["node_id"],
                                "node1_name": loc1["display_name"],
                                "node2_id": loc2["node_id"],
                                "node2_name": loc2["display_name"],
                                "distance_km": round(distance_km, 2),
                                "distance_meters": round(distance_km * 1000, 0),
                                "node1_location": {
                                    "latitude": loc1["latitude"],
                                    "longitude": loc1["longitude"],
                                    "altitude": loc1.get("altitude"),
                                },
                                "node2_location": {
                                    "latitude": loc2["latitude"],
                                    "longitude": loc2["longitude"],
                                    "altitude": loc2.get("altitude"),
                                },
                            }
                        )

            # Sort by distance
            distances.sort(key=lambda x: x["distance_km"])

            logger.info(f"Calculated {len(distances)} potential hop distances")
            return distances

        except Exception as e:
            logger.error(f"Error calculating hop distances: {e}")
            raise

    @staticmethod
    def get_node_neighbors(
        node_id: int, max_distance_km: float = 10.0
    ) -> list[dict[str, Any]]:
        """
        Find neighboring nodes within a certain distance.

        Args:
            node_id: Target node ID
            max_distance_km: Maximum distance in kilometers

        Returns:
            List of neighboring nodes with distances
        """
        logger.info(f"Finding neighbors for node {node_id} within {max_distance_km}km")

        try:
            locations = LocationService.get_node_locations()

            # Find target node location
            target_location = None
            for loc in locations:
                if loc["node_id"] == node_id:
                    target_location = loc
                    break

            if not target_location:
                logger.warning(f"No location found for node {node_id}")
                return []

            # Find neighbors within distance
            neighbors = []

            for loc in locations:
                if loc["node_id"] == node_id:
                    continue  # Skip self

                distance_km = LocationService.calculate_haversine_distance(
                    target_location["latitude"],
                    target_location["longitude"],
                    loc["latitude"],
                    loc["longitude"],
                )

                if distance_km <= max_distance_km:
                    neighbors.append(
                        {
                            "node_id": loc["node_id"],
                            "display_name": loc["display_name"],
                            "distance_km": round(distance_km, 2),
                            "distance_meters": round(distance_km * 1000, 0),
                            "location": {
                                "latitude": loc["latitude"],
                                "longitude": loc["longitude"],
                                "altitude": loc.get("altitude"),
                            },
                            "hw_model": loc.get("hw_model"),
                            "last_updated": loc.get("timestamp"),
                        }
                    )

            # Sort by distance
            neighbors.sort(key=lambda x: x["distance_km"])

            logger.info(f"Found {len(neighbors)} neighbors for node {node_id}")
            return neighbors

        except Exception as e:
            logger.error(f"Error finding neighbors for node {node_id}: {e}")
            raise

    @staticmethod
    def calculate_haversine_distance(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """
        Calculate the great circle distance between two points using the Haversine formula.

        Args:
            lat1, lon1: Latitude and longitude of first point
            lat2, lon2: Latitude and longitude of second point

        Returns:
            Distance in kilometers
        """
        # Earth's radius in kilometers
        R = 6371.0

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

    @staticmethod
    def _calculate_coverage_area(
        min_lat: float, max_lat: float, min_lon: float, max_lon: float
    ) -> float:
        """Calculate approximate coverage area using bounding box."""
        # Calculate distances for the bounding box
        lat_distance = LocationService.calculate_haversine_distance(
            min_lat, min_lon, max_lat, min_lon
        )
        lon_distance = LocationService.calculate_haversine_distance(
            min_lat, min_lon, min_lat, max_lon
        )

        # Approximate area (not exact due to Earth's curvature, but good enough)
        area_km2 = lat_distance * lon_distance
        return area_km2

    @staticmethod
    def _analyze_location_freshness(
        locations: list[dict], current_timestamp: float
    ) -> dict[str, Any]:
        """Analyze how fresh/recent the location data is."""
        if not locations:
            return {}

        # Categorize by age
        age_categories = {
            "very_fresh": 0,  # < 1 hour
            "fresh": 0,  # < 1 day
            "recent": 0,  # < 1 week
            "old": 0,  # < 1 month
            "very_old": 0,  # >= 1 month
        }

        ages = []

        for loc in locations:
            if loc.get("timestamp"):
                age_seconds = current_timestamp - loc["timestamp"]
                ages.append(age_seconds)

                age_hours = age_seconds / 3600
                age_days = age_hours / 24

                if age_hours < 1:
                    age_categories["very_fresh"] += 1
                elif age_days < 1:
                    age_categories["fresh"] += 1
                elif age_days < 7:
                    age_categories["recent"] += 1
                elif age_days < 30:
                    age_categories["old"] += 1
                else:
                    age_categories["very_old"] += 1

        # Calculate statistics
        avg_age_seconds = sum(ages) / len(ages) if ages else 0
        avg_age_days = avg_age_seconds / (24 * 3600)

        return {
            "categories": age_categories,
            "average_age_days": round(avg_age_days, 2),
            "oldest_location_days": round(max(ages) / (24 * 3600), 2) if ages else 0,
            "newest_location_days": round(min(ages) / (24 * 3600), 2) if ages else 0,
        }

    @staticmethod
    def _calculate_density_statistics(locations: list[dict]) -> dict[str, Any]:
        """Calculate node density statistics."""
        if len(locations) < 2:
            return {"node_density_per_km2": 0, "average_node_separation_km": 0}

        # Calculate all pairwise distances
        distances = []

        for i, loc1 in enumerate(locations):
            for _j, loc2 in enumerate(locations[i + 1 :], i + 1):
                distance = LocationService.calculate_haversine_distance(
                    loc1["latitude"],
                    loc1["longitude"],
                    loc2["latitude"],
                    loc2["longitude"],
                )
                distances.append(distance)

        # Calculate statistics
        avg_separation = sum(distances) / len(distances) if distances else 0
        min_separation = min(distances) if distances else 0
        max_separation = max(distances) if distances else 0

        # Estimate density (very rough approximation)
        # Calculate coverage area and divide by number of nodes
        lats = [loc["latitude"] for loc in locations]
        lons = [loc["longitude"] for loc in locations]

        coverage_area = LocationService._calculate_coverage_area(
            min(lats), max(lats), min(lons), max(lons)
        )

        density = len(locations) / coverage_area if coverage_area > 0 else 0

        return {
            "node_density_per_km2": round(density, 4),
            "average_node_separation_km": round(avg_separation, 2),
            "min_node_separation_km": round(min_separation, 2),
            "max_node_separation_km": round(max_separation, 2),
            "total_node_pairs": len(distances),
        }
