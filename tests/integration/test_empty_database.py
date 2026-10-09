"""Empty-database regression tests.

Two empty states are covered:

* *Fresh*: a database file that does not exist yet. The web app must create
  the core schema itself at startup (previously only the capture tool did,
  so every endpoint 500-ed with "no such table" — surfaced by UI smoke tests
  on ``/api/traceroute/data``).
* *Schema-only*: tables exist but contain no rows. Every ``/api/v1`` endpoint
  must answer 200 with empty/zero data or a clean coded 4xx — never 500.
"""

import sqlite3
import tempfile
from typing import Any

import pytest

from src.malla.config import AppConfig
from src.malla.database.repositories import DashboardRepository, NodeRepository
from src.malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures


def _clear_process_caches() -> None:
    """Drop process-global stat caches keyed without the database path.

    The dashboard/analytics caches are plain dicts with a short TTL; without
    this, a previous test's populated numbers (same process, different temp
    db) leak into the empty-database assertions.
    """
    import src.malla.database.repositories as repositories
    from src.malla.services.analytics_service import AnalyticsService
    from src.malla.services.gateway_service import GatewayService

    repositories._dashboard_stats_cache.clear()
    AnalyticsService._CACHE.clear()
    AnalyticsService._TIMELINE_CACHE.clear()
    GatewayService._cache.clear()


def _cache_state() -> dict[str, int]:
    import src.malla.database.repositories as repositories
    from src.malla.services.analytics_service import AnalyticsService

    return {
        "dashboard_cached": len(repositories._dashboard_stats_cache),
        "analytics_cached": len(AnalyticsService._CACHE),
        "timeline_cached": len(AnalyticsService._TIMELINE_CACHE),
    }


def _db_snapshot() -> dict[str, int | str | None]:
    import os

    path = os.getenv("MALLA_DATABASE_FILE")
    if not path or not os.path.exists(path):
        return {"path": path, "exists": False}
    conn = sqlite3.connect(path)
    try:
        nodes = conn.execute("SELECT COUNT(*) FROM node_info").fetchone()[0]
        pkts = conn.execute("SELECT COUNT(*) FROM packet_history").fetchone()[0]
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {"path": path, "nodes": nodes, "packets": pkts, "tables": len(tables)}
    finally:
        conn.close()


def _flush_process_wide_caches() -> None:
    """Clear process-wide caches keyed without the db path.

    The dashboard-stats / analytics caches are keyed without the database
    path, so values computed against one temporary database would leak into
    the next fixture within the same worker. The codebase is a src-layout
    that can be imported both as ``malla`` and ``src.malla`` (distinct module
    instances, each with their own caches), so both trees are flushed. This
    matches the flush used by the unit-level cache tests.
    """
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


@pytest.fixture()
def fresh_database_client():
    """App + client over a database file that does not exist yet."""
    _flush_process_wide_caches()
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    import os

    os.unlink(handle.name)
    try:
        # The web no longer writes DDL (contract since the migration registry):
        # bootstrap exactly like the capture daemon would, then verify the
        # empty-data behavior of a provisioned database.
        from src.malla.capture_startup import (
            init_database as _capture_init,
        )
        from src.malla.capture_startup import (
            run_write_locking_migrations as _capture_blocking,
        )

        _capture_init(handle.name)
        _capture_blocking(handle.name)
        app = create_app(AppConfig(database_file=handle.name))
        app.config["TESTING"] = True
        _clear_process_caches()
        yield app.test_client()
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass


@pytest.fixture()
def schema_only_client():
    """App + client over a database with the full schema but zero rows."""
    _flush_process_wide_caches()
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    connection = sqlite3.connect(handle.name)
    try:
        DatabaseFixtures()._create_schema(connection.cursor())
        connection.commit()
    finally:
        connection.close()
    try:
        from src.malla.capture_startup import (
            init_database as _capture_init,
        )
        from src.malla.capture_startup import (
            run_write_locking_migrations as _capture_blocking,
        )

        _capture_init(handle.name)
        _capture_blocking(handle.name)
        app = create_app(AppConfig(database_file=handle.name))
        app.config["TESTING"] = True
        _clear_process_caches()
        yield app.test_client()
    finally:
        import os

        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass


class TestFreshDatabaseBootstrap:
    @pytest.mark.integration
    def test_traceroute_data_empty_state(self, fresh_database_client):
        """Regression: /api/traceroute/data 500-ed ("no such table"/NoneType)."""
        response = fresh_database_client.get("/api/traceroute/data")
        assert response.status_code == 200
        body = response.get_json()
        assert body["data"] == []
        assert body["total_count"] == 0
        assert body["page"] == 1

    @pytest.mark.integration
    def test_table_endpoints_empty_state(self, fresh_database_client):
        for path in (
            "/api/packets/data",
            "/api/nodes/data",
            "/api/packets",
            "/api/nodes",
            "/api/stats",
            "/api/v1/nodes",
            "/api/v1/packets",
            "/api/v1/traceroutes",
            "/api/v1/gateways",
            "/api/v1/meta",
        ):
            response = fresh_database_client.get(path)
            assert response.status_code == 200, path
            if path.startswith("/api/v1"):
                body = response.get_json()
                assert set(body.keys()) == {"data", "meta"}, path


