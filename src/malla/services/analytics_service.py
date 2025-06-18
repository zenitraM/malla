"""
Analytics service for Meshtastic Mesh Health Web UI
"""

import logging
import time
from collections import defaultdict
from typing import Any

from ..database.repositories import NodeRepository

logger = logging.getLogger(__name__)

# NOTE: Lightweight, in-process cache so that repeated calls in a short period
# do not hit the database multiple times. This is intentionally simple to keep
# dependencies minimal; for a multi-process deployment a proper cache (e.g.
# Redis) should be used instead.


class AnalyticsService:
    """Service for analytics and statistical calculations."""

    # (gateway_id, from_node, hop_count) → (timestamp, data)
    _CACHE: dict[
        tuple[str | None, int | None, int | None], tuple[float, dict[str, Any]]
    ] = {}
    _CACHE_TTL_SEC: int = 60  # one minute cache window

    @staticmethod
    def get_analytics_data(
        gateway_id: str | None = None,
        from_node: int | None = None,
        hop_count: int | None = None,
    ) -> dict[str, Any]:
        """Get comprehensive analytics data for the dashboard with simple in-memory caching."""

        cache_key = (gateway_id, from_node, hop_count)
        now_ts = time.time()

        # Return cached value if still valid
        cached = AnalyticsService._CACHE.get(cache_key)
        if cached and (now_ts - cached[0] < AnalyticsService._CACHE_TTL_SEC):
            return cached[1]

        logger.info(
            "Computing analytics data (cache miss): gateway_id=%s, from_node=%s, hop_count=%s",
            gateway_id,
            from_node,
            hop_count,
        )

        try:
            # Build filters object
            filters: dict[str, Any] = {}
            if gateway_id:
                filters["gateway_id"] = gateway_id
            if from_node:
                filters["from_node"] = from_node
            if hop_count is not None:
                filters["hop_count"] = hop_count

            twenty_four_hours_ago = now_ts - 24 * 3600
            seven_days_ago = now_ts - 7 * 24 * 3600

            packet_stats = AnalyticsService._get_packet_statistics(
                filters, twenty_four_hours_ago
            )
            node_stats = AnalyticsService._get_node_activity_statistics(
                filters, twenty_four_hours_ago
            )
            signal_stats = AnalyticsService._get_signal_quality_statistics(
                filters, twenty_four_hours_ago
            )
            temporal_stats = AnalyticsService._get_temporal_patterns(
                filters, twenty_four_hours_ago
            )
            top_nodes = AnalyticsService._get_top_active_nodes(filters, seven_days_ago)
            packet_types = AnalyticsService._get_packet_type_distribution(
                filters, twenty_four_hours_ago
            )
            gateway_stats = AnalyticsService._get_gateway_distribution(
                filters, twenty_four_hours_ago
            )

            result = {
                "packet_statistics": packet_stats,
                "node_statistics": node_stats,
                "signal_quality": signal_stats,
                "temporal_patterns": temporal_stats,
                "top_nodes": top_nodes,
                "packet_types": packet_types,
                "gateway_distribution": gateway_stats,
            }

            # Save to cache
            AnalyticsService._CACHE[cache_key] = (now_ts, result)

            logger.info("Analytics data computed successfully (cached)")
            return result

        except Exception as e:
            logger.error(f"Error getting analytics data: {e}")
            raise

    @staticmethod
    def _get_packet_statistics(filters: dict, since_timestamp: float) -> dict[str, Any]:
        """Get basic packet statistics using optimized SQL query."""
        from ..database.connection import get_db_connection

        # Build WHERE clause
        where_conditions: list[str] = ["timestamp >= ?"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = ?")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = ?")
            params.append(filters["from_node"])

        if filters.get("hop_count") is not None:
            where_conditions.append("(hop_start - hop_limit) = ?")
            params.append(filters["hop_count"])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                COUNT(*) as total_packets,
                SUM(CASE WHEN processed_successfully = 1 THEN 1 ELSE 0 END) as successful_packets,
                AVG(CASE WHEN payload_length IS NOT NULL AND payload_length > 0 THEN payload_length END) as avg_payload_size
            FROM packet_history
            WHERE {where_clause}
        """

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()

        total_packets = row["total_packets"] or 0
        successful_packets = row["successful_packets"] or 0
        success_rate = (
            (successful_packets / total_packets * 100) if total_packets > 0 else 0
        )

        return {
            "total_packets": total_packets,
            "successful_packets": successful_packets,
            "failed_packets": total_packets - successful_packets,
            "success_rate": round(success_rate, 2),
            "average_payload_size": round(row["avg_payload_size"] or 0, 2),
        }

    @staticmethod
    def _get_node_activity_statistics(
        filters: dict, since_timestamp: float
    ) -> dict[str, Any]:
        """Get node activity statistics using optimized SQL query."""
        from ..database.connection import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get total node count
        cursor.execute("SELECT COUNT(*) as total_nodes FROM node_info")
        total_nodes = cursor.fetchone()["total_nodes"]

        # Build WHERE clause for packet filtering
        where_conditions: list[str] = ["timestamp >= ?"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = ?")
            params.append(filters["gateway_id"])

        where_clause = " AND ".join(where_conditions)

        # Get node activity distribution using SQL aggregation
        cursor.execute(
            f"""
            WITH node_activity AS (
                SELECT
                    from_node_id,
                    COUNT(*) as packet_count
                FROM packet_history
                WHERE from_node_id IS NOT NULL AND {where_clause}
                GROUP BY from_node_id
            )
            SELECT
                COUNT(*) as active_nodes,
                SUM(CASE WHEN packet_count > 100 THEN 1 ELSE 0 END) as very_active,
                SUM(CASE WHEN packet_count > 10 AND packet_count <= 100 THEN 1 ELSE 0 END) as moderately_active,
                SUM(CASE WHEN packet_count >= 1 AND packet_count <= 10 THEN 1 ELSE 0 END) as lightly_active
            FROM node_activity
        """,
            params,
        )

        activity_row = cursor.fetchone()
        conn.close()

        active_nodes = activity_row["active_nodes"] or 0
        inactive_nodes = total_nodes - active_nodes

        activity_ranges = {
            "very_active": activity_row["very_active"] or 0,
            "moderately_active": activity_row["moderately_active"] or 0,
            "lightly_active": activity_row["lightly_active"] or 0,
            "inactive": inactive_nodes,
        }

        return {
            "total_nodes": total_nodes,
            "active_nodes": active_nodes,
            "inactive_nodes": inactive_nodes,
            "activity_rate": round((active_nodes / total_nodes * 100), 2)
            if total_nodes > 0
            else 0,
            "activity_distribution": activity_ranges,
        }

    @staticmethod
    def _get_signal_quality_statistics(
        filters: dict, since_timestamp: float
    ) -> dict[str, Any]:
        """Get signal quality statistics using optimized SQL query."""
        from ..database.connection import get_db_connection

        # Build WHERE clause
        where_conditions: list[str] = ["timestamp >= ?"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = ?")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = ?")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get signal statistics using SQL aggregation
        cursor.execute(
            f"""
            SELECT
                AVG(CASE WHEN rssi IS NOT NULL AND rssi != 0 THEN rssi END) as avg_rssi,
                AVG(CASE WHEN snr IS NOT NULL THEN snr END) as avg_snr,
                COUNT(CASE WHEN rssi IS NOT NULL AND rssi != 0 THEN 1 END) as rssi_count,
                COUNT(CASE WHEN snr IS NOT NULL THEN 1 END) as snr_count,
                -- RSSI distribution
                SUM(CASE WHEN rssi > -70 THEN 1 ELSE 0 END) as rssi_excellent,
                SUM(CASE WHEN rssi > -80 AND rssi <= -70 THEN 1 ELSE 0 END) as rssi_good,
                SUM(CASE WHEN rssi > -90 AND rssi <= -80 THEN 1 ELSE 0 END) as rssi_fair,
                SUM(CASE WHEN rssi <= -90 THEN 1 ELSE 0 END) as rssi_poor,
                -- SNR distribution
                SUM(CASE WHEN snr > 10 THEN 1 ELSE 0 END) as snr_excellent,
                SUM(CASE WHEN snr > 5 AND snr <= 10 THEN 1 ELSE 0 END) as snr_good,
                SUM(CASE WHEN snr > 0 AND snr <= 5 THEN 1 ELSE 0 END) as snr_fair,
                SUM(CASE WHEN snr <= 0 THEN 1 ELSE 0 END) as snr_poor
            FROM packet_history
            WHERE {where_clause}
        """,
            params,
        )

        row = cursor.fetchone()
        conn.close()

        if not row or (row["rssi_count"] == 0 and row["snr_count"] == 0):
            return {
                "avg_rssi": None,
                "avg_snr": None,
                "rssi_distribution": {},
                "snr_distribution": {},
                "total_measurements": 0,
            }

        rssi_distribution = {
            "excellent": row["rssi_excellent"] or 0,
            "good": row["rssi_good"] or 0,
            "fair": row["rssi_fair"] or 0,
            "poor": row["rssi_poor"] or 0,
        }

        snr_distribution = {
            "excellent": row["snr_excellent"] or 0,
            "good": row["snr_good"] or 0,
            "fair": row["snr_fair"] or 0,
            "poor": row["snr_poor"] or 0,
        }

        return {
            "avg_rssi": round(row["avg_rssi"], 2) if row["avg_rssi"] else None,
            "avg_snr": round(row["avg_snr"], 2) if row["avg_snr"] else None,
            "rssi_distribution": rssi_distribution,
            "snr_distribution": snr_distribution,
            "total_measurements": max(row["rssi_count"] or 0, row["snr_count"] or 0),
        }

    @staticmethod
    def _get_temporal_patterns(filters: dict, since_timestamp: float) -> dict[str, Any]:
        """Get temporal patterns (hourly breakdown) efficiently using SQL aggregation."""

        from ..database.connection import get_db_connection

        # Build WHERE clause similarly to PacketRepository but simplified (only params we care about)
        where_conditions: list[str] = ["timestamp >= ?"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = ?")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = ?")
            params.append(filters["from_node"])

        if filters.get("hop_count") is not None:
            where_conditions.append("(hop_start - hop_limit) = ?")
            params.append(filters["hop_count"])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT
                strftime('%H', datetime(timestamp, 'unixepoch')) AS hour,
                COUNT(*) AS total_packets,
                SUM(CASE WHEN processed_successfully = 1 THEN 1 ELSE 0 END) AS successful_packets
            FROM packet_history
            WHERE {where_clause}
            GROUP BY hour
        """

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)

        rows = cursor.fetchall()

        hourly_counts: dict[int, int] = defaultdict(int)
        hourly_success: dict[int, int] = defaultdict(int)

        for row in rows:
            hour = int(row["hour"])
            hourly_counts[hour] = row["total_packets"]
            hourly_success[hour] = row["successful_packets"]

        hourly_data: list[dict[str, Any]] = []
        for hour in range(24):
            count = hourly_counts.get(hour, 0)
            success = hourly_success.get(hour, 0)
            success_rate = (success / count * 100) if count > 0 else 0

            hourly_data.append(
                {
                    "hour": hour,
                    "total_packets": count,
                    "successful_packets": success,
                    "success_rate": round(success_rate, 2),
                }
            )

        # Determine peak and quiet hours if any packets exist
        peak_hour = (
            max(hourly_counts, key=lambda x: hourly_counts[x])
            if hourly_counts
            else None
        )
        quiet_hour = (
            min(hourly_counts, key=lambda x: hourly_counts[x])
            if hourly_counts
            else None
        )

        return {
            "hourly_breakdown": hourly_data,
            "peak_hour": peak_hour,
            "quiet_hour": quiet_hour,
        }

    @staticmethod
    def _get_top_active_nodes(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get top active nodes by packet count."""
        # Get node data sorted by activity
        node_data = NodeRepository.get_nodes(
            limit=20, order_by="packet_count_24h", order_dir="desc"
        )

        # Format for display
        top_nodes = []
        for node in node_data["nodes"]:
            if node.get("packet_count_24h", 0) > 0:
                top_nodes.append(
                    {
                        "node_id": node["node_id"],
                        "display_name": node.get("long_name")
                        or node.get("short_name")
                        or f"!{node['node_id']:08x}",
                        "packet_count": node.get("packet_count_24h", 0),
                        "avg_rssi": node.get("avg_rssi"),
                        "avg_snr": node.get("avg_snr"),
                        "last_seen": node.get("last_packet_time"),
                        "hw_model": node.get("hw_model"),
                    }
                )

        return top_nodes[:10]  # Return top 10

    @staticmethod
    def _get_packet_type_distribution(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get distribution of packet types using optimized SQL query."""
        from ..database.connection import get_db_connection

        # Build WHERE clause
        where_conditions: list[str] = ["timestamp >= ?", "portnum_name IS NOT NULL"]
        params: list[Any] = [since_timestamp]

        if filters.get("gateway_id"):
            where_conditions.append("gateway_id = ?")
            params.append(filters["gateway_id"])

        if filters.get("from_node"):
            where_conditions.append("from_node_id = ?")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get packet type distribution with percentages
        cursor.execute(
            f"""
            WITH type_counts AS (
                SELECT
                    portnum_name,
                    COUNT(*) as count
                FROM packet_history
                WHERE {where_clause}
                GROUP BY portnum_name
            ),
            total_count AS (
                SELECT SUM(count) as total FROM type_counts
            )
            SELECT
                tc.portnum_name,
                tc.count,
                ROUND(tc.count * 100.0 / t.total, 2) as percentage
            FROM type_counts tc, total_count t
            ORDER BY tc.count DESC
            LIMIT 15
        """,
            params,
        )

        packet_types = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return packet_types

    @staticmethod
    def _get_gateway_distribution(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get distribution of packets by gateway using optimized SQL query."""
        from ..database.connection import get_db_connection

        # Build WHERE clause (excluding gateway_id filter since we're analyzing gateways)
        where_conditions: list[str] = ["timestamp >= ?"]
        params: list[Any] = [since_timestamp]

        if filters.get("from_node"):
            where_conditions.append("from_node_id = ?")
            params.append(filters["from_node"])

        where_clause = " AND ".join(where_conditions)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get gateway distribution with success rates and percentages
        cursor.execute(
            f"""
            WITH gateway_stats AS (
                SELECT
                    COALESCE(gateway_id, 'Unknown') as gateway_id,
                    COUNT(*) as total_packets,
                    SUM(CASE WHEN processed_successfully = 1 THEN 1 ELSE 0 END) as successful_packets
                FROM packet_history
                WHERE {where_clause}
                GROUP BY gateway_id
            ),
            total_count AS (
                SELECT SUM(total_packets) as total FROM gateway_stats
            )
            SELECT
                gs.gateway_id,
                gs.total_packets,
                gs.successful_packets,
                ROUND(gs.successful_packets * 100.0 / gs.total_packets, 2) as success_rate,
                ROUND(gs.total_packets * 100.0 / t.total, 2) as percentage_of_total
            FROM gateway_stats gs, total_count t
            ORDER BY gs.total_packets DESC
            LIMIT 20
        """,
            params,
        )

        gateway_stats = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return gateway_stats
