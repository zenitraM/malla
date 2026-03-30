"""
Chat routes for the Meshtastic Mesh Health Web UI.
"""

import logging

from flask import Blueprint, render_template

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/chat")
def chat():
    """Chat view showing text messages in an IRC-like layout."""
    logger.debug("Chat route accessed")
    try:
        return render_template("chat.html")
    except Exception:
        logger.exception("Error in chat route")
        return "Internal server error", 500
