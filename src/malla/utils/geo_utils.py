"""
Geographic utility functions for Meshtastic Mesh Health Web UI
"""

import math

# Positions within this radius of (0, 0) are treated as firmware garbage.
# (0, 0) lies in the Atlantic Ocean ~600 km from the nearest coast, so real
# nodes are never affected. Firmware bugs emit near-zero coordinates (e.g.
# 0.00012, -0.003) instead of exactly (0, 0), which dodge simple == 0 checks.
NULL_ISLAND_RADIUS_KM = 50.0


def is_valid_position(latitude: float | None, longitude: float | None) -> bool:
    """
    Check whether decoded coordinates represent a plausible real location.

    Rejects missing values, non-finite numbers, out-of-range coordinates, and
    positions near "null island" (0, 0) produced by firmware bugs.

    Args:
        latitude: Latitude in decimal degrees (or None if unset)
        longitude: Longitude in decimal degrees (or None if unset)

    Returns:
        True if the position is plausible and safe to use.
    """
    if latitude is None or longitude is None:
        return False
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return False
    if not -90.0 <= latitude <= 90.0:
        return False
    if not -180.0 <= longitude <= 180.0:
        return False
    if calculate_distance(latitude, longitude, 0.0, 0.0) < NULL_ISLAND_RADIUS_KM:
        return False
    return True


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees) using the Haversine formula.

    Args:
        lat1: Latitude of first point in decimal degrees
        lon1: Longitude of first point in decimal degrees
        lat2: Latitude of second point in decimal degrees
        lon2: Longitude of second point in decimal degrees

    Returns:
        Distance in kilometers
    """
    # Earth's radius in km
    R = 6371.0

    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the initial bearing from point 1 to point 2.

    Args:
        lat1: Latitude of first point in decimal degrees
        lon1: Longitude of first point in decimal degrees
        lat2: Latitude of second point in decimal degrees
        lon2: Longitude of second point in decimal degrees

    Returns:
        Bearing in degrees (0-360)
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)

    y = math.sin(dlon_rad) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(
        lat2_rad
    ) * math.cos(dlon_rad)

    bearing_rad = math.atan2(y, x)
    bearing_deg = math.degrees(bearing_rad)

    # Normalize to 0-360 degrees
    return (bearing_deg + 360) % 360
