"""
Integration tests for NEIGHBORINFO_APP packet handling.

Tests the complete flow from packet creation to web interface display.
"""

import time

import pytest

try:
    import meshtastic.protobuf.mesh_pb2 as mesh_pb2

    protobuf_available = True
except ImportError:
    protobuf_available = False
    mesh_pb2 = None

from tests.fixtures.database_fixtures import DatabaseFixtures


class TestNeighborInfoPacketIntegration:
    """Integration tests for NEIGHBORINFO_APP packet handling."""

    def create_neighborinfo_packet(
        self,
        fixtures,
        packet_id=None,
        from_node_id=None,
        neighbors_data=None,
        node_id=None,
        last_sent_by_id=None,
        node_broadcast_interval_secs=None,
    ):
        """Helper to create a NEIGHBORINFO_APP packet with custom neighbor data."""
        if not protobuf_available or mesh_pb2 is None:
            pytest.skip("Protobuf not available")

        # Create the NeighborInfo protobuf
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = node_id or from_node_id or 0x11111111
        neighbor_info.last_sent_by_id = last_sent_by_id or 0
        neighbor_info.node_broadcast_interval_secs = node_broadcast_interval_secs or 0

        # Add neighbors
        if neighbors_data:
            for neighbor_data in neighbors_data:
                neighbor = neighbor_info.neighbors.add()
                neighbor.node_id = neighbor_data["node_id"]
                neighbor.snr = neighbor_data.get("snr", 0.0)
                neighbor.last_rx_time = neighbor_data.get("last_rx_time", 0)
                neighbor.node_broadcast_interval_secs = neighbor_data.get(
                    "node_broadcast_interval_secs", 0
                )

        # Serialize the protobuf
        raw_payload = neighbor_info.SerializeToString()

        # Create packet using the base method and then update with our custom payload
        packet = fixtures.create_test_packet(
            packet_id=packet_id,
            from_node_id=from_node_id,
            portnum=71,  # NEIGHBORINFO_APP
            portnum_name="NEIGHBORINFO_APP",
        )

        # Override the payload with our custom data
        packet["raw_payload"] = raw_payload
        packet["payload_length"] = len(raw_payload)

        return packet

    @pytest.mark.skipif(not protobuf_available, reason="Protobuf not available")
    def test_neighborinfo_packet_creation_and_display(self, app, client, temp_database):
        """Test creating and displaying a NEIGHBORINFO_APP packet."""
        fixtures = DatabaseFixtures()

        # Create test packet with neighbor data
        neighbors_data = [
            {
                "node_id": 0x12345678,
                "snr": 8.5,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },
            {
                "node_id": 0x87654321,
                "snr": -2.1,
                "last_rx_time": int(time.time()) - 300,
                "node_broadcast_interval_secs": 1800,
            },
            {
                "node_id": 0xAABBCCDD,
                "snr": 12.3,
                "last_rx_time": 0,
                "node_broadcast_interval_secs": 0,
            },  # Zero values
        ]

        packet = self.create_neighborinfo_packet(
            fixtures,
            packet_id=99999,
            from_node_id=0x11111111,
            neighbors_data=neighbors_data,
            node_id=0x11111111,
            last_sent_by_id=0x22222222,
            node_broadcast_interval_secs=1200,
        )

        # Insert packet into database
        with app.app_context():
            from src.malla.database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                ),
            )
            conn.commit()
            conn.close()

        # Test packet detail page
        response = client.get(f"/packet/{packet['id']}")
        assert response.status_code == 200

        # Check that the page contains neighbor information
        html = response.get_data(as_text=True)
        assert "NEIGHBORINFO_APP" in html
        assert "Neighbor Information Report" in html
        assert "Neighbors Found:" in html
        assert "5" in html  # Number of neighbors

        # Check for specific neighbor data
        assert "8.5" in html  # SNR value
        assert "-2.1" in html  # Negative SNR
        assert "12.3" in html  # High SNR
        assert "Unknown" in html  # For zero timestamp/interval values

    @pytest.mark.skipif(not protobuf_available, reason="Protobuf not available")
    def test_neighborinfo_packet_empty_neighbors(self, app, client, temp_database):
        """Test NEIGHBORINFO_APP packet with no neighbors."""
        fixtures = DatabaseFixtures()

        packet = self.create_neighborinfo_packet(
            fixtures,
            packet_id=99998,
            from_node_id=0x11111111,
            neighbors_data=[],  # Empty neighbors list
            node_id=0x11111111,
        )

        # Insert packet into database
        with app.app_context():
            from src.malla.database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                ),
            )
            conn.commit()
            conn.close()

        # Test packet detail page
        response = client.get(f"/packet/{packet['id']}")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "NEIGHBORINFO_APP" in html
        assert "Neighbors Found:" in html
        assert "0" in html  # Zero neighbors
        assert "No neighbors reported" in html

    @pytest.mark.skipif(not protobuf_available, reason="Protobuf not available")
    def test_neighborinfo_packet_with_unknown_nodes(self, app, client, temp_database):
        """Test NEIGHBORINFO_APP packet with unknown node IDs."""
        fixtures = DatabaseFixtures()

        # Use node IDs that don't exist in the test database
        neighbors_data = [
            {
                "node_id": 0x99999999,
                "snr": 5.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 600,
            }
        ]

        packet = self.create_neighborinfo_packet(
            fixtures,
            packet_id=99997,
            from_node_id=0x88888888,  # Unknown node
            neighbors_data=neighbors_data,
            node_id=0x88888888,
        )

        # Insert packet into database
        with app.app_context():
            from src.malla.database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                ),
            )
            conn.commit()
            conn.close()

        # Test packet detail page
        response = client.get(f"/packet/{packet['id']}")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "NEIGHBORINFO_APP" in html
        assert "Neighbors Found:" in html
        assert "1" in html  # Number of neighbors

        # Check for the actual node ID format that appears in the template
        assert "!99999999" in html  # The hex format of node_id 2576980377
        assert "5.0 dB" in html  # SNR value
        assert "Excellent" in html  # Signal quality

    @pytest.mark.skipif(not protobuf_available, reason="Protobuf not available")
    def test_neighborinfo_packet_decode_error(self, app, client, temp_database):
        """Test NEIGHBORINFO_APP packet with invalid protobuf data."""
        fixtures = DatabaseFixtures()

        # Create packet with invalid protobuf data
        packet = fixtures.create_test_packet(
            packet_id=99996,
            from_node_id=0x11111111,
            portnum=71,
            portnum_name="NEIGHBORINFO_APP",
        )

        # Override with invalid protobuf data
        packet["raw_payload"] = b"\x00\x01\x02\x03\x04"  # Invalid protobuf
        packet["payload_length"] = len(packet["raw_payload"])

        # Insert packet into database
        with app.app_context():
            from src.malla.database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                ),
            )
            conn.commit()
            conn.close()

        # Test packet detail page
        response = client.get(f"/packet/{packet['id']}")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "NEIGHBORINFO_APP" in html
        assert "NeighborInfo decode error" in html

    @pytest.mark.skipif(not protobuf_available, reason="Protobuf not available")
    def test_neighborinfo_packet_various_snr_levels(self, app, client, temp_database):
        """Test NEIGHBORINFO_APP packet with various SNR levels for visual verification."""
        fixtures = DatabaseFixtures()

        # Create neighbors with different SNR levels to test color coding
        neighbors_data = [
            {
                "node_id": 0x11111111,
                "snr": 15.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },  # Excellent
            {
                "node_id": 0x22222222,
                "snr": 8.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },  # Good
            {
                "node_id": 0x33333333,
                "snr": 2.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },  # Fair
            {
                "node_id": 0x44444444,
                "snr": -5.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },  # Poor
            {
                "node_id": 0x55555555,
                "snr": 0.0,
                "last_rx_time": int(time.time()),
                "node_broadcast_interval_secs": 900,
            },  # Zero
        ]

        packet = self.create_neighborinfo_packet(
            fixtures,
            packet_id=99995,
            from_node_id=0x11111111,
            neighbors_data=neighbors_data,
            node_id=0x11111111,
        )

        # Insert packet into database
        with app.app_context():
            from src.malla.database.connection import get_db_connection

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                ),
            )
            conn.commit()
            conn.close()

        # Test packet detail page
        response = client.get(f"/packet/{packet['id']}")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "NEIGHBORINFO_APP" in html

        # Check for SNR values
        assert "15.0" in html
        assert "8.0" in html
        assert "2.0" in html
        assert "-5.0" in html
        assert "0.0" in html


