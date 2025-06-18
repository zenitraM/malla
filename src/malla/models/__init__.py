"""
Data models for Meshtastic Mesh Health Web UI.

This package contains data structures and parsing logic for different entities.
"""

from .traceroute import TracerouteHop, TraceroutePacket, TraceroutePath

__all__ = ["TraceroutePacket", "TracerouteHop", "TraceroutePath"]
