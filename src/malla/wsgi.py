#!/usr/bin/env python3
"""
WSGI entry point for Malla Web UI with Gunicorn support.

This module provides the WSGI application factory and a main function
that starts Gunicorn with appropriate configuration for production deployment.
"""

import logging
import os
import sys

from .config import get_config
from .web_ui import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def _build_gunicorn_config(cfg):
    worker_class = "gthread" if cfg.gunicorn_threads > 1 else "sync"

    gunicorn_config = {
        "bind": f"{cfg.host}:{cfg.port}",
        "workers": cfg.gunicorn_workers,
        "threads": cfg.gunicorn_threads,
        "worker_class": worker_class,
        "worker_connections": 1000,
        "max_requests": 1000,
        "max_requests_jitter": 50,
        "timeout": 30,
        "keepalive": 2,
        "preload_app": True,
        "access_log_format": '%({REMOTE_ADDR}e)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s',
        "accesslog": "-",
        "errorlog": "-",
        "loglevel": "info",
        "capture_output": True,
        "enable_stdio_inheritance": True,
    }

    if cfg.trusted_proxy_ips:
        gunicorn_config["forwarded_allow_ips"] = cfg.trusted_proxy_ips

    return gunicorn_config


def create_wsgi_app():
    """Create and return the WSGI application."""
    logger.info("Creating WSGI application for Gunicorn")
    return create_app()


# Lazy application creation to avoid config caching issues during testing
_application = None


def get_application():
    """Get the WSGI application instance, creating it if necessary."""
    global _application
    if _application is None:
        _application = create_wsgi_app()
    return _application


# WSGI application callable for servers - use a callable that defers execution
def application(*args, **kwargs):
    """WSGI application entry point."""
    app = get_application()
    _rearm_workers(app)
    return app(*args, **kwargs)


_CREATION_PID = None


def _rearm_workers(app):
    """After a preload fork, the workers inherited the master's warmer guard.

    Threads do not survive fork: re-arm the per-process background helpers
    once per worker pid (the guards in web_ui are pid-keyed and dedupe).
    """
    global _CREATION_PID
    pid = os.getpid()
    creator = app.config.get("_CREATOR_PID") if hasattr(app, "config") else None
    if creator is None:
        return
    if pid == creator:
        return
    marker = f"_worker_threads_pid_{pid}"
    if getattr(app, marker, False):
        return
    setattr(app, marker, True)
    try:
        from .web_ui import start_dashboard_warmer

        start_dashboard_warmer(app)
    except Exception as exc:  # noqa: BLE001 - best effort per worker
        logger.warning("Worker background threads failed to start: %s", exc)


def main():
    """Main entry point for running with Gunicorn."""
    logger.info("Starting Malla Web UI with Gunicorn")

    try:
        # Import gunicorn here to avoid hard dependency when not using WSGI
        from gunicorn.app.wsgiapp import WSGIApplication

        # Get configuration
        cfg = get_config()

        # Print startup information
        print("=" * 60)
        print("🌐 Malla Web UI (Gunicorn)")
        print("=" * 60)
        print(f"Database: {cfg.database_file}")
        print(f"Web UI: http://{cfg.host}:{cfg.port}")
        print(f"Workers: {cfg.gunicorn_workers or 'auto (gunicorn default)'}")
        print(f"Threads: {cfg.gunicorn_threads}")
        print(f"Debug mode: {cfg.debug}")
        print("=" * 60)
        print()

        gunicorn_config = _build_gunicorn_config(cfg)

        def _post_fork(server, worker):  # pragma: no cover - worker process
            app_obj = getattr(worker, "wsgi", None)
            if app_obj is None:
                app_obj = getattr(worker, "app", None)
            if app_obj is not None and hasattr(app_obj, "application"):
                app_obj = app_obj.application
            if app_obj is None:
                return
            try:
                from .web_ui import start_dashboard_warmer

                start_dashboard_warmer(app_obj)
            except Exception as exc:  # noqa: BLE001 - best effort
                logger.warning("Worker background threads failed: %s", exc)

        gunicorn_config["post_fork"] = _post_fork

        # Create Gunicorn application
        class MallaWSGIApplication(WSGIApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                if hasattr(self, "cfg") and self.cfg:
                    config = {
                        key: value
                        for key, value in self.options.items()
                        if key in self.cfg.settings and value is not None
                    }
                    for key, value in config.items():
                        self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        # Start Gunicorn
        logger.info(f"Starting Gunicorn server on {cfg.host}:{cfg.port}")
        MallaWSGIApplication(get_application(), gunicorn_config).run()

    except ImportError:
        logger.error(
            "Gunicorn is not installed. Please install it with: pip install gunicorn"
        )
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to start Gunicorn application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
