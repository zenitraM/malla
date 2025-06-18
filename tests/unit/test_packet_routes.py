"""
Unit tests for packet route functionality including payload decoding.
"""

from unittest.mock import patch

from meshtastic import mesh_pb2

from src.malla.routes.packet_routes import decode_packet_payload


class TestDecodePacketPayload:
    """Test the decode_packet_payload function for various packet types."""

    def test_decode_packet_payload_no_raw_payload(self):
        """Test decode_packet_payload when packet has no raw payload."""
        packet = {
            "id": 1,
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": None,
            "payload_length": 0,
        }

        result = decode_packet_payload(packet)
        assert result is None

    def test_decode_text_message_app_success(self):
        """Test successful TEXT_MESSAGE_APP decoding."""
        message = "Hello, Mesh!"
        packet = {
            "id": 1,
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": message.encode("utf-8"),
            "payload_length": len(message),
        }

        result = decode_packet_payload(packet)
        assert result is not None
        assert result["portnum"] == "TEXT_MESSAGE_APP"
        assert result["decoded"] is True
        assert result["text"] == message
        assert result["error"] is None

    def test_decode_text_message_app_unicode_error(self):
        """Test TEXT_MESSAGE_APP decoding with invalid UTF-8."""
        invalid_utf8 = b"\xff\xfe\xfd"
        packet = {
            "id": 1,
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": invalid_utf8,
            "payload_length": len(invalid_utf8),
        }

        result = decode_packet_payload(packet)
        assert result is not None
        assert result["portnum"] == "TEXT_MESSAGE_APP"
        assert result["decoded"] is True
        assert result["text"] == invalid_utf8.hex()
        assert "Could not decode as UTF-8" in result["error"]

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_decode_neighborinfo_app_success(self, mock_get_node_names):
        """Test successful NEIGHBORINFO_APP decoding."""
        # Mock node name resolution
        mock_get_node_names.return_value = {
            0x12345678: "Node1",
            0x87654321: "Node2",
            0xABCDEF00: "Node3",
            0x11111111: "ReportingNode",
        }

        # Create NeighborInfo protobuf message
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 0x11111111
        neighbor_info.last_sent_by_id = 0x12345678
        neighbor_info.node_broadcast_interval_secs = 900

        # Add neighbors
        neighbor1 = neighbor_info.neighbors.add()
        neighbor1.node_id = 0x12345678
        neighbor1.snr = 10.5
        neighbor1.last_rx_time = 1640995200  # 2022-01-01 00:00:00 UTC
        neighbor1.node_broadcast_interval_secs = 600

        neighbor2 = neighbor_info.neighbors.add()
        neighbor2.node_id = 0x87654321
        neighbor2.snr = -2.3
        neighbor2.last_rx_time = 1640995260  # 2022-01-01 00:01:00 UTC
        neighbor2.node_broadcast_interval_secs = 300

        neighbor3 = neighbor_info.neighbors.add()
        neighbor3.node_id = 0xABCDEF00
        neighbor3.snr = 0.0
        neighbor3.last_rx_time = 0  # Invalid/missing timestamp
        neighbor3.node_broadcast_interval_secs = 0  # Missing interval

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        result = decode_packet_payload(packet)

        # Verify basic structure
        assert result is not None
        assert result["portnum"] == "NEIGHBORINFO_APP"
        assert result["decoded"] is True
        assert result["error"] is None

        # Verify data structure
        data = result["data"]
        assert data["node_id"] == 0x11111111
        assert data["last_sent_by_id"] == 0x12345678
        assert data["node_broadcast_interval_secs"] == 900
        assert data["neighbor_count"] == 3
        assert data["node_name"] == "ReportingNode"
        assert data["last_sent_by_name"] == "Node1"

        # Verify neighbors
        neighbors = data["neighbors"]
        assert len(neighbors) == 3

        # Check first neighbor (good signal)
        neighbor1_data = neighbors[0]
        assert neighbor1_data["node_id"] == 0x12345678
        assert neighbor1_data["snr"] == 10.5
        assert neighbor1_data["last_rx_time"] == 1640995200
        assert neighbor1_data["node_broadcast_interval_secs"] == 600
        assert neighbor1_data["node_name"] == "Node1"
        assert neighbor1_data["last_rx_time_str"] == "2022-01-01 00:00:00"

        # Check second neighbor (poor signal)
        neighbor2_data = neighbors[1]
        assert neighbor2_data["node_id"] == 0x87654321
        assert (
            abs(neighbor2_data["snr"] - (-2.3)) < 0.001
        )  # Use approximate equality for floating point
        assert neighbor2_data["last_rx_time"] == 1640995260
        assert neighbor2_data["node_broadcast_interval_secs"] == 300
        assert neighbor2_data["node_name"] == "Node2"
        assert neighbor2_data["last_rx_time_str"] == "2022-01-01 00:01:00"

        # Check third neighbor (missing data)
        neighbor3_data = neighbors[2]
        assert neighbor3_data["node_id"] == 0xABCDEF00
        assert neighbor3_data["snr"] == 0.0
        assert neighbor3_data["last_rx_time"] is None
        assert neighbor3_data["node_broadcast_interval_secs"] is None
        assert neighbor3_data["node_name"] == "Node3"
        assert neighbor3_data["last_rx_time_str"] == "Unknown"

        # Verify node name resolution was called correctly
        expected_calls = [
            [0x12345678, 0x87654321, 0xABCDEF00],  # For neighbors
            [0x11111111, 0x12345678],  # For reporting node and last_sent_by
        ]
        assert mock_get_node_names.call_count == 2
        calls = mock_get_node_names.call_args_list
        assert set(calls[0][0][0]) == set(expected_calls[0])
        assert set(calls[1][0][0]) == set(expected_calls[1])

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_decode_neighborinfo_app_empty_neighbors(self, mock_get_node_names):
        """Test NEIGHBORINFO_APP decoding with no neighbors."""
        mock_get_node_names.return_value = {0x11111111: "LonelyNode"}

        # Create NeighborInfo with no neighbors
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 0x11111111
        neighbor_info.node_broadcast_interval_secs = 900

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        result = decode_packet_payload(packet)

        assert result is not None
        assert result["decoded"] is True
        data = result["data"]
        assert data["neighbor_count"] == 0
        assert data["neighbors"] == []
        assert data["node_name"] == "LonelyNode"

    def test_decode_neighborinfo_app_invalid_protobuf(self):
        """Test NEIGHBORINFO_APP decoding with invalid protobuf data."""
        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": b"invalid protobuf data",
            "payload_length": 20,
        }

        result = decode_packet_payload(packet)

        assert result is not None
        assert result["portnum"] == "NEIGHBORINFO_APP"
        assert result["decoded"] is False
        assert "NeighborInfo decode error" in result["error"]

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_decode_neighborinfo_app_invalid_timestamp(self, mock_get_node_names):
        """Test NEIGHBORINFO_APP decoding with invalid timestamp."""
        mock_get_node_names.return_value = {}

        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 0x11111111

        neighbor = neighbor_info.neighbors.add()
        neighbor.node_id = 0x12345678
        neighbor.snr = 5.0
        neighbor.last_rx_time = 1640995200  # Valid timestamp (2022-01-01)

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        # Mock datetime.fromtimestamp to raise ValueError
        with patch("datetime.datetime") as mock_datetime:
            mock_datetime.fromtimestamp.side_effect = ValueError(
                "timestamp out of range"
            )

            result = decode_packet_payload(packet)

            assert result is not None
            assert result["decoded"] is True
            assert result["data"]["neighbor_count"] == 1
            assert len(result["data"]["neighbors"]) == 1

            neighbor_data = result["data"]["neighbors"][0]
            assert neighbor_data["node_id"] == 0x12345678
            assert neighbor_data["snr"] == 5.0
            # Should handle invalid timestamp gracefully
            assert neighbor_data["last_rx_time_str"] == "Invalid timestamp"

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_decode_neighborinfo_app_no_node_names(self, mock_get_node_names):
        """Test NEIGHBORINFO_APP decoding when node names are not found."""
        mock_get_node_names.return_value = {}  # No node names found

        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 0x11111111

        neighbor = neighbor_info.neighbors.add()
        neighbor.node_id = 0x12345678
        neighbor.snr = 5.0

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        result = decode_packet_payload(packet)

        assert result is not None
        assert result["decoded"] is True
        data = result["data"]
        assert data["node_name"] == "Unknown Node (286331153)"  # Hex: 0x11111111
        neighbors = data["neighbors"]
        assert (
            neighbors[0]["node_name"] == "Unknown Node (305419896)"
        )  # Hex: 0x12345678

    def test_decode_unknown_portnum(self):
        """Test decoding with unknown portnum."""
        packet = {
            "id": 1,
            "portnum_name": "UNKNOWN_APP",
            "raw_payload": b"some data",
            "payload_length": 9,
        }

        result = decode_packet_payload(packet)

        assert result is not None
        assert result["portnum"] == "UNKNOWN_APP"
        assert result["decoded"] is False
        assert result["text"] == b"some data".hex()
        assert "No decoder available for UNKNOWN_APP" in result["error"]

    def test_decode_packet_payload_exception(self):
        """Test decode_packet_payload with general exception."""
        packet = {
            "id": 1,
            "portnum_name": "TRACEROUTE_APP",  # Use a portnum that requires imports
            "raw_payload": b"test",
            "payload_length": 4,
        }

        # Patch the import to raise an exception
        with patch("builtins.__import__", side_effect=Exception("Unexpected error")):
            result = decode_packet_payload(packet)

            assert result is not None
            assert result["portnum"] == "TRACEROUTE_APP"
            assert result["decoded"] is False
            assert "No decoder available" in result["error"]
            assert result["text"] == b"test".hex()


