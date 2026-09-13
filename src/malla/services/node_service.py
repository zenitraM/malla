"""
Node service for business logic related to node operations
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any

# Import from the new modular architecture
from ..database import NodeRepository
from ..services.location_service import LocationService
from ..services.traceroute_service import TracerouteService
from ..utils.node_utils import convert_node_id

logger = logging.getLogger(__name__)


class NodeNotFoundError(Exception):
    """Exception raised when a node is not found in the database."""

    pass


class NodeService:
    """Service class for node-related business operations."""

    @staticmethod
    def get_node_info(node_id) -> dict[str, Any]:
        """
        Get detailed information about a specific node.

        Args:
            node_id: Node ID in various formats

        Returns:
            Dictionary containing node information, traceroute stats, location history, and neighbors

        Raises:
            ValueError: If node_id cannot be converted
            NodeNotFoundError: If node is not found in database
        """
        # Convert node_id to int
        node_id_int = convert_node_id(node_id)

        # Get node data directly from repository using get_node_details
        node_details = NodeRepository.get_node_details(node_id_int)

        if not node_details:
            raise NodeNotFoundError("Node not found")

        # Extract the node info from the details
        node = node_details["node"]

        # Get traceroute statistics for this node
        traceroute_stats = TracerouteService.get_node_traceroute_stats(node_id_int)

        # Get location history if available
        location_history = LocationService.get_node_location_history(
            node_id_int, limit=10
        )

        # Get neighbors
        neighbors = LocationService.get_node_neighbors(
            node_id_int, max_distance_km=10.0
        )

        # Combine all data
        return {
            "node": node,
            "traceroute_stats": traceroute_stats,
            "location_history": location_history,
            "neighbors": neighbors,
        }

    @staticmethod
    def get_node_location_history(node_id, limit: int = 100) -> dict[str, Any]:
        """
        Get location history for a specific node.

        Args:
            node_id: Node ID in various formats
            limit: Maximum number of location records to return

        Returns:
            Dictionary containing node_id and location history
        """
        node_id_int = convert_node_id(node_id)
        history = LocationService.get_node_location_history(node_id_int, limit=limit)

        return {"node_id": node_id_int, "location_history": history}

    # Supported telemetry chart ranges -> window length in seconds (0 = all).
    TELEMETRY_RANGES = {"1d": 86400, "7d": 604800, "30d": 2592000, "all": 0}

    @staticmethod
    def get_node_telemetry_history(
        node_id,
        range_key: str = "7d",
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """
        Get telemetry (device / environment) history for a node's charts.

        Args:
            node_id: Node ID in various formats
            range_key: One of "1d", "7d", "30d", "all" (defaults to "7d")
            start, end: Explicit unix-second window. When both are given they
                take precedence over ``range_key`` — used by the charts to load
                full-resolution data for a zoomed-in time range.

        Returns:
            Dictionary with node_id, the window, per-metric series and count
        """
        node_id_int = convert_node_id(node_id)

        if start is not None and end is not None:
            result = NodeRepository.get_node_telemetry_history(
                node_id_int, start_time=start, end_time=end
            )
            return {"node_id": node_id_int, "start": start, "end": end, **result}

        seconds = NodeService.TELEMETRY_RANGES.get(range_key, 604800)
        start_time = (time.time() - seconds) if seconds else None
        result = NodeRepository.get_node_telemetry_history(
            node_id_int, start_time=start_time
        )
        return {"node_id": node_id_int, "range": range_key, **result}

    @staticmethod
    def get_node_neighbors(node_id, max_distance: float = 10.0) -> dict[str, Any]:
        """
        Get neighbors for a specific node within a certain distance.

        Args:
            node_id: Node ID in various formats
            max_distance: Maximum distance in kilometers

        Returns:
            Dictionary containing node_id, max_distance, neighbors, and neighbor_count
        """
        node_id_int = convert_node_id(node_id)
        neighbors = LocationService.get_node_neighbors(
            node_id_int, max_distance_km=max_distance
        )

        return {
            "node_id": node_id_int,
            "max_distance_km": max_distance,
            "neighbors": neighbors,
            "neighbor_count": len(neighbors),
        }

    @staticmethod
    def get_traceroute_related_nodes(node_id) -> dict[str, Any]:
        """
        Get nodes that have DIRECT RF hop connections to the specified node.

        This only includes nodes that have actual radio frequency hops with the target node,
        not just nodes that appear in the same traceroute path.

        Args:
            node_id: Node ID in various formats

        Returns:
            Dictionary containing related nodes and their RF hop counts
        """
        from ..database import get_db_connection

        node_id_int = convert_node_id(node_id)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get recent traceroute packets (same 7-day window as link analysis)
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)  # Look at last 7 days

        rows = cursor.execute(
            """
            SELECT
                CASE WHEN from_node_id = ? THEN to_node_id ELSE from_node_id END AS other_node,
                COUNT(*) AS observation_count
            FROM traceroute_hops
            WHERE timestamp >= ? AND timestamp <= ?
              AND (from_node_id = ? OR to_node_id = ?)
            GROUP BY other_node
            ORDER BY observation_count DESC, other_node
            """,
            (
                node_id_int,
                start_time.timestamp(),
                end_time.timestamp(),
                node_id_int,
                node_id_int,
            ),
        ).fetchall()
        related_nodes = {row["other_node"]: row["observation_count"] for row in rows}

        # Get node info for all related nodes
        if related_nodes:
            node_ids_str = ",".join(str(nid) for nid in related_nodes.keys())
            node_info_query = f"""
                SELECT
                    node_id,
                    long_name,
                    short_name,
                    printf('!%08x', node_id) as hex_id
                FROM node_info
                WHERE node_id IN ({node_ids_str})
            """
            cursor.execute(node_info_query)
            node_info_data = {
                row[0]: dict(
                    zip(
                        ["node_id", "long_name", "short_name", "hex_id"],
                        row,
                        strict=False,
                    )
                )
                for row in cursor.fetchall()
            }
        else:
            node_info_data = {}

        conn.close()

        # Format the response
        formatted_related_nodes = []
        for node_id_rel, count in sorted(
            related_nodes.items(), key=lambda x: x[1], reverse=True
        ):
            node_info = node_info_data.get(node_id_rel, {})
            display_name = (
                node_info.get("long_name")
                or node_info.get("short_name")
                or f"!{node_id_rel:08x}"
            )

            formatted_related_nodes.append(
                {
                    "node_id": node_id_rel,
                    "hex_id": node_info.get("hex_id", f"!{node_id_rel:08x}"),
                    "display_name": display_name,
                    "long_name": node_info.get("long_name"),
                    "short_name": node_info.get("short_name"),
                    "traceroute_count": count,  # Keep same field name for frontend compatibility
                }
            )

        return {
            "node_id": node_id_int,
            "related_nodes": formatted_related_nodes,
            "total_count": len(formatted_related_nodes),
        }
