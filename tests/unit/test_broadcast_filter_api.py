"""
Tests for broadcast packet filtering in API endpoints.

This module tests the exclude_broadcast parameter in the API endpoints
to ensure broadcast packets can be filtered out via the API.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestBroadcastFilterAPI:
    """Test broadcast packet filtering at the API level."""

    @patch('src.malla.routes.api_routes.PacketRepository.get_packets')
    def test_api_packets_exclude_broadcast_parameter(self, mock_get_packets):
        """Test that API packets endpoint correctly processes exclude_broadcast parameter."""
        # Mock the repository response
        mock_get_packets.return_value = {
            "packets": [
                {
                    "id": 1,
                    "timestamp": 1000,
                    "from_node_id": 123,
                    "to_node_id": 456,  # Non-broadcast packet
                    "portnum_name": "TEXT_MESSAGE_APP",
                }
            ],
            "total_count": 1
        }
        
        # Import and test the Flask app
        from src.malla.web_ui import create_app
        
        app = create_app()
        with app.test_client() as client:
            # Test with exclude_broadcast=true
            response = client.get('/api/packets?exclude_broadcast=true')
            
            assert response.status_code == 200
            
            # Verify that get_packets was called with exclude_broadcast filter
            mock_get_packets.assert_called_once()
            call_args = mock_get_packets.call_args
            filters = call_args[1]['filters']  # keyword argument
            
            assert 'exclude_broadcast' in filters
            assert filters['exclude_broadcast'] is True

    @patch('src.malla.routes.api_routes.PacketRepository.get_packets')
    def test_api_packets_exclude_broadcast_false(self, mock_get_packets):
        """Test that API packets endpoint doesn't filter when exclude_broadcast=false."""
        # Mock the repository response
        mock_get_packets.return_value = {
            "packets": [
                {
                    "id": 1,
                    "timestamp": 1000,
                    "from_node_id": 123,
                    "to_node_id": 4294967295,  # Broadcast packet
                    "portnum_name": "TEXT_MESSAGE_APP",
                }
            ],
            "total_count": 1
        }
        
        # Import and test the Flask app
        from src.malla.web_ui import create_app
        
        app = create_app()
        with app.test_client() as client:
            # Test with exclude_broadcast=false
            response = client.get('/api/packets?exclude_broadcast=false')
            
            assert response.status_code == 200
            
            # Verify that get_packets was called without exclude_broadcast filter
            mock_get_packets.assert_called_once()
            call_args = mock_get_packets.call_args
            filters = call_args[1]['filters']  # keyword argument
            
            assert 'exclude_broadcast' not in filters

    @patch('src.malla.routes.api_routes.PacketRepository.get_packets')
    def test_api_packets_no_exclude_broadcast_parameter(self, mock_get_packets):
        """Test that API packets endpoint doesn't filter when exclude_broadcast parameter is not provided."""
        # Mock the repository response
        mock_get_packets.return_value = {
            "packets": [],
            "total_count": 0
        }
        
        # Import and test the Flask app
        from src.malla.web_ui import create_app
        
        app = create_app()
        with app.test_client() as client:
            # Test without exclude_broadcast parameter
            response = client.get('/api/packets')
            
            assert response.status_code == 200
            
            # Verify that get_packets was called without exclude_broadcast filter
            mock_get_packets.assert_called_once()
            call_args = mock_get_packets.call_args
            filters = call_args[1]['filters']  # keyword argument
            
            assert 'exclude_broadcast' not in filters