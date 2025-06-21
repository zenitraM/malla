"""
Node utility functions for Meshtastic Mesh Health Web UI
"""

import atexit
import logging
import threading
from typing import Any

from ..database.connection import get_db_connection

logger = logging.getLogger(__name__)

# Cache for node names to improve performance
node_name_cache: dict[int, str] = {}
cache_lock = threading.Lock()

# Background thread for periodic cache invalidation
_cache_cleanup_thread: threading.Thread | None = None
_cache_cleanup_stop_event = threading.Event()


def _cache_cleanup_worker() -> None:
    """Background worker that periodically clears the node name cache."""
    try:
        logger.info("Node name cache cleanup worker started (5 minute intervals)")
    except Exception:
        # Logging system may be shut down during test cleanup
        pass

    while not _cache_cleanup_stop_event.wait(300):  # 300 seconds = 5 minutes
        try:
            with cache_lock:
                cache_size = len(node_name_cache)
                node_name_cache.clear()
                if cache_size > 0:
                    try:
                        logger.debug(f"Cleared node name cache ({cache_size} entries)")
                    except Exception:
                        # Logging system may be shut down during test cleanup
                        pass
        except Exception as e:
            try:
                logger.error(f"Error in cache cleanup worker: {e}")
            except Exception:
                # Logging system may be shut down during test cleanup
                pass

    # logger.info("Node name cache cleanup worker stopped")


def start_cache_cleanup() -> None:
    """Start the background cache cleanup thread."""
    global _cache_cleanup_thread

    if _cache_cleanup_thread is not None and _cache_cleanup_thread.is_alive():
        try:
            logger.debug("Cache cleanup thread already running")
        except (ValueError, OSError):
            # Logging system may be shut down during test cleanup
            pass
        return

    _cache_cleanup_stop_event.clear()
    _cache_cleanup_thread = threading.Thread(
        target=_cache_cleanup_worker, name="NodeCacheCleanup", daemon=True
    )
    _cache_cleanup_thread.start()
    try:
        logger.info("Started node name cache cleanup background thread")
    except (ValueError, OSError):
        # Logging system may be shut down during test cleanup
        pass


def stop_cache_cleanup() -> None:
    """Stop the background cache cleanup thread."""
    global _cache_cleanup_thread

    if _cache_cleanup_thread is None or not _cache_cleanup_thread.is_alive():
        return

    _cache_cleanup_stop_event.set()
    _cache_cleanup_thread.join(timeout=1.0)

    # Detach all handlers to prevent logging after shutdown
    logger.handlers.clear()


