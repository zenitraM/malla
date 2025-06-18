"""
Main routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template

# Import from the new modular architecture
from ..database.repositories import (
    DashboardRepository,
    PacketRepository,
)
from ..services import LocationService

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def dashboard():
    """Comprehensive dashboard showing overview statistics."""
    logger.info("Dashboard route accessed")
    try:
        # Get basic dashboard stats (without gateway filtering for heterogeneous networks)
        stats = DashboardRepository.get_stats()

        # Get gateway count for informational purposes (only need the count, not the full list)
        gateway_count = PacketRepository.get_unique_gateway_count()

        logger.info("Dashboard rendered successfully")
        return render_template(
            "dashboard.html",
            stats=stats,
            gateway_count=gateway_count,
        )
    except Exception as e:
        logger.error(f"Error in dashboard route: {e}")
        return f"Dashboard error: {e}", 500


@main_bp.route("/map")
def map_view():
    """Node location map view."""
    logger.info("Map route accessed")
    try:
        # Retrieve locations once and reuse for statistics to avoid duplicate heavy queries
        locations = LocationService.get_node_locations()
        stats = LocationService.get_location_statistics(locations)
        logger.info(
            f"Map rendered with {len(locations)} locations (stats calculated using same dataset)"
        )
        return render_template("map.html", locations=locations, stats=stats)
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
