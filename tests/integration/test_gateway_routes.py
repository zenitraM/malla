"""
Integration tests for gateway comparison routes.
"""

import json
from datetime import UTC


class TestGatewayComparisonRoutes:
    """Test gateway comparison routes."""

    def test_gateway_compare_page_loads(self, client):
        """Test that the gateway comparison page loads successfully."""
        response = client.get("/gateway/compare")
        assert response.status_code == 200
        assert b"Gateway Comparison" in response.data
        assert b"Select two gateways above to start the comparison" in response.data

    def test_gateway_compare_with_valid_gateways(self, client):
        """Test gateway comparison with valid gateway selection."""
        # Get available gateways first
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 2:
            gateway1 = gateways[0]["id"]
            gateway2 = gateways[1]["id"]

            response = client.get(
                f"/gateway/compare?gateway1={gateway1}&gateway2={gateway2}"
            )
            assert response.status_code == 200
            assert b"Gateway Comparison" in response.data

    def test_gateway_compare_with_same_gateway(self, client):
        """Test gateway comparison with same gateway selected for both."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 1:
            gateway_id = gateways[0]["id"]

            response = client.get(
                f"/gateway/compare?gateway1={gateway_id}&gateway2={gateway_id}"
            )
            assert response.status_code == 200
            assert b"Please select two different gateways" in response.data

    def test_gateway_compare_with_invalid_gateway(self, client):
        """Test gateway comparison with invalid gateway ID."""
        response = client.get("/gateway/compare?gateway1=invalid&gateway2=also_invalid")
        assert response.status_code == 200
        # Should still load the page but show no comparison data
        assert b"Gateway Comparison" in response.data

    def test_gateway_api_compare_endpoint(self, client):
        """Test the API endpoint for gateway comparison."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 2:
            gateway1 = gateways[0]["id"]
            gateway2 = gateways[1]["id"]

            response = client.get(
                f"/gateway/api/compare?gateway1={gateway1}&gateway2={gateway2}"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert "gateway1_name" in data
            assert "gateway2_name" in data
            assert "common_packets" in data
            assert "statistics" in data
            assert "chart_data" in data

    def test_gateway_api_compare_with_filters(self, client):
        """Test the API endpoint with time and node filters."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 2:
            gateway1 = gateways[0]["id"]
            gateway2 = gateways[1]["id"]

            # Test with time filter
            response = client.get(
                f"/gateway/api/compare?gateway1={gateway1}&gateway2={gateway2}&hours=24"
            )
            assert response.status_code == 200

            # Test with node filter
            response = client.get(
                f"/gateway/api/compare?gateway1={gateway1}&gateway2={gateway2}&from_node_id=123456789"
            )
            assert response.status_code == 200

    def test_gateway_api_compare_error_handling(self, client):
        """Test error handling in the API endpoint."""
        # Missing gateway parameters
        response = client.get("/gateway/api/compare")
        assert response.status_code == 400

        # Missing gateway2
        response = client.get("/gateway/api/compare?gateway1=test")
        assert response.status_code == 400

        # Same gateway IDs
        response = client.get("/gateway/api/compare?gateway1=test&gateway2=test")
        assert response.status_code == 400

    def test_gateway_api_gateways_endpoint(self, client):
        """Test the gateways list API endpoint."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200

        gateways = json.loads(response.data)
        assert isinstance(gateways, list)

        # Each gateway should have required fields
        for gateway in gateways:
            assert "id" in gateway
            assert "display_name" in gateway

    def test_gateway_comparison_statistics_structure(self, client):
        """Test that comparison statistics have the correct structure."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 2:
            gateway1 = gateways[0]["id"]
            gateway2 = gateways[1]["id"]

            response = client.get(
                f"/gateway/api/compare?gateway1={gateway1}&gateway2={gateway2}"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            stats = data["statistics"]

            # Check basic required fields
            assert "total_common_packets" in stats
            assert "gateway1_id" in stats
            assert "gateway2_id" in stats
            assert "gateway1_name" in stats
            assert "gateway2_name" in stats

            # If there are common packets, check for additional statistics
            if stats["total_common_packets"] > 0:
                # Check for difference statistics (may or may not be present)
                possible_fields = [
                    "rssi_diff_avg",
                    "rssi_diff_min",
                    "rssi_diff_max",
                    "rssi_diff_std",
                    "snr_diff_avg",
                    "snr_diff_min",
                    "snr_diff_max",
                    "snr_diff_std",
                    "gateway1_rssi_avg",
                    "gateway1_rssi_min",
                    "gateway1_rssi_max",
                    "gateway1_snr_avg",
                    "gateway1_snr_min",
                    "gateway1_snr_max",
                    "gateway2_rssi_avg",
                    "gateway2_rssi_min",
                    "gateway2_rssi_max",
                    "gateway2_snr_avg",
                    "gateway2_snr_min",
                    "gateway2_snr_max",
                ]

                # At least some of these should be present if there are common packets
                present_fields = [field for field in possible_fields if field in stats]
                assert len(present_fields) > 0, (
                    "Expected some statistics fields when common packets exist"
                )

    def test_gateway_comparison_chart_data_structure(self, client):
        """Test that chart data has the correct structure."""
        response = client.get("/gateway/api/gateways")
        assert response.status_code == 200
        gateways = json.loads(response.data)

        if len(gateways) >= 2:
            gateway1 = gateways[0]["id"]
            gateway2 = gateways[1]["id"]

            response = client.get(
                f"/gateway/api/compare?gateway1={gateway1}&gateway2={gateway2}"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            chart_data = data["chart_data"]

            # Check required chart data fields
            required_charts = [
                "rssi_scatter",
                "snr_scatter",
                "rssi_diff_histogram",
                "snr_diff_histogram",
                "timeline_rssi",
                "timeline_snr",
            ]

            for chart in required_charts:
                assert chart in chart_data

            # Check scatter plot structure (may be empty)
            for scatter in ["rssi_scatter", "snr_scatter"]:
                assert "x" in chart_data[scatter]
                assert "y" in chart_data[scatter]
                assert isinstance(chart_data[scatter]["x"], list)
                assert isinstance(chart_data[scatter]["y"], list)

                # 'text' field only present when there's data
                if chart_data[scatter]["x"]:
                    assert "text" in chart_data[scatter]
                    assert isinstance(chart_data[scatter]["text"], list)

            # Check histogram structure
            for hist in ["rssi_diff_histogram", "snr_diff_histogram"]:
                assert "values" in chart_data[hist]
                assert isinstance(chart_data[hist]["values"], list)

            # Check timeline structure
            for timeline in ["timeline_rssi", "timeline_snr"]:
                assert "timestamps" in chart_data[timeline]
                assert "gateway1" in chart_data[timeline]
                assert "gateway2" in chart_data[timeline]
                assert isinstance(chart_data[timeline]["timestamps"], list)
                assert isinstance(chart_data[timeline]["gateway1"], list)
                assert isinstance(chart_data[timeline]["gateway2"], list)


class TestGatewayComparisonWithData:
    """Test gateway comparison with specific test data."""

    def test_gateway_comparison_with_common_packets(self, client, app):
        """Test gateway comparison when gateways have common packets."""
        from datetime import datetime

        from src.malla.database.connection import get_db_connection

        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()

            # Create test packets that should be common between gateways
            base_time = datetime.now(UTC).timestamp()

            # Insert packets for gateway1 and gateway2 with SAME hop counts (should be included)
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_1",
                    123456789,
                    987654321,
                    "gateway1",
                    -80,
                    5.5,
                    base_time,
                    3,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway1",
                    10,
                    True,
                ),
            )

            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_1",
                    123456789,
                    987654321,
                    "gateway2",
                    -75,
                    6.0,
                    base_time,
                    3,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway2",
                    10,
                    True,
                ),
            )

            # Insert another packet with same hop counts (should be included)
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_2",
                    111111111,
                    222222222,
                    "gateway1",
                    -85,
                    4.0,
                    base_time + 10,
                    5,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway1",
                    15,
                    True,
                ),
            )

            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_2",
                    111111111,
                    222222222,
                    "gateway2",
                    -82,
                    4.5,
                    base_time + 10,
                    5,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway2",
                    15,
                    True,
                ),
            )

            # Insert packets with DIFFERENT hop counts (should be excluded from comparison)
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_3",
                    333333333,
                    444444444,
                    "gateway1",
                    -90,
                    3.0,
                    base_time + 20,
                    2,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway1",
                    20,
                    True,
                ),
            )

            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "test_packet_3",
                    333333333,
                    444444444,
                    "gateway2",
                    -88,
                    3.5,
                    base_time + 20,
                    4,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway2",
                    20,
                    True,
                ),
            )

            conn.commit()
            conn.close()

            # Test the comparison
            response = client.get(
                "/gateway/api/compare?gateway1=gateway1&gateway2=gateway2"
            )
            assert response.status_code == 200

            data = json.loads(response.data)

            # Should only have 2 common packets (the ones with matching hop limits)
            assert len(data["common_packets"]) == 2

            # Verify the common packets have matching hop limits
            for packet in data["common_packets"]:
                assert packet["hop_limit"] is not None
                # Both packets should have hop_limit 3 or 5 (the matching ones)
                assert packet["hop_limit"] in [3, 5]

            # Check that statistics are calculated for the 2 matching packets
            stats = data["statistics"]
            assert stats["total_common_packets"] == 2

            # Check for presence of difference statistics
            if "rssi_diff_avg" in stats:
                assert isinstance(stats["rssi_diff_avg"], int | float)
            if "snr_diff_avg" in stats:
                assert isinstance(stats["snr_diff_avg"], int | float)

    def test_gateway_comparison_no_common_packets(self, client, app):
        """Test gateway comparison when gateways have no common packets."""
        from datetime import datetime

        from src.malla.database.connection import get_db_connection

        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()

            base_time = datetime.now(UTC).timestamp()

            # Insert packet for gateway1 only
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "unique_packet_1",
                    111111111,
                    222222222,
                    "gateway_unique1",
                    -80,
                    5.5,
                    base_time,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_unique1",
                    10,
                    True,
                ),
            )

            # Insert different packet for gateway2
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "unique_packet_2",
                    333333333,
                    444444444,
                    "gateway_unique2",
                    -75,
                    6.0,
                    base_time,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_unique2",
                    10,
                    True,
                ),
            )

            conn.commit()
            conn.close()

            # Test the comparison
            response = client.get(
                "/gateway/api/compare?gateway1=gateway_unique1&gateway2=gateway_unique2"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert len(data["common_packets"]) == 0

            # Statistics should show no common packets
            stats = data["statistics"]
            assert stats["total_common_packets"] == 0

            # Difference statistics should not be present when no common packets
            assert "rssi_diff_avg" not in stats
            assert "snr_diff_avg" not in stats

    def test_gateway_comparison_hop_limit_filtering(self, client, app):
        """Test that gateway comparison only includes packets with same hop limit."""
        from datetime import datetime

        from src.malla.database.connection import get_db_connection

        with app.app_context():
            conn = get_db_connection()
            cursor = conn.cursor()

            base_time = datetime.now(UTC).timestamp()

            # Insert same packet received by both gateways with same hop limit
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "hop_test_packet_1",
                    123456789,
                    987654321,
                    "gateway_hop1",
                    -80,
                    5.5,
                    base_time,
                    3,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_hop1",
                    10,
                    True,
                ),
            )

            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "hop_test_packet_1",
                    123456789,
                    987654321,
                    "gateway_hop2",
                    -75,
                    6.0,
                    base_time,
                    3,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_hop2",
                    10,
                    True,
                ),
            )

            # Insert same packet with different hop limit (retransmission) - should be excluded
            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "hop_test_packet_1",
                    123456789,
                    987654321,
                    "gateway_hop1",
                    -85,
                    4.5,
                    base_time + 1,
                    2,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_hop1",
                    10,
                    True,
                ),
            )

            cursor.execute(
                """
                INSERT INTO packet_history
                (mesh_packet_id, from_node_id, to_node_id, gateway_id, rssi, snr, timestamp,
                 hop_limit, hop_start, portnum, portnum_name, topic, payload_length, processed_successfully)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "hop_test_packet_1",
                    123456789,
                    987654321,
                    "gateway_hop2",
                    -82,
                    5.0,
                    base_time + 1,
                    1,
                    7,
                    1,
                    "TEXT_MESSAGE_APP",
                    "msh/2/c/LongFast/!gateway_hop2",
                    10,
                    True,
                ),
            )

            conn.commit()
            conn.close()

            # Test the comparison
            response = client.get(
                "/gateway/api/compare?gateway1=gateway_hop1&gateway2=gateway_hop2"
            )
            assert response.status_code == 200

            data = json.loads(response.data)

            # Should only have 1 common packet (the one with matching hop limits)
            assert len(data["common_packets"]) == 1

            # Verify it's the packet with hop_limit = 3
            common_packet = data["common_packets"][0]
            assert common_packet["hop_limit"] == 3
            assert common_packet["gateway1_rssi"] == -80
            assert common_packet["gateway2_rssi"] == -75

            # Statistics should reflect only the matching packet
            stats = data["statistics"]
            assert stats["total_common_packets"] == 1
