"""
Optimized PacketRepository implementation with time-windowed grouping
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from . import get_db_connection

logger = logging.getLogger(__name__)


class PacketRepositoryOptimized:
    """Optimized repository for packet operations with improved grouped query performance."""

    @staticmethod
    def get_packets(
        limit: int = 100,
        offset: int = 0,
        filters: dict | None = None,
        order_by: str = "timestamp",
        order_dir: str = "desc",
        search: str | None = None,
        group_packets: bool = False,
    ) -> dict[str, Any]:
        """Get packet history with optional filtering and optimized grouping."""
        if filters is None:
            filters = {}

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Build WHERE clause
            where_conditions = []
            params = []

            if filters.get("start_time"):
                where_conditions.append("timestamp >= ?")
                params.append(filters["start_time"])

            if filters.get("end_time"):
                where_conditions.append("timestamp <= ?")
                params.append(filters["end_time"])

            if filters.get("from_node"):
                where_conditions.append("from_node_id = ?")
                params.append(filters["from_node"])

            if filters.get("to_node"):
                where_conditions.append("to_node_id = ?")
                params.append(filters["to_node"])

            if filters.get("portnum"):
                where_conditions.append("portnum_name = ?")
                params.append(filters["portnum"])

            if filters.get("min_rssi"):
                where_conditions.append("rssi >= ?")
                params.append(filters["min_rssi"])

            if filters.get("max_rssi"):
                where_conditions.append("rssi <= ?")
                params.append(filters["max_rssi"])

            if filters.get("gateway_id"):
                where_conditions.append("gateway_id = ?")
                params.append(filters["gateway_id"])

            if filters.get("hop_count") is not None:
                where_conditions.append("(hop_start - hop_limit) = ?")
                params.append(filters["hop_count"])

            # Generic exclusion filters for from/to node IDs
            # Optimized: Use simple != condition to allow index usage
            if filters.get("exclude_from") is not None:
                where_conditions.append("from_node_id != ?")
                params.append(filters["exclude_from"])

            if filters.get("exclude_to") is not None:
                where_conditions.append("to_node_id != ?")
                params.append(filters["exclude_to"])

            # Search functionality
            if search:
                # Search in multiple text fields
                search_condition = """(
                    portnum_name LIKE ? OR
                    gateway_id LIKE ? OR
                    channel_id LIKE ? OR
                    CAST(from_node_id AS TEXT) LIKE ? OR
                    CAST(to_node_id AS TEXT) LIKE ?
                )"""
                where_conditions.append(search_condition)
                search_param = f"%{search}%"
                params.extend([search_param] * 5)

            where_clause = (
                "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            )

            if group_packets:
                # OPTIMIZED GROUPED APPROACH
                # Since grouped packets are usually within ~10 min of each other,
                # we use a time-windowed approach instead of expensive GROUP BY + ORDER BY

                # Add mesh_packet_id filter
                if where_conditions:
                    where_clause += " AND mesh_packet_id IS NOT NULL"
                else:
                    where_clause = "WHERE mesh_packet_id IS NOT NULL"

                # Add time window to limit data scan (improves performance dramatically)
                # If no explicit time filter, default to last 7 days for reasonable performance
                if not filters.get("start_time") and not filters.get("end_time"):
                    recent_cutoff = time.time() - (7 * 24 * 3600)  # 7 days ago
                    where_clause += " AND timestamp >= ?"
                    params.append(recent_cutoff)

                # Get individual packets ordered by timestamp (uses timestamp index efficiently)
                # Fetch more than needed to account for grouping
                fetch_multiplier = max(
                    10, limit // 5
                )  # Adaptive multiplier based on limit
                fetch_limit = min(
                    limit * fetch_multiplier, 10000
                )  # Cap at 10k for safety

                query = f"""
                    SELECT
                        id, timestamp, from_node_id, to_node_id, portnum, portnum_name,
                        gateway_id, mesh_packet_id, rssi, snr, hop_limit, hop_start,
                        payload_length, processed_successfully,
                        datetime(timestamp, 'unixepoch') as timestamp_str,
                        (hop_start - hop_limit) as hop_count
                    FROM packet_history
                    {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """

                cursor.execute(query, params + [fetch_limit])
                individual_packets = cursor.fetchall()

                # Group packets in memory by (mesh_packet_id, from_node_id, to_node_id, portnum, portnum_name)
                groups = {}
                for packet in individual_packets:
                    # Create group key
                    group_key = (
                        packet["mesh_packet_id"],
                        packet["from_node_id"],
                        packet["to_node_id"],
                        packet["portnum"],
                        packet["portnum_name"],
                    )

                    if group_key not in groups:
                        groups[group_key] = {
                            "packets": [],
                            "min_timestamp": packet["timestamp"],
                        }

                    groups[group_key]["packets"].append(packet)
                    groups[group_key]["min_timestamp"] = min(
                        groups[group_key]["min_timestamp"], packet["timestamp"]
                    )

                # Convert groups to result format
                packets = []
                for group_key, group_data in groups.items():
                    mesh_packet_id, from_node_id, to_node_id, portnum, portnum_name = (
                        group_key
                    )
                    packets_in_group = group_data["packets"]

                    # Calculate aggregated values
                    gateway_ids = list(
                        {p["gateway_id"] for p in packets_in_group if p["gateway_id"]}
                    )
                    rssi_values = [
                        p["rssi"] for p in packets_in_group if p["rssi"] is not None
                    ]
                    snr_values = [
                        p["snr"] for p in packets_in_group if p["snr"] is not None
                    ]
                    hop_values = [
                        p["hop_count"]
                        for p in packets_in_group
                        if p["hop_count"] is not None
                    ]
                    payload_lengths = [
                        p["payload_length"]
                        for p in packets_in_group
                        if p["payload_length"] is not None
                    ]

                    # Use the earliest packet as the representative
                    representative_packet = min(
                        packets_in_group, key=lambda p: p["timestamp"]
                    )

                    packet = {
                        "id": representative_packet["id"],
                        "timestamp": group_data["min_timestamp"],
                        "from_node_id": from_node_id,
                        "to_node_id": to_node_id,
                        "portnum": portnum,
                        "portnum_name": portnum_name,
                        "mesh_packet_id": mesh_packet_id,
                        "gateway_count": len(gateway_ids),
                        "gateway_list": ",".join(gateway_ids),
                        "min_rssi": min(rssi_values) if rssi_values else None,
                        "max_rssi": max(rssi_values) if rssi_values else None,
                        "min_snr": min(snr_values) if snr_values else None,
                        "max_snr": max(snr_values) if snr_values else None,
                        "min_hops": min(hop_values) if hop_values else None,
                        "max_hops": max(hop_values) if hop_values else None,
                        "avg_payload_length": sum(payload_lengths)
                        / len(payload_lengths)
                        if payload_lengths
                        else None,
                        "processed_successfully": min(
                            p["processed_successfully"] for p in packets_in_group
                        ),
                        "timestamp_str": datetime.fromtimestamp(
                            group_data["min_timestamp"]
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                        "reception_count": len(packets_in_group),
                        "is_grouped": True,
                        "success": min(
                            p["processed_successfully"] for p in packets_in_group
                        ),
                    }

                    # Format hop range
                    if (
                        packet["min_hops"] is not None
                        and packet["max_hops"] is not None
                    ):
                        if packet["min_hops"] == packet["max_hops"]:
                            packet["hop_range"] = str(packet["min_hops"])
                        else:
                            packet["hop_range"] = (
                                f"{packet['min_hops']}-{packet['max_hops']}"
                            )
                    else:
                        packet["hop_range"] = None

                    # Format RSSI range
                    if (
                        packet["min_rssi"] is not None
                        and packet["max_rssi"] is not None
                    ):
                        if packet["min_rssi"] == packet["max_rssi"]:
                            packet["rssi_range"] = f"{packet['min_rssi']:.1f} dBm"
                        else:
                            packet["rssi_range"] = (
                                f"{packet['min_rssi']:.1f} to {packet['max_rssi']:.1f} dBm"
                            )
                    else:
                        packet["rssi_range"] = None

                    # Format SNR range
                    if packet["min_snr"] is not None and packet["max_snr"] is not None:
                        if packet["min_snr"] == packet["max_snr"]:
                            packet["snr_range"] = f"{packet['min_snr']:.2f} dB"
                        else:
                            packet["snr_range"] = (
                                f"{packet['min_snr']:.2f} to {packet['max_snr']:.2f} dB"
                            )
                    else:
                        packet["snr_range"] = None

                    packets.append(packet)

                # Sort by timestamp (fast in-memory sort)
                packets.sort(
                    key=lambda x: x["timestamp"], reverse=(order_dir.lower() == "desc")
                )

                # Apply pagination
                paginated_packets = packets[offset : offset + limit]

                # For total count, use the number of groups we found as approximation
                # This is much faster than doing a separate COUNT(DISTINCT) query
                total_count = len(groups)

                packets = paginated_packets

            else:
                # Original ungrouped behavior
                # Get total count first
                count_query = f"SELECT COUNT(*) FROM packet_history {where_clause}"
                cursor.execute(count_query, params)
                total_count = cursor.fetchone()[0]

                # Main query
                query = f"""
                    SELECT
                        id, timestamp, from_node_id, to_node_id, portnum, portnum_name,
                        gateway_id, channel_id, mesh_packet_id, rssi, snr, hop_limit, hop_start,
                        payload_length, processed_successfully,
                        via_mqtt, want_ack, priority, delayed, channel_index, rx_time,
                        pki_encrypted, next_hop, relay_node, tx_after,
                        datetime(timestamp, 'unixepoch') as timestamp_str,
                        (hop_start - hop_limit) as hop_count
                    FROM packet_history
                    {where_clause}
                    ORDER BY {order_by} {order_dir.upper()}
                    LIMIT ? OFFSET ?
                """

                query_params = params + [limit, offset]
                cursor.execute(query, query_params)

                packets = []
                for row in cursor.fetchall():
                    packet = dict(row)

                    # Format timestamp if not already formatted
                    if packet["timestamp_str"] is None:
                        packet["timestamp_str"] = datetime.fromtimestamp(
                            packet["timestamp"], UTC
                        ).strftime("%Y-%m-%d %H:%M:%S UTC")

                    # Calculate hop count if not already set
                    if (
                        packet["hop_count"] is None
                        and packet["hop_start"] is not None
                        and packet["hop_limit"] is not None
                    ):
                        packet["hop_count"] = packet["hop_start"] - packet["hop_limit"]

                    # Add success indicator
                    packet["success"] = packet["processed_successfully"]
                    packet["is_grouped"] = False

                    packets.append(packet)

            conn.close()

            return {
                "packets": packets,
                "total_count": total_count,
                "has_more": total_count > (offset + limit),
                "is_grouped": group_packets,
            }

        except Exception as e:
            logger.error(f"Error getting packets: {e}")
            raise
