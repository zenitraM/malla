"""
Unit tests for the WSGI application factory.
"""

from unittest.mock import MagicMock, patch

from src.malla.wsgi import create_wsgi_app, get_application


class TestWSGIApplication:
    """Test the WSGI application factory."""

    def test_create_wsgi_app_returns_flask_app(self):
        """Test that create_wsgi_app returns a Flask application."""
        app = create_wsgi_app()

        # Check that it's a Flask app
        assert hasattr(app, "run")
        assert hasattr(app, "config")
        assert hasattr(app, "route")

        # Check that it has our expected configuration
        assert "APP_CONFIG" in app.config
        assert "DATABASE_FILE" in app.config

    def test_get_application_returns_flask_app(self):
        """Test that get_application returns a Flask application."""
        # The application instance should be created when get_application is called
        app = get_application()
        assert app is not None
        assert hasattr(app, "run")
        assert hasattr(app, "config")

    def test_wsgi_app_has_health_endpoint(self):
        """Test that the WSGI app has the health check endpoint."""
        app = get_application()
        with app.test_client() as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.get_json()
            assert data["status"] == "healthy"
            assert data["service"] == "meshtastic-mesh-health-ui"

    @patch("src.malla.web_ui.get_config")
    def test_create_wsgi_app_uses_config(self, mock_get_config):
        """Test that create_wsgi_app uses the configuration properly."""
        # Mock the config
        mock_config = MagicMock()
        mock_config.database_file = "/test/path/test.db"
        mock_config.secret_key = "test-secret"
        mock_config.host = "127.0.0.1"
        mock_config.port = 5008
        mock_config.debug = False
        mock_config.name = "Test Malla"
        mock_get_config.return_value = mock_config

        app = create_wsgi_app()

        # Verify config was called
        mock_get_config.assert_called_once()

        # Verify the app was configured
        assert app.config["DATABASE_FILE"] == "/test/path/test.db"