class TestNeighborInfoPacketListIntegration:
    """Integration tests for NEIGHBORINFO_APP packets in list views."""

    def create_neighborinfo_packet(
        self,
        fixtures,
        packet_id=None,
        from_node_id=None,
        neighbors_data=None,
        node_id=None,
        last_sent_by_id=None,
        node_broadcast_interval_secs=None,
    ):
        """Create a NEIGHBORINFO_APP packet for testing."""
        if not protobuf_available or mesh_pb2 is None:
            pytest.skip("Protobuf library not available")

        # Create NeighborInfo protobuf message
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = node_id or from_node_id or 0x11111111
        neighbor_info.last_sent_by_id = last_sent_by_id or from_node_id or 0x11111111
        neighbor_info.node_broadcast_interval_secs = node_broadcast_interval_secs or 900

        # Add neighbors
        if neighbors_data:
            for neighbor_data in neighbors_data:
                neighbor = neighbor_info.neighbors.add()
                neighbor.node_id = neighbor_data["node_id"]
                neighbor.snr = neighbor_data["snr"]
                neighbor.last_rx_time = neighbor_data.get("last_rx_time", 0)
                neighbor.node_broadcast_interval_secs = neighbor_data.get(
                    "node_broadcast_interval_secs", 900
                )

        # Serialize to bytes
        raw_payload = neighbor_info.SerializeToString()

        # Create packet using fixtures
        packet = fixtures.create_test_packet(
            packet_id=packet_id,
            from_node_id=from_node_id,
            portnum=71,
            portnum_name="NEIGHBORINFO_APP",
        )

        # Override payload
        packet["raw_payload"] = raw_payload
        packet["payload_length"] = len(raw_payload)

        return packet

    def test_neighborinfo_packets_in_list(self, temp_database, app):
        """Test that NEIGHBORINFO_APP packets appear in the packets list."""
        if not protobuf_available or mesh_pb2 is None:
            pytest.skip("Protobuf library not available")

        fixtures = DatabaseFixtures()

        with app.app_context():
            # Create test packets
            self.create_neighborinfo_packet(
                fixtures,
                packet_id=99994,
                from_node_id=286331153,
                neighbors_data=[
                    {
                        "node_id": 305419896,
                        "snr": 8.5,
                        "last_rx_time": 0,
                        "node_broadcast_interval_secs": 0,
                    },
                    {
                        "node_id": 858993459,
                        "snr": -2.1,
                        "last_rx_time": 0,
                        "node_broadcast_interval_secs": 0,
                    },
                    {
                        "node_id": 1431655765,
                        "snr": 12.3,
                        "last_rx_time": 0,
                        "node_broadcast_interval_secs": 0,
                    },
                ],
            )

            self.create_neighborinfo_packet(
                fixtures,
                packet_id=99995,
                from_node_id=1450704904,
                neighbors_data=[],  # Empty neighbors
            )

        # Test packets list page
        response = app.test_client().get("/packets")
        assert response.status_code == 200

        # Check that the packets list page loads correctly
        html = response.get_data(as_text=True)
        assert "Packets" in html

        # Check that the table structure is present
        assert "packetsTable" in html

        # Test that NEIGHBORINFO_APP is available in the packet types API
        response = app.test_client().get("/api/meshtastic/packet-types")
        assert response.status_code == 200

        packet_types_data = response.get_json()
        assert "packet_types" in packet_types_data

        # Check that NEIGHBORINFO_APP is in the packet types
        packet_types = dict(packet_types_data["packet_types"])
        assert "Neighbor Info" in packet_types.values()