def get_node_display_name(node_id: int | str) -> str:
    """
    Get the display name for a node, with caching for performance.

    Args:
        node_id: The node ID to get the name for

    Returns:
        Display name for the node
    """
    # Handle different node ID formats
    if isinstance(node_id, str):
        if node_id.startswith("!"):
            try:
                node_id = int(node_id[1:], 16)
            except ValueError:
                return str(node_id)
        else:
            try:
                node_id = int(node_id)
            except ValueError:
                return str(node_id)

    # Check cache first
    with cache_lock:
        if node_id in node_name_cache:
            return node_name_cache[node_id]

    # Query database for node info
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT long_name, short_name, hex_id
            FROM node_info
            WHERE node_id = ?
        """,
            (node_id,),
        )
        result = cursor.fetchone()
        conn.close()

        if result:
            long_name = result["long_name"]
            short_name = result["short_name"]
            hex_id = result["hex_id"]

            # Format display name with fallback hierarchy
            display_name = _format_node_display_name(
                node_id, long_name, short_name, hex_id
            )
        else:
            # Fallback to hex format
            if isinstance(node_id, int):
                display_name = f"!{node_id:08x}"
            else:
                display_name = "Unknown"

        # Cache the result
        with cache_lock:
            node_name_cache[node_id] = display_name

        return display_name

    except Exception as e:
        logger.warning(f"Error getting node name for {node_id}: {e}")
        # Ensure node_id is an integer before hex formatting
        if isinstance(node_id, int):
            return f"!{node_id:08x}"
        else:
            return "Unknown"


def _format_node_display_name(
    node_id: int,
    long_name: str | None = None,
    short_name: str | None = None,
    hex_id: str | None = None,
) -> str:
    """
    Format a complete display name for a node with fallback hierarchy.

    Priority:
    1. If we have both long_name and short_name and they're different: "Long Name (short)"
    2. If we have only long_name: use long_name
    3. If we have only short_name: use short_name
    4. If we have hex_id: use hex_id
    5. Fallback to formatting node_id as hex
    """
    # Clean up names
    long_clean = long_name.strip() if long_name else None
    short_clean = short_name.strip() if short_name else None
    hex_clean = hex_id.strip() if hex_id else None

    # If we have both long and short names and they're different
    if long_clean and short_clean and long_clean != short_clean:
        return f"{long_clean} ({short_clean})"

    # Use single name if available
    if long_clean:
        return long_clean
    if short_clean:
        return short_clean
    if hex_clean:
        return hex_clean

    # Fallback to formatting the node_id
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    else:
        return "Unknown"


def get_bulk_node_short_names(node_ids: list[int]) -> dict[int, str]:
    """
    Get short names for multiple nodes in a single database query.

    Args:
        node_ids: List of node IDs to get short names for

    Returns:
        Dictionary mapping node_id to short_name (or fallback to last 4 hex digits)
    """
    if not node_ids:
        return {}

    logger.debug(f"Getting bulk node short names for {len(node_ids)} nodes")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Use placeholders for the IN clause
        placeholders = ",".join("?" * len(node_ids))
        cursor.execute(
            f"""
            SELECT node_id, short_name
            FROM node_info
            WHERE node_id IN ({placeholders})
        """,
            node_ids,
        )

        db_results = cursor.fetchall()
        conn.close()

        # Process database results
        result = {}
        found_ids = set()

        for row in db_results:
            node_id = row["node_id"]
            found_ids.add(node_id)

            short_name = row["short_name"]
            if short_name and short_name.strip():
                # Use the actual short name from the database
                result[node_id] = short_name.strip()
            else:
                # Fallback to last 4 hex digits (lowercase)
                result[node_id] = f"{node_id:08x}"[-4:]

        # Handle nodes not found in database
        for node_id in node_ids:
            if node_id not in found_ids:
                # Fallback to last 4 hex digits (lowercase)
                result[node_id] = f"{node_id:08x}"[-4:]

        logger.debug(f"Bulk node short names completed: {len(result)} names returned")
        return result

    except Exception as e:
        logger.error(f"Error getting bulk node short names: {e}")
        # Return fallback names for all IDs
        result = {}
        for node_id in node_ids:
            result[node_id] = f"{node_id:08x}"[-4:]
        return result


def get_bulk_node_names(node_ids: list[int]) -> dict[int, str]:
    """
    Get display names for multiple nodes in a single database query.

    Args:
        node_ids: List of node IDs to get names for

    Returns:
        Dictionary mapping node_id to display_name
    """
    if not node_ids:
        return {}

    logger.debug(f"Getting bulk node names for {len(node_ids)} nodes")

    # Check cache first
    result = {}
    uncached_ids = []

    with cache_lock:
        for node_id in node_ids:
            if node_id in node_name_cache:
                result[node_id] = node_name_cache[node_id]
            else:
                uncached_ids.append(node_id)

    # Query database for uncached nodes
    if uncached_ids:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Use placeholders for the IN clause
            placeholders = ",".join("?" * len(uncached_ids))
            cursor.execute(
                f"""
                SELECT node_id, long_name, short_name, hex_id
                FROM node_info
                WHERE node_id IN ({placeholders})
            """,
                uncached_ids,
            )

            db_results = cursor.fetchall()
            conn.close()

            # Process database results
            found_ids = set()
            for row in db_results:
                node_id = row["node_id"]
                found_ids.add(node_id)

                display_name = _format_node_display_name(
                    node_id, row["long_name"], row["short_name"], row["hex_id"]
                )

                result[node_id] = display_name

                # Cache the result
                with cache_lock:
                    node_name_cache[node_id] = display_name

            # Handle nodes not found in database
            for node_id in uncached_ids:
                if node_id not in found_ids:
                    display_name = f"!{node_id:08x}"
                    result[node_id] = display_name

                    # Cache the fallback result
                    with cache_lock:
                        node_name_cache[node_id] = display_name

        except Exception as e:
            logger.error(f"Error getting bulk node names: {e}")
            # Return fallback names for all uncached IDs
            for node_id in uncached_ids:
                result[node_id] = f"!{node_id:08x}"

    logger.debug(f"Bulk node names completed: {len(result)} names returned")
    return result


def clear_node_name_cache() -> None:
    """Clear the node name cache. Useful for testing or when node info is updated."""
    global node_name_cache
    with cache_lock:
        node_name_cache.clear()
        logger.info("Node name cache cleared")


def get_cache_stats() -> dict[str, int]:
    """Get statistics about the node name cache."""
    with cache_lock:
        return {
            "cached_nodes": len(node_name_cache),
        }


def convert_node_id(node_id: int | str) -> int:
    """
    Convert node ID to integer, handling both hex (!12345678) and decimal formats.

    Args:
        node_id: Node ID in various formats (int, hex string with !, decimal string, etc.)

    Returns:
        Node ID as integer

    Raises:
        ValueError: If the node_id cannot be converted to an integer
    """
    if isinstance(node_id, int):
        return node_id

    if isinstance(node_id, str):
        node_id = node_id.strip()

        if node_id.startswith("!"):
            # Hex format with ! prefix
            return int(node_id[1:], 16)
        elif node_id.startswith("0x"):
            # Hex format with 0x prefix
            return int(node_id, 16)
        else:
            # All other strings are treated as decimal
            return int(node_id, 10)

    raise ValueError(f"Cannot convert {type(node_id)} to integer")


def transform_nodes_for_template(
    raw_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Transform raw node data from repository to format expected by templates.

    Args:
        raw_nodes: List of dicts with keys: node_id, long_name, short_name, hex_id, packet_count

    Returns:
        List of dicts with keys: id, name, packet_count
    """
    transformed_nodes = []
    for node in raw_nodes:
        # Use the same fallback hierarchy as _format_node_display_name
        long_name = node.get("long_name", "").strip() if node.get("long_name") else None
        short_name = (
            node.get("short_name", "").strip() if node.get("short_name") else None
        )
        hex_id = node.get("hex_id", "").strip() if node.get("hex_id") else None

        # Determine base display name
        if long_name:
            base_name = long_name
        elif short_name:
            base_name = short_name
        elif hex_id:
            base_name = hex_id
        else:
            base_name = f"!{node['node_id']:08x}"

        # Format with packet count
        packet_count = node.get("packet_count", 0)
        display_name = f"{base_name} ({packet_count} packets)"

        transformed_nodes.append(
            {"id": node["node_id"], "name": display_name, "packet_count": packet_count}
        )
    return transformed_nodes


# Ensure the cache cleanup thread is stopped before the logging system shuts down
atexit.register(stop_cache_cleanup)
