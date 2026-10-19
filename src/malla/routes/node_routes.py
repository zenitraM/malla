"""
Node-related routes for the Meshtastic Mesh Health Web UI
"""

import logging
import time
from datetime import UTC, datetime

from flask import Blueprint, render_template

# Import from the new modular architecture
from ..database.repositories import LocationRepository, NodeRepository
from ..fingerprint import verdict_min_version

logger = logging.getLogger(__name__)
node_bp = Blueprint("node", __name__)


@node_bp.route("/nodes")
def nodes():
    """Node browser page using modern table interface."""
    logger.info("Nodes route accessed")
    try:
        logger.info("Nodes page rendered")
        return render_template("nodes.html")
    except Exception as e:
        logger.error(f"Error in nodes route: {e}")
        return f"Nodes error: {e}", 500


# Firmware 2.8 turns position (and telemetry) broadcasts off on public
# channels at the upgrade; a 2.8 node that has not shared a position for this
# long most likely still has them off.
POSITION_HINT_AFTER_SECONDS = 7 * 86400


def _position_opt_in_hint(details: dict) -> dict | None:
    """Explain a missing/stale position on a firmware 2.8+ node, or None."""
    min_version = verdict_min_version(details.get("firmware"))
    if min_version is None or min_version < (2, 8, 0):
        return None
    location = details.get("location") or {}
    last_position = location.get("timestamp_unix")
    if last_position and time.time() - last_position < POSITION_HINT_AFTER_SECONDS:
        return None
    hint: dict = {
        "last_position_str": (
            datetime.fromtimestamp(last_position, UTC).strftime("%Y-%m-%d")
            if last_position
            else None
        ),
        "predecessor": None,
    }
    for pred in details.get("predecessors") or []:
        try:
            old_location = LocationRepository.get_latest_node_location(pred["node_id"])
        except Exception:  # noqa: BLE001 - the hint is decoration only
            old_location = None
        if old_location:
            hint["predecessor"] = {
                "hex_id": pred["hex_id"],
                "date": datetime.fromtimestamp(old_location["timestamp"], UTC).strftime(
                    "%Y-%m-%d"
                ),
            }
            break
    return hint


@node_bp.route("/node/<node_id>")
def node_detail(node_id):
    """Node detail page showing comprehensive information about a specific node."""
    logger.info(f"Node detail route accessed for node {node_id}")
    try:
        # Handle both hex ID and integer node ID
        if isinstance(node_id, str) and node_id.startswith("!"):
            node_id_int = int(node_id[1:], 16)
        elif isinstance(node_id, str) and not node_id.isdigit():
            try:
                node_id_int = int(node_id, 16)
            except ValueError:
                return "Invalid node ID format", 400
        else:
            node_id_int = int(node_id)

        # Get node details using the repository
        node_details = NodeRepository.get_node_details(node_id_int)
        if not node_details:
            return "Node not found", 404

        node = node_details.get("node") or {}
        node_details["firmware"] = NodeRepository.get_firmware_estimate(
            node_id_int, role=node.get("role"), hw_model=node.get("hw_model")
        )
        node_details["same_mac_nodes"] = NodeRepository.get_same_mac_nodes(node_id_int)
        renumbering = NodeRepository.get_renumbering(
            node_id_int, node.get("last_seen_timestamp")
        )
        node_details["successor"] = renumbering["successor"]
        node_details["predecessors"] = renumbering["predecessors"]
        node_details["position_hint"] = _position_opt_in_hint(node_details)

        logger.info("Node detail page rendered successfully")
        return render_template("node_detail.html", **node_details)
    except Exception as e:
        logger.error(f"Error in node detail route: {e}")
        return f"Node detail error: {e}", 500
