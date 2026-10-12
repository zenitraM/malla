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
from datetime import datetime, timedelta
from typing import Any

from ..database.repositories import (
    LocationRepository,
    TracerouteRepository,
)
from ..database.traceroute_read_repository import (
    get_node_traceroute_statistics,
    get_route_patterns_data,
    get_traceroute_hops_for_graph,
    get_traceroute_hops_for_longest_links,
    route_data_from_row,
)
from ..models.traceroute import (
    TraceroutePacket,  # Use the correct TraceroutePacket class
)
from ..utils.geo_utils import calculate_distance
from ..utils.node_utils import get_bulk_node_names
from ..utils.signal_quality import is_plausible_traceroute_snr

logger = logging.getLogger(__name__)

_NETWORK_GRAPH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NETWORK_GRAPH_CACHE_TTL_SECONDS = 60
_NETWORK_GRAPH_CACHE_MAX_ENTRIES = 32


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


def _rf_hop_qualifies(hop: dict[str, Any], min_snr: float | None = None) -> bool:
    """True when a hop is an evidenced RF link (usable SNR, real endpoints)."""
    snr = hop.get("snr")
    if not is_plausible_traceroute_snr(snr) or snr == 0:
        return False
    if min_snr is not None and min_snr != -200 and snr < min_snr:
        return False
    return 4294967295 not in (hop["from_node_id"], hop["to_node_id"])


