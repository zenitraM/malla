#!/usr/bin/env python3
"""
Meshtastic Mesh Health Web UI - Main Application

A Flask web application for browsing and analyzing Meshtastic mesh network data.
This is the main entry point for the web UI component.
"""

import atexit
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request
from werkzeug.exceptions import InternalServerError

# Import application configuration loader
from . import capture_rollups
from .config import AppConfig, get_config

# Optional CORS support will be checked inline
# Import configuration and database setup
from .database.connection import init_database, required_tables_missing
from .migrations import Phase, run_migrations
from .migrations.derived import PLANNER_STATS
from .routes import register_routes

# Import utility functions for template filters
from .utils.formatting import format_node_id, format_time_ago
from .utils.node_utils import (
    start_cache_cleanup,
    stop_cache_cleanup,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

#: Shown (plainly styled, no DB access) while the database is still
#: uninitialized; the capture daemon or the migration CLI bootstraps it.
_UNINITIALIZED_DB_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Database not initialized</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 42rem; margin: 4rem auto; padding: 0 1rem; color: #1f2430; }
h1 { font-size: 1.25rem; } code, pre { background: #f2f4f8; border-radius: 4px; }
code { padding: 0.1rem 0.35rem; } pre { padding: 0.75rem 1rem; overflow-x: auto; }
</style></head>
<body>
<h1>Database not initialized</h1>
<p>{{ message }}</p>
<pre>malla-capture
{{ cli_command }}</pre>
</body>
</html>"""

_BOOTSTRAP_CLI_COMMAND = "python -m malla.migrations.cli"

# One planner-stats bootstrap attempt per database path, process-wide: the
# DERIVED migration is idempotent, but there is no reason to race it either.
_PLANNER_STATS_STARTED: set[str] = set()
_PLANNER_STATS_LOCK = threading.Lock()

# Static-asset cache-busting token; changes each process start (i.e. each deploy).
_ASSET_VERSION = str(int(time.time()))


def _spawn_planner_stats_bootstrap(db_path: str) -> None:
    """Run the PLANNER_STATS DERIVED migration once, in a daemon thread.

    The capture daemon normally owns DERIVED work; this restores parity for
    capture-less web boots, which would otherwise serve a cold ``sqlite_stat1``
    on a large database — exactly the mis-planned-query scenario the ANALYZE
    exists to prevent. Idempotent, and never raises into request serving.
    """

    def _run() -> None:
        conn: sqlite3.Connection | None = None
        try:
            from malla.capture_startup import configure_connection

            conn = sqlite3.connect(db_path, timeout=30.0)
            configure_connection(conn)
            results = run_migrations(
                conn,
                migrations=[PLANNER_STATS],
                phases=(Phase.DERIVED,),
                take_lock=False,
            )
            for result in results:
                logger.info("Planner-stats bootstrap: %s", result.describe())
        except Exception as exc:  # noqa: BLE001 - background, best effort
            logger.warning("Planner-stats bootstrap failed: %s", exc)
        finally:
            if conn is not None:
                conn.close()

    with _PLANNER_STATS_LOCK:
        if db_path in _PLANNER_STATS_STARTED:
            return
        _PLANNER_STATS_STARTED.add(db_path)
    threading.Thread(target=_run, name="planner-stats-bootstrap", daemon=True).start()


# Dashboard warmer: one attempt per process. Fires the aggregate summary once
# at boot and refreshes it inside the analytics TTL window, so the first
# visitor gets a warm dashboard instead of the multi-second cold aggregate.
# Same contract as every background worker here: idempotent work, daemon
# thread, never raises into request serving.
_SUMMARY_WARMER_STARTED: set[str] = set()
_SUMMARY_WARMER_LOCK = threading.Lock()


def start_dashboard_warmer(flask_app: Any, interval_s: int = 45) -> None:
    """Pre-warm and keep-warm the dashboard summary aggregate (daemon thread).

    Runs inside *flask_app*'s context so ``get_db_connection`` resolves the
    same database the app serves. Idempotent work, daemon thread, never
    raises into request serving.
    """

    def _warm_once(inner_app: Any) -> None:
        from .services.analytics_service import AnalyticsService

        with inner_app.app_context():
            AnalyticsService.get_analytics_data()
            AnalyticsService.get_activity_timeline("24h", 0)

    def _loop() -> None:
        import time as _time

        while True:
            try:
                _warm_once(flask_app)
            except Exception as exc:  # noqa: BLE001 - background, best effort
                logger.debug("Dashboard warmer cycle failed: %s", exc)
            _time.sleep(interval_s)

    guard_key = str(getattr(flask_app, "config", {}).get("DATABASE_FILE", ""))
    with _SUMMARY_WARMER_LOCK:
        if guard_key in _SUMMARY_WARMER_STARTED:
            return
        _SUMMARY_WARMER_STARTED.add(guard_key)
    threading.Thread(target=_loop, name="dashboard-warmer", daemon=True).start()


class TrustedProxyClientIPMiddleware:
    """Rewrite REMOTE_ADDR from a trusted proxy-provided header."""

    def __init__(self, app, trusted_proxy_ips: str, client_ip_header: str):  # noqa: ANN001
        self.app = app
        self.trusted_proxy_ips = {
            ip.strip() for ip in trusted_proxy_ips.split(",") if ip.strip()
        }
        self.client_ip_header = f"HTTP_{client_ip_header.upper().replace('-', '_')}"

    def __call__(self, environ, start_response):  # noqa: ANN001
        remote_addr = environ.get("REMOTE_ADDR")
        forwarded_ip = environ.get(self.client_ip_header)

        if remote_addr in self.trusted_proxy_ips and forwarded_ip:
            # Preserve the original peer IP for troubleshooting.
            environ["trusted_proxy.orig_remote_addr"] = remote_addr
            environ["REMOTE_ADDR"] = forwarded_ip.split(",", 1)[0].strip()

        return self.app(environ, start_response)


def make_json_safe(obj):
    """
    Recursively convert an object to be JSON-serializable by handling bytes objects.

    Args:
        obj: The object to make JSON-safe

    Returns:
        A JSON-serializable version of the object
    """
    if isinstance(obj, bytes):
        # Convert bytes to hex string
        return obj.hex()
    elif isinstance(obj, dict):
        return {key: make_json_safe(value) for key, value in obj.items()}
    elif isinstance(obj, list | tuple):
        return [make_json_safe(item) for item in obj]
    elif hasattr(obj, "__dict__"):
        # Handle objects with attributes by converting to dict
        return make_json_safe(obj.__dict__)
    else:
        # Return as-is for JSON-serializable types (str, int, float, bool, None)
        return obj


def create_app(cfg: AppConfig | None = None):  # noqa: D401
    """Create and configure the Flask application.

    If *cfg* is ``None`` the configuration is loaded via :func:`get_config`.
    Tests can pass an :class:`~malla.config.AppConfig` instance directly which
    eliminates the need for fiddling with environment variables.
    """

    logger.info("Creating Flask application")

    # Get the package directory for templates and static files
    package_dir = Path(__file__).parent

    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )

    # ---------------------------------------------------------------------
    # Load application configuration (YAML + environment overrides)
    # ---------------------------------------------------------------------

    if cfg is None:
        cfg = get_config()
    else:
        # Ensure subsequent calls to get_config() return this instance (tests)
        from .config import _override_config  # local import to avoid circular

        _override_config(cfg)

    # Persist config on Flask instance for later use
    app.config["APP_CONFIG"] = cfg

    # Setup OpenTelemetry if endpoint is configured
    if cfg.otlp_endpoint:
        from .telemetry import setup_telemetry

        setup_telemetry(app, cfg.otlp_endpoint)

    # Apply ProxyFix after other WSGI middleware so they see rewritten values.
    if cfg.trusted_proxy_ips:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = TrustedProxyClientIPMiddleware(
            app.wsgi_app,
            cfg.trusted_proxy_ips,
            cfg.trusted_proxy_client_ip_header,
        )
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_proto=1,
        )

    # Mirror a few frequently-used values to top-level keys for backwards
    # compatibility with the existing code base. Over time we should migrate
    # direct usages to the nested ``APP_CONFIG`` object instead.
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["DATABASE_FILE"] = cfg.database_file

    # Ensure helper modules relying on env-var fallback pick up the correct DB
    # path in contexts where they cannot access Flask's app.config (e.g.
    # standalone scripts).  This is primarily relevant for the test suite.
    os.environ["MALLA_DATABASE_FILE"] = str(cfg.database_file)

    # ---------------------------------------------------------------------

    # Add template filters for consistent formatting
    @app.template_filter("format_node_id")
    def format_node_id_filter(node_id):
        """Template filter for consistent node ID formatting."""
        return format_node_id(node_id)

    @app.template_filter("format_node_short_name")
    def format_node_short_name_filter(node_name):
        """Template filter for short node names."""
        if not node_name:
            return "Unknown"
        # If it's a long name with hex ID in parentheses, extract just the name part
        if " (" in node_name and node_name.endswith(")"):
            return node_name.split(" (")[0]
        return node_name

    @app.template_filter("format_time_ago")
    def format_time_ago_filter(dt):
        """Template filter for relative time formatting."""
        return format_time_ago(dt)

    @app.template_filter("safe_json")
    def safe_json_filter(obj, indent=None):
        """
        Template filter for safely serializing objects to JSON, handling bytes objects.

        Args:
            obj: The object to serialize
            indent: Optional indentation for pretty printing

        Returns:
            JSON string with bytes objects converted to hex strings
        """
        try:
            safe_obj = make_json_safe(obj)
            return json.dumps(safe_obj, indent=indent, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error in safe_json filter: {e}")
            return json.dumps(
                {"error": f"Serialization failed: {str(e)}"}, indent=indent
            )

    @app.template_filter("format_rssi")
    def format_rssi_filter(rssi):
        """Template filter for consistent RSSI formatting with 1 decimal place."""
        if rssi is None:
            return "N/A"
        try:
            return f"{float(rssi):.1f}"
        except (ValueError, TypeError):
            return str(rssi)

    @app.template_filter("format_snr")
    def format_snr_filter(snr):
        """Template filter for consistent SNR formatting with 2 decimal places."""
        if snr is None:
            return "N/A"
        try:
            return f"{float(snr):.2f}"
        except (ValueError, TypeError):
            return str(snr)

    @app.template_filter("format_signal")
    def format_signal_filter(value, decimals=1):
        """Template filter for consistent signal value formatting with configurable decimal places."""
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.{decimals}f}"
        except (ValueError, TypeError):
            return str(value)

    # ------------------------------------------------------------------
    # Markdown rendering filter & context processor for config variables
    # ------------------------------------------------------------------

    try:
        import markdown as _markdown  # import locally to avoid hard dependency at runtime until used
    except ModuleNotFoundError:  # pragma: no cover – dependency should be present
        _markdown = None  # type: ignore[assignment]

    @app.template_filter("markdown")
    def markdown_filter(text: str | None):  # noqa: ANN001
        """Render *text* (Markdown) to HTML for safe embedding."""

        if text is None:
            return ""
        if _markdown is None:
            logger.warning("markdown package not installed – returning raw text")
            return text
        from markupsafe import Markup

        return Markup(_markdown.markdown(text))

    @app.context_processor
    def inject_config():
        """Inject selected config values into all templates."""

        return {
            "APP_NAME": cfg.name,
            "APP_CONFIG": cfg,
            "DATABASE_FILE": cfg.database_file,
            # Cache-busting token for static assets: changes each time the app
            # starts (i.e. on every deploy/restart), so browsers reliably pick
            # up updated JS/CSS instead of serving a stale cached copy.
            "ASSET_VERSION": _ASSET_VERSION,
        }

    # Initialize database
    logger.info("Initializing database connection")
    init_database()

    # ---------------------------------------------------------------------
    # Uninitialized-database guidance (web-only boots without capture).
    # A locked/busy database keeps its default handling: the check below
    # returns an empty missing-list for every initialized schema.
    # ---------------------------------------------------------------------

    @app.errorhandler(sqlite3.OperationalError)
    def _database_operational_error(exc: sqlite3.OperationalError):
        """Answer with boot guidance while the database is uninitialized."""
        from flask import current_app

        missing = required_tables_missing()
        if not missing:
            # Initialized: locked/timeout errors keep their default path. An
            # errorhandler returning None would break response finalization,
            # so reproduce Flask's own default here (logged identically).
            if exc.__traceback__ is not None:
                current_app.log_exception((type(exc), exc, exc.__traceback__))
            return InternalServerError()
        message = (
            "Database not initialized. Run the capture daemon once "
            "(malla-capture) to bootstrap it, then retry."
        )
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "error": {
                            "code": "database_not_initialized",
                            "message": message,
                        }
                    }
                ),
                503,
            )
        return (
            render_template_string(
                _UNINITIALIZED_DB_PAGE,
                message=message,
                cli_command=_BOOTSTRAP_CLI_COMMAND,
            ),
            503,
        )

    # Capture-less parity for the planner-stats DERIVED migration: without
    # sqlite_stat1 the planner mis-scales plans on a big database. The check
    # is a cheap marker/stats read; the thread no-ops when capture ran.
    try:
        _db_file = str(app.config.get("DATABASE_FILE") or "")
        _check = sqlite3.connect(_db_file, timeout=5.0)
        try:
            _planner_pending = PLANNER_STATS.pending(_check, None)
        finally:
            _check.close()
        if _planner_pending:
            _spawn_planner_stats_bootstrap(_db_file)
    except Exception as exc:  # noqa: BLE001 - must not block app creation
        logger.debug("Planner-stats bootstrap check skipped: %s", exc)

    # Rollup maintenance: one budgeted catch-up chunk now (mirrors the
    # AnalyticsService lazy-rollup precedent) plus a persistent low-priority
    # refresher. The capture daemon refreshes too; overlap is safe because
    # every rollup write is idempotent on its natural keys. NOTE: this
    # intentionally deviates from design §0's "web does a single bounded
    # chunk only" - the standing sign-off is a persistent thread here as well.
    if capture_rollups.refresh_enabled():
        db_path = str(app.config.get("DATABASE_FILE") or cfg.database_file)
        try:
            capture_rollups.run_boot_refresh(db_path)
        except Exception as exc:  # noqa: BLE001 - never block startup
            logger.warning("Rollup boot refresh failed: %s", exc)
        capture_rollups.ensure_refresh_thread(db_path)

    # Keep the dashboard aggregates warm (see start_dashboard_warmer).
    try:
        start_dashboard_warmer(app)
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Dashboard warmer failed to start: %s", exc)

    # Start periodic cache cleanup for node names
    logger.info("Starting node name cache cleanup background thread")
    start_cache_cleanup()

    # Register cleanup on app shutdown
    atexit.register(stop_cache_cleanup)

    # Register all routes
    logger.info("Registering application routes")
    register_routes(app)

    # Add health check endpoint
    @app.route("/health")
    def health_check():
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "service": "meshtastic-mesh-health-ui",
            "version": "2.0.0",
        }

    # Add application info
    @app.route("/info")
    def app_info():
        """Application information endpoint."""
        return {
            "name": "Meshtastic Mesh Health Web UI",
            "version": "2.0.0",
            "description": "Web interface for monitoring Meshtastic mesh network health",
            "database_file": app.config["DATABASE_FILE"],
            "components": {
                "database": "Repository pattern with SQLite",
                "models": "Data models and packet parsing",
                "services": "Business logic layer",
                "utils": "Utility functions",
                "routes": "HTTP request handling",
            },
        }

    logger.info("Flask application created successfully")
    return app


def main():
    """Main entry point for the application."""
    logger.info("Starting Meshtastic Mesh Health Web UI")

    try:
        # Create the application
        app = create_app()

        # Use configuration values (environment overrides already applied)
        cfg: AppConfig = app.config.get("APP_CONFIG")  # type: ignore[assignment]

        host = cfg.host
        port = cfg.port
        debug = cfg.debug

        # Print startup information
        print("=" * 60)
        print("🌐 Meshtastic Mesh Health Web UI")
        print("=" * 60)
        print(f"Database: {app.config['DATABASE_FILE']}")
        print(f"Web UI: http://{host}:{port}")
        print(f"Debug mode: {debug}")
        print(f"Log level: {logging.getLogger().level}")
        print("=" * 60)
        print()

        logger.info(f"Starting server on {host}:{port} (debug={debug})")

        # Run the application
        app.run(host=host, port=port, debug=debug, threaded=True)

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
