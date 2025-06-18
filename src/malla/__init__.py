"""
Malla - Meshtastic MQTT to SQLite capture and web monitoring tools.

A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data.
"""

__version__ = "0.1.0"
__title__ = "Malla"
__description__ = "A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data"
__author__ = "Malla Contributors"
__license__ = "MIT"

# Package-level imports for convenience
from .web_ui import create_app

__all__ = [
    "create_app",
    "__version__",
    "__title__",
    "__description__",
    "__author__",
    "__license__",
]
