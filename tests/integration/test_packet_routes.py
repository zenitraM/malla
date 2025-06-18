"""
Integration tests for packet routes
"""

import pytest


class TestPacketRoutes:
    """Test packet-related routes."""

    def test_packets_page_renders(self, client):
        """Test that the packets page renders successfully."""
        response = client.get("/packets")
        assert response.status_code == 200
        assert b"Packets" in response.data
        assert b"packetsTable" in response.data  # Table container ID

    def test_packet_detail_page_renders(self, client):
        """Test that a packet detail page renders successfully."""
        # First, get a packet ID from the database
        from src.malla.database.repositories import PacketRepository

        # Get the first packet
        result = PacketRepository.get_packets(limit=1, offset=0)
        if result["packets"]:
            packet_id = result["packets"][0]["id"]

            # Test the packet detail page
            response = client.get(f"/packet/{packet_id}")
            assert response.status_code == 200
            assert b"Packet #" in response.data
            assert str(packet_id).encode() in response.data
        else:
            pytest.skip("No packets available for testing")

    def test_packet_detail_not_found(self, client):
        """Test that non-existent packet returns 404."""
        response = client.get("/packet/999999")
        assert response.status_code == 404
        assert b"Packet not found" in response.data
