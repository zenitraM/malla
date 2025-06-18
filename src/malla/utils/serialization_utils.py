"""
Serialization utility functions for Meshtastic Mesh Health Web UI
"""

import base64
from typing import Any


def convert_bytes_to_base64(obj: Any) -> Any:
    """
    Recursively convert bytes objects to base64 strings for JSON serialization.

    Args:
        obj: The object to process, which may contain bytes objects

    Returns:
        The object with all bytes converted to base64 strings
    """
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("utf-8")
    elif isinstance(obj, dict):
        return {k: convert_bytes_to_base64(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_bytes_to_base64(item) for item in obj]
    else:
        return obj
