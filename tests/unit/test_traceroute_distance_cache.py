"""
Test location cache optimization in TraceroutePacket distance calculations.
"""

from unittest.mock import call, patch

from src.malla.models.traceroute import TraceroutePacket


class TestTracerouteDistanceCache:
    """Test location caching in distance calculations."""

    def test_location_cache_reduces_db_calls(self):
        """Test that the method now uses internal caching by default."""
        # Create test packet data
        packet_data = {
            "id": 1,
            "from_node_id": 123,
            "to_node_id": 456,
            "timestamp": 1640995200.0,  # 2022-01-01 00:00:00
            "raw_payload": b"",  # Empty payload for simple test
            "gateway_id": "test_gateway",
            "hop_limit": 3,
            "hop_start": 3,
        }

        # Mock location data
        mock_location_123 = {
            "latitude": 40.7128,
            "longitude": -74.0060,
            "altitude": 10,
            "timestamp": 1640995100.0,
            "age_warning": "from 1.7m ago",
        }

        mock_location_456 = {
            "latitude": 40.7589,
            "longitude": -73.9851,
            "altitude": 20,
            "timestamp": 1640995150.0,
            "age_warning": "from 0.8m ago",
        }

        # Test that even without explicit cache, internal caching reduces DB calls
        with patch(
            "src.malla.utils.traceroute_utils.get_node_location_at_timestamp"
        ) as mock_get_location:
            mock_get_location.side_effect = lambda node_id, timestamp: {
                123: mock_location_123,
                456: mock_location_456,
            }.get(node_id)

            tr_packet = TraceroutePacket(packet_data=packet_data, resolve_names=False)

            # Manually add some hops to test caching
            from src.malla.models.traceroute import TracerouteHop

            test_hop1 = TracerouteHop(
                hop_number=1, from_node_id=123, to_node_id=456, snr=-10.0
            )
            test_hop2 = TracerouteHop(
                hop_number=2,
                from_node_id=456,
                to_node_id=123,  # Same nodes, different direction
                snr=-12.0,
            )
            tr_packet.forward_path.hops = [test_hop1, test_hop2]

            # Calculate distances without explicit cache (but internal caching is used)
            tr_packet.calculate_hop_distances()

            # Should have made only 2 calls due to internal caching (one per unique node)
            assert mock_get_location.call_count == 2
            expected_calls = [
                call(123, 1640995200.0),  # hop1 from_node
                call(456, 1640995200.0),  # hop1 to_node
                # No additional calls for hop2 due to caching
            ]
            mock_get_location.assert_has_calls(expected_calls)

            # Verify distances were calculated for both hops
            assert test_hop1.distance_meters is not None
            assert test_hop2.distance_meters is not None
            assert (
                test_hop1.distance_meters == test_hop2.distance_meters
            )  # Same distance, different direction

    def test_location_cache_with_shared_cache(self):
        """Test that using a shared cache reduces database calls."""
        # Create test packet data
        packet_data = {
            "id": 1,
            "from_node_id": 123,
            "to_node_id": 456,
            "timestamp": 1640995200.0,
            "raw_payload": b"",
            "gateway_id": "test_gateway",
            "hop_limit": 3,
            "hop_start": 3,
        }

        # Mock location data
        mock_location_123 = {
            "latitude": 40.7128,
            "longitude": -74.0060,
            "altitude": 10,
            "timestamp": 1640995100.0,
            "age_warning": "from 1.7m ago",
        }

        mock_location_456 = {
            "latitude": 40.7589,
            "longitude": -73.9851,
            "altitude": 20,
            "timestamp": 1640995150.0,
            "age_warning": "from 0.8m ago",
        }

        # Test with shared cache - should make fewer DB calls
        with patch(
            "src.malla.utils.traceroute_utils.get_node_location_at_timestamp"
        ) as mock_get_location:
            mock_get_location.side_effect = lambda node_id, timestamp: {
                123: mock_location_123,
                456: mock_location_456,
            }.get(node_id)

            tr_packet = TraceroutePacket(packet_data=packet_data, resolve_names=False)

            # Manually add some hops to test caching
            from src.malla.models.traceroute import TracerouteHop

            test_hop1 = TracerouteHop(
                hop_number=1, from_node_id=123, to_node_id=456, snr=-10.0
            )
            test_hop2 = TracerouteHop(
                hop_number=2,
                from_node_id=456,
                to_node_id=123,  # Same nodes, different direction
                snr=-12.0,
            )
            tr_packet.forward_path.hops = [test_hop1, test_hop2]

            # Create shared cache
            location_cache = {}

            # Calculate distances with cache
            tr_packet.calculate_hop_distances(location_cache=location_cache)

            # Should have made only 2 calls (one per unique node)
            assert mock_get_location.call_count == 2

            # Verify cache contains expected entries
            assert len(location_cache) == 2
            assert (123, 1640995200.0) in location_cache
            assert (456, 1640995200.0) in location_cache

            # Verify distances were calculated
            assert test_hop1.distance_meters is not None
            assert test_hop2.distance_meters is not None
            assert (
                test_hop1.distance_meters == test_hop2.distance_meters
            )  # Same distance, different direction

    def test_cache_persists_across_multiple_packets(self):
        """Test that cache persists and is reused across multiple TraceroutePacket instances."""
        # Create shared cache
        location_cache = {}

        # Mock location data
        mock_location_123 = {
            "latitude": 40.7128,
            "longitude": -74.0060,
            "altitude": 10,
            "timestamp": 1640995100.0,
            "age_warning": "from 1.7m ago",
        }

        mock_location_456 = {
            "latitude": 40.7589,
            "longitude": -73.9851,
            "altitude": 20,
            "timestamp": 1640995150.0,
            "age_warning": "from 0.8m ago",
        }

        with patch(
            "src.malla.utils.traceroute_utils.get_node_location_at_timestamp"
        ) as mock_get_location:
            mock_get_location.side_effect = lambda node_id, timestamp: {
                123: mock_location_123,
                456: mock_location_456,
            }.get(node_id)

            # First packet
            packet_data_1 = {
                "id": 1,
                "from_node_id": 123,
                "to_node_id": 456,
                "timestamp": 1640995200.0,
                "raw_payload": b"",
                "gateway_id": "test_gateway",
                "hop_limit": 3,
                "hop_start": 3,
            }

            tr_packet_1 = TraceroutePacket(
                packet_data=packet_data_1, resolve_names=False
            )

            # Add hop to first packet
            from src.malla.models.traceroute import TracerouteHop

            test_hop1 = TracerouteHop(
                hop_number=1, from_node_id=123, to_node_id=456, snr=-10.0
            )
            tr_packet_1.forward_path.hops = [test_hop1]

            # Calculate distances for first packet
            tr_packet_1.calculate_hop_distances(location_cache=location_cache)

            # Should have made 2 calls
            assert mock_get_location.call_count == 2
            assert len(location_cache) == 2

            # Second packet with same nodes and timestamp
            packet_data_2 = {
                "id": 2,
                "from_node_id": 456,
                "to_node_id": 123,  # Reverse direction
                "timestamp": 1640995200.0,  # Same timestamp
                "raw_payload": b"",
                "gateway_id": "test_gateway",
                "hop_limit": 3,
                "hop_start": 3,
            }

            tr_packet_2 = TraceroutePacket(
                packet_data=packet_data_2, resolve_names=False
            )

            # Add hop to second packet
            test_hop2 = TracerouteHop(
                hop_number=1, from_node_id=456, to_node_id=123, snr=-12.0
            )
            tr_packet_2.forward_path.hops = [test_hop2]

            # Calculate distances for second packet using same cache
            tr_packet_2.calculate_hop_distances(location_cache=location_cache)

            # Should still have made only 2 calls total (no additional calls)
            assert mock_get_location.call_count == 2
            assert len(location_cache) == 2

            # Verify both hops have distances calculated
            assert test_hop1.distance_meters is not None
            assert test_hop2.distance_meters is not None
            assert (
                test_hop1.distance_meters == test_hop2.distance_meters
            )  # Same distance

    def test_cache_handles_missing_locations(self):
        """Test that cache correctly handles and stores None values for missing locations."""
        location_cache = {}

        with patch(
            "src.malla.utils.traceroute_utils.get_node_location_at_timestamp"
        ) as mock_get_location:
            # Return None for missing location
            mock_get_location.return_value = None

            packet_data = {
                "id": 1,
                "from_node_id": 123,
                "to_node_id": 456,
                "timestamp": 1640995200.0,
                "raw_payload": b"",
                "gateway_id": "test_gateway",
                "hop_limit": 3,
                "hop_start": 3,
            }

            tr_packet = TraceroutePacket(packet_data=packet_data, resolve_names=False)

            # Add hop
            from src.malla.models.traceroute import TracerouteHop

            test_hop = TracerouteHop(
                hop_number=1, from_node_id=123, to_node_id=456, snr=-10.0
            )
            tr_packet.forward_path.hops = [test_hop]

            # Calculate distances
            tr_packet.calculate_hop_distances(location_cache=location_cache)

            # Should have made 2 calls
            assert mock_get_location.call_count == 2

            # Cache should contain None values
            assert len(location_cache) == 2
            assert location_cache[(123, 1640995200.0)] is None
            assert location_cache[(456, 1640995200.0)] is None

            # Distance should be None
            assert test_hop.distance_meters is None
            assert test_hop.from_location_age_warning == "No location data available"
            assert test_hop.to_location_age_warning == "No location data available"
