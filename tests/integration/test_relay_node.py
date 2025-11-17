"""Tests for relay_node field display in packets."""

import pytest

from malla.database.repositories import PacketRepository


class TestRelayNode:
    """Test cases for relay_node field in packet details and API."""

    def test_relay_node_in_packet_details(self, test_client, temp_database):
        """Test that relay_node is displayed in packet details page."""
        # Get first packet from repository
        result = PacketRepository.get_packets(limit=1, offset=0)
        if not result["packets"]:
            pytest.skip("No packets in database")

        packet = result["packets"][0]
        packet_id = packet["id"]

        # Access packet detail page
        response = test_client.get(f"/packet/{packet_id}")
        assert response.status_code == 200

        # Check that the page contains relay node information
        html = response.data.decode("utf-8")
        assert "Relay Node:" in html

    def test_relay_node_in_api_packets_data(self, test_client, temp_database):
        """Test that relay_node is included in /api/packets/data endpoint."""
        response = test_client.get("/api/packets/data?limit=10")
        assert response.status_code == 200

        data = response.get_json()
        assert "data" in data

        # Check that packets include relay_node field
        if data["data"]:
            packet = data["data"][0]
            # relay_node should be present (may be None or a number)
            assert "relay_node" in packet

    def test_relay_node_hex_format(self, test_client, temp_database):
        """Test that relay_node field is present and correctly formatted when available."""
        # Get a packet
        result = PacketRepository.get_packets(limit=10, offset=0)
        if not result["packets"]:
            pytest.skip("No packets in database")

        packet = result["packets"][0]
        packet_id = packet["id"]

        response = test_client.get(f"/packet/{packet_id}")
        assert response.status_code == 200

        html = response.data.decode("utf-8")

        # Verify "Relay Node:" label is present
        assert "Relay Node:" in html

        # If packet has relay_node set, verify hex format
        if packet.get("relay_node") and packet["relay_node"] != 0:
            relay_value = packet["relay_node"]
            expected_hex = f"0x{relay_value & 0xFF:02x}"
            assert expected_hex in html.lower()