class TestNeighborInfoDataStructure:
    """Test the data structure returned by NEIGHBORINFO_APP decoder."""

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_neighbor_data_completeness(self, mock_get_node_names):
        """Test that all expected fields are present in neighbor data."""
        mock_get_node_names.return_value = {}

        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 123
        neighbor_info.last_sent_by_id = 456
        neighbor_info.node_broadcast_interval_secs = 900

        neighbor = neighbor_info.neighbors.add()
        neighbor.node_id = 789
        neighbor.snr = 7.5
        neighbor.last_rx_time = 1640995200
        neighbor.node_broadcast_interval_secs = 600

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        result = decode_packet_payload(packet)
        assert result is not None
        data = result["data"]

        # Check main data fields
        required_main_fields = [
            "node_id",
            "last_sent_by_id",
            "node_broadcast_interval_secs",
            "neighbors",
            "neighbor_count",
            "node_name",
            "last_sent_by_name",
        ]
        for field in required_main_fields:
            assert field in data, f"Missing field: {field}"

        # Check neighbor data fields
        neighbor_data = data["neighbors"][0]
        required_neighbor_fields = [
            "node_id",
            "snr",
            "last_rx_time",
            "node_broadcast_interval_secs",
            "last_rx_time_str",
            "node_name",
        ]
        for field in required_neighbor_fields:
            assert field in neighbor_data, f"Missing neighbor field: {field}"

    @patch("src.malla.routes.packet_routes.get_bulk_node_names")
    def test_snr_value_types(self, mock_get_node_names):
        """Test that SNR values are handled correctly for different types."""
        mock_get_node_names.return_value = {}

        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.node_id = 123

        # Test various SNR scenarios
        test_cases = [
            (10.5, 10.5),  # Positive float
            (-5.2, -5.2),  # Negative float
            (0.0, 0.0),  # Zero
            (None, None),  # None (should be handled gracefully)
        ]

        for i, (input_snr, _expected_snr) in enumerate(test_cases):
            neighbor = neighbor_info.neighbors.add()
            neighbor.node_id = 1000 + i
            if input_snr is not None:
                neighbor.snr = input_snr
            neighbor.last_rx_time = 1640995200

        packet = {
            "id": 1,
            "portnum_name": "NEIGHBORINFO_APP",
            "raw_payload": neighbor_info.SerializeToString(),
            "payload_length": len(neighbor_info.SerializeToString()),
        }

        result = decode_packet_payload(packet)
        assert result is not None
        neighbors = result["data"]["neighbors"]

        for i, (_, expected_snr) in enumerate(test_cases):
            if expected_snr is not None:
                # Use approximate equality for floating point values
                assert abs(neighbors[i]["snr"] - expected_snr) < 0.01
            else:
                assert neighbors[i]["snr"] is None or neighbors[i]["snr"] == 0.0

    def test_neighborinfo_app_real_packet_data(self, app):
        """Test NEIGHBORINFO_APP decoding with real packet data from packet 38930"""
        with app.app_context():
            # Real packet data from packet 38930 - has zero values for timestamps and intervals
            raw_payload = bytes.fromhex(
                "08a498f4990410a498f4990418c070220b08bc97fc99041500008cc1220b08b8ad97fd05"
                "15000070c0220b08ccd3cfd30d150000b040220b08c4f6c6c50215000082c1220b08e8cbf2810b15000080c1220b0"
                "8b084a59102150000d040220b08c7cfc7a30815000028c1220b089ceb8aad0915000000c0220b0888b3cfe3061500"
                "000040220b08b4b2eba4081500009ac1"
            )

            packet = {
                "id": 38930,
                "portnum_name": "NEIGHBORINFO_APP",
                "raw_payload": raw_payload,
                "payload_length": len(raw_payload),
            }

            result = decode_packet_payload(packet)

            # Verify basic structure
            assert result is not None
            assert result["decoded"] is True
            assert result["portnum"] == "NEIGHBORINFO_APP"
            assert result["data"] is not None

            data = result["data"]

            # Verify main node info
            assert data["node_id"] == 1128074276
            assert data["last_sent_by_id"] == 1128074276
            assert data["node_broadcast_interval_secs"] == 14400  # This one has a value
            assert data["neighbor_count"] == 10

            # Verify neighbors list
            assert len(data["neighbors"]) == 10

            # Check first neighbor (has zero values for timestamp and interval)
            neighbor = data["neighbors"][0]
            assert neighbor["node_id"] == 1128205244
            assert neighbor["snr"] == -17.5  # SNR should be preserved
            assert neighbor["last_rx_time"] is None  # Zero timestamp should become None
            assert (
                neighbor["node_broadcast_interval_secs"] is None
            )  # Zero interval should become None
            assert neighbor["last_rx_time_str"] == "Unknown"  # Should show "Unknown"

            # Check a neighbor with positive SNR
            neighbor_positive_snr = None
            for neighbor in data["neighbors"]:
                if neighbor["snr"] > 0:
                    neighbor_positive_snr = neighbor
                    break

            assert neighbor_positive_snr is not None
            assert neighbor_positive_snr["snr"] > 0
            assert (
                neighbor_positive_snr["last_rx_time"] is None
            )  # Still None for timestamp
            assert (
                neighbor_positive_snr["node_broadcast_interval_secs"] is None
            )  # Still None for interval

            # Verify all neighbors have the same pattern (zero timestamps/intervals)
            for neighbor in data["neighbors"]:
                assert neighbor["last_rx_time"] is None
                assert neighbor["node_broadcast_interval_secs"] is None
                assert neighbor["last_rx_time_str"] == "Unknown"
                assert neighbor["snr"] is not None  # SNR should always be present
                assert isinstance(neighbor["snr"], float)
