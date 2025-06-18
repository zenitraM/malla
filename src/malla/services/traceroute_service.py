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
from typing import Any, cast

from ..database.repositories import (
    LocationRepository,
    TracerouteRepository,
)
from ..models.traceroute import (
    RouteData,
    TraceroutePacket,  # Use the correct TraceroutePacket class
)
from ..utils.node_utils import get_bulk_node_names
from ..utils.traceroute_utils import parse_traceroute_payload

logger = logging.getLogger(__name__)


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
            # Fetch raw data (only the last 7 days & successfully processed)
            # ------------------------------------------------------------------
            fetch_start = time.time()
            from datetime import datetime, timedelta

            end_time = datetime.now()
            start_time_filter = end_time - timedelta(days=7)

            filters = {
                "start_time": start_time_filter.timestamp(),
                "end_time": end_time.timestamp(),
                "processed_successfully_only": True,
            }

            result = TracerouteRepository.get_traceroute_packets(
                # Fetch a larger sample of packets to cover busy networks
                # 25k packets ≈ several hours of traffic on busy meshes but still manageable
                limit=25000,
                filters=filters,
            )
            fetch_duration = time.time() - fetch_start
            logger.info(
                f"TIMING: Data fetch took {fetch_duration:.3f}s for {len(result['packets'])} packets"
            )

            # ------------------------------------------------------------------
            # Pre-fetch node location history using a single query per node
            # (replaces the previous expensive nested node->packet cache fill).
            # ------------------------------------------------------------------
            # First collect all unique node ids that appear in the packets
            unique_node_ids: set[int] = set()
            parsed_route_cache: dict[int, RouteData] = {}
            for packet in result["packets"]:
                if not packet.get("raw_payload"):
                    continue
                try:
                    route_data = parse_traceroute_payload(packet["raw_payload"])
                    parsed_route_cache[packet["id"]] = route_data
                    nodes_for_packet = {packet["from_node_id"], packet["to_node_id"]}
                    nodes_for_packet.update(route_data.get("route_nodes", []))
                    # Remove invalid placeholders
                    nodes_for_packet.discard(None)
                    nodes_for_packet.discard(4294967295)
                    unique_node_ids.update(nodes_for_packet)
                except Exception as e:
                    logger.warning(
                        f"Error parsing packet {packet.get('id', 'unknown')} for node collection: {e}"
                    )
                    continue

            prefetch_start = time.time()

            from ..utils import traceroute_utils as _tru  # Local import to avoid cycles

            # Build a dict: node_id -> list[location_dict] (DESC by timestamp)
            location_history_cache: dict[int, list[dict[str, Any]]] = {}
            for node_id in unique_node_ids:
                try:
                    locations = LocationRepository.get_node_location_history(
                        node_id, limit=50
                    )
                    if locations:
                        location_history_cache[node_id] = (
                            locations  # already DESC order
                        )
                except Exception as e:
                    logger.warning(
                        f"Error fetching location history for node {node_id}: {e}"
                    )
                    continue

            prefetch_duration = time.time() - prefetch_start
            logger.info(
                f"TIMING: Location history pre-fetch took {prefetch_duration:.3f}s for {len(location_history_cache)} nodes"
            )

            # ------------------------------------------------------------------
            # Inject a fast in-memory location lookup to avoid per-hop DB hits.
            # ------------------------------------------------------------------
            _orig_get_location = _tru.get_node_location_at_timestamp  # Backup original

            def _fast_location_lookup(
                node_id: int, target_ts: float
            ) -> dict[str, Any] | None:
                """Return the best location for a node at target_ts from the pre-loaded history.

                Falls back to the original DB implementation if the node isn't in cache
                (keeps behaviour identical for very old/unknown nodes).
                """
                # Use an hour bucket to maximise cache hits without losing much accuracy
                bucket = int(target_ts // 3600)
                memo_key = (node_id, bucket)
                if memo_key in location_cache:
                    return location_cache[memo_key]

                history = location_history_cache.get(node_id)
                if not history:
                    loc = _orig_get_location(node_id, target_ts)
                    if loc:
                        location_cache[memo_key] = loc
                    return loc

                # histories are DESC (newest first). Find first <= ts.
                best = None
                for loc in history:
                    if loc["timestamp"] <= target_ts:
                        best = loc
                        break
                if best is None:
                    # No past location found – use oldest future record.
                    best = history[-1]

                age_sec = target_ts - best["timestamp"]
                age_hours = abs(age_sec) / 3600
                if age_sec >= 0:  # Past record
                    if age_hours <= 24:
                        age_warning = f"from {age_hours:.1f}h ago"
                    elif age_hours <= 168:
                        age_warning = f"from {age_hours / 24:.1f}d ago"
                    else:
                        age_warning = f"from {age_hours / 168:.1f}w ago"
                else:  # Future record
                    if age_hours <= 24:
                        age_warning = f"from {age_hours:.1f}h later"
                    elif age_hours <= 168:
                        age_warning = f"from {age_hours / 24:.1f}d later"
                    else:
                        age_warning = f"from {age_hours / 168:.1f}w later"

                loc_dict = {
                    "latitude": best["latitude"],
                    "longitude": best["longitude"],
                    "altitude": best.get("altitude"),
                    "timestamp": best["timestamp"],
                    "age_warning": age_warning,
                }
                location_cache[memo_key] = loc_dict
                return loc_dict

            # Override location lookup with fast in-memory version for this analysis
            _tru.get_node_location_at_timestamp = cast(Any, _fast_location_lookup)

            # Location cache used by TraceroutePacket.calculate_hop_distances
            location_cache: dict[tuple, Any] = {}

            try:
                # ------------------------------------------------------------------
                # Stream-process each hop to avoid holding large intermediate lists.
                # ------------------------------------------------------------------
                process_start = time.time()
                link_stats: dict[tuple, dict[str, Any]] = {}
                # Track multi-hop path statistics (indirect links)
                path_stats: dict[tuple, dict[str, Any]] = {}

                logger.info(
                    f"Processing {len(result['packets'])} packets with pre-populated location cache"
                )

                packets_processed = 0
                hops_processed = 0
                distance_calculations = 0
                cache_hits = 0
                cache_misses = 0
                early_filtered = 0

                for packet in result["packets"]:
                    packet_start = time.time()
                    try:
                        # Early filtering: skip packets that won't contribute any valid hops
                        if (
                            not packet["raw_payload"]
                            or not packet["processed_successfully"]
                        ):
                            early_filtered += 1
                            continue

                        tr_packet = TraceroutePacket(
                            packet_data=packet,
                            resolve_names=True,
                        )

                        # Track cache performance before distance calculation
                        cache_size_before = len(location_cache)

                        # Populate distance information – uses pre-populated location_cache
                        distance_calc_start = time.time()
                        tr_packet.calculate_hop_distances(location_cache=location_cache)
                        # Track timing (result not used but calculation is important)
                        _ = time.time() - distance_calc_start
                        distance_calculations += 1

                        # Track cache performance after distance calculation
                        cache_size_after = len(location_cache)
                        if cache_size_after > cache_size_before:
                            cache_misses += cache_size_after - cache_size_before
                        else:
                            cache_hits += 1

                        rf_hops = tr_packet.get_rf_hops()
                        hops_processed += len(rf_hops)

                        for hop in rf_hops:
                            # Early filtering: skip hops that won't meet criteria
                            if (
                                hop.snr is None
                                or hop.snr == 0
                                or hop.snr < min_snr
                                or not hop.distance_km
                                or hop.distance_km < min_distance_km
                                or 4294967295 in [hop.from_node_id, hop.to_node_id]
                            ):
                                continue

                            # Use a bidirectional key so A<->B == B<->A
                            key = tuple(sorted([hop.from_node_id, hop.to_node_id]))

                            if key not in link_stats:
                                # Determine the correct orientation for names
                                node1_id, node2_id = key
                                if hop.from_node_id == node1_id:
                                    from_name = hop.from_node_name
                                    to_name = hop.to_node_name
                                else:
                                    from_name = hop.to_node_name
                                    to_name = hop.from_node_name

                                link_stats[key] = {
                                    "from_node_name": from_name,
                                    "to_node_name": to_name,
                                    "total_distance": 0.0,
                                    "total_snr": 0.0,
                                    "traceroute_count": 0,
                                    "max_distance": 0.0,
                                    "best_snr": None,
                                    "recent_packets": [],  # keep last 5 ids
                                }

                            stats_dict = link_stats[key]

                            # Update aggregates
                            stats_dict["traceroute_count"] += 1
                            stats_dict["total_distance"] += hop.distance_km
                            stats_dict["total_snr"] += hop.snr
                            stats_dict["max_distance"] = max(
                                stats_dict["max_distance"], hop.distance_km
                            )

                            if (
                                stats_dict["best_snr"] is None
                                or hop.snr > stats_dict["best_snr"]
                            ):
                                stats_dict["best_snr"] = hop.snr

                            # Maintain only last 5 packet ids (newest first)
                            stats_dict["recent_packets"].append(packet["id"])
                            if len(stats_dict["recent_packets"]) > 5:
                                stats_dict["recent_packets"].pop(0)

                        packets_processed += 1

                        # Log progress every 100 packets
                        if packets_processed % 100 == 0:
                            packet_duration = time.time() - packet_start
                            logger.info(
                                f"TIMING: Processed {packets_processed} packets, last packet took {packet_duration:.3f}s"
                            )

                        # --------------------------------------------------
                        # Indirect path processing (entire traceroute path)
                        # --------------------------------------------------
                        if len(rf_hops) > 1:
                            # Calculate total distance of the full path
                            path_distance_km = sum(
                                h.distance_km or 0.0 for h in rf_hops
                            )

                            # Skip if it doesn't meet distance threshold
                            if path_distance_km < min_distance_km:
                                pass  # too short – ignore
                            else:
                                # Average SNR across hops (ignore None values)
                                valid_snrs = [
                                    h.snr for h in rf_hops if h.snr is not None
                                ]
                                avg_path_snr = (
                                    (sum(valid_snrs) / len(valid_snrs))
                                    if valid_snrs
                                    else None
                                )

                                # Apply SNR filter (only if we actually have a value)
                                if avg_path_snr is None or avg_path_snr < min_snr:
                                    pass  # SNR below threshold – ignore
                                else:
                                    from_node_id_path = rf_hops[0].from_node_id
                                    to_node_id_path = rf_hops[-1].to_node_id

                                    path_key = (from_node_id_path, to_node_id_path)

                                    if path_key not in path_stats:
                                        path_stats[path_key] = {
                                            "from_node_name": rf_hops[0].from_node_name,
                                            "to_node_name": rf_hops[-1].to_node_name,
                                            "total_distance": 0.0,
                                            "total_snr": 0.0,
                                            "traceroute_count": 0,
                                            "hop_count_total": 0,
                                            "recent_packets": [],
                                            "route_preview": [
                                                h.from_node_name for h in rf_hops
                                            ]
                                            + [rf_hops[-1].to_node_name],
                                            "max_distance": 0.0,
                                        }

                                    pstats = path_stats[path_key]

                                    # Update aggregates
                                    pstats["traceroute_count"] += 1
                                    pstats["total_distance"] += path_distance_km
                                    pstats["hop_count_total"] += len(rf_hops)
                                    pstats["total_snr"] += avg_path_snr
                                    pstats["max_distance"] = max(
                                        pstats["max_distance"], path_distance_km
                                    )

                                    pstats["recent_packets"].append(packet["id"])
                                    if len(pstats["recent_packets"]) > 5:
                                        pstats["recent_packets"].pop(0)

                    except Exception as e:
                        logger.warning(
                            f"Error processing packet {packet.get('id', 'unknown')} for longest links: {e}"
                        )
                        continue

                process_duration = time.time() - process_start
                logger.info(f"TIMING: Packet processing took {process_duration:.3f}s")
                logger.info(
                    f"TIMING: Processed {packets_processed} packets, {hops_processed} hops, {distance_calculations} distance calculations"
                )
                logger.info(
                    f"TIMING: Cache performance - {cache_hits} hits, {cache_misses} misses, final size: {len(location_cache)}"
                )

                logger.info(
                    f"Location cache efficiency: {len(location_cache)} unique location lookups cached"
                )

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

                    # Get last_seen timestamp from the most recent packet
                    last_seen = None
                    if stats["recent_packets"] and len(stats["recent_packets"]) > 0:
                        packet_id = stats["recent_packets"][0]
                        pkt = next(
                            (p for p in result["packets"] if p["id"] == packet_id), None
                        )
                        if pkt and "timestamp" in pkt:
                            last_seen = pkt["timestamp"]

                    packet_id = (
                        stats["recent_packets"][0] if stats["recent_packets"] else None
                    )
                    packet_url = (
                        f"/packet/{packet_id}" if packet_id is not None else None
                    )

                    analyzed_links.append(
                        {
                            "from_node_id": node1_id,
                            "to_node_id": node2_id,
                            "from_node_name": stats["from_node_name"],
                            "to_node_name": stats["to_node_name"],
                            "distance_km": round(avg_distance, 2),
                            "avg_snr": round(avg_snr, 1),
                            "traceroute_count": stats["traceroute_count"],
                            "recent_packets": sorted(
                                stats["recent_packets"], reverse=True
                            ),
                            "packet_id": packet_id,
                            "packet_url": packet_url,
                            "last_seen": last_seen,
                        }
                    )

                # Build indirect paths results
                for (from_id, to_id), stats in path_stats.items():
                    if stats["traceroute_count"] == 0:
                        continue

                    avg_distance = stats["total_distance"] / stats["traceroute_count"]
                    avg_snr = (
                        (stats["total_snr"] / stats["traceroute_count"])
                        if stats["total_snr"]
                        else None
                    )

                    # Determine last_seen timestamp
                    last_seen = None
                    if stats["recent_packets"]:
                        pkt_id = stats["recent_packets"][0]
                        pkt_obj = next(
                            (p for p in result["packets"] if p["id"] == pkt_id), None
                        )
                        if pkt_obj and "timestamp" in pkt_obj:
                            last_seen = pkt_obj["timestamp"]

                    pkt_id = (
                        stats["recent_packets"][0] if stats["recent_packets"] else None
                    )
                    pkt_url = f"/packet/{pkt_id}" if pkt_id is not None else None

                    analyzed_paths.append(
                        {
                            "from_node_id": from_id,
                            "to_node_id": to_id,
                            "from_node_name": stats["from_node_name"],
                            "to_node_name": stats["to_node_name"],
                            "total_distance_km": round(avg_distance, 2),
                            "hop_count": int(
                                round(
                                    stats["hop_count_total"] / stats["traceroute_count"]
                                )
                            ),
                            "avg_snr": round(avg_snr, 1)
                            if avg_snr is not None
                            else None,
                            "traceroute_count": stats["traceroute_count"],
                            "route_preview": stats["route_preview"],
                            "recent_packets": sorted(
                                stats["recent_packets"], reverse=True
                            ),
                            "packet_id": pkt_id,
                            "packet_url": pkt_url,
                            "last_seen": last_seen,
                        }
                    )

                # Sort and trim results to the requested maximum
                sort_start = time.time()
                analyzed_links.sort(key=lambda x: x["distance_km"], reverse=True)
                analyzed_links = analyzed_links[:max_results]
                sort_duration = time.time() - sort_start

                # Sort and trim indirect paths
                analyzed_paths.sort(key=lambda x: x["total_distance_km"], reverse=True)
                analyzed_paths = analyzed_paths[:max_results]

                build_duration = time.time() - build_start
                logger.info(
                    f"TIMING: Result building took {build_duration:.3f}s (sort: {sort_duration:.3f}s)"
                )

                # ------------------------------------------------------------------
                # Compose summary.
                # ------------------------------------------------------------------
                summary_start = time.time()
                total_links = len(analyzed_links) + len(analyzed_paths)

                # Format longest distances as strings for summary
                longest_direct = None
                if analyzed_links:
                    longest_direct = f"{analyzed_links[0]['distance_km']:.2f} km"

                longest_path = None
                if analyzed_paths:
                    longest_path = f"{analyzed_paths[0]['total_distance_km']:.2f} km"

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
                        "location_lookups_cached": len(location_cache),
                    },
                }

                summary_duration = time.time() - summary_start
                total_duration = time.time() - start_time

                logger.info(f"TIMING: Summary creation took {summary_duration:.3f}s")
                logger.info(f"TIMING: Total function duration: {total_duration:.3f}s")
                logger.info(
                    f"TIMING: Breakdown - Fetch: {fetch_duration:.3f}s ({fetch_duration / total_duration * 100:.1f}%), "
                    f"Prefetch: {prefetch_duration:.3f}s ({prefetch_duration / total_duration * 100:.1f}%), "
                    f"Process: {process_duration:.3f}s ({process_duration / total_duration * 100:.1f}%), "
                    f"Build: {build_duration:.3f}s ({build_duration / total_duration * 100:.1f}%)"
                )

                return result_dict

            finally:
                # Restore original implementation to avoid side-effects
                _tru.get_node_location_at_timestamp = cast(Any, _orig_get_location)

        except Exception as e:
            logger.error(f"Error in longest links analysis: {e}")
            raise

    @staticmethod
    def get_network_graph_data(
        hours: int = 24,
        min_snr: float = -200.0,
        include_indirect: bool = False,
        filters: dict | None = None,
        limit_packets: int = 5000,
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
            result = TracerouteRepository.get_traceroute_packets(
                limit=limit_packets,
                filters=filters,
                group_packets=False,  # Disable grouping to avoid payload corruption
            )

            # Track nodes and links
            nodes = {}  # node_id -> node_data
            direct_links = {}  # (node1, node2) -> link_data
            indirect_connections = {}  # (node1, node2) -> connection_data

            # Statistics
            stats = {
                "packets_analyzed": len(result["packets"]),
                "packets_with_rf_hops": 0,
                "total_rf_hops": 0,
                "links_found": 0,
                "links_filtered_by_snr": 0,
                "links_filtered_due_to_snr_0": 0,
            }

            # Process each traceroute packet
            for tr_data in result["packets"]:
                if not tr_data["raw_payload"]:
                    continue

                try:
                    # Create TraceroutePacket object for analysis
                    tr_packet = TraceroutePacket(
                        packet_data=tr_data, resolve_names=True
                    )

                    # Get RF hops (actual radio transmissions)
                    rf_hops = tr_packet.get_rf_hops()
                    if not rf_hops:
                        continue

                    stats["packets_with_rf_hops"] += 1
                    stats["total_rf_hops"] += len(rf_hops)

                    # Process direct RF links
                    for hop in rf_hops:
                        # Filter by SNR - if min_snr is -200, it means "no limit" so only filter None values
                        if hop.snr is None or (min_snr != -200 and hop.snr < min_snr):
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
                                indirect_connections[indirect_key] = {
                                    "source": indirect_key[0],
                                    "target": indirect_key[1],
                                    "hop_count": len(rf_hops),
                                    "path_count": 1,
                                    "avg_snr": sum(
                                        hop.snr for hop in rf_hops if hop.snr
                                    )
                                    / len([h for h in rf_hops if h.snr]),
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

            # Get location data for all nodes in the graph
            # Import here to avoid circular dependencies
            from ..database.repositories import LocationRepository

            node_ids = list(nodes.keys())
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

            return {
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

        except Exception as e:
            logger.error(f"Error building network graph data: {e}")
            raise