class TestApiV1EmptyDatabase:
    @pytest.mark.integration
    @pytest.mark.parametrize(
        "path,allowed",
        [
            ("/api/v1/nodes", {200}),
            ("/api/v1/nodes?sort=battery", {200}),
            ("/api/v1/nodes?has_position=true", {200}),
            ("/api/v1/nodes?last_seen_since=2026-01-01T00:00:00Z", {200}),
            ("/api/v1/nodes/123", {200, 404}),
            ("/api/v1/nodes/123/telemetry", {200, 404}),
            ("/api/v1/nodes/123/packets", {200, 404}),
            ("/api/v1/packets", {200}),
            ("/api/v1/packets?page_size=10&page=2", {200}),
            ("/api/v1/packets?primary_channel=LongFast", {200}),
            ("/api/v1/packets/1", {200, 404}),
            ("/api/v1/traceroutes", {200}),
            ("/api/v1/traceroutes?since=1", {200}),
            ("/api/v1/traceroutes/1", {200, 404}),
            ("/api/v1/gateways", {200}),
            ("/api/v1/gateways/!433d0c24", {200, 404}),
            ("/api/v1/stats/summary?range=24h", {200}),
            ("/api/v1/stats/summary?range=7d", {200}),
            ("/api/v1/stats/summary?range=30d", {200}),
            ("/api/v1/stats/summary?range=all", {200}),
            ("/api/v1/meta", {200}),
            ("/api/v1/meta/filters", {200}),
            ("/api/v1/locations", {200}),
            ("/api/v1/locations?include_links=true", {200}),
            ("/api/v1/locations?enrich=false", {200}),
            ("/api/v1/chat/messages", {200}),
            ("/api/v1/chat/relay-filters", {200}),
            ("/api/v1/longest-links", {200}),
            ("/api/v1/traceroute-graph", {200}),
            ("/api/v1/traceroute-hops/nodes", {200}),
            ("/api/v1/traceroute-link/1/2", {200}),
            ("/api/v1/related-nodes/1", {200}),
            ("/api/v1/nodes/1/direct-receptions", {200}),
            ("/api/v1/nodes/1/relay-node-analysis", {200}),
            ("/api/v1/nodes/123/locations", {200, 404}),
            ("/api/v1/openapi.json", {200}),
        ],
    )
    def test_never_500_on_empty_database(
        self, schema_only_client, path: str, allowed: set[int]
    ):
        response = schema_only_client.get(path)
        assert response.status_code in allowed, (
            path,
            response.get_data(as_text=True)[:200],
        )
        assert response.status_code != 500
        if (
            response.status_code == 200
            and path != "/api/v1/openapi.json"
            and "include_links=true" not in path
        ):
            body = response.get_json()
            assert set(body.keys()) == {"data", "meta"}, path

    @pytest.mark.integration
    def test_list_payloads_are_empty(self, schema_only_client):
        for path, _payload_key in (
            ("/api/v1/nodes", "data"),
            ("/api/v1/packets", "data"),
            ("/api/v1/traceroutes", "data"),
            ("/api/v1/gateways", "data"),
        ):
            body = schema_only_client.get(path).get_json()
            assert body["data"] == [], path
            pagination = body["meta"]["pagination"]
            assert pagination["total"] == 0, path
            assert pagination["total_pages"] == 0, path
            assert pagination["has_next"] is False, path
            assert pagination["has_prev"] is False, path

    @pytest.mark.integration
    def test_summary_zeros_on_empty_database(self, schema_only_client):
        body = schema_only_client.get("/api/v1/stats/summary?range=24h").get_json()
        totals = body["data"]["totals"]
        assert totals["total_nodes"] == 0, (
            totals,
            _cache_state(),
            _db_snapshot(),
            {
                "app_db": schema_only_client.application.config["DATABASE_FILE"],
                "env_db": __import__("os").getenv("MALLA_DATABASE_FILE"),
                "live_nodes": NodeRepository.get_nodes(limit=1, order_by="node_id")[
                    "total_count"
                ],
                "dash": DashboardRepository.get_stats(),
            },
        )
        assert totals["total_packets"] == 0
        assert totals["active_nodes_24h"] == 0
        assert body["data"]["activity"]["buckets"]
        assert body["data"]["top_nodes"] == []
        assert body["data"]["transport_types"] == []

    @pytest.mark.integration
    def test_meta_zeros_on_empty_database(self, schema_only_client):
        data = schema_only_client.get("/api/v1/meta").get_json()["data"]
        assert data["node_count"] == 0
        assert isinstance(data["database_size_bytes"], int)
        assert data["server_time_utc"].endswith("Z")

    @pytest.mark.integration
    def test_empty_database_missing_ids_are_coded_404(self, schema_only_client):
        for path, code in (
            ("/api/v1/nodes/123", "node_not_found"),
            ("/api/v1/packets/1", "packet_not_found"),
            ("/api/v1/traceroutes/1", "traceroute_not_found"),
        ):
            response = schema_only_client.get(path)
            assert response.status_code == 404, path
            error: dict[str, Any] = response.get_json()["error"]
            assert error["code"] == code, path
