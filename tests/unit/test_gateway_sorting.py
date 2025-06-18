"""
Tests for gateway sorting functionality in both packets and traceroute views.

This module tests that gateway columns sort correctly by gateway count in grouped view,
both at the API level and in the frontend JavaScript logic.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.malla.database.repositories import PacketRepository, TracerouteRepository


class TestGatewaySortingAPI:
    """Test gateway sorting at the API/repository level."""

    def test_packet_repository_gateway_sorting_asc(self):
        """Test that PacketRepository sorts by gateway_count in ascending order when requested."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock the count query results (for total_count estimation)
        # The sample query returns (individual_count, distinct_groups)
        # The total individual query returns just a count
        mock_cursor.fetchone.side_effect = [
            [3, 3],  # Sample query: 3 individual packets, 3 distinct groups
            [3],  # Total individual query: 3 total packets
        ]

        # Mock individual packet records that will be grouped in memory
        # These represent the same packets received by different gateways
        mock_cursor.fetchall.return_value = [
            # Group 1: mesh_packet_id "abc123" - 1 gateway
            {
                "id": 1,
                "timestamp": 1000,
                "from_node_id": 123,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "abc123",
                "gateway_id": "!433d0c24",
                "rssi": -80,
                "snr": 5,
                "hop_limit": 3,
                "hop_start": 5,
                "hop_count": 2,
                "payload_length": 50,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:00:00",
            },
            # Group 2: mesh_packet_id "def456" - 2 gateways
            {
                "id": 2,
                "timestamp": 2000,
                "from_node_id": 789,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "def456",
                "gateway_id": "!433d0c24",
                "rssi": -75,
                "snr": 8,
                "hop_limit": 2,
                "hop_start": 3,
                "hop_count": 1,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:00",
            },
            {
                "id": 3,
                "timestamp": 2001,
                "from_node_id": 789,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "def456",
                "gateway_id": "!da73e9cc",
                "rssi": -70,
                "snr": 10,
                "hop_limit": 0,
                "hop_start": 3,
                "hop_count": 3,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:01",
            },
            # Group 3: mesh_packet_id "ghi789" - 3 gateways
            {
                "id": 4,
                "timestamp": 3000,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!433d0c24",
                "rssi": -85,
                "snr": 3,
                "hop_limit": 3,
                "hop_start": 3,
                "hop_count": 0,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:00",
            },
            {
                "id": 5,
                "timestamp": 3001,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!da73e9cc",
                "rssi": -65,
                "snr": 12,
                "hop_limit": 0,
                "hop_start": 4,
                "hop_count": 4,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:01",
            },
            {
                "id": 6,
                "timestamp": 3002,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!12345678",
                "rssi": -75,
                "snr": 8,
                "hop_limit": 1,
                "hop_start": 3,
                "hop_count": 2,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:02",
            },
        ]

        with patch(
            "src.malla.database.repositories.get_db_connection", return_value=mock_conn
        ):
            result = PacketRepository.get_packets(
                limit=10,
                offset=0,
                order_by="gateway_id",
                order_dir="asc",
                group_packets=True,
            )

        # Test the behavior: results should be sorted by gateway count in ascending order
        packets = result["packets"]
        assert len(packets) == 3  # 3 groups

        # Verify ascending order by gateway count
        assert packets[0]["gateway_count"] == 1  # abc123 group
        assert packets[1]["gateway_count"] == 2  # def456 group
        assert packets[2]["gateway_count"] == 3  # ghi789 group

        # Verify the mesh_packet_ids match expected order
        assert packets[0]["mesh_packet_id"] == "abc123"
        assert packets[1]["mesh_packet_id"] == "def456"
        assert packets[2]["mesh_packet_id"] == "ghi789"

        # Verify gateway lists are correct
        assert packets[0]["gateway_list"] == "!433d0c24"
        assert set(packets[1]["gateway_list"].split(",")) == {"!433d0c24", "!da73e9cc"}
        assert set(packets[2]["gateway_list"].split(",")) == {
            "!433d0c24",
            "!da73e9cc",
            "!12345678",
        }

    def test_packet_repository_gateway_sorting_desc(self):
        """Test that PacketRepository sorts by gateway_count in descending order when requested."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock the count query results (for total_count estimation)
        # The sample query returns (individual_count, distinct_groups)
        # The total individual query returns just a count
        mock_cursor.fetchone.side_effect = [
            [3, 3],  # Sample query: 3 individual packets, 3 distinct groups
            [3],  # Total individual query: 3 total packets
        ]

        # Mock individual packet records (same data as ascending test)
        mock_cursor.fetchall.return_value = [
            # Group 1: mesh_packet_id "abc123" - 1 gateway
            {
                "id": 1,
                "timestamp": 1000,
                "from_node_id": 123,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "abc123",
                "gateway_id": "!433d0c24",
                "rssi": -80,
                "snr": 5,
                "hop_limit": 3,
                "hop_start": 5,
                "hop_count": 2,
                "payload_length": 50,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:00:00",
            },
            # Group 2: mesh_packet_id "def456" - 2 gateways
            {
                "id": 2,
                "timestamp": 2000,
                "from_node_id": 789,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "def456",
                "gateway_id": "!433d0c24",
                "rssi": -75,
                "snr": 8,
                "hop_limit": 2,
                "hop_start": 3,
                "hop_count": 1,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:00",
            },
            {
                "id": 3,
                "timestamp": 2001,
                "from_node_id": 789,
                "to_node_id": 456,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "def456",
                "gateway_id": "!da73e9cc",
                "rssi": -70,
                "snr": 10,
                "hop_limit": 0,
                "hop_start": 3,
                "hop_count": 3,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:01",
            },
            # Group 3: mesh_packet_id "ghi789" - 3 gateways
            {
                "id": 4,
                "timestamp": 3000,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!433d0c24",
                "rssi": -85,
                "snr": 3,
                "hop_limit": 3,
                "hop_start": 3,
                "hop_count": 0,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:00",
            },
            {
                "id": 5,
                "timestamp": 3001,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!da73e9cc",
                "rssi": -65,
                "snr": 12,
                "hop_limit": 0,
                "hop_start": 4,
                "hop_count": 4,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:01",
            },
            {
                "id": 6,
                "timestamp": 3002,
                "from_node_id": 111,
                "to_node_id": 222,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "mesh_packet_id": "ghi789",
                "gateway_id": "!12345678",
                "rssi": -75,
                "snr": 8,
                "hop_limit": 1,
                "hop_start": 3,
                "hop_count": 2,
                "payload_length": 100,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:02:02",
            },
        ]

        with patch(
            "src.malla.database.repositories.get_db_connection", return_value=mock_conn
        ):
            result = PacketRepository.get_packets(
                limit=10,
                offset=0,
                order_by="gateway_id",
                order_dir="desc",
                group_packets=True,
            )

        # Test the behavior: results should be sorted by gateway count in descending order
        packets = result["packets"]
        assert len(packets) == 3  # 3 groups

        # Verify descending order by gateway count
        assert packets[0]["gateway_count"] == 3  # ghi789 group
        assert packets[1]["gateway_count"] == 2  # def456 group
        assert packets[2]["gateway_count"] == 1  # abc123 group

        # Verify the mesh_packet_ids match expected order
        assert packets[0]["mesh_packet_id"] == "ghi789"
        assert packets[1]["mesh_packet_id"] == "def456"
        assert packets[2]["mesh_packet_id"] == "abc123"

    def test_traceroute_repository_gateway_sorting_asc(self):
        """Test that TracerouteRepository sorts by gateway_count in ascending order when requested."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock the database query results
        # First call: total count query (returns count as tuple/row)
        # Second call: no longer used (removed sample count estimation)
        mock_cursor.fetchone.side_effect = [
            (2,),  # Total count query result
        ]

        # Mock the main query results - individual packets that will be grouped in memory
        # These represent individual packet records, not pre-grouped results
        mock_cursor.fetchall.return_value = [
            # First group: mesh_packet_id="trace123" with 1 gateway
            {
                "id": 1,
                "timestamp": 1000,
                "from_node_id": 123,
                "to_node_id": 456,
                "mesh_packet_id": "trace123",
                "gateway_id": "!433d0c24",
                "hop_start": 3,
                "hop_limit": 1,
                "rssi": -80,
                "snr": 5,
                "payload_length": 50,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:00:00",
                "raw_payload": b"test",
            },
            # Second group: mesh_packet_id="trace456" with 2 gateways (2 individual records)
            {
                "id": 2,
                "timestamp": 2000,
                "from_node_id": 789,
                "to_node_id": 456,
                "mesh_packet_id": "trace456",
                "gateway_id": "!433d0c24",
                "hop_start": 4,
                "hop_limit": 3,
                "rssi": -75,
                "snr": 8,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:00",
                "raw_payload": b"test2",
            },
            {
                "id": 3,
                "timestamp": 2001,
                "from_node_id": 789,
                "to_node_id": 456,
                "mesh_packet_id": "trace456",  # Same mesh_packet_id as above
                "gateway_id": "!da73e9cc",  # Different gateway
                "hop_start": 2,
                "hop_limit": 1,
                "rssi": -70,
                "snr": 10,
                "payload_length": 75,
                "processed_successfully": 1,
                "timestamp_str": "2024-01-01 12:01:01",
                "raw_payload": b"test2_longer",  # Longer payload to test best selection
            },
        ]

        with patch(
            "src.malla.database.repositories.get_db_connection", return_value=mock_conn
        ):
            result = TracerouteRepository.get_traceroute_packets(
                limit=10,
                offset=0,
                order_by="gateway_id",
                order_dir="asc",
                group_packets=True,
            )

        # Verify results are correctly grouped and sorted by gateway count
        packets = result["packets"]
        assert len(packets) == 2

        # First packet should have 1 gateway (ascending order)
        assert packets[0]["gateway_count"] == 1
        assert packets[0]["mesh_packet_id"] == "trace123"
        assert packets[0]["gateway_list"] == "!433d0c24"

        # Second packet should have 2 gateways
        assert packets[1]["gateway_count"] == 2
        assert packets[1]["mesh_packet_id"] == "trace456"
        # Gateway list order may vary due to set() usage, so check both gateways are present
        gateway_list = packets[1]["gateway_list"]
        assert "!433d0c24" in gateway_list
        assert "!da73e9cc" in gateway_list
        assert gateway_list.count(",") == 1  # Exactly 2 gateways

        # Verify aggregation worked correctly for the second group
        assert packets[1]["min_rssi"] == -75
        assert packets[1]["max_rssi"] == -70
        assert packets[1]["min_snr"] == 8
        assert packets[1]["max_snr"] == 10

        # Verify best payload was selected (longest one)
        assert packets[1]["raw_payload"] == b"test2_longer"


