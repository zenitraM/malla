"""Integration: web boots against an uninitialized database answer 503.

``connection.init_database`` only verifies (the capture daemon owns DDL), so a
web process pointed at a database ``malla-capture`` has never run must get a
clear, coded answer — not one 500 per missing table.
"""

import sqlite3

from src.malla.config import AppConfig
from src.malla.web_ui import create_app


def _flush_stat_caches() -> None:
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


def _app_for(path: str):
    app = create_app(AppConfig(database_file=path))
    app.config["TESTING"] = True
    return app


def _fresh_client(tmp_path, name: str = "fresh.db"):
    path = str(tmp_path / name)
    sqlite3.connect(path).close()  # a valid database file with no tables

    _flush_stat_caches()
    return _app_for(path)


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


def test_legacy_pair_schema_answers_503(tmp_path) -> None:
    """A pre-rollup release database (packet_history + node_info only) gets
    the coded 503 on the read paths that hard-depend on the rollups -- not
    one raw ``no such table`` 500 apiece.

    Seeded literally instead of derived from ``REQUIRED_TABLES``: the
    regression guarded here (the tuple narrowed to the core pair) makes the
    helper agree with exactly this schema, so a derived fixture could never
    notice it.
    """

    path = str(tmp_path / "legacy-pair.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE packet_history (id INTEGER PRIMARY KEY,"
            " timestamp REAL, topic TEXT, from_node_id INTEGER,"
            " to_node_id INTEGER, portnum INTEGER, portnum_name TEXT,"
            " gateway_id TEXT, channel_id INTEGER, raw_payload BLOB,"
            " processed_successfully INTEGER)"
        )
        conn.execute(
            "CREATE TABLE node_info (node_id INTEGER PRIMARY KEY,"
            " long_name TEXT, short_name TEXT, hw_model TEXT)"
        )
        conn.commit()
    finally:
        conn.close()

    _flush_stat_caches()
    client = _app_for(path).test_client()

    # Landing page: the guidance render, not a traceback.
    resp = client.get("/")
    assert resp.status_code == 503
    assert "malla-capture" in resp.get_data(as_text=True)

    for url in ("/api/v1/nodes", "/api/v1/packets"):
        resp = client.get(url)
        assert resp.status_code == 503, url
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

    # Bootstrap the required schema; the handler must no longer interfere.
    # The required set covers the rollup/activity tables the read paths
    # hard-depend on, not just packet_history/node_info.
    from src.malla.database.connection import REQUIRED_TABLES

    conn = sqlite3.connect(app.config["DATABASE_FILE"])
    try:
        for table in REQUIRED_TABLES:
            cols = (
                "id INTEGER PRIMARY KEY"
                if table == "packet_history"
                else ("node_id INTEGER PRIMARY KEY" if "node" in table else "x")
            )
            conn.execute(f"CREATE TABLE {table} ({cols})")
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/guidance-probe")
    assert resp.status_code == 500  # handler returned None: default handling
    assert "database_not_initialized" not in resp.get_data(as_text=True)


def test_v1_missing_activity_table_answers_503(tmp_path) -> None:
    """The activity store is a hard dependency, not an optional rollup.

    Dropping one activity table must produce the coded bootstrap response, not
    a generic 500 from the dashboard summary.
    """
    from tests.fixtures.database_fixtures import DatabaseFixtures

    path = str(tmp_path / "missing-activity.db")
    DatabaseFixtures().create_test_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TABLE activity_packet_quarter")
        conn.commit()
    finally:
        conn.close()

    # Process-wide caches are keyed without the database path; a previous
    # test's populated activity would otherwise serve 200 without touching
    # the missing table.
    import importlib

    for pkg in ("malla", "src.malla"):
        try:
            analytics = importlib.import_module(f"{pkg}.services.analytics_service")
            analytics.AnalyticsService._CACHE.clear()
            analytics.AnalyticsService._TIMELINE_CACHE.clear()
        except Exception:  # noqa: BLE001 - flush is best-effort
            pass

    app = create_app(AppConfig(database_file=path))
    app.config["TESTING"] = True
    client = app.test_client()

    resp = client.get("/api/v1/stats/summary")
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "database_not_initialized"
