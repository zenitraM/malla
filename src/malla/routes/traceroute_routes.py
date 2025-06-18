"""
Traceroute-related routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template, request

# Import from the new modular architecture

logger = logging.getLogger(__name__)
traceroute_bp = Blueprint("traceroute", __name__)


@traceroute_bp.route("/traceroute")
def traceroute():
    """Traceroute analysis page using modern table interface."""
    logger.info("Traceroute route accessed")
    try:
        # Determine if the request URL already contains filter parameters. If it
        # does, we want the front-end ModernTable to *defer* the initial data
        # load until those filters have been applied client-side – otherwise we
        # would wastefully fire an unfiltered request first.

        filter_params = {
            "from_node",
            "to_node",
            "route_node",
            "gateway_id",
            "return_path_only",
            "start_time",
            "end_time",
        }

        has_filters = any(param in request.args for param in filter_params)

        logger.info(
            "Traceroute page rendered (has_filters=%s, args=%s)",
            has_filters,
            dict(request.args),
        )

        return render_template("traceroute.html", defer_initial_load=has_filters)
    except Exception as e:
        logger.error(f"Error in traceroute route: {e}")
        return f"Traceroute error: {e}", 500


@traceroute_bp.route("/traceroute-hops")
def traceroute_hops():
    """Traceroute hops visualization page."""
    logger.info("Traceroute hops route accessed")
    try:
        return render_template("traceroute_hops.html")
    except Exception as e:
        logger.error(f"Error in traceroute hops route: {e}")
        return f"Traceroute hops error: {e}", 500


@traceroute_bp.route("/traceroute-graph")
def traceroute_graph():
    """Traceroute network graph visualization page."""
    logger.info("Traceroute graph route accessed")
    try:
        # Get filter parameters
        hours = request.args.get("hours", 24, type=int)
        min_snr = request.args.get("min_snr", -200.0, type=float)
        include_indirect = request.args.get("include_indirect", False, type=bool)

        # Validate parameters
        if hours < 1 or hours > 168:  # Max 7 days
            hours = 24
        # Allow -200 as special "no limit" value, otherwise validate normal range
        if min_snr < -200 or min_snr > 20:
            min_snr = -200.0

        return render_template(
            "traceroute_graph.html",
            hours=hours,
            min_snr=min_snr,
            include_indirect=include_indirect,
        )
    except Exception as e:
        logger.error(f"Error in traceroute graph route: {e}")
        return f"Traceroute graph error: {e}", 500
