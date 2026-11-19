"""
Traceroute Service - Business logic for traceroute analysis and operations.

This service provides comprehensive traceroute analysis functionality including:
- Traceroute data retrieval with pagination and filtering
- Route pattern analysis
- Node-specific traceroute statistics
- Route performance analysis
"""

import logging
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from ..database.connection import get_db_connection
from ..database.repositories import (
    TracerouteRepository,
)
from ..models.traceroute import (
    TraceroutePacket,  # Use the correct TraceroutePacket class
)
from ..services.location_service import LocationService
from ..utils.node_utils import get_bulk_node_names
from ..utils.signal_quality import is_plausible_traceroute_snr
from ..utils.traceroute_utils import parse_traceroute_payload

logger = logging.getLogger(__name__)

_NETWORK_GRAPH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NETWORK_GRAPH_CACHE_TTL_SECONDS = 60
_NETWORK_GRAPH_CACHE_MAX_ENTRIES = 32

# Default cap on traceroute packets analyzed per network graph build. The graph
# advertises a multi-day window (e.g. 168h for the map), so this must be large
# enough that the newest N packets still span that window; on busy brokers a
# low cap silently shrinks the analysis to the last few hours and older RF
# links drop off the map. ~20k packets parse in a couple of seconds.
DEFAULT_GRAPH_PACKET_LIMIT = 20000


def _network_graph_cache_key(
    hours: int,
    min_snr: float,
    include_indirect: bool,
    limit_packets: int,
    filters: dict[str, Any] | None,
) -> str:
    return repr(
        (
            hours,
            min_snr,
            include_indirect,
            limit_packets,
            sorted((filters or {}).items()),
        )
    )


def _copy_network_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "nodes": [node.copy() for node in payload.get("nodes", [])],
        "links": [link.copy() for link in payload.get("links", [])],
        "indirect_connections": [
            connection.copy() for connection in payload.get("indirect_connections", [])
        ],
        "stats": payload.get("stats", {}).copy(),
        "metadata": payload.get("metadata", {}).copy(),
    }


def _prune_network_graph_cache(now: float) -> None:
    expired_keys = [
        key
        for key, (cached_at, _) in _NETWORK_GRAPH_CACHE.items()
        if now - cached_at > _NETWORK_GRAPH_CACHE_TTL_SECONDS
    ]
    for key in expired_keys:
        _NETWORK_GRAPH_CACHE.pop(key, None)

    overflow = len(_NETWORK_GRAPH_CACHE) - _NETWORK_GRAPH_CACHE_MAX_ENTRIES
    if overflow > 0:
        oldest_keys = sorted(_NETWORK_GRAPH_CACHE.items(), key=lambda item: item[1][0])[
            :overflow
        ]
        for key, _ in oldest_keys:
            _NETWORK_GRAPH_CACHE.pop(key, None)


