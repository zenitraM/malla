"""Integration: web boots against an uninitialized database answer 503.

``connection.init_database`` only verifies (the capture daemon owns DDL), so a
web process pointed at a database ``malla-capture`` has never run must get a
clear, coded answer — not one 500 per missing table.
"""

import sqlite3

from src.malla.config import AppConfig
from src.malla.web_ui import create_app


def _fresh_client(tmp_path, name: str = "fresh.db"):
    path = str(tmp_path / name)
    sqlite3.connect(path).close()  # a valid database file with no tables

    # Process-wide stat caches are keyed without the database path; a previous
    # test's populated numbers would turn this empty-DB request into a 200.
    import importlib

    for pkg in ("malla", "src.malla"):
        try:
            repositories = importlib.import_module(f"{pkg}.database.repositories")
            repositories._dashboard_stats_cache.clear()
        except Exception:  # noqa: BLE001 - flush is best-effort
            pass
        try:
            analytics = importlib.import_module(f"{pkg}.services.analytics_service")
            analytics.AnalyticsService._CACHE.clear()
            analytics.AnalyticsService._TIMELINE_CACHE.clear()
        except Exception:  # noqa: BLE001 - flush is best-effort
            pass
        try:
            gateway = importlib.import_module(f"{pkg}.services.gateway_service")
            gateway.GatewayService._cache.clear()
        except Exception:  # noqa: BLE001 - flush is best-effort
            pass

    app = create_app(AppConfig(database_file=path))
    app.config["TESTING"] = True
    return app


def test_index_answers_503_with_bootstrap_guidance(tmp_path) -> None:
    client = _fresh_client(tmp_path).test_client()

    resp = client.get("/")
    assert resp.status_code == 503
    body = resp.get_data(as_text=True)
    assert "malla-capture" in body
    assert "python -m malla.migrations.cli" in body
    assert "Database not initialized" in body


def test_api_paths_answer_503_envelope(tmp_path) -> None:
    app = _fresh_client(tmp_path)

    # The legacy /api views catch database errors internally; the envelope
    # contract below is what every propagating API surface (v1 included) gets.
    @app.route("/api/guidance-probe")
    def _probe():
        raise sqlite3.OperationalError("no such table: probe")

    client = app.test_client()
    resp = client.get("/api/guidance-probe")

    assert resp.status_code == 503
    error = resp.get_json()["error"]
    assert error["code"] == "database_not_initialized"
    assert "malla-capture" in error["message"]


def test_initialized_database_keeps_default_error_handling(tmp_path) -> None:
    """A present schema means the handler steps aside (locked DBs included)."""
    app = _fresh_client(tmp_path)

    @app.route("/api/guidance-probe")
    def _probe():
        raise sqlite3.OperationalError("database is locked")

    client = app.test_client()
    assert client.get("/").status_code == 503

    # Bootstrap the minimal schema; the handler must no longer interfere.
    conn = sqlite3.connect(app.config["DATABASE_FILE"])
    try:
        conn.execute("CREATE TABLE packet_history (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE node_info (node_id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/guidance-probe")
    assert resp.status_code == 500  # handler returned None: default handling
    assert "database_not_initialized" not in resp.get_data(as_text=True)
