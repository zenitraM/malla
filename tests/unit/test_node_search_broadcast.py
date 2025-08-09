"""
Tests for broadcast node functionality in node search API.

This module tests that the broadcast node (4294967295 / !ffffffff) appears 
as a selectable option in node search results for both /api/nodes/search
and /api/nodes endpoints.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.malla.web_ui import create_app


class TestNodeSearchBroadcast:
    """Test broadcast node functionality in node search API."""

    def test_node_search_no_query_includes_broadcast(self):
        """Test that broadcast node is included when no query is provided."""
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return no tables (simulating fresh database)
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None  # No node_info table
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes/search')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 1
                assert len(data['nodes']) == 1
                assert data['is_popular'] is True
                assert data['query'] == ""
                
                # Check broadcast node properties
                broadcast_node = data['nodes'][0]
                assert broadcast_node['node_id'] == 4294967295
                assert broadcast_node['hex_id'] == "!ffffffff"
                assert broadcast_node['long_name'] == "Broadcast"
                assert broadcast_node['short_name'] == "Broadcast"
                assert broadcast_node['role'] == "Broadcast"

    def test_api_nodes_no_search_includes_broadcast(self):
        """Test that /api/nodes endpoint includes broadcast node when no search is provided."""
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return no tables (simulating fresh database)
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None  # No node_info table
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 1
                assert len(data['nodes']) == 1
                assert data['page'] == 1
                assert data['per_page'] == 100
                
                # Check broadcast node properties
                broadcast_node = data['nodes'][0]
                assert broadcast_node['node_id'] == 4294967295
                assert broadcast_node['hex_id'] == "!ffffffff"
                assert broadcast_node['long_name'] == "Broadcast"
                assert broadcast_node['short_name'] == "Broadcast"
                assert broadcast_node['role'] == "Broadcast"

    def test_api_nodes_search_includes_broadcast(self):
        """Test that /api/nodes endpoint includes broadcast node when search matches."""
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return no tables (simulating fresh database)
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None  # No node_info table
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes?search=broadcast')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 1
                assert len(data['nodes']) == 1
                
                # Check broadcast node properties
                broadcast_node = data['nodes'][0]
                assert broadcast_node['node_id'] == 4294967295
                assert broadcast_node['hex_id'] == "!ffffffff"
                assert broadcast_node['long_name'] == "Broadcast"

    @patch('src.malla.routes.api_routes.NodeRepository.get_nodes')
    def test_node_search_no_query_with_real_nodes(self, mock_get_nodes):
        """Test that broadcast node is added to real nodes when no query is provided."""
        # Mock repository to return some real nodes
        mock_get_nodes.return_value = {
            "nodes": [
                {
                    "node_id": 123456,
                    "long_name": "Test Node",
                    "short_name": "Test",
                    "hex_id": "!0001e240",
                    "hw_model": "RAK4631",
                    "role": "Client",
                    "packet_count_24h": 10,
                }
            ],
            "total_count": 1
        }
        
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return node_info table exists
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = {"name": "node_info"}  # Table exists
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes/search')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 2  # Real node + broadcast
                assert len(data['nodes']) == 2
                assert data['is_popular'] is True
                
                # Check that broadcast node comes first
                assert data['nodes'][0]['node_id'] == 4294967295
                assert data['nodes'][0]['long_name'] == "Broadcast"
                
                # Check that real node comes second
                assert data['nodes'][1]['node_id'] == 123456
                assert data['nodes'][1]['long_name'] == "Test Node"

    def test_node_search_broadcast_query_variations(self):
        """Test that various broadcast-related queries return the broadcast node."""
        app = create_app()
        
        test_queries = [
            "broadcast",
            "BROADCAST", 
            "Broadcast",
            "ffffffff",
            "FFFFFFFF",
            "!ffffffff",
            "4294967295"
        ]
        
        with app.test_client() as client:
            for query in test_queries:
                with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                    # Mock database connection to return no tables
                    mock_cursor = MagicMock()
                    mock_cursor.fetchone.return_value = None
                    mock_conn.return_value.cursor.return_value = mock_cursor
                    
                    response = client.get(f'/api/nodes/search?q={query}')
                    
                    assert response.status_code == 200, f"Failed for query: {query}"
                    data = response.get_json()
                    
                    assert data['total_count'] == 1, f"Wrong count for query: {query}"
                    assert len(data['nodes']) == 1, f"Wrong nodes length for query: {query}"
                    assert data['query'] == query, f"Wrong query echo for: {query}"
                    assert data['is_popular'] is False, f"Wrong is_popular for: {query}"
                    
                    # Check broadcast node properties
                    broadcast_node = data['nodes'][0]
                    assert broadcast_node['node_id'] == 4294967295, f"Wrong node_id for query: {query}"
                    assert broadcast_node['hex_id'] == "!ffffffff", f"Wrong hex_id for query: {query}"

    def test_api_nodes_broadcast_query_variations(self):
        """Test that /api/nodes endpoint handles various broadcast-related search queries."""
        app = create_app()
        
        test_queries = [
            "broadcast",
            "ffffffff", 
            "!ffffffff",
            "4294967295"
        ]
        
        with app.test_client() as client:
            for query in test_queries:
                with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                    # Mock database connection to return no tables
                    mock_cursor = MagicMock()
                    mock_cursor.fetchone.return_value = None
                    mock_conn.return_value.cursor.return_value = mock_cursor
                    
                    response = client.get(f'/api/nodes?search={query}')
                    
                    assert response.status_code == 200, f"Failed for query: {query}"
                    data = response.get_json()
                    
                    assert data['total_count'] == 1, f"Wrong count for query: {query}"
                    assert len(data['nodes']) == 1, f"Wrong nodes length for query: {query}"
                    
                    # Check broadcast node properties
                    broadcast_node = data['nodes'][0]
                    assert broadcast_node['node_id'] == 4294967295, f"Wrong node_id for query: {query}"
                    assert broadcast_node['hex_id'] == "!ffffffff", f"Wrong hex_id for query: {query}"

    def test_node_search_non_broadcast_query(self):
        """Test that non-broadcast queries don't return the broadcast node."""
        app = create_app()
        
        test_queries = [
            "test",
            "node123",
            "12345678",
            "!12345678",
            "some random text"
        ]
        
        with app.test_client() as client:
            for query in test_queries:
                with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                    # Mock database connection to return no tables
                    mock_cursor = MagicMock()
                    mock_cursor.fetchone.return_value = None
                    mock_conn.return_value.cursor.return_value = mock_cursor
                    
                    response = client.get(f'/api/nodes/search?q={query}')
                    
                    assert response.status_code == 200, f"Failed for query: {query}"
                    data = response.get_json()
                    
                    assert data['total_count'] == 0, f"Expected 0 results for query: {query}"
                    assert len(data['nodes']) == 0, f"Expected empty nodes for query: {query}"

    @patch('src.malla.routes.api_routes.NodeRepository.get_nodes')
    def test_node_search_broadcast_query_with_real_nodes(self, mock_get_nodes):
        """Test that broadcast node is added to search results when query matches broadcast."""
        # Mock repository to return some real nodes matching the search
        mock_get_nodes.return_value = {
            "nodes": [
                {
                    "node_id": 555666,
                    "long_name": "BroadcastRepeater",  # Contains "broadcast" in name
                    "short_name": "BR01",
                    "hex_id": "!00087a8a",
                    "hw_model": "TBEAM",
                    "role": "Router",
                    "packet_count_24h": 15,
                }
            ],
            "total_count": 1
        }
        
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return node_info table exists
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = {"name": "node_info"}  # Table exists
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes/search?q=broadcast')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 2  # Real node + broadcast
                assert len(data['nodes']) == 2
                assert data['query'] == "broadcast"
                assert data['is_popular'] is False
                
                # Check that broadcast node comes first
                assert data['nodes'][0]['node_id'] == 4294967295
                assert data['nodes'][0]['long_name'] == "Broadcast"
                
                # Check that real node comes second
                assert data['nodes'][1]['node_id'] == 555666
                assert data['nodes'][1]['long_name'] == "BroadcastRepeater"

    def test_node_search_limit_handling(self):
        """Test that limit parameter is properly handled with broadcast node."""
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return no tables
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                # Test with small limit
                response = client.get('/api/nodes/search?limit=1')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['total_count'] == 1
                assert len(data['nodes']) == 1
                assert data['nodes'][0]['node_id'] == 4294967295

    def test_broadcast_node_structure(self):
        """Test that broadcast node has all required fields with correct values."""
        app = create_app()
        
        with app.test_client() as client:
            with patch('src.malla.routes.api_routes.get_db_connection') as mock_conn:
                # Mock database connection to return no tables
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = None
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                response = client.get('/api/nodes/search')
                
                assert response.status_code == 200
                data = response.get_json()
                
                broadcast_node = data['nodes'][0]
                
                # Check all required fields exist and have correct types/values
                assert isinstance(broadcast_node['node_id'], int)
                assert broadcast_node['node_id'] == 4294967295
                
                assert isinstance(broadcast_node['hex_id'], str)
                assert broadcast_node['hex_id'] == "!ffffffff"
                
                assert isinstance(broadcast_node['long_name'], str)
                assert broadcast_node['long_name'] == "Broadcast"
                
                assert isinstance(broadcast_node['short_name'], str)
                assert broadcast_node['short_name'] == "Broadcast"
                
                assert isinstance(broadcast_node['hw_model'], str)
                assert broadcast_node['hw_model'] == "Special"
                
                assert isinstance(broadcast_node['role'], str)
                assert broadcast_node['role'] == "Broadcast"
                
                assert broadcast_node['primary_channel'] is None
                assert broadcast_node['last_updated'] is None
                assert broadcast_node['last_packet_time'] is None
                assert broadcast_node['last_packet_str'] is None
                
                assert isinstance(broadcast_node['packet_count_24h'], int)
                assert broadcast_node['packet_count_24h'] == 0
                
                assert isinstance(broadcast_node['gateway_packet_count_24h'], int)
                assert broadcast_node['gateway_packet_count_24h'] == 0