def _contiguous_path_segments(
    hops: list[dict[str, Any]],
    qualifies: Any = _rf_hop_qualifies,
) -> list[list[dict[str, Any]]]:
    """Split hops in path order into maximal contiguous runs of qualifying hops.

    A run continues only while each hop starts where the previous one ended.
    Removing a hop from the middle of a route (zero/invalid SNR, weak link)
    must not splice the survivors into a shorter path: for A->B->C->D with
    B->C filtered, A->B and C->D stay two disconnected segments instead of
    aggregating into a bogus A->D path.
    """
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for hop in hops:
        if not qualifies(hop):
            if len(current) > 1:
                segments.append(current)
            current = []
            continue
        if current and hop["from_node_id"] != current[-1]["to_node_id"]:
            if len(current) > 1:
                segments.append(current)
            current = [hop]
        else:
            current.append(hop)
    if len(current) > 1:
        segments.append(current)
    return segments


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

            # Saved JSON arrays make full-window analysis practical without
            # decoding packet payloads during the request.
            result = TracerouteRepository.get_traceroute_packets(
                limit=-1,
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

                    route_data = route_data_from_row(tr)
                    if route_data is not None:

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
    def get_route_patterns(
        limit: int = 50,
        hours: int = 168,
        filters: dict | None = None,
    ) -> dict[str, Any]:
        """
        Analyze common route patterns in the mesh network using materialized routes.

        Args:
            limit: Maximum number of patterns to return
            hours: Hours window for analysis (default 168h / 7 days)
            filters: Optional filters with explicit start_time and end_time

        Returns:
            Dictionary with route pattern analysis
        """
        logger.info(f"Getting route patterns (limit={limit}, hours={hours})")

        try:
            now = datetime.now()
            start_time = (now - timedelta(hours=hours)).timestamp()
            end_time = now.timestamp()
            if filters:
                if filters.get("start_time"):
                    start_time = float(filters["start_time"])
                if filters.get("end_time"):
                    end_time = float(filters["end_time"])

            raw_result = get_route_patterns_data(
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )

            sorted_patterns = raw_result["sorted_patterns"]

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
                "total_patterns": raw_result["total_patterns"],
                "analyzed_traceroutes": raw_result["analyzed_traceroutes"],
                "time_period_hours": hours,
            }

        except Exception as e:
            logger.error(f"Error getting route patterns: {e}")
            raise

    @staticmethod
    def get_node_traceroute_stats(
        node_id: int,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> dict[str, Any]:
        """
        Get traceroute statistics for a specific node.

        Args:
            node_id: Node ID to analyze
            start_time: Optional start timestamp filter
            end_time: Optional end timestamp filter

        Returns:
            Dictionary with node's traceroute statistics
        """
        logger.info(f"Getting traceroute stats for node {node_id}")

        try:
            stats = get_node_traceroute_statistics(
                node_id=node_id,
                start_time=start_time,
                end_time=end_time,
            )
            node_names = get_bulk_node_names([node_id])
            node_name = node_names.get(node_id, f"!{node_id:08x}")
            stats["node_name"] = node_name
            return stats
        except Exception as e:
            logger.error(f"Error getting node traceroute stats: {e}")
            raise

    @staticmethod
    def get_longest_links_analysis(
        min_distance_km: float = 1.0, min_snr: float = -20.0, max_results: int = 100
    ) -> dict[str, Any]:
        """
        Analyze the longest RF links in the mesh network.

        Args:
            min_distance_km: Minimum distance in kilometers to consider
            min_snr: Minimum SNR threshold
            max_results: Maximum number of results to return

        Returns:
            Dictionary with longest links analysis
        """
        start_time = time.time()
        logger.info(
            f"Getting longest links analysis: min_distance={min_distance_km}km, "
            f"min_snr={min_snr}dB, max_results={max_results}"
        )

        try:
            # ------------------------------------------------------------------
            # Fetch RF hops for the last 7 days from materialized traceroute_hops
            # ------------------------------------------------------------------
            fetch_start = time.time()
            end_time = datetime.now()
            start_time_filter = end_time - timedelta(days=7)

            hops = get_traceroute_hops_for_longest_links(
                start_time=start_time_filter.timestamp(),
                end_time=end_time.timestamp(),
            )
            fetch_duration = time.time() - fetch_start
            logger.info(
                f"TIMING: Data fetch took {fetch_duration:.3f}s for {len(hops)} hops"
            )

            # ------------------------------------------------------------------
            # Batch fetch node location history and names
            # ------------------------------------------------------------------
            unique_node_ids: set[int] = set()
            for hop in hops:
                for nid in (hop["from_node_id"], hop["to_node_id"]):
                    if nid and nid != 4294967295:
                        unique_node_ids.add(nid)

            prefetch_start = time.time()
            node_ids_list = list(unique_node_ids)
            location_history_cache = (
                LocationRepository.get_nodes_location_history(
                    node_ids_list, limit_per_node=50
                )
                if node_ids_list
                else {}
            )
            node_names = get_bulk_node_names(node_ids_list) if node_ids_list else {}
            prefetch_duration = time.time() - prefetch_start
            logger.info(
                f"TIMING: Batch pre-fetch took {prefetch_duration:.3f}s for {len(node_ids_list)} nodes"
            )

            # Fast in-memory location lookup
            location_cache: dict[tuple[int, int], dict[str, Any] | None] = {}

            def get_node_loc(node_id: int, target_ts: float) -> dict[str, Any] | None:
                bucket = int(target_ts // 3600)
                memo_key = (node_id, bucket)
                if memo_key in location_cache:
                    return location_cache[memo_key]

                history = location_history_cache.get(node_id)
                if not history:
                    location_cache[memo_key] = None
                    return None

                # Find first location with timestamp <= target_ts (history is newest first)
                best = None
                for loc in history:
                    if loc["timestamp"] <= target_ts:
                        best = loc
                        break
                if best is None:
                    best = history[-1]

                location_cache[memo_key] = best
                return best

            # ------------------------------------------------------------------
            # Group hops by (packet_id, direction) to evaluate direct and indirect paths
            # ------------------------------------------------------------------
            process_start = time.time()
            link_stats: dict[tuple[int, int], dict[str, Any]] = {}
            path_stats: dict[tuple[int, int], dict[str, Any]] = {}

            # Group hops
            hops_by_path: dict[tuple[int, str], list[dict[str, Any]]] = {}
            for hop in hops:
                path_key = (hop["packet_id"], hop.get("direction", "forward"))
                if path_key not in hops_by_path:
                    hops_by_path[path_key] = []
                hops_by_path[path_key].append(hop)

            for (packet_id, _direction), path_hops in hops_by_path.items():
                for hop in path_hops:
                    from_id = hop["from_node_id"]
                    to_id = hop["to_node_id"]
                    ts = hop["timestamp"]

                    dist: float | None = None
                    if from_id != 4294967295 and to_id != 4294967295:
                        loc_from = get_node_loc(from_id, ts)
                        loc_to = get_node_loc(to_id, ts)
                        if (
                            loc_from
                            and loc_to
                            and loc_from.get("latitude") is not None
                            and loc_from.get("longitude") is not None
                            and loc_to.get("latitude") is not None
                            and loc_to.get("longitude") is not None
                        ):
                            dist = calculate_distance(
                                loc_from["latitude"],
                                loc_from["longitude"],
                                loc_to["latitude"],
                                loc_to["longitude"],
                            )
                    hop["_distance_km"] = dist

                    # Direct link processing
                    snr = hop["snr"]
                    if (
                        dist is not None
                        and dist >= min_distance_km
                        and is_plausible_traceroute_snr(snr)
                        and snr != 0
                        and snr >= min_snr
                    ):
                        node1_id, node2_id = sorted((from_id, to_id))
                        key: tuple[int, int] = (node1_id, node2_id)
                        from_name = node_names.get(node1_id, f"!{node1_id:08x}")
                        to_name = node_names.get(node2_id, f"!{node2_id:08x}")

                        if key not in link_stats:
                            link_stats[key] = {
                                "from_node_name": from_name,
                                "to_node_name": to_name,
                                "total_distance": 0.0,
                                "total_snr": 0.0,
                                "traceroute_count": 0,
                                "max_distance": 0.0,
                                "best_snr": None,
                                "recent_packets": [],
                                "last_seen": ts,
                            }
                        stats_dict = link_stats[key]
                        stats_dict["traceroute_count"] += 1
                        stats_dict["total_distance"] += dist
                        stats_dict["total_snr"] += snr
                        stats_dict["max_distance"] = max(stats_dict["max_distance"], dist)
                        if stats_dict["best_snr"] is None or snr > stats_dict["best_snr"]:
                            stats_dict["best_snr"] = snr
                        if ts > stats_dict["last_seen"]:
                            stats_dict["last_seen"] = ts
                        if packet_id not in stats_dict["recent_packets"]:
                            stats_dict["recent_packets"].append(packet_id)
                            if len(stats_dict["recent_packets"]) > 5:
                                stats_dict["recent_packets"].pop(0)

                # Indirect path processing: only contiguous runs of qualifying
                # hops are real multi-hop paths. When a middle hop fails the
                # filters, the remaining hops are disconnected segments whose
                # endpoints and distance sums must not be joined.
                for segment in _contiguous_path_segments(path_hops):
                    segment_distances = [h["_distance_km"] for h in segment]
                    if any(d is None for d in segment_distances):
                        continue
                    path_distance_km = sum(segment_distances)
                    if path_distance_km < min_distance_km:
                        continue
                    avg_path_snr = sum(h["snr"] for h in segment) / len(segment)
                    if avg_path_snr < min_snr:
                        continue
                    from_id_path = segment[0]["from_node_id"]
                    to_id_path = segment[-1]["to_node_id"]
                    p_key = (from_id_path, to_id_path)
                    if p_key not in path_stats:
                        from_name = node_names.get(from_id_path, f"!{from_id_path:08x}")
                        to_name = node_names.get(to_id_path, f"!{to_id_path:08x}")
                        route_preview = [
                            node_names.get(h["from_node_id"], f"!{h['from_node_id']:08x}")
                            for h in segment
                        ] + [node_names.get(to_id_path, f"!{to_id_path:08x}")]
                        path_stats[p_key] = {
                            "from_node_name": from_name,
                            "to_node_name": to_name,
                            "total_distance": 0.0,
                            "total_snr": 0.0,
                            "traceroute_count": 0,
                            "hop_count_total": 0,
                            "recent_packets": [],
                            "route_preview": route_preview,
                            "max_distance": 0.0,
                            "last_seen": segment[0]["timestamp"],
                        }
                    pstats = path_stats[p_key]
                    pstats["traceroute_count"] += 1
                    pstats["total_distance"] += path_distance_km
                    pstats["hop_count_total"] += len(segment)
                    pstats["total_snr"] += avg_path_snr
                    pstats["max_distance"] = max(pstats["max_distance"], path_distance_km)
                    ts = segment[0]["timestamp"]
                    if ts > pstats["last_seen"]:
                        pstats["last_seen"] = ts
                    if packet_id not in pstats["recent_packets"]:
                        pstats["recent_packets"].append(packet_id)
                        if len(pstats["recent_packets"]) > 5:
                            pstats["recent_packets"].pop(0)

            process_duration = time.time() - process_start
            logger.info(f"TIMING: Hop processing took {process_duration:.3f}s")

            # ------------------------------------------------------------------
            # Build the final list from aggregated statistics.
            # ------------------------------------------------------------------
            build_start = time.time()
            analyzed_links: list[dict[str, Any]] = []
            analyzed_paths: list[dict[str, Any]] = []

            for (node1_id, node2_id), stats in link_stats.items():
                if stats["traceroute_count"] == 0:
                    continue

                avg_distance = stats["total_distance"] / stats["traceroute_count"]
                avg_snr = stats["total_snr"] / stats["traceroute_count"]
                packet_id = stats["recent_packets"][0] if stats["recent_packets"] else None
                packet_url = f"/packet/{packet_id}" if packet_id is not None else None

                analyzed_links.append(
                    {
                        "from_node_id": node1_id,
                        "to_node_id": node2_id,
                        "from_node_name": stats["from_node_name"],
                        "to_node_name": stats["to_node_name"],
                        "distance_km": round(avg_distance, 2),
                        "avg_snr": round(avg_snr, 1),
                        "traceroute_count": stats["traceroute_count"],
                        "recent_packets": sorted(stats["recent_packets"], reverse=True),
                        "packet_id": packet_id,
                        "packet_url": packet_url,
                        "last_seen": stats["last_seen"],
                    }
                )

            for (from_id, to_id), stats in path_stats.items():
                if stats["traceroute_count"] == 0:
                    continue

                avg_distance = stats["total_distance"] / stats["traceroute_count"]
                avg_snr = (stats["total_snr"] / stats["traceroute_count"]) if stats["total_snr"] else None
                pkt_id = stats["recent_packets"][0] if stats["recent_packets"] else None
                pkt_url = f"/packet/{pkt_id}" if pkt_id is not None else None

                analyzed_paths.append(
                    {
                        "from_node_id": from_id,
                        "to_node_id": to_id,
                        "from_node_name": stats["from_node_name"],
                        "to_node_name": stats["to_node_name"],
                        "total_distance_km": round(avg_distance, 2),
                        "hop_count": int(round(stats["hop_count_total"] / stats["traceroute_count"])),
                        "avg_snr": round(avg_snr, 1) if avg_snr is not None else None,
                        "traceroute_count": stats["traceroute_count"],
                        "route_preview": stats["route_preview"],
                        "recent_packets": sorted(stats["recent_packets"], reverse=True),
                        "packet_id": pkt_id,
                        "packet_url": pkt_url,
                        "last_seen": stats["last_seen"],
                    }
                )

            analyzed_links.sort(key=lambda x: x["distance_km"], reverse=True)
            analyzed_links = analyzed_links[:max_results]

            analyzed_paths.sort(key=lambda x: x["total_distance_km"], reverse=True)
            analyzed_paths = analyzed_paths[:max_results]

            build_duration = time.time() - build_start
            logger.info(f"TIMING: Result building took {build_duration:.3f}s")

            longest_direct = f"{analyzed_links[0]['distance_km']:.2f} km" if analyzed_links else None
            longest_path = f"{analyzed_paths[0]['total_distance_km']:.2f} km" if analyzed_paths else None

            result_dict = {
                "summary": {
                    "total_links": len(analyzed_links) + len(analyzed_paths),
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
                    "location_lookups_cached": len(location_cache),
                },
            }
            total_duration = time.time() - start_time
            logger.info(f"TIMING: Total longest links duration: {total_duration:.3f}s")
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
        limit_packets: int = -1,
    ) -> dict[str, Any]:
        """
        Extract RF links from traceroute data to build a network connectivity graph.

        Args:
            hours: Number of hours to analyze (used if no time filters provided)
            min_snr: Minimum SNR threshold for including links
            include_indirect: Whether to include indirect (multi-hop) connections
            filters: Optional filters dict with start_time, end_time, gateway_id, etc.
            limit_packets: Maximum number of packets to analyze (-1 for unlimited)

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

            # Get traceroute hops directly from materialized traceroute_hops.
            # The query returns complete hop sequences so path structure is
            # preserved; SNR filtering happens per hop below and continuity is
            # validated before any path-level aggregation.
            hops = get_traceroute_hops_for_graph(filters=filters)

            # Track nodes and links
            nodes = {}  # node_id -> node_data
            direct_links = {}  # (node1, node2) -> link_data
            indirect_connections = {}  # (node1, node2) -> connection_data

            # Statistics
            stats = {
                "packets_analyzed": len({h["packet_id"] for h in hops}),
                "packets_with_rf_hops": len({(h["packet_id"], h.get("direction", "forward")) for h in hops}),
                "total_rf_hops": len(hops),
                "links_found": 0,
                "links_filtered_by_snr": 0,
                "links_filtered_due_to_snr_0": 0,
            }

            # Group hops by (packet_id, direction) to preserve path context
            hops_by_path: dict[tuple[int, str], list[dict[str, Any]]] = {}
            for hop in hops:
                path_key = (hop["packet_id"], hop.get("direction", "forward"))
                if path_key not in hops_by_path:
                    hops_by_path[path_key] = []
                hops_by_path[path_key].append(hop)

            for (packet_id, _direction), rf_hops in hops_by_path.items():
                ts = rf_hops[0]["timestamp"]
                for hop in rf_hops:
                    snr = hop["snr"]
                    if not is_plausible_traceroute_snr(snr) or (
                        min_snr != -200 and snr < min_snr
                    ):
                        stats["links_filtered_by_snr"] += 1
                        continue
                    if snr == 0:
                        stats["links_filtered_due_to_snr_0"] += 1
                        continue
                    from_id = hop["from_node_id"]
                    to_id = hop["to_node_id"]
                    if 4294967295 in (from_id, to_id):
                        continue

                    # Add nodes to the graph
                    for node_id in (from_id, to_id):
                        if node_id not in nodes:
                            nodes[node_id] = {
                                "id": node_id,
                                "name": f"!{node_id:08x}",
                                "packet_count": 0,
                                "total_snr": 0.0,
                                "snr_count": 0,
                                "connections": set(),
                                "last_seen": ts,
                            }
                        nodes[node_id]["packet_count"] += 1
                        if ts > nodes[node_id]["last_seen"]:
                            nodes[node_id]["last_seen"] = ts

                    link_key = tuple(sorted([from_id, to_id]))
                    if link_key not in direct_links:
                        direct_links[link_key] = {
                            "source": link_key[0],
                            "target": link_key[1],
                            "snr_values": [snr],
                            "packet_count": 1,
                            "last_seen": ts,
                            "last_packet_id": packet_id,
                        }
                        stats["links_found"] += 1
                    else:
                        link = direct_links[link_key]
                        link["snr_values"].append(snr)
                        link["packet_count"] += 1
                        if ts > link["last_seen"]:
                            link["last_seen"] = ts
                            link["last_packet_id"] = packet_id

                    nodes[from_id]["connections"].add(to_id)
                    nodes[to_id]["connections"].add(from_id)
                    nodes[from_id]["total_snr"] += snr
                    nodes[from_id]["snr_count"] += 1

                # Process indirect connections if requested. Only contiguous
                # runs of qualifying hops count as a path: a route whose middle
                # hop failed the SNR filters is two disconnected segments, not
                # a shortcut between its endpoints.
                if include_indirect:
                    for segment in _contiguous_path_segments(
                        rf_hops, lambda hop: _rf_hop_qualifies(hop, min_snr)
                    ):
                        first_from = segment[0]["from_node_id"]
                        last_to = segment[-1]["to_node_id"]
                        if 4294967295 in (first_from, last_to):
                            continue
                        indirect_key = tuple(sorted([first_from, last_to]))
                        if indirect_key in direct_links:
                            continue
                        path_snrs = [h["snr"] for h in segment]
                        if indirect_key not in indirect_connections:
                            indirect_connections[indirect_key] = {
                                "source": indirect_key[0],
                                "target": indirect_key[1],
                                "hop_count": len(segment),
                                "path_count": 1,
                                "avg_snr": sum(path_snrs) / len(path_snrs),
                                "last_seen": ts,
                                "last_packet_id": packet_id,
                            }
                        else:
                            conn = indirect_connections[indirect_key]
                            conn["path_count"] += 1
                            if ts > conn["last_seen"]:
                                conn["last_seen"] = ts
                                conn["last_packet_id"] = packet_id

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
