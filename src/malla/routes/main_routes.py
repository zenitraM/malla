"""
Main routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template, request

# Import from the new modular architecture
from ..database.repositories import ChatRepository, DashboardRepository

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def dashboard():
    """Dashboard route with network statistics."""
    try:
        # Get basic dashboard stats
        stats = DashboardRepository.get_stats()

        # Get gateway statistics from the new cached service
        from ..services.gateway_service import GatewayService

        gateway_stats = GatewayService.get_gateway_statistics(hours=24)
        gateway_count = gateway_stats.get("total_gateways", 0)

        return render_template(
            "dashboard.html",
            stats=stats,
            gateway_count=gateway_count,
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        # Fallback to basic stats without gateway info
        stats = DashboardRepository.get_stats()
        return render_template(
            "dashboard.html",
            stats=stats,
            gateway_count=0,
            error_message="Some dashboard features may be unavailable",
        )


@main_bp.route("/chat")
def chat():
    """Chat view displaying recent text messages."""
    selected_channel = request.args.get("channel")
    limit = request.args.get("limit", default=100, type=int)
    limit = max(10, min(limit, 200))

    chat_data = ChatRepository.get_recent_messages(
        limit=limit,
        offset=0,
        channel=selected_channel,
    )
    channels = ChatRepository.get_channels()

    return render_template(
        "chat.html",
        messages=chat_data["messages"],
        channels=channels,
        selected_channel=selected_channel,
        chat_meta=chat_data,
    )


@main_bp.route("/map")
def map_view():
    """Node location map view."""
    try:
        return render_template("map.html")
    except Exception as e:
        logger.error(f"Error in map route: {e}")
        return f"Map error: {e}", 500


@main_bp.route("/longest-links")
def longest_links():
    """Longest links analysis page."""
    logger.info("Longest links route accessed")
    try:
        return render_template("longest_links.html")
    except Exception as e:
        logger.error(f"Error in longest links route: {e}")
        return f"Longest links error: {e}", 500