class TestGatewaySortingDataFormat:
    """Test the data format returned by the API for frontend consumption."""

    def test_api_returns_correct_gateway_format_for_grouped_packets(self):
        """Test that the API returns gateway data in the correct format for the table."""
        from flask import Flask

        from src.malla.routes.api_routes import api_packets_data

        app = Flask(__name__)

        with app.test_request_context(
            method="GET",
            query_string={
                "page": "1",
                "limit": "10",
                "sort_by": "gateway_count",
                "sort_order": "asc",
                "group_packets": "true",
            },
        ):
            # Mock the repository response
            mock_packets = [
                {
                    "id": 1,
                    "timestamp": 1000,
                    "from_node_id": 123,
                    "to_node_id": 456,
                    "portnum_name": "TEXT_MESSAGE_APP",
                    "gateway_count": 1,
                    "gateway_list": "!433d0c24",
                    "rssi_range": "-80 dBm",
                    "snr_range": "5 dB",
                    "hop_range": "2",
                    "avg_payload_length": 50,
                    "success": True,
                    "is_grouped": True,
                    "timestamp_str": "2024-01-01 12:00:00",
                },
                {
                    "id": 2,
                    "timestamp": 2000,
                    "from_node_id": 789,
                    "to_node_id": 456,
                    "portnum_name": "TEXT_MESSAGE_APP",
                    "gateway_count": 2,
                    "gateway_list": "!433d0c24,!da73e9cc",
                    "rssi_range": "-75 to -70 dBm",
                    "snr_range": "8 to 10 dB",
                    "hop_range": "1-3",
                    "avg_payload_length": 75,
                    "success": True,
                    "is_grouped": True,
                    "timestamp_str": "2024-01-01 12:01:00",
                },
            ]

            mock_result = {
                "packets": mock_packets,
                "total_count": 2,
                "is_grouped": True,
            }

            with patch(
                "src.malla.routes.api_routes.PacketRepository.get_packets",
                return_value=mock_result,
            ):
                with patch(
                    "src.malla.routes.api_routes.get_bulk_node_names", return_value={}
                ):
                    response = api_packets_data()
                    # Handle case where response might be a tuple (Response, status_code)
                    if isinstance(response, tuple):
                        response_obj, status_code = response
                        assert status_code == 200, f"Expected 200, got {status_code}"
                        data = json.loads(response_obj.data)
                    else:
                        data = json.loads(response.data)

            # Verify the response structure
            assert "data" in data
            assert len(data["data"]) == 2

            # Check first row (1 gateway)
            row1 = data["data"][0]
            assert row1["gateway"] == "1 gateway"  # Gateway column should show count
            assert row1["is_grouped"] is True  # Is grouped flag
            assert row1["gateway_list"] == "!433d0c24"  # Gateway list

            # Check second row (2 gateways)
            row2 = data["data"][1]
            assert row2["gateway"] == "2 gateways"  # Gateway column should show count
            assert row2["is_grouped"] is True  # Is grouped flag
            assert row2["gateway_list"] == "!433d0c24,!da73e9cc"  # Gateway list


