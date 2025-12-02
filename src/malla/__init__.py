"""
Malla - Meshtastic MQTT to SQLite capture and web monitoring tools.

A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data.
"""

__title__ = "Malla"
__description__ = "A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data"
__author__ = "Malla Contributors"
__license__ = "MIT"

# Import version from the auto-generated _version.py file
# This file is created by uv-dynamic-versioning during build
try:
    from ._version import __version__
except ImportError:
    # Fallback for development mode when package is not built
    __version__ = "0.1.0.dev0+unknown"

__all__ = [
    "create_app",
    "__version__",
    "__title__",
    "__description__",
    "__author__",
    "__license__",
]


# get_version() simply returns __version__ which is set by uv-dynamic-versioning
def get_version():
    """
    Get version information for the application.

    Returns the version string set by uv-dynamic-versioning during build,
    which includes git commit information for rolling releases.

    Returns:
        str: Version string from uv-dynamic-versioning or fallback
    """
    return __version__


# Import create_app at the end to avoid circular import issues
# This import comes after all module-level definitions
from .web_ui import create_app  # noqa: E402
