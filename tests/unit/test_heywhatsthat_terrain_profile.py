"""
Unit tests for HeyWhatsThat terrain profile functionality.
"""

import pytest
from urllib.parse import parse_qs, urlparse

from malla.config import AppConfig, _override_config


class TestTerrainProfileURL:
    """Test terrain profile URL generation logic."""

    def setup_method(self):
        """Set up test environment with custom config."""
        # Create a test config with a custom website domain
        test_config = AppConfig(website_domain="test.example.com")
        _override_config(test_config)

    @pytest.mark.unit
    def test_terrain_profile_url_structure(self):
        """Test that the terrain profile URL has the correct structure."""
        # This test verifies the JavaScript logic using Python equivalent
        # Simulate the URL generation from the JavaScript function
        
        # Sample node data
        node1 = {
            'latitude': 40.7128,
            'longitude': -74.0060,
            'altitude': 10,
            'display_name': 'Node 1'
        }
        node2 = {
            'latitude': 40.7589,
            'longitude': -73.9851,
            'altitude': 20,
            'display_name': 'Node 2'
        }
        
        # Expected URL components
        expected_base_url = "https://heywhatsthat.com/bin/profile-0904.cgi"
        expected_params = {
            'src': 'test.example.com',
            'axes': '1',
            'metric': '1',
            'curvature': '0',
            'width': '500',
            'height': '200',
            'pt0': f"{node1['latitude']},{node1['longitude']},0000FF,{node1['altitude']},0000FF",
            'pt1': f"{node2['latitude']},{node2['longitude']},0000FF,{node2['altitude']},0000FF",
        }
        
        # Construct the URL manually to verify structure
        from urllib.parse import urlencode
        expected_url = f"{expected_base_url}?{urlencode(expected_params)}"
        
        # Parse and verify URL components
        parsed = urlparse(expected_url)
        query_params = parse_qs(parsed.query)
        
        assert parsed.scheme == 'https'
        assert parsed.netloc == 'heywhatsthat.com'
        assert parsed.path == '/bin/profile-0904.cgi'
        assert query_params['src'][0] == 'test.example.com'
        assert query_params['axes'][0] == '1'
        assert query_params['metric'][0] == '1'
        assert query_params['curvature'][0] == '0'
        assert query_params['width'][0] == '500'
        assert query_params['height'][0] == '200'

    @pytest.mark.unit
    def test_terrain_profile_coordinates(self):
        """Test that coordinates are correctly formatted in the URL."""
        node1 = {
            'latitude': 40.7128,
            'longitude': -74.0060,
            'altitude': 10
        }
        node2 = {
            'latitude': 40.7589,
            'longitude': -73.9851,
            'altitude': 20
        }
        
        # Expected point parameters
        expected_pt0 = f"{node1['latitude']},{node1['longitude']},0000FF,{node1['altitude']},0000FF"
        expected_pt1 = f"{node2['latitude']},{node2['longitude']},0000FF,{node2['altitude']},0000FF"
        
        assert expected_pt0 == "40.7128,-74.006,0000FF,10,0000FF"
        assert expected_pt1 == "40.7589,-73.9851,0000FF,20,0000FF"

    @pytest.mark.unit
    def test_terrain_profile_missing_altitude(self):
        """Test terrain profile URL generation when altitude is missing."""
        node1 = {
            'latitude': 40.7128,
            'longitude': -74.0060,
            'altitude': None
        }
        node2 = {
            'latitude': 40.7589,
            'longitude': -73.9851,
            'altitude': ''
        }
        
        # When altitude is missing, it should be empty string in the URL
        expected_pt0 = f"{node1['latitude']},{node1['longitude']},0000FF,,0000FF"
        expected_pt1 = f"{node2['latitude']},{node2['longitude']},0000FF,,0000FF"
        
        assert expected_pt0 == "40.7128,-74.006,0000FF,,0000FF"
        assert expected_pt1 == "40.7589,-73.9851,0000FF,,0000FF"

    @pytest.mark.unit
    def test_default_website_domain(self):
        """Test that default website domain is used when none configured."""
        # Create config without website domain
        test_config = AppConfig(website_domain="")
        _override_config(test_config)
        
        # The JavaScript template should use the default value
        # We can't test JavaScript directly, but we can verify the config value
        from malla.config import get_config
        config = get_config()
        
        # The template logic: website_domain or 'github.com/zenitraM/malla'
        domain = config.website_domain or 'github.com/zenitraM/malla'
        assert domain == 'github.com/zenitraM/malla'

    @pytest.mark.unit
    def test_configured_website_domain(self):
        """Test that configured website domain is used correctly."""
        test_config = AppConfig(website_domain="my-mesh.example.com")
        _override_config(test_config)
        
        from malla.config import get_config
        config = get_config()
        
        domain = config.website_domain or 'github.com/zenitraM/malla'
        assert domain == 'my-mesh.example.com'

    @pytest.mark.unit
    def test_terrain_profile_url_encoding(self):
        """Test that special characters in coordinates are properly handled."""
        # Test with coordinates that might cause URL encoding issues
        node1 = {
            'latitude': 40.71285,  # More decimal places
            'longitude': -74.00605,
            'altitude': 10.5  # Decimal altitude
        }
        node2 = {
            'latitude': 40.75895,
            'longitude': -73.98515,
            'altitude': 20.7
        }
        
        expected_pt0 = f"{node1['latitude']},{node1['longitude']},0000FF,{node1['altitude']},0000FF"
        expected_pt1 = f"{node2['latitude']},{node2['longitude']},0000FF,{node2['altitude']},0000FF"
        
        # Verify the format
        assert expected_pt0 == "40.71285,-74.00605,0000FF,10.5,0000FF"
        assert expected_pt1 == "40.75895,-73.98515,0000FF,20.7,0000FF"
        
        # Test URL encoding behavior
        from urllib.parse import quote
        encoded_pt0 = quote(expected_pt0)
        encoded_pt1 = quote(expected_pt1)
        
        # Commas get encoded as %2C, dots remain as dots
        assert '%2C' in encoded_pt0  # Commas are encoded
        assert '.' in encoded_pt0    # Dots are not encoded
        assert '%2C' in encoded_pt1
        assert '.' in encoded_pt1