"""
Gateway service for Meshtastic Mesh Health Web UI

Provides cached gateway analysis and statistics that were previously part of the locations service.
This service is optimized for dashboard use and includes caching to avoid performance impacts.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from ..database.connection import get_db_connection
from ..database.repositories import PacketRepository
from ..utils.node_utils import get_bulk_node_names

logger = logging.getLogger(__name__)


class GatewayService:
    """Service for gateway analysis and statistics with caching."""

    # Simple in-memory cache for gateway statistics
    _cache: dict[str, tuple[float, Any]] = {}
    _cache_ttl_seconds = 300  # 5 minutes cache

    @staticmethod
    def get_gateway_statistics(hours: int = 24) -> dict[str, Any]:
        """Get comprehensive gateway statistics with caching.

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            Dictionary containing gateway statistics including:
            - total_gateways: Total number of unique gateways
            - gateway_distribution: List of gateways with packet counts
            - nodes_with_gateway_counts: Number of nodes that have gateway data
            - gateway_diversity_score: Score from 0-100 indicating gateway diversity
        """
        cache_key = f"gateway_stats_{hours}h"
        now = time.time()

        # Check cache first
        if cache_key in GatewayService._cache:
            cached_time, cached_data = GatewayService._cache[cache_key]
            if now - cached_time < GatewayService._cache_ttl_seconds:
                logger.debug(f"Returning cached gateway statistics for {hours}h")
                return cached_data

        logger.info(f"Computing gateway statistics for {hours}h (cache miss)")
        start_time = time.time()

        try:
            # Calculate time window
            end_time = datetime.now()
            start_time_dt = end_time - timedelta(hours=hours)

            conn = get_db_connection()
            cursor = conn.cursor()

            # Get total unique gateways
            cursor.execute(
                """
                SELECT COUNT(DISTINCT gateway_id) as total_gateways
                FROM packet_history
                WHERE gateway_id IS NOT NULL
                AND timestamp >= ? AND timestamp <= ?
            """,
                (start_time_dt.timestamp(), end_time.timestamp()),
            )

            total_gateways = cursor.fetchone()["total_gateways"] or 0

            # Get gateway distribution (top 20)
            cursor.execute(
                """
                SELECT
                    gateway_id,
                    COUNT(*) as packet_count,
                    COUNT(DISTINCT from_node_id) as unique_sources,
                    AVG(CAST(rssi AS FLOAT)) as avg_rssi,
                    AVG(CAST(snr AS FLOAT)) as avg_snr,
                    MAX(timestamp) as last_seen
                FROM packet_history
                WHERE gateway_id IS NOT NULL
                AND timestamp >= ? AND timestamp <= ?
                GROUP BY gateway_id
                ORDER BY packet_count DESC
                LIMIT 20
            """,
                (start_time_dt.timestamp(), end_time.timestamp()),
            )

            gateway_distribution = []
            for row in cursor.fetchall():
                gateway_distribution.append(
                    {
                        "gateway_id": row["gateway_id"],
                        "packet_count": row["packet_count"],
                        "unique_sources": row["unique_sources"],
                        "avg_rssi": round(row["avg_rssi"], 1)
                        if row["avg_rssi"]
                        else None,
                        "avg_snr": round(row["avg_snr"], 1) if row["avg_snr"] else None,
                        "last_seen": row["last_seen"],
                        "last_seen_str": datetime.fromtimestamp(
                            row["last_seen"]
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

            # Get nodes with gateway counts
            cursor.execute(
                """
                SELECT COUNT(DISTINCT from_node_id) as nodes_with_gateways
                FROM packet_history
                WHERE gateway_id IS NOT NULL
                AND timestamp >= ? AND timestamp <= ?
            """,
                (start_time_dt.timestamp(), end_time.timestamp()),
            )

            nodes_with_gateways = cursor.fetchone()["nodes_with_gateways"] or 0

            # Calculate gateway diversity score (0-100)
            # Based on total gateways and distribution
            if total_gateways == 0:
                diversity_score = 0
            elif total_gateways >= 10:
                diversity_score = 100
            else:
                diversity_score = min(100, total_gateways * 10)

            conn.close()

            result = {
                "total_gateways": total_gateways,
                "gateway_distribution": gateway_distribution,
                "nodes_with_gateway_counts": nodes_with_gateways,
                "gateway_diversity_score": diversity_score,
                "analysis_hours": hours,
                "generated_at": now,
                "generated_at_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Cache the result
            GatewayService._cache[cache_key] = (now, result)

            computation_time = time.time() - start_time
            logger.info(
                f"Gateway statistics computed in {computation_time:.3f}s (cached for {GatewayService._cache_ttl_seconds}s)"
            )

            return result

        except Exception as e:
            logger.error(f"Error computing gateway statistics: {e}")
            # Return empty result on error
            return {
                "total_gateways": 0,
                "gateway_distribution": [],
                "nodes_with_gateway_counts": 0,
                "gateway_diversity_score": 0,
                "analysis_hours": hours,
                "generated_at": now,
                "generated_at_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e),
            }

    @staticmethod
    def get_node_gateway_counts(node_ids: list[int], hours: int = 24) -> dict[int, int]:
        """Get gateway counts for specific nodes.

        Args:
            node_ids: List of node IDs to get gateway counts for
            hours: Number of hours to analyze (default: 24)

        Returns:
            Dictionary mapping node_id -> gateway_count
        """
        if not node_ids:
            return {}

        cache_key = f"node_gateway_counts_{len(node_ids)}_{hours}h"
        now = time.time()

        # Check cache (for small lists only)
        if len(node_ids) <= 10 and cache_key in GatewayService._cache:
            cached_time, cached_data = GatewayService._cache[cache_key]
            if now - cached_time < GatewayService._cache_ttl_seconds:
                return cached_data

        try:
            end_time = datetime.now()
            start_time_dt = end_time - timedelta(hours=hours)

            conn = get_db_connection()
            cursor = conn.cursor()

            # Build query with proper parameterization
            placeholders = ",".join("?" * len(node_ids))
            params = list(node_ids) + [start_time_dt.timestamp(), end_time.timestamp()]

            cursor.execute(
                f"""
                SELECT from_node_id, COUNT(DISTINCT gateway_id) as gateway_count
                FROM packet_history
                WHERE from_node_id IN ({placeholders})
                AND gateway_id IS NOT NULL
                AND timestamp >= ? AND timestamp <= ?
                GROUP BY from_node_id
            """,
                params,
            )

            result = {}
            for row in cursor.fetchall():
                result[row["from_node_id"]] = row["gateway_count"]

            # Fill in missing nodes with 0
            for node_id in node_ids:
                if node_id not in result:
                    result[node_id] = 0

            conn.close()

            # Cache small results
            if len(node_ids) <= 10:
                GatewayService._cache[cache_key] = (now, result)

            return result

        except Exception as e:
            logger.error(f"Error getting node gateway counts: {e}")
            return dict.fromkeys(node_ids, 0)

    @staticmethod
    def clear_cache():
        """Clear the gateway statistics cache."""
        GatewayService._cache.clear()
        logger.info("Gateway service cache cleared")

    @staticmethod
    def get_available_gateways() -> list[dict[str, Any]]:
        """
        Get list of available gateways with their display names.

        Returns:
            List of gateway dictionaries with id and display_name
        """
        try:
            gateway_ids = PacketRepository.get_unique_gateway_ids()

            # Convert gateway IDs to node IDs for name lookup where possible
            gateway_node_ids = []
            gateway_id_to_node_id = {}

            for gw_id in gateway_ids:
                if gw_id and gw_id.startswith("!"):
                    try:
                        node_id = int(gw_id[1:], 16)
                        gateway_node_ids.append(node_id)
                        gateway_id_to_node_id[gw_id] = node_id
                    except ValueError:
                        pass

            # Get node names for gateway IDs that are node IDs
            node_names = {}
            if gateway_node_ids:
                node_names = get_bulk_node_names(gateway_node_ids)

            # Build gateway list with display names
            gateways = []
            for gw_id in gateway_ids:
                if gw_id in gateway_id_to_node_id:
                    node_id = gateway_id_to_node_id[gw_id]
                    display_name = node_names.get(node_id, gw_id)
                else:
                    display_name = gw_id

                gateways.append({"id": gw_id, "display_name": display_name})

            # Sort by display name
            gateways.sort(key=lambda x: x["display_name"])

            return gateways

        except Exception as e:
            logger.error(f"Error getting available gateways: {e}")
            raise

    @staticmethod
    def compare_gateways(
        gateway1_id: str, gateway2_id: str, filters: dict | None = None
    ) -> dict[str, Any]:
        """
        Compare two gateways by analyzing their common received packets.

        Args:
            gateway1_id: First gateway ID
            gateway2_id: Second gateway ID
            filters: Optional filters for the comparison

        Returns:
            Dictionary containing comparison data and visualizations
        """
        try:
            # Get comparison data from repository
            comparison_data = PacketRepository.get_gateway_comparison_data(
                gateway1_id, gateway2_id, filters
            )

            common_packets = comparison_data["common_packets"]
            statistics = comparison_data["statistics"]

            # Get gateway display names
            gateways = GatewayService.get_available_gateways()
            gateway_names = {gw["id"]: gw["display_name"] for gw in gateways}

            gateway1_name = gateway_names.get(gateway1_id, gateway1_id)
            gateway2_name = gateway_names.get(gateway2_id, gateway2_id)

            # Get node names for the packets
            if common_packets:
                node_ids = list(
                    {p["from_node_id"] for p in common_packets if p["from_node_id"]}
                )
                node_names = get_bulk_node_names(node_ids)

                # Add node names to packets
                for packet in common_packets:
                    packet["from_node_name"] = node_names.get(
                        packet["from_node_id"], f"!{packet['from_node_id']:08x}"
                    )

            # Prepare chart data
            chart_data = GatewayService._prepare_chart_data(
                common_packets, gateway1_name, gateway2_name
            )

            # Add display names to statistics
            statistics["gateway1_name"] = gateway1_name
            statistics["gateway2_name"] = gateway2_name

            return {
                "common_packets": common_packets,
                "statistics": statistics,
                "chart_data": chart_data,
                "gateway1_name": gateway1_name,
                "gateway2_name": gateway2_name,
            }

        except Exception as e:
            logger.error(
                f"Error comparing gateways {gateway1_id} and {gateway2_id}: {e}"
            )
            raise

    @staticmethod
    def _prepare_chart_data(
        common_packets: list[dict], gateway1_name: str, gateway2_name: str
    ) -> dict[str, Any]:
        """
        Prepare data for charts and visualizations.

        Args:
            common_packets: List of common packets
            gateway1_name: Display name for gateway 1
            gateway2_name: Display name for gateway 2

        Returns:
            Dictionary containing chart data
        """
        if not common_packets:
            return {
                "rssi_scatter": {"x": [], "y": []},
                "snr_scatter": {"x": [], "y": []},
                "rssi_diff_histogram": {"values": []},
                "snr_diff_histogram": {"values": []},
                "timeline_rssi": {"timestamps": [], "gateway1": [], "gateway2": []},
                "timeline_snr": {"timestamps": [], "gateway1": [], "gateway2": []},
            }

        # Extract data for charts
        gateway1_rssi = [
            p["gateway1_rssi"] for p in common_packets if p["gateway1_rssi"] is not None
        ]
        gateway2_rssi = [
            p["gateway2_rssi"] for p in common_packets if p["gateway2_rssi"] is not None
        ]
        gateway1_snr = [
            p["gateway1_snr"] for p in common_packets if p["gateway1_snr"] is not None
        ]
        gateway2_snr = [
            p["gateway2_snr"] for p in common_packets if p["gateway2_snr"] is not None
        ]

        rssi_diffs = [
            p["rssi_diff"] for p in common_packets if p["rssi_diff"] is not None
        ]
        snr_diffs = [p["snr_diff"] for p in common_packets if p["snr_diff"] is not None]

        timestamps = [p["timestamp_str"] for p in common_packets]

        # Prepare scatter plot data (gateway1 vs gateway2)
        rssi_scatter_data = {
            "x": gateway1_rssi,
            "y": gateway2_rssi,
            "text": [
                f"Packet from {p.get('from_node_name', 'Unknown')}<br>Time: {p['timestamp_str']}"
                for p in common_packets
                if p["gateway1_rssi"] is not None and p["gateway2_rssi"] is not None
            ],
        }

        snr_scatter_data = {
            "x": gateway1_snr,
            "y": gateway2_snr,
            "text": [
                f"Packet from {p.get('from_node_name', 'Unknown')}<br>Time: {p['timestamp_str']}"
                for p in common_packets
                if p["gateway1_snr"] is not None and p["gateway2_snr"] is not None
            ],
        }

        # Timeline data
        timeline_rssi = {
            "timestamps": timestamps,
            "gateway1": [p["gateway1_rssi"] for p in common_packets],
            "gateway2": [p["gateway2_rssi"] for p in common_packets],
        }

        timeline_snr = {
            "timestamps": timestamps,
            "gateway1": [p["gateway1_snr"] for p in common_packets],
            "gateway2": [p["gateway2_snr"] for p in common_packets],
        }

        return {
            "rssi_scatter": rssi_scatter_data,
            "snr_scatter": snr_scatter_data,
            "rssi_diff_histogram": {"values": rssi_diffs},
            "snr_diff_histogram": {"values": snr_diffs},
            "timeline_rssi": timeline_rssi,
            "timeline_snr": timeline_snr,
            "gateway1_name": gateway1_name,
            "gateway2_name": gateway2_name,
        }
