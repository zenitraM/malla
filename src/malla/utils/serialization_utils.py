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


def sanitize_floats(obj: Any) -> Any:
    """Recursively replace ``NaN`` and (−)``Infinity`` float values with ``None``.

    Standard JSON does *not* support special floating-point values such as ``NaN``,
    ``Infinity`` or ``-Infinity``.  If they end up in the response payload
    many browsers will fail to parse the JSON produced by :pyfunc:`flask.json.jsonify`.

    This helper walks the supplied structure (dict / list / scalar) and
    converts any offending float to ``None`` so that the resulting payload is
    fully standards-compliant.

    Args:
        obj: Arbitrary, potentially nested, data structure.

    Returns:
        The sanitised structure with only valid JSON scalar values.
    """
    import math

    # Fast-path common scalar types --------------------------------------------------
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj

    if isinstance(obj, str | int | type(None) | bool):
        return obj

    # Recurse for containers ---------------------------------------------------------
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}

    if isinstance(obj, list | tuple | set):
        return [sanitize_floats(v) for v in obj]

    # Anything else (e.g. bytes) leave untouched – other helpers may convert it later
    return obj


__all__ = [
    "convert_bytes_to_base64",
    "sanitize_floats",
]