class TestJavaScriptSortingLogic:
    """Test the JavaScript sorting logic that extracts numeric values from gateway strings."""

    def test_gateway_count_extraction_from_string(self):
        """Test that the JavaScript logic correctly extracts gateway counts from strings."""
        # This test simulates the JavaScript logic in Python to verify the pattern matching

        test_cases = [
            ("1 gateways", 1),
            ("2 gateways", 2),
            ("5 gateways", 5),
            ("10 gateways", 10),
            ("1 gateway", 1),  # Singular form
            ("N/A", 0),
            ("", 0),
            (None, 0),
        ]

        def extract_gateway_count(data):
            """Simulate the JavaScript gateway count extraction logic."""
            if not data or data == "N/A":
                return 0

            # Match the pattern used in JavaScript: /^(\d+)\s+gateways?$/
            import re

            match = re.match(r"^(\d+)\s+gateways?$", str(data))
            if match:
                return int(match.group(1))
            return 0

        for input_str, expected_count in test_cases:
            actual_count = extract_gateway_count(input_str)
            assert actual_count == expected_count, (
                f"Failed for input '{input_str}': expected {expected_count}, got {actual_count}"
            )

    def test_gateway_list_fallback_counting(self):
        """Test the fallback logic that counts gateways from the gateway list."""

        test_cases = [
            ("!433d0c24", 1),
            ("!433d0c24,!da73e9cc", 2),
            ("!433d0c24,!da73e9cc,!12345678", 3),
            ("!433d0c24,!da73e9cc,!12345678,!abcdef00,!fedcba98", 5),
            ("", 0),
            (None, 0),
        ]

        def count_from_gateway_list(gateway_list):
            """Simulate the JavaScript gateway list counting logic."""
            if not gateway_list or gateway_list == "":
                return 0
            return len(gateway_list.split(","))

        for gateway_list, expected_count in test_cases:
            actual_count = count_from_gateway_list(gateway_list)
            assert actual_count == expected_count, (
                f"Failed for gateway list '{gateway_list}': expected {expected_count}, got {actual_count}"
            )

    def test_individual_packet_gateway_sorting_value(self):
        """Test that individual packets return correct sorting values (1 or 0)."""

        test_cases = [
            ("!433d0c24", 1),  # Has gateway
            ("gateway-01", 1),  # Has gateway
            ("N/A", 0),  # No gateway
            ("", 0),  # Empty gateway
            (None, 0),  # Null gateway
        ]

        def get_individual_packet_sort_value(data):
            """Simulate the JavaScript individual packet sorting logic."""
            return 1 if (data and data != "" and data != "N/A") else 0

        for gateway_data, expected_value in test_cases:
            actual_value = get_individual_packet_sort_value(gateway_data)
            assert actual_value == expected_value, (
                f"Failed for gateway data '{gateway_data}': expected {expected_value}, got {actual_value}"
            )


