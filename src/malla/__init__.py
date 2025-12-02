"""
Malla - Meshtastic MQTT to SQLite capture and web monitoring tools.

A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data.
"""

import subprocess
from pathlib import Path

__version__ = "0.1.0"
__title__ = "Malla"
__description__ = "A comprehensive web UI for browsing and analyzing Meshtastic mesh network health data"
__author__ = "Malla Contributors"
__license__ = "MIT"

__all__ = [
    "create_app",
    "__version__",
    "get_version",
    "__title__",
    "__description__",
    "__author__",
    "__license__",
]


def get_version():
    """
    Get version information for the application.

    In a rolling release model, this returns the git commit hash.
    Falls back to the package version if git is not available.

    Returns:
        str: Version string (git commit hash or package version)
    """
    try:
        # Try to get git commit hash
        repo_path = Path(__file__).parent.parent.parent
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # Git not available or not a git repository
        pass

    # Fallback to package version
    return __version__


# Import create_app at the end to avoid circular import issues
# This import comes after all module-level definitions
from .web_ui import create_app  # noqa: E402
