"""
Analytics service for Meshtastic Mesh Health Web UI
"""

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
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
                filters, twenty_four_hours_ago, seven_days_ago
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
            hop_distribution = AnalyticsService._get_hop_distribution(
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
                "hop_distribution": hop_distribution,
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
        filters: dict, since_timestamp: float, seven_days_ago: float
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

        # Nodes heard from in the trailing 7 days — the reference roster for
        # activity ratios. node_info only ever grows (every node ever seen),
        # so ratios against it decay toward zero as the roster ages; a rolling
        # window measures against nodes that are actually still around.
        seen_params: list[Any] = [seven_days_ago]
        seen_filter = ""
        if filters.get("gateway_id"):
            seen_filter = " AND gateway_id = ?"
            seen_params.append(filters["gateway_id"])
        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT from_node_id) as nodes_seen_7d
            FROM packet_history
            WHERE timestamp >= ? AND from_node_id IS NOT NULL{seen_filter}
        """,
            seen_params,
        )
        nodes_seen_7d = cursor.fetchone()["nodes_seen_7d"] or 0
        conn.close()

        active_nodes = activity_row["active_nodes"] or 0
        # "Inactive" = seen this week but silent in the current window.
        inactive_nodes = max(nodes_seen_7d - active_nodes, 0)

        activity_ranges = {
            "very_active": activity_row["very_active"] or 0,
            "moderately_active": activity_row["moderately_active"] or 0,
            "lightly_active": activity_row["lightly_active"] or 0,
            "inactive": inactive_nodes,
        }

        return {
            "total_nodes": total_nodes,
            "nodes_seen_7d": nodes_seen_7d,
            "active_nodes": active_nodes,
            "inactive_nodes": inactive_nodes,
            "activity_rate": round((active_nodes / nodes_seen_7d * 100), 2)
            if nodes_seen_7d > 0
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

    # ------------------------------------------------------------------
    # Activity timeline (dashboard trends panels with a range selector)
    # ------------------------------------------------------------------

    TIMELINE_RANGES: frozenset[str] = frozenset({"24h", "7d", "30d", "all"})

    # (range_key, tz_offset_minutes) → (timestamp, data)
    _TIMELINE_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}

    # Wall-clock budget per request for backfilling missing rollup days. Must
    # stay well under the gunicorn worker timeout (30s in wsgi.py): a request
    # that runs out of budget returns a "pending" response with its progress
    # already committed, instead of being SIGKILLed mid-transaction — which
    # would roll everything back and make the next request start from zero,
    # a permanent failure loop on deployments where the full backfill can't
    # finish inside one worker timeout.
    _ROLLUP_TIME_BUDGET_SEC: float = 15.0

    @staticmethod
    def get_activity_timeline(
        range_key: str = "7d", tz_offset_minutes: int = 0
    ) -> dict[str, Any]:
        """Get the activity timeline for one of the ranges 24h / 7d / 30d / all.

        Buckets are hourly for 24h and per local calendar day otherwise
        (tz_offset_minutes = viewer's minutes east of UTC). Each bucket carries
        packet volume, distinct sending nodes, distinct reporting gateways and
        newly discovered nodes. Completed days are served from the
        activity_daily_rollup table (append-only history makes them immutable),
        so even the "all" range stays fast; only the current day/hour window is
        aggregated live.

        Backfilling missing rollup days is bounded by _ROLLUP_TIME_BUDGET_SEC
        per request. If the budget runs out the response carries
        ``pending: True`` plus ``days_remaining``; the committed progress
        survives, so the client just retries until pending clears.
        """
        if range_key not in AnalyticsService.TIMELINE_RANGES:
            range_key = "7d"

        cache_key = (range_key, tz_offset_minutes)
        now_ts = time.time()
        cached = AnalyticsService._TIMELINE_CACHE.get(cache_key)
        if cached and (now_ts - cached[0] < AnalyticsService._CACHE_TTL_SEC):
            return cached[1]

        if range_key == "24h":
            buckets = AnalyticsService._get_hourly_buckets(tz_offset_minutes)
            granularity = "hour"
            days_remaining = 0
        else:
            buckets, days_remaining = AnalyticsService._get_daily_buckets(
                range_key, tz_offset_minutes
            )
            granularity = "day"

        result = {
            "range": range_key,
            "granularity": granularity,
            "buckets": buckets,
            "pending": days_remaining > 0,
        }
        if days_remaining:
            # Partial: some completed days aren't rolled up yet. Don't cache —
            # the next request must resume the backfill, not replay this.
            result["days_remaining"] = days_remaining
            return result

        AnalyticsService._TIMELINE_CACHE[cache_key] = (now_ts, result)
        return result

    @staticmethod
    def _get_hourly_buckets(tz_offset_minutes: int) -> list[dict[str, Any]]:
        """Aggregate the trailing 24 local-clock hours (last bucket = this hour so far)."""
        from ..database.connection import get_db_connection

        offset_sec = tz_offset_minutes * 60
        current_hour_local = (int(time.time() + offset_sec) // 3600) * 3600
        start_local = current_hour_local - 23 * 3600
        start_utc = start_local - offset_sec

        buckets: dict[str, dict[str, Any]] = {}
        for i in range(24):
            key = datetime.fromtimestamp(start_local + i * 3600, tz=UTC).strftime(
                "%Y-%m-%d %H:00"
            )
            buckets[key] = {
                "bucket": key,
                "total_packets": 0,
                "active_nodes": 0,
                "gateway_count": 0,
                "new_nodes": 0,
            }

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    strftime('%Y-%m-%d %H:00', timestamp + ?, 'unixepoch') AS bucket,
                    COUNT(*) AS total_packets,
                    COUNT(DISTINCT from_node_id) AS active_nodes
                FROM packet_history
                WHERE timestamp >= ?
                GROUP BY bucket
            """,
                (offset_sec, start_utc),
            )
            for row in cursor.fetchall():
                entry = buckets.get(row["bucket"])
                if entry:
                    entry["total_packets"] = row["total_packets"]
                    entry["active_nodes"] = row["active_nodes"]

            cursor.execute(
                """
                SELECT
                    strftime('%Y-%m-%d %H:00', timestamp + ?, 'unixepoch') AS bucket,
                    COUNT(DISTINCT gateway_id) AS gateway_count
                FROM packet_history
                WHERE gateway_id IS NOT NULL AND timestamp >= ?
                GROUP BY bucket
            """,
                (offset_sec, start_utc),
            )
            for row in cursor.fetchall():
                entry = buckets.get(row["bucket"])
                if entry:
                    entry["gateway_count"] = row["gateway_count"]

            cursor.execute(
                """
                SELECT
                    strftime('%Y-%m-%d %H:00', first_seen + ?, 'unixepoch') AS bucket,
                    COUNT(*) AS new_nodes
                FROM node_info
                WHERE first_seen >= ?
                GROUP BY bucket
            """,
                (offset_sec, start_utc),
            )
            for row in cursor.fetchall():
                entry = buckets.get(row["bucket"])
                if entry:
                    entry["new_nodes"] = row["new_nodes"]
        finally:
            conn.close()

        return list(buckets.values())

    @staticmethod
    def _get_daily_buckets(
        range_key: str, tz_offset_minutes: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Aggregate per local calendar day for 7d / 30d / all.

        Completed days come from (and are persisted to) activity_daily_rollup;
        only today is computed live from packet_history. Returns the buckets
        and how many completed days are still missing from the rollup (0 when
        the timeline is complete; buckets for missing days read as zero).
        """
        from ..database.connection import get_db_connection
        from ..database.schema import ACTIVITY_ROLLUP_TABLE_SQL

        offset_sec = tz_offset_minutes * 60
        deadline = time.time() + AnalyticsService._ROLLUP_TIME_BUDGET_SEC
        today_local = (int(time.time() + offset_sec) // 86400) * 86400

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Defensive create: the web app normally creates this at startup,
            # but the service must also work against bare test databases.
            cursor.execute(ACTIVITY_ROLLUP_TABLE_SQL)

            if range_key == "7d":
                start_local = today_local - 7 * 86400
            elif range_key == "30d":
                start_local = today_local - 30 * 86400
            else:  # all: from the local day of the first recorded packet
                cursor.execute("SELECT MIN(timestamp) AS mn FROM packet_history")
                row = cursor.fetchone()
                mn = row["mn"] if row else None
                start_local = (
                    (int(mn + offset_sec) // 86400) * 86400
                    if mn is not None
                    else today_local
                )
                start_local = min(start_local, today_local)

            day_epochs = list(range(start_local, today_local + 86400, 86400))
            completed_epochs = [d for d in day_epochs if d < today_local]

            rollup_rows, days_remaining = AnalyticsService._ensure_daily_rollup(
                cursor, tz_offset_minutes, offset_sec, completed_epochs, deadline
            )
            conn.commit()

            if days_remaining:
                # Out of budget: the caller will report pending and the client
                # retries, so don't spend more time aggregating today live.
                today_stats: dict[str, dict[str, Any]] = {}
            else:
                today_stats = AnalyticsService._compute_daily_span(
                    cursor, offset_sec, today_local, today_local + 86400
                )
        finally:
            conn.close()

        buckets: list[dict[str, Any]] = []
        for day_epoch in day_epochs:
            key = AnalyticsService._local_day_key(day_epoch)
            source = today_stats if day_epoch >= today_local else rollup_rows
            stats = source.get(key, {})
            buckets.append(
                {
                    "bucket": key,
                    "total_packets": stats.get("total_packets", 0),
                    "active_nodes": stats.get("active_nodes", 0),
                    "gateway_count": stats.get("gateway_count", 0),
                    "new_nodes": stats.get("new_nodes", 0),
                }
            )
        return buckets, days_remaining

    @staticmethod
    def _local_day_key(local_day_epoch: int) -> str:
        """ISO date string for a local-midnight epoch (local time == shifted UTC)."""
        return datetime.fromtimestamp(local_day_epoch, tz=UTC).date().isoformat()

    @staticmethod
    def _ensure_daily_rollup(
        cursor: Any,
        tz_offset_minutes: int,
        offset_sec: int,
        completed_epochs: list[int],
        deadline: float,
    ) -> tuple[dict[str, dict[str, Any]], int]:
        """Return rollup stats for the given completed local days, computing
        missing ones from packet_history until *deadline* and persisting them.

        Rows are safe to persist forever: packet_history is append-only with
        insert-time timestamps and node_info.first_seen is assigned once, so a
        finished local day can never change retroactively.

        Missing days are computed one at a time, newest first, and each day is
        committed as soon as it is done, so progress survives even if this
        request is killed or runs out of budget. At least one day is always
        computed per call (guaranteed convergence); past that, the loop stops
        once *deadline* is reached. Returns the stats found/computed plus the
        number of days still missing (0 = complete).
        """
        if not completed_epochs:
            return {}, 0

        wanted = {AnalyticsService._local_day_key(d): d for d in completed_epochs}
        placeholders = ",".join("?" * len(wanted))
        cursor.execute(
            f"""
            SELECT day, total_packets, active_nodes, gateway_count, new_nodes
            FROM activity_daily_rollup
            WHERE tz_offset_minutes = ? AND day IN ({placeholders})
        """,
            [tz_offset_minutes, *wanted.keys()],
        )
        cached: dict[str, dict[str, Any]] = {
            row["day"]: dict(row) for row in cursor.fetchall()
        }

        missing = sorted(
            (epoch for key, epoch in wanted.items() if key not in cached),
            reverse=True,
        )
        for done, epoch in enumerate(missing):
            if done and time.time() >= deadline:
                return cached, len(missing) - done

            key = AnalyticsService._local_day_key(epoch)
            stats = AnalyticsService._compute_daily_span(
                cursor, offset_sec, epoch, epoch + 86400
            ).get(key, {})
            row = {
                "total_packets": stats.get("total_packets", 0),
                "active_nodes": stats.get("active_nodes", 0),
                "gateway_count": stats.get("gateway_count", 0),
                "new_nodes": stats.get("new_nodes", 0),
            }
            cursor.execute(
                """
                INSERT OR REPLACE INTO activity_daily_rollup
                (tz_offset_minutes, day, total_packets, active_nodes,
                 gateway_count, new_nodes, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    tz_offset_minutes,
                    key,
                    row["total_packets"],
                    row["active_nodes"],
                    row["gateway_count"],
                    row["new_nodes"],
                    time.time(),
                ),
            )
            cursor.connection.commit()
            cached[key] = {"day": key, **row}
        return cached, 0

    @staticmethod
    def _compute_daily_span(
        cursor: Any, offset_sec: int, span_start_local: int, span_end_local: int
    ) -> dict[str, dict[str, Any]]:
        """Aggregate packet/node/gateway metrics per local day over one span.

        The packet queries are answered entirely from the (timestamp,
        from_node_id) and (timestamp, gateway_id) covering indexes.
        """
        start_utc = span_start_local - offset_sec
        end_utc = span_end_local - offset_sec

        stats: dict[str, dict[str, Any]] = {}

        def entry(day: str) -> dict[str, Any]:
            return stats.setdefault(day, {})

        cursor.execute(
            """
            SELECT
                date(timestamp + ?, 'unixepoch') AS day,
                COUNT(*) AS total_packets,
                COUNT(DISTINCT from_node_id) AS active_nodes
            FROM packet_history
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY day
        """,
            (offset_sec, start_utc, end_utc),
        )
        for row in cursor.fetchall():
            entry(row["day"]).update(
                total_packets=row["total_packets"], active_nodes=row["active_nodes"]
            )

        cursor.execute(
            """
            SELECT
                date(timestamp + ?, 'unixepoch') AS day,
                COUNT(DISTINCT gateway_id) AS gateway_count
            FROM packet_history
            WHERE gateway_id IS NOT NULL AND timestamp >= ? AND timestamp < ?
            GROUP BY day
        """,
            (offset_sec, start_utc, end_utc),
        )
        for row in cursor.fetchall():
            entry(row["day"]).update(gateway_count=row["gateway_count"])

        cursor.execute(
            """
            SELECT
                date(first_seen + ?, 'unixepoch') AS day,
                COUNT(*) AS new_nodes
            FROM node_info
            WHERE first_seen >= ? AND first_seen < ?
            GROUP BY day
        """,
            (offset_sec, start_utc, end_utc),
        )
        for row in cursor.fetchall():
            entry(row["day"]).update(new_nodes=row["new_nodes"])

        return stats

    @staticmethod
    def _get_hop_distribution(
        filters: dict, since_timestamp: float
    ) -> list[dict[str, Any]]:
        """Get the real hop-count distribution (hop_start - hop_limit) for the window."""
        from ..database.connection import get_db_connection

        where_conditions: list[str] = [
            "timestamp >= ?",
            "hop_start IS NOT NULL",
            "hop_limit IS NOT NULL",
            # Guard against malformed packets reporting negative hop counts.
            "hop_start >= hop_limit",
        ]
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
        cursor.execute(
            f"""
            SELECT
                (hop_start - hop_limit) AS hops,
                COUNT(*) AS count
            FROM packet_history
            WHERE {where_clause}
            GROUP BY hops
            ORDER BY hops
        """,
            params,
        )
        distribution = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return distribution

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