class TestIntegrationGatewaySorting:
    """Integration tests that verify the complete gateway sorting flow."""

    @pytest.mark.integration
    def test_complete_gateway_sorting_flow(self, client):
        """Test the complete flow from API request to sorted response."""
        # This test requires a test client and would test the actual API endpoint

        # Test ascending order
        response = client.get(
            "/api/packets/data?page=1&limit=10&sort_by=gateway_count&sort_order=asc&group_packets=true"
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify response structure
        assert "data" in data
        assert "total_count" in data

        # If there's data, verify it's sorted correctly
        if len(data["data"]) > 1:
            gateway_counts = []
            for row in data["data"]:
                gateway_str = row["gateway"]  # Gateway column
                if gateway_str and "gateway" in gateway_str:
                    # Extract count from "X gateway(s)" format
                    import re

                    match = re.match(r"^(\d+)\s+gateways?$", gateway_str)
                    if match:
                        gateway_counts.append(int(match.group(1)))

            # Verify ascending order
            if len(gateway_counts) > 1:
                assert gateway_counts == sorted(gateway_counts), (
                    "Gateway counts should be in ascending order"
                )

        # Test descending order
        response = client.get(
            "/api/packets/data?page=1&limit=10&sort_by=gateway_count&sort_order=desc&group_packets=true"
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # If there's data, verify it's sorted correctly
        if len(data["data"]) > 1:
            gateway_counts = []
            for row in data["data"]:
                gateway_str = row["gateway"]  # Gateway column
                if gateway_str and "gateway" in gateway_str:
                    # Extract count from "X gateway(s)" format
                    import re

                    match = re.match(r"^(\d+)\s+gateways?$", gateway_str)
                    if match:
                        gateway_counts.append(int(match.group(1)))

            # Verify descending order
            if len(gateway_counts) > 1:
                assert gateway_counts == sorted(gateway_counts, reverse=True), (
                    "Gateway counts should be in descending order"
                )
