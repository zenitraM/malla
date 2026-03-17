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
    logger.info("Chat route accessed")
    try:
        return render_template("chat.html")
    except Exception as e:
        logger.error(f"Error in chat route: {e}")
        return f"Chat error: {e}", 500
