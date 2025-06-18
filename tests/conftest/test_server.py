"""
Generic test server fixture for E2E tests.
"""

import os
import threading
import time

import pytest
from flask import Flask, jsonify, render_template_string

from tests.fixtures.traceroute_graph_data import get_sample_graph_data


class GenericTestServer:
    """Generic test server for E2E tests."""

    def __init__(self, port=5009):
        self.port = port
        self.app = Flask(__name__)
        self.server_thread = None
        self.custom_routes = {}
        self.custom_api_routes = {}
        self.setup_default_routes()

    def add_route(self, path, handler, methods=None):
        """Add a custom route to the server."""
        if methods is None:
            methods = ["GET"]
        self.custom_routes[path] = (handler, methods)

    def add_api_route(self, path, data_provider, methods=None):
        """Add a custom API route that returns JSON data."""
        if methods is None:
            methods = ["GET"]
        self.custom_api_routes[path] = (data_provider, methods)

    def setup_default_routes(self):
        """Set up default test routes."""

        @self.app.route("/traceroute-graph")
        def traceroute_graph():
            """Serve the traceroute graph page."""
            return self._serve_template(
                "traceroute_graph.html",
                {"hours": 24, "min_snr": -200, "include_indirect": True},
            )

        @self.app.route("/api/traceroute/graph")
        def api_traceroute_graph():
            """Serve sample graph data."""
            return jsonify(get_sample_graph_data())

    def _serve_template(self, template_name, context=None):
        """Serve a template with minimal base HTML."""
        if context is None:
            context = {}

        # Read the actual template file
        template_path = os.path.join(
            os.path.dirname(__file__), f"../../src/malla/templates/{template_name}"
        )

        if not os.path.exists(template_path):
            return f"Template {template_name} not found", 404

        with open(template_path) as f:
            template_content = f.read()

        # Replace the extends directive with a minimal base
        base_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Application</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary" style="height: 56px;">
    <div class="container-fluid">
        <span class="navbar-brand">Test Application</span>
    </div>
</nav>
<div class="container mt-4">"""

        template_content = template_content.replace(
            '{% extends "base.html" %}', base_html
        )
        template_content = template_content.replace("{% block content %}", "")
        template_content = template_content.replace(
            "{% endblock %}", "</div></body></html>"
        )

        return render_template_string(template_content, **context)

    def _register_custom_routes(self):
        """Register custom routes added via add_route."""
        for path, (handler, methods) in self.custom_routes.items():
            self.app.add_url_rule(
                path,
                endpoint=f"custom_{path.replace('/', '_')}",
                view_func=handler,
                methods=methods,
            )

        for path, (data_provider, methods) in self.custom_api_routes.items():

            def make_api_handler(provider):
                def api_handler():
                    if callable(provider):
                        data = provider()
                    else:
                        data = provider
                    return jsonify(data)

                return api_handler

            self.app.add_url_rule(
                path,
                endpoint=f"api_{path.replace('/', '_')}",
                view_func=make_api_handler(data_provider),
                methods=methods,
            )

    def start(self):
        """Start the test server."""
        # Register custom routes before starting
        self._register_custom_routes()

        def run_server():
            self.app.run(
                host="127.0.0.1", port=self.port, debug=False, use_reloader=False
            )

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to start
        time.sleep(2)

        # Verify server is running
        import requests

        try:
            response = requests.get(
                f"http://127.0.0.1:{self.port}/api/traceroute/graph", timeout=5
            )
            if response.status_code != 200:
                raise Exception(
                    f"Test server not responding correctly: {response.status_code}"
                )
        except Exception as e:
            raise Exception(f"Failed to start test server: {e}") from e

    def stop(self):
        """Stop the test server."""
        # Flask development server doesn't have a clean shutdown method
        # The daemon thread will be cleaned up when the main process exits
        pass


@pytest.fixture(scope="session")
def test_server():
    """Provide a generic test server for E2E tests."""
    server = GenericTestServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def test_server_url(test_server):
    """Provide the test server URL."""
    return f"http://127.0.0.1:{test_server.port}"


# Convenience fixtures for specific use cases
@pytest.fixture(scope="session")
def traceroute_graph_server():
    """Provide a test server specifically configured for traceroute graph testing."""
    server = GenericTestServer()

    # Add any additional routes specific to traceroute graph testing
    # server.add_api_route('/api/custom/endpoint', lambda: {'custom': 'data'})

    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def traceroute_graph_url(traceroute_graph_server):
    """Provide the traceroute graph URL from the test server."""
    return f"http://127.0.0.1:{traceroute_graph_server.port}/traceroute-graph"
