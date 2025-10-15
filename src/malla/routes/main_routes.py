"""
Main routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template, request

# Import from the new modular architecture
from ..config import get_config
from ..database.repositories import ChatRepository, DashboardRepository
from ..utils.node_utils import convert_node_id

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
    selected_audience = request.args.get("audience") or "all"
    selected_sender = request.args.get("sender")
    search_query = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", default=100, type=int)
    limit = max(10, min(limit, 200))

    sender_id = None
    if selected_sender:
        try:
            sender_id = convert_node_id(selected_sender)
        except ValueError:
            sender_id = None

    chat_data = ChatRepository.get_recent_messages(
        limit=limit,
        offset=0,
        channel=selected_channel,
        audience=selected_audience,
        sender_id=sender_id,
        search=search_query,
    )
    channels = ChatRepository.get_channels()
    senders = ChatRepository.get_senders()

    channel_label = "All channels"
    if selected_channel:
        for channel in channels:
            if channel["id"] == selected_channel:
                channel_label = channel["label"]
                break

    sender_label = "All senders"
    if selected_sender:
        for sender in senders:
            if sender["id"] == selected_sender:
                sender_label = sender["label"]
                break

    audience_labels = {
        "broadcast": "Broadcast only",
        "direct": "Direct messages",
        "all": "All messages",
    }
    audience_label = audience_labels.get(selected_audience, "All messages")

    config = get_config()
    mqtt_info = {
        "broker": config.mqtt_broker_address,
        "port": config.mqtt_port,
        "topic_prefix": config.mqtt_topic_prefix,
        "topic_suffix": config.mqtt_topic_suffix,
    }

    return render_template(
        "chat.html",
        messages=chat_data["messages"],
        channels=channels,
        selected_channel=selected_channel,
        chat_meta=chat_data,
        senders=senders,
        selected_audience=selected_audience,
        selected_sender=selected_sender,
        search_query=search_query,
        channel_label=channel_label,
        sender_label=sender_label,
        audience_label=audience_label,
        limit_label=str(limit),
        mqtt_info=mqtt_info,
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
