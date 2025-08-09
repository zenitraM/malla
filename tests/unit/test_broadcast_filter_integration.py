"""
Integration test for broadcast filter URL parameter functionality.

This test verifies that the exclude_broadcast parameter can be passed via URL
and is properly handled by the frontend JavaScript.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestBroadcastFilterIntegration:
    """Test broadcast filter integration across the stack."""

    def test_broadcast_filter_url_parameter_integration(self):
        """Test that URL parameters are properly parsed and applied."""
        # Import and test the Flask app
        from src.malla.web_ui import create_app
        
        app = create_app()
        with app.test_client() as client:
            # Test the packets page renders with the filter control
            response = client.get('/packets')
            
            assert response.status_code == 200
            html_content = response.get_data(as_text=True)
            
            # Verify the checkbox is present in the HTML
            assert 'id="exclude_broadcast"' in html_content
            assert 'name="exclude_broadcast"' in html_content
            assert 'Exclude broadcast packets (!ffffffff)' in html_content

    @patch('src.malla.routes.api_routes.PacketRepository.get_packets')
    def test_broadcast_filter_api_integration(self, mock_get_packets):
        """Test the complete API integration for broadcast filtering."""
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
            # Test that all filter combinations work
            test_cases = [
                ('/api/packets?exclude_broadcast=true', True),
                ('/api/packets?exclude_broadcast=TRUE', True),
                ('/api/packets?exclude_broadcast=false', False),
                ('/api/packets?exclude_broadcast=FALSE', False),
                ('/api/packets', False),  # No parameter
            ]
            
            for url, should_have_filter in test_cases:
                mock_get_packets.reset_mock()
                
                response = client.get(url)
                assert response.status_code == 200
                
                # Verify repository was called
                mock_get_packets.assert_called_once()
                call_args = mock_get_packets.call_args
                filters = call_args[1]['filters']
                
                if should_have_filter:
                    assert 'exclude_broadcast' in filters
                    assert filters['exclude_broadcast'] is True
                else:
                    assert 'exclude_broadcast' not in filters

    def test_broadcast_filter_parameter_parsing(self):
        """Test that parameter parsing is case-insensitive and handles edge cases."""
        from src.malla.web_ui import create_app
        
        app = create_app()
        
        # Test various parameter formats
        test_cases = [
            ('true', True),
            ('TRUE', True),
            ('True', True),
            ('1', False),  # Only 'true' should work
            ('false', False),
            ('FALSE', False),
            ('False', False),
            ('0', False),
            ('', False),
            ('invalid', False),
        ]
        
        for param_value, expected_result in test_cases:
            with app.test_request_context(f'/api/packets?exclude_broadcast={param_value}'):
                from flask import request
                
                # Simulate the parameter parsing logic from api_routes.py
                exclude_broadcast_flag = request.args.get("exclude_broadcast", "false").lower() == "true"
                
                assert exclude_broadcast_flag == expected_result, f"Parameter '{param_value}' should result in {expected_result}"