"""
Node-related routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template

# Import from the new modular architecture
from ..database.repositories import NodeRepository

logger = logging.getLogger(__name__)
node_bp = Blueprint("node", __name__)


@node_bp.route("/nodes")
def nodes():
    """Node browser page using modern table interface."""
    logger.info("Nodes route accessed")
    try:
        # Get summary statistics for the cards
        # We'll get basic counts for the summary cards
        all_nodes = NodeRepository.get_nodes(limit=10000)  # Get all nodes for stats
        nodes_data = all_nodes.get("nodes", [])

        # Calculate summary statistics
        total_count = len(nodes_data)
        active_count = len([n for n in nodes_data if n.get("packet_count_24h", 0) > 0])
        named_count = len([n for n in nodes_data if n.get("long_name")])
        recent_count = len([n for n in nodes_data if n.get("last_packet_time")])

        summary = {
            "total_count": total_count,
            "active_count": active_count,
            "named_count": named_count,
            "recent_count": recent_count,
        }

        logger.info("Nodes page rendered")
        return render_template(
            "nodes.html",
            summary=summary,
        )
    except Exception as e:
        logger.error(f"Error in nodes route: {e}")
        return f"Nodes error: {e}", 500


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

        logger.info("Node detail page rendered successfully")
        return render_template("node_detail.html", **node_details)
    except Exception as e:
        logger.error(f"Error in node detail route: {e}")
        return f"Node detail error: {e}", 500
