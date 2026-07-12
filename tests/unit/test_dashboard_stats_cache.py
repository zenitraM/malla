"""Tests for the dashboard statistics TTL cache.

DashboardRepository.get_stats runs an all-time COUNT(*) plus 24h aggregates over
packet_history on the most-visited page ("/") and /api/stats. A short TTL cache
keeps repeated views O(1); these tests pin that behaviour.
"""

import malla.database.repositories as repositories
from malla.database.repositories import DashboardRepository


def test_get_stats_cached_within_ttl(temp_database, monkeypatch):
    """A second call within the TTL reuses the cache and skips the DB."""

    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    repositories._dashboard_stats_cache.clear()

    calls = {"n": 0}
    real_get_conn = repositories.get_db_connection

    def counting_get_conn():
        calls["n"] += 1
        return real_get_conn()

    monkeypatch.setattr(repositories, "get_db_connection", counting_get_conn)

    first = DashboardRepository.get_stats()
    second = DashboardRepository.get_stats()

    assert first == second
    assert "total_packets" in first
    # Only the first call touches the database; the second is served from cache.
    assert calls["n"] == 1


def test_get_stats_recomputes_after_ttl_expiry(temp_database, monkeypatch):
    """Once the cache entry ages past the TTL the stats are recomputed."""

    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    repositories._dashboard_stats_cache.clear()

    calls = {"n": 0}
    real_get_conn = repositories.get_db_connection

    def counting_get_conn():
        calls["n"] += 1
        return real_get_conn()

    monkeypatch.setattr(repositories, "get_db_connection", counting_get_conn)

    DashboardRepository.get_stats()
    assert calls["n"] == 1

    # Age the cached entry beyond the TTL by rewriting its timestamp.
    cached_at, cached_stats = repositories._dashboard_stats_cache[None]
    repositories._dashboard_stats_cache[None] = (
        cached_at - repositories.DASHBOARD_STATS_CACHE_TTL_SECONDS - 1,
        cached_stats,
    )

    DashboardRepository.get_stats()
    assert calls["n"] == 2


def test_get_stats_cache_keyed_by_gateway(temp_database, monkeypatch):
    """Different gateway filters are cached independently."""

    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    repositories._dashboard_stats_cache.clear()

    DashboardRepository.get_stats()
    DashboardRepository.get_stats(gateway_id="!deadbeef")

    assert None in repositories._dashboard_stats_cache
    assert "!deadbeef" in repositories._dashboard_stats_cache