class TracerouteService:
    """Service for traceroute analysis and management."""

    @staticmethod
    def get_traceroutes(
        page: int = 1,
        per_page: int = 50,
        gateway_id: str | None = None,
        from_node: int | None = None,
        to_node: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """
        Get paginated traceroute data with optional filtering.

        Args:
            page: Page number (1-based)
            per_page: Items per page
            gateway_id: Filter by gateway ID
            from_node: Filter by source node
            to_node: Filter by destination node
            search: Search term for filtering

        Returns:
            Dictionary with traceroute data and pagination info
        """
        logger.info(
            f"Getting traceroutes: page={page}, per_page={per_page}, "
            f"gateway_id={gateway_id}, from_node={from_node}, to_node={to_node}, search={search}"
        )

        try:
            # Build filters (allow heterogeneous types)
            filters: dict[str, Any] = {}
            if gateway_id:
                filters["gateway_id"] = gateway_id
            if from_node:
                filters["from_node"] = from_node
            if to_node:
                filters["to_node"] = to_node

            # Convert page to offset
            offset = (page - 1) * per_page

            # Get data from repository
            result = TracerouteRepository.get_traceroute_packets(
                limit=per_page, offset=offset, filters=filters, search=search
            )

            # Enhance with business logic
            enhanced_traceroutes = []
            for tr in result["packets"]:
                # Create TraceroutePacket for enhanced analysis
                tr_packet = TraceroutePacket(packet_data=tr, resolve_names=True)

                # Add enhanced fields
                enhanced_tr = tr.copy()
                enhanced_tr.update(
                    {
                        "has_return_path": tr_packet.has_return_path(),
                        "is_complete": tr_packet.is_complete(),
                        "display_path": tr_packet.format_path_display("display"),
                        "total_hops": tr_packet.forward_path.total_hops,
                        "rf_hops": len(tr_packet.get_rf_hops()),
                    }
                )
                enhanced_traceroutes.append(enhanced_tr)

            return {
                "traceroutes": enhanced_traceroutes,
                "total_count": result["total_count"],
                "page": page,
                "per_page": per_page,
                "total_pages": (result["total_count"] + per_page - 1) // per_page,
            }

        except Exception as e:
            logger.error(f"Error getting traceroutes: {e}")
            raise

    @staticmethod
    def get_traceroute_analysis(hours: int = 24) -> dict[str, Any]:
        """
        Get comprehensive traceroute analysis for the specified time period.

        Args:
            hours: Number of hours to analyze

        Returns:
            Dictionary with analysis data
        """
        logger.info(f"Getting traceroute analysis for {hours} hours")

        try:
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)

            filters = {
                "start_time": start_time.timestamp(),
                "end_time": end_time.timestamp(),
            }

            # Get raw traceroute data
            result = TracerouteRepository.get_traceroute_packets(
                limit=1000,  # Large limit for analysis
                filters=filters,
            )

            # Analyze the data
            total_traceroutes = len(result["packets"])
            successful_traceroutes = 0
            traceroutes_with_return = 0
            route_lengths = []
            unique_routes = set()
            node_participation: dict[int, int] = {}

            for tr in result["packets"]:
                if tr["processed_successfully"]:
                    successful_traceroutes += 1

                    # Parse route data
                    if tr["raw_payload"]:
                        route_data = parse_traceroute_payload(tr["raw_payload"])

                        if route_data["route_back"]:
                            traceroutes_with_return += 1

                        route_length = len(route_data["route_nodes"])
                        route_lengths.append(route_length)

                        # Track unique routes
                        route_key = (
                            tr["from_node_id"],
                            tr["to_node_id"],
                            tuple(route_data["route_nodes"]),
                        )
                        unique_routes.add(route_key)

                        # Track node participation
                        for node_id in (
                            [tr["from_node_id"]]
                            + route_data["route_nodes"]
                            + [tr["to_node_id"]]
                        ):
                            if node_id:
                                node_participation[node_id] = (
                                    node_participation.get(node_id, 0) + 1
                                )

            # Calculate statistics
            success_rate = (
                (successful_traceroutes / total_traceroutes * 100)
                if total_traceroutes > 0
                else 0
            )
            return_path_rate = (
                (traceroutes_with_return / successful_traceroutes * 100)
                if successful_traceroutes > 0
                else 0
            )

            avg_route_length = (
                sum(route_lengths) / len(route_lengths) if route_lengths else 0
            )

            # Get top participating nodes
            top_nodes = sorted(
                node_participation.items(), key=lambda x: x[1], reverse=True
            )[:10]
            top_node_names = get_bulk_node_names([node_id for node_id, _ in top_nodes])

            top_nodes_with_names = [
                {
                    "node_id": node_id,
                    "node_name": top_node_names.get(node_id, f"!{node_id:08x}"),
                    "participation_count": count,
                }
                for node_id, count in top_nodes
            ]

            return {
                "time_period_hours": hours,
                "total_traceroutes": total_traceroutes,
                "successful_traceroutes": successful_traceroutes,
                "success_rate": round(success_rate, 1),
                "traceroutes_with_return": traceroutes_with_return,
                "return_path_rate": round(return_path_rate, 1),
                "unique_routes": len(unique_routes),
                "avg_route_length": round(avg_route_length, 1),
                "top_participating_nodes": top_nodes_with_names,
            }

        except Exception as e:
            logger.error(f"Error in traceroute analysis: {e}")
            raise

    @staticmethod
    def get_route_patterns(limit: int = 50) -> dict[str, Any]:
        """
        Analyze common route patterns in the mesh network.

        Args:
            limit: Maximum number of patterns to return

        Returns:
            Dictionary with route pattern analysis
        """
        logger.info(f"Getting route patterns (limit={limit})")

        try:
            # Get recent successful traceroutes
            filters = {"processed_successfully_only": True}
            result = TracerouteRepository.get_traceroute_packets(
                limit=1000,  # Analyze more data
                filters=filters,
            )

            # Analyze patterns
            route_patterns: dict[
                tuple[tuple[int, int], tuple[int, ...]], dict[str, Any]
            ] = {}
            directional_patterns: dict[tuple[int, int, tuple[int, ...]], int] = {}

            for tr in result["packets"]:
                if tr["raw_payload"] and tr["processed_successfully"]:
                    route_data = parse_traceroute_payload(tr["raw_payload"])

                    # Create pattern key (normalized)
                    route_nodes = tuple(route_data["route_nodes"])
                    if route_nodes:
                        # Bidirectional pattern (normalized by sorting endpoints)
                        endpoints = tuple(
                            sorted([tr["from_node_id"], tr["to_node_id"]])
                        )
                        pattern_key = (endpoints, route_nodes)

                        if pattern_key not in route_patterns:
                            route_patterns[pattern_key] = {
                                "count": 0,
                                "endpoints": endpoints,
                                "route_nodes": route_nodes,
                                "avg_success_rate": 0,
                                "examples": [],
                            }

                        route_patterns[pattern_key]["count"] += 1
                        if len(route_patterns[pattern_key]["examples"]) < 3:
                            route_patterns[pattern_key]["examples"].append(
                                {
                                    "packet_id": tr["id"],
                                    "timestamp": tr["timestamp"],
                                    "from_node": tr["from_node_id"],
                                    "to_node": tr["to_node_id"],
                                }
                            )

                        # Directional pattern
                        dir_key = (tr["from_node_id"], tr["to_node_id"], route_nodes)
                        directional_patterns[dir_key] = (
                            directional_patterns.get(dir_key, 0) + 1
                        )

            # Sort patterns by frequency
            sorted_patterns = sorted(
                route_patterns.items(), key=lambda x: x[1]["count"], reverse=True
            )[:limit]

            # Enhance with node names
            all_node_ids: set[int] = set()
            for (endpoints, route_nodes), _data in sorted_patterns:
                all_node_ids.update(endpoints)
                all_node_ids.update(route_nodes)

            node_names = get_bulk_node_names(list(all_node_ids))

            enhanced_patterns = []
            for (endpoints, route_nodes), data in sorted_patterns:
                pattern = data.copy()
                pattern["endpoints_names"] = [
                    node_names.get(node_id, f"!{node_id:08x}") for node_id in endpoints
                ]
                pattern["route_nodes_names"] = [
                    node_names.get(node_id, f"!{node_id:08x}")
                    for node_id in route_nodes
                ]
                pattern["route_display"] = " → ".join(pattern["route_nodes_names"])
                enhanced_patterns.append(pattern)

            return {
                "patterns": enhanced_patterns,
                "total_patterns": len(route_patterns),
                "analyzed_traceroutes": len(result["packets"]),
            }

        except Exception as e:
            logger.error(f"Error getting route patterns: {e}")
            raise

    @staticmethod
    def get_node_traceroute_stats(node_id: int) -> dict[str, Any]:
        """
        Get traceroute statistics for a specific node.

        Args:
            node_id: Node ID to analyze

        Returns:
            Dictionary with node's traceroute statistics
        """
        logger.info(f"Getting traceroute stats for node {node_id}")

        try:
            # Get traceroutes involving this node as source or destination
            source_filters = {"from_node": node_id}
            dest_filters = {"to_node": node_id}

            source_result = TracerouteRepository.get_traceroute_packets(
                limit=1000, filters=source_filters
            )
            dest_result = TracerouteRepository.get_traceroute_packets(
                limit=1000, filters=dest_filters
            )

            # Analyze as source
            source_total = len(source_result["packets"])
            source_successful = sum(
                1 for tr in source_result["packets"] if tr["processed_successfully"]
            )

            # Analyze as destination
            dest_total = len(dest_result["packets"])
            dest_successful = sum(
                1 for tr in dest_result["packets"] if tr["processed_successfully"]
            )

            # Get node name
            node_names = get_bulk_node_names([node_id])
            node_name = node_names.get(node_id, f"!{node_id:08x}")

            # Analyze route participation (as intermediate hop)
            # This requires checking all traceroutes for this node in route_nodes
            participation_count = 0
            all_traceroutes = TracerouteRepository.get_traceroute_packets(
                limit=1000, filters={"processed_successfully_only": True}
            )

            for tr in all_traceroutes["packets"]:
                if tr["raw_payload"]:
                    route_data = parse_traceroute_payload(tr["raw_payload"])
                    if node_id in route_data.get("route_nodes", []):
                        participation_count += 1

            return {
                "node_id": node_id,
                "node_name": node_name,
                "as_source": {
                    "total": source_total,
                    "successful": source_successful,
                    "success_rate": (source_successful / source_total * 100)
                    if source_total > 0
                    else 0,
                },
                "as_destination": {
                    "total": dest_total,
                    "successful": dest_successful,
                    "success_rate": (dest_successful / dest_total * 100)
                    if dest_total > 0
                    else 0,
                },
                "as_intermediate_hop": {"participation_count": participation_count},
                "total_involvement": source_total + dest_total + participation_count,
            }

        except Exception as e:
            logger.error(f"Error getting node traceroute stats: {e}")
            raise

    @staticmethod
    def get_longest_links_analysis(
        min_distance_km: float = 1.0, min_snr: float = -20.0, max_results: int = 100
    ) -> dict[str, Any]:
        """Analyze the longest RF links in the mesh network.

        Served from the capture-maintained ``link_day_rollup`` /
        ``route_day_rollup`` tables (see ``malla.capture_rollups``): per-pair
        hop aggregates folded per completed UTC day, so the endpoint is two
        grouped scans over a tiny table plus one position join - no packet
        re-parsing and no per-node location queries.

        Semantics (approved sign-off): hop distances use each endpoint's
        *latest* position (``node_latest_position``), not the position at
        hop time; position staleness is driven by
        ``node_latest_position.last_seen`` via the existing age_warning
        mechanism. Two bounded approximations versus the legacy per-hop loop:

        - the trailing 7d window is evaluated on whole UTC days
        (``day >= date(start)``), so the window edge fuzzes by up to 24h;
        - ``min_snr`` applies to the pair's best recorded hop SNR (direct
        links) / mean path SNR (indirect links) instead of per-hop.

        Distances between nodes without a usable position are skipped (direct)
        or contribute zero (indirect), mirroring the legacy
        ``hop.distance_km`` handling.
        """
        start_time = time.time()
        logger.info(
            f"Getting longest links analysis: min_distance={min_distance_km}km, "
            f"min_snr={min_snr}dB, max_results={max_results}"
        )

        try:
            since = time.time() - 7 * 86400
            day_floor = datetime.fromtimestamp(since, UTC).date().isoformat()

            conn = get_db_connection()
            try:
                link_rows = conn.execute(
                    """
                    SELECT node_a, node_b,
                           SUM(packet_count) AS traceroute_count,
                           SUM(snr_sum) / NULLIF(SUM(snr_count), 0) AS avg_snr,
                           MAX(snr_max) AS best_snr,
                           MAX(last_seen) AS last_seen,
                           MAX(COALESCE(last_packet_id, 0)) AS packet_id
                    FROM link_day_rollup
                    WHERE day >= ?
                    GROUP BY node_a, node_b
                    HAVING SUM(snr_count) > 0
                    """,
                    (day_floor,),
                ).fetchall()

                path_rows = conn.execute(
                    """
                    SELECT end_a, end_b,
                           SUM(path_count) AS path_count,
                           SUM(hop_count_sum) AS hop_count_sum,
                           SUM(snr_avg_sum) / NULLIF(SUM(path_count), 0) AS avg_snr,
                           MAX(last_seen) AS last_seen,
                           MAX(COALESCE(last_packet_id, 0)) AS packet_id,
                           last_route
                    FROM route_day_rollup
                    WHERE day >= ?
                    GROUP BY end_a, end_b
                    """,
                    (day_floor,),
                ).fetchall()

                position_rows = conn.execute(
                    "SELECT node_id, latitude, longitude FROM node_latest_position"
                ).fetchall()
            finally:
                conn.close()

            positions: dict[int, tuple[float, float]] = {}
            for row in position_rows:
                latitude, longitude = row["latitude"], row["longitude"]
                if (
                    latitude is not None
                    and longitude is not None
                    and latitude != 0
                    and longitude != 0
                ):
                    positions[row["node_id"]] = (latitude, longitude)

            link_node_ids = {
                node_id
                for row in link_rows
                for node_id in (row["node_a"], row["node_b"])
            }
            path_node_ids = {
                node_id for row in path_rows for node_id in (row["end_a"], row["end_b"])
            }
            route_chain_ids: set[int] = set()
            for row in path_rows:
                if row["last_route"]:
                    route_chain_ids.update(
                        int(part) for part in str(row["last_route"]).split(",")
                    )
            names = get_bulk_node_names(
                list(link_node_ids | path_node_ids | route_chain_ids)
            )

            def node_name(node_id: int) -> str:
                return names.get(node_id, f"!{node_id:08x}")

            analyzed_links: list[dict[str, Any]] = []
            for row in link_rows:
                node_a, node_b = int(row["node_a"]), int(row["node_b"])
                best_snr = row["best_snr"]
                if best_snr is None or best_snr < min_snr:
                    continue
                endpoint_a = positions.get(node_a)
                endpoint_b = positions.get(node_b)
                if endpoint_a is None or endpoint_b is None:
                    continue  # legacy: hops without a distance never counted
                distance_km = LocationService.calculate_haversine_distance(
                    endpoint_a[0], endpoint_a[1], endpoint_b[0], endpoint_b[1]
                )
                if distance_km < min_distance_km:
                    continue

                packet_id = int(row["packet_id"]) if row["packet_id"] else None
                analyzed_links.append(
                    {
                        "from_node_id": node_a,
                        "to_node_id": node_b,
                        "from_node_name": node_name(node_a),
                        "to_node_name": node_name(node_b),
                        "distance_km": round(distance_km, 2),
                        "avg_snr": round(row["avg_snr"], 1)
                        if row["avg_snr"] is not None
                        else None,
                        "traceroute_count": int(row["traceroute_count"]),
                        "recent_packets": [packet_id] if packet_id else [],
                        "packet_id": packet_id,
                        "packet_url": f"/packet/{packet_id}"
                        if packet_id is not None
                        else None,
                        "last_seen": row["last_seen"],
                    }
                )

            analyzed_links.sort(key=lambda link: link["distance_km"], reverse=True)
            analyzed_links = analyzed_links[:max_results]

            def path_distance_km(row: Any) -> float | None:
                chain = str(row["last_route"] or "")
                node_ids = [part for part in chain.split(",") if part]
                if len(node_ids) < 2:
                    return None
                total = 0.0
                for left, right in zip(node_ids, node_ids[1:], strict=False):
                    try:
                        left_pos = positions.get(int(left))
                        right_pos = positions.get(int(right))
                    except ValueError:
                        return None
                    if left_pos is None or right_pos is None:
                        continue  # legacy: unresolvable hops contribute zero
                    total += LocationService.calculate_haversine_distance(
                        left_pos[0], left_pos[1], right_pos[0], right_pos[1]
                    )
                return total

            analyzed_paths: list[dict[str, Any]] = []
            for row in path_rows:
                end_a, end_b = int(row["end_a"]), int(row["end_b"])
                path_count = int(row["path_count"])
                if path_count <= 0:
                    continue
                avg_snr = row["avg_snr"]
                if avg_snr is not None and avg_snr < min_snr:
                    continue
                distance = path_distance_km(row)
                if distance is None:
                    endpoint_a = positions.get(end_a)
                    endpoint_b = positions.get(end_b)
                    if endpoint_a is None or endpoint_b is None:
                        continue
                    distance = LocationService.calculate_haversine_distance(
                        endpoint_a[0], endpoint_a[1], endpoint_b[0], endpoint_b[1]
                    )
                if distance < min_distance_km:
                    continue

                packet_id = int(row["packet_id"]) if row["packet_id"] else None
                chain = [
                    int(part)
                    for part in str(row["last_route"] or "").split(",")
                    if part
                ]
                analyzed_paths.append(
                    {
                        "from_node_id": end_a,
                        "to_node_id": end_b,
                        "from_node_name": node_name(end_a),
                        "to_node_name": node_name(end_b),
                        "total_distance_km": round(distance, 2),
                        "hop_count": int(round(row["hop_count_sum"] / path_count)),
                        "avg_snr": round(avg_snr, 1) if avg_snr is not None else None,
                        "traceroute_count": path_count,
                        "route_preview": [node_name(node_id) for node_id in chain]
                        if chain
                        else [node_name(end_a), node_name(end_b)],
                        "recent_packets": [packet_id] if packet_id else [],
                        "packet_id": packet_id,
                        "packet_url": f"/packet/{packet_id}"
                        if packet_id is not None
                        else None,
                        "last_seen": row["last_seen"],
                    }
                )

            analyzed_paths.sort(
                key=lambda link: link["total_distance_km"], reverse=True
            )
            analyzed_paths = analyzed_paths[:max_results]

            total_links = len(analyzed_links) + len(analyzed_paths)
            longest_direct = (
                f"{analyzed_links[0]['distance_km']:.2f} km" if analyzed_links else None
            )
            longest_path = (
                f"{analyzed_paths[0]['total_distance_km']:.2f} km"
                if analyzed_paths
                else None
            )

            result_dict = {
                "summary": {
                    "total_links": total_links,
                    "direct_links": len(analyzed_links),
                    "longest_direct": longest_direct,
                    "longest_path": longest_path,
                },
                "direct_links": analyzed_links,
                "indirect_links": analyzed_paths,
                "criteria": {
                    "min_distance_km": min_distance_km,
                    "min_snr": min_snr,
                    "max_results": max_results,
                    "analysis_period_days": 7,
                },
                "cache_stats": {
                    "location_lookups_cached": len(positions),
                },
            }

            logger.info(
                "Longest links from rollups: %d direct, %d indirect in %.3fs",
                len(analyzed_links),
                len(analyzed_paths),
                time.time() - start_time,
            )
            return result_dict

        except Exception as e:
            logger.error(f"Error in longest links analysis: {e}")
            raise

    @staticmethod
    def get_network_graph_data(
        hours: int = 24,
        min_snr: float = -200.0,
        include_indirect: bool = False,
        filters: dict | None = None,
        limit_packets: int = DEFAULT_GRAPH_PACKET_LIMIT,
    ) -> dict[str, Any]:
        """
        Extract RF links from traceroute data to build a network connectivity graph.

        Args:
            hours: Number of hours to analyze (used if no time filters provided)
            min_snr: Minimum SNR threshold for including links
            include_indirect: Whether to include indirect (multi-hop) connections
            filters: Optional filters dict with start_time, end_time, gateway_id, etc.
            limit_packets: Maximum number of packets to analyze

        Returns:
            Dictionary with nodes and links data for graph visualization
        """
        logger.info(
            f"Building network graph data for {hours} hours (min_snr={min_snr}dB)"
        )

        cache_key = _network_graph_cache_key(
            hours=hours,
            min_snr=min_snr,
            include_indirect=include_indirect,
            limit_packets=limit_packets,
            filters=filters,
        )
        now = time.time()
        _prune_network_graph_cache(now)
        cached = _NETWORK_GRAPH_CACHE.get(cache_key)
        if cached and now - cached[0] < _NETWORK_GRAPH_CACHE_TTL_SECONDS:
            logger.debug(
                "Returning cached network graph data for %sh filters=%s",
                hours,
                filters,
            )
            return _copy_network_graph_payload(cached[1])

        try:
            # Build filters for traceroute data
            if filters is None:
                filters = {}

            # Use provided time filters or calculate from hours parameter
            if not filters.get("start_time") and not filters.get("end_time"):
                # Calculate time range from hours parameter
                from datetime import datetime, timedelta

                end_time = datetime.now()
                start_time = end_time - timedelta(hours=hours)

                filters["start_time"] = start_time.timestamp()
                filters["end_time"] = end_time.timestamp()

            # Always filter for successfully processed packets
            filters["processed_successfully_only"] = True

            # Get traceroute data
            packets = TracerouteRepository.get_traceroute_packets_for_graph(
                limit=limit_packets,
                filters=filters,
            )

            # Track nodes and links
            nodes = {}  # node_id -> node_data
            direct_links = {}  # (node1, node2) -> link_data
            indirect_connections = {}  # (node1, node2) -> connection_data

            # Statistics
            stats = {
                "packets_analyzed": len(packets),
                "packets_with_rf_hops": 0,
                "total_rf_hops": 0,
                "links_found": 0,
                "links_filtered_by_snr": 0,
                "links_filtered_due_to_snr_0": 0,
            }

            # Process each traceroute packet
            for tr_data in packets:
                if not tr_data["raw_payload"]:
                    continue

                try:
                    # Create TraceroutePacket object for analysis
                    tr_packet = TraceroutePacket(
                        packet_data=tr_data, resolve_names=False
                    )

                    # Get RF hops (actual radio transmissions)
                    rf_hops = tr_packet.get_rf_hops()
                    if not rf_hops:
                        continue

                    stats["packets_with_rf_hops"] += 1
                    stats["total_rf_hops"] += len(rf_hops)

                    # Process direct RF links
                    for hop in rf_hops:
                        # Filter by SNR - if min_snr is -200, it means "no limit" so only filter missing/garbage values
                        if not is_plausible_traceroute_snr(hop.snr) or (
                            min_snr != -200 and hop.snr < min_snr
                        ):
                            stats["links_filtered_by_snr"] += 1
                            continue
                        # filter 0db links (MQTT or UDP)
                        if hop.snr == 0:
                            stats["links_filtered_due_to_snr_0"] += 1
                            continue
                        if 4294967295 in [hop.from_node_id, hop.to_node_id]:
                            continue
                        # Add nodes to the graph
                        for node_id, node_name in [
                            (hop.from_node_id, hop.from_node_name),
                            (hop.to_node_id, hop.to_node_name),
                        ]:
                            if node_id not in nodes:
                                nodes[node_id] = {
                                    "id": node_id,
                                    "name": node_name or f"!{node_id:08x}",
                                    "packet_count": 0,
                                    "total_snr": 0.0,
                                    "snr_count": 0,
                                    "connections": set(),
                                    "last_seen": tr_data["timestamp"],
                                }

                            # Update node stats
                            nodes[node_id]["packet_count"] += 1
                            if tr_data["timestamp"] > nodes[node_id]["last_seen"]:
                                nodes[node_id]["last_seen"] = tr_data["timestamp"]

                        # Create bidirectional link key (sorted to ensure consistency)
                        link_key = tuple(sorted([hop.from_node_id, hop.to_node_id]))

                        # Add/update direct link
                        if link_key not in direct_links:
                            direct_links[link_key] = {
                                "source": link_key[0],
                                "target": link_key[1],
                                "snr_values": [hop.snr],
                                "packet_count": 1,
                                "last_seen": tr_data["timestamp"],
                                "last_packet_id": tr_data["id"],
                            }
                            stats["links_found"] += 1
                        else:
                            link = direct_links[link_key]
                            link["snr_values"].append(hop.snr)
                            link["packet_count"] += 1
                            if tr_data["timestamp"] > link["last_seen"]:
                                link["last_seen"] = tr_data["timestamp"]
                                link["last_packet_id"] = tr_data["id"]

                        # Track connections for nodes
                        nodes[hop.from_node_id]["connections"].add(hop.to_node_id)
                        nodes[hop.to_node_id]["connections"].add(hop.from_node_id)
                        nodes[hop.from_node_id]["total_snr"] += hop.snr
                        nodes[hop.from_node_id]["snr_count"] += 1

                    # Process indirect connections if requested
                    if include_indirect and len(rf_hops) > 1:
                        # Find endpoints of multi-hop paths
                        first_hop = rf_hops[0]
                        last_hop = rf_hops[-1]

                        # Create indirect connection key
                        indirect_key = tuple(
                            sorted([first_hop.from_node_id, last_hop.to_node_id])
                        )

                        # Only add if it's not already a direct link
                        if indirect_key not in direct_links:
                            if indirect_key not in indirect_connections:
                                path_snrs = [
                                    h.snr
                                    for h in rf_hops
                                    if h.snr and is_plausible_traceroute_snr(h.snr)
                                ]
                                indirect_connections[indirect_key] = {
                                    "source": indirect_key[0],
                                    "target": indirect_key[1],
                                    "hop_count": len(rf_hops),
                                    "path_count": 1,
                                    "avg_snr": (sum(path_snrs) / len(path_snrs))
                                    if path_snrs
                                    else None,
                                    "last_seen": tr_data["timestamp"],
                                    "last_packet_id": tr_data["id"],
                                }
                            else:
                                conn = indirect_connections[indirect_key]
                                conn["path_count"] += 1
                                if tr_data["timestamp"] > conn["last_seen"]:
                                    conn["last_seen"] = tr_data["timestamp"]
                                    conn["last_packet_id"] = tr_data["id"]

                except Exception as e:
                    logger.warning(
                        f"Error processing traceroute packet {tr_data['id']}: {e}"
                    )
                    continue

            node_ids = list(nodes.keys())
            node_names = get_bulk_node_names(node_ids) if node_ids else {}

            for node_id, node_data in nodes.items():
                node_data["name"] = node_names.get(node_id, node_data["name"])

            # Get location data for all nodes in the graph
            # Import here to avoid circular dependencies
            from ..database.repositories import LocationRepository

            logger.info(f"Fetching location data for {len(node_ids)} nodes")

            try:
                locations = LocationRepository.get_node_locations(
                    {"node_ids": node_ids}
                )
                location_map = {loc["node_id"]: loc for loc in locations}
                logger.info(f"Found location data for {len(location_map)} nodes")
            except Exception as e:
                logger.warning(f"Error fetching location data: {e}")
                location_map = {}

            # Process direct links - calculate average SNR and strength
            processed_links = []
            for link_data in direct_links.values():
                avg_snr = sum(link_data["snr_values"]) / len(link_data["snr_values"])

                # Calculate link strength based on SNR and packet count
                # Higher SNR and more packets = stronger link
                strength = min(
                    10,
                    max(1, (avg_snr + 20) / 5 + math.log10(link_data["packet_count"])),
                )

                processed_links.append(
                    {
                        "source": link_data["source"],
                        "target": link_data["target"],
                        "type": "direct",
                        "avg_snr": round(avg_snr, 1),
                        "packet_count": link_data["packet_count"],
                        "strength": round(strength, 1),
                        "last_seen": link_data["last_seen"],
                        "last_packet_id": link_data["last_packet_id"],
                    }
                )

            # Process indirect connections
            processed_indirect = []
            if include_indirect:
                for conn_data in indirect_connections.values():
                    processed_indirect.append(
                        {
                            "source": conn_data["source"],
                            "target": conn_data["target"],
                            "type": "indirect",
                            "hop_count": conn_data["hop_count"],
                            "path_count": conn_data["path_count"],
                            "avg_snr": round(conn_data["avg_snr"], 1)
                            if conn_data["avg_snr"]
                            else None,
                            "strength": min(
                                5,
                                max(
                                    0.5,
                                    conn_data["path_count"] / conn_data["hop_count"],
                                ),
                            ),
                            "last_seen": conn_data["last_seen"],
                            "last_packet_id": conn_data["last_packet_id"],
                        }
                    )

            # Process nodes - calculate average SNR and connectivity, add location data
            processed_nodes = []
            for node_data in nodes.values():
                # Convert set to count for JSON serialization
                node_data["connections"] = len(node_data["connections"])

                # Calculate average SNR for this node
                avg_snr = None
                if node_data["snr_count"] > 0:
                    avg_snr = round(node_data["total_snr"] / node_data["snr_count"], 1)

                # Get location data for this node
                location = location_map.get(node_data["id"])

                node_info = {
                    "id": node_data["id"],
                    "name": node_data["name"],
                    "packet_count": node_data["packet_count"],
                    "connections": node_data["connections"],
                    "avg_snr": avg_snr,
                    "last_seen": node_data["last_seen"],
                    "size": min(
                        20, max(5, math.log10(node_data["packet_count"] + 1) * 3)
                    ),  # Visual size
                }

                # Add location data if available
                if location:
                    node_info["location"] = {
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                        "altitude": location.get("altitude"),
                    }

                processed_nodes.append(node_info)

            result = {
                "nodes": processed_nodes,
                "links": processed_links,
                "indirect_connections": processed_indirect,
                "stats": stats,
                "filters": {
                    "hours": hours,
                    "min_snr": min_snr,
                    "include_indirect": include_indirect,
                },
            }
            _NETWORK_GRAPH_CACHE[cache_key] = (time.time(), result)
            return _copy_network_graph_payload(result)

        except Exception as e:
            logger.error(f"Error building network graph data: {e}")
            raise
