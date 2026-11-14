"""Unit tests for the capture maintenance slot's DERIVED retry and lock knobs."""

import sqlite3
from contextlib import contextmanager

from malla.capture_startup import (
    LOCK_STALE_AFTER_DEFAULT,
    LOCK_STALE_AFTER_ENV,
    migration_lock_stale_after,
    retry_derived_migrations,
)


def _fresh_db(tmp_path) -> str:
    path = str(tmp_path / "retry.db")
    sqlite3.connect(path).close()
    return path


def test_retry_derived_migrations_is_quiet_when_up_to_date(tmp_path) -> None:
    path = _fresh_db(tmp_path)
    retry_derived_migrations(path)  # must not raise
    retry_derived_migrations(path)  # idempotent: second pass finds nothing


def test_retry_derived_migrations_survives_a_broken_database(tmp_path) -> None:
    bogus = str(tmp_path / "missing-dir" / "x.db")  # parent dir absent
    retry_derived_migrations(bogus)  # logged, never raised


def test_retry_applies_pending_planner_stats(tmp_path) -> None:
    path = _fresh_db(tmp_path)
    retry_derived_migrations(path)

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT value FROM malla_meta WHERE key = 'migration:planner_stats'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_lock_staleness_env_overrides_default(monkeypatch) -> None:
    monkeypatch.delenv(LOCK_STALE_AFTER_ENV, raising=False)
    assert migration_lock_stale_after() == LOCK_STALE_AFTER_DEFAULT

    monkeypatch.setenv(LOCK_STALE_AFTER_ENV, "1800")
    assert migration_lock_stale_after() == 1800.0

    monkeypatch.setenv(LOCK_STALE_AFTER_ENV, "not-a-number")
    assert migration_lock_stale_after() == LOCK_STALE_AFTER_DEFAULT


def test_runner_threads_stale_after_into_the_lock(monkeypatch) -> None:
    """The env knob reaches migration_lock via run_migrations(stale_after=...)."""
    from malla.migrations import Phase, run_migrations
    from malla.migrations import runner as runner_module

    seen: dict[str, float] = {}

    @contextmanager
    def _spy_lock(conn, *, timeout, stale_after):  # noqa: ANN001
        seen["stale_after"] = stale_after
        yield

    monkeypatch.setattr(runner_module, "migration_lock", _spy_lock)
    monkeypatch.setenv(LOCK_STALE_AFTER_ENV, "1234")

    conn = sqlite3.connect(":memory:")
    try:
        from malla.capture_startup import migration_lock_stale_after

        run_migrations(
            conn,
            phases=(Phase.SCHEMA,),
            stale_after=migration_lock_stale_after(),
        )
    finally:
        conn.close()
    assert seen["stale_after"] == 1234.0
