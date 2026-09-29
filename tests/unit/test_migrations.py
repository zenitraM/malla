"""Tests for the migration runner: ordering, markers, phases, failure isolation."""

import socket
import sqlite3
import time

import pytest

from malla.migrations import (
    MIGRATIONS,
    Migration,
    Phase,
    Status,
    ensure_meta_table,
    forget_marker,
    marker_key,
    read_marker,
    run_migrations,
)
from malla.migrations.base import Watermark


def _conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE data (value INTEGER)")
    conn.commit()
    return conn


def _append(
    name: str, phase: Phase, log: list[str], *, raises: bool = False
) -> Migration:
    def apply(conn: sqlite3.Connection, watermark: Watermark) -> Watermark:
        if raises:
            raise RuntimeError(f"{name} exploded")
        conn.execute("INSERT INTO data (value) VALUES (?)", (len(log),))
        log.append(name)
        return watermark

    return Migration(name=name, phase=phase, apply=apply)


def test_phases_run_in_order_and_markers_are_written(tmp_path):
    log: list[str] = []
    migrations = (
        _append("derived_one", Phase.DERIVED, log),
        _append("schema_one", Phase.SCHEMA, log),
        _append("blocking_one", Phase.BLOCKING, log),
    )

    conn = _conn(tmp_path / "order.db")
    results = run_migrations(conn, migrations, take_lock=False)

    assert log == ["schema_one", "blocking_one", "derived_one"]
    assert [r.status for r in results] == [Status.APPLIED] * 3
    # One-shot migrations record "applied, nothing to track" and report no
    # watermark; the stored value is the empty-string sentinel.
    assert [r.watermark for r in results] == [None, None, None]
    for migration in migrations:
        recorded, watermark = read_marker(conn, migration.name)
        assert recorded is True
        assert watermark == ""
    conn.close()


def test_second_run_is_a_noop_for_one_shot_migrations(tmp_path):
    log: list[str] = []
    migrations = (_append("once", Phase.DERIVED, log),)

    conn = _conn(tmp_path / "repeat.db")
    first = run_migrations(conn, migrations, take_lock=False)
    second = run_migrations(conn, migrations, take_lock=False)

    assert [r.status for r in first] == [Status.APPLIED]
    assert [r.status for r in second] == [Status.SKIPPED]
    assert log == ["once"]
    conn.close()


def test_forget_marker_makes_it_run_again(tmp_path):
    log: list[str] = []
    migrations = (_append("again", Phase.DERIVED, log),)

    conn = _conn(tmp_path / "forget.db")
    run_migrations(conn, migrations, take_lock=False)
    assert forget_marker(conn, "again") is True
    conn.commit()
    assert forget_marker(conn, "again") is False

    results = run_migrations(conn, migrations, take_lock=False)
    assert [r.status for r in results] == [Status.APPLIED]
    assert log == ["again", "again"]
    conn.close()


def test_watermark_is_stored_and_handed_back(tmp_path):
    seen: list[Watermark] = []

    def apply(conn: sqlite3.Connection, watermark: Watermark) -> Watermark:
        seen.append(watermark)
        return "2026-01-01T00:00:00"

    def pending(conn: sqlite3.Connection, watermark: Watermark) -> bool:
        # Incremental migration: still pending while the watermark lags.
        return watermark != "2026-01-01T00:00:00"

    migration = Migration(
        name="incremental", phase=Phase.DERIVED, apply=apply, pending=pending
    )

    conn = _conn(tmp_path / "watermark.db")
    first = run_migrations(conn, (migration,), take_lock=False)
    second = run_migrations(conn, (migration,), take_lock=False)

    assert [r.status for r in first] == [Status.APPLIED]
    assert [r.status for r in second] == [Status.SKIPPED]
    assert seen == [None]
    assert read_marker(conn, "incremental") == (True, "2026-01-01T00:00:00")
    conn.close()


def test_phase_filter_only_runs_the_selected_phase(tmp_path):
    log: list[str] = []
    migrations = (
        _append("schema_one", Phase.SCHEMA, log),
        _append("derived_one", Phase.DERIVED, log),
    )

    conn = _conn(tmp_path / "phases.db")
    results = run_migrations(conn, migrations, phases=(Phase.DERIVED,), take_lock=False)

    assert log == ["derived_one"]
    assert [r.name for r in results] == ["derived_one"]
    conn.close()


def test_failure_is_isolated_and_does_not_advance_the_marker(tmp_path):
    log: list[str] = []
    migrations = (
        _append("broken", Phase.DERIVED, log, raises=True),
        _append("after", Phase.DERIVED, log),
    )

    conn = _conn(tmp_path / "failure.db")
    results = run_migrations(conn, migrations, take_lock=False)

    assert [r.status for r in results] == [Status.FAILED, Status.APPLIED]
    assert log == ["after"]
    assert read_marker(conn, "broken") == (False, None)
    assert "exploded" in results[0].detail
    conn.close()


def test_strict_mode_raises(tmp_path):
    log: list[str] = []
    migrations = (_append("broken", Phase.DERIVED, log, raises=True),)

    conn = _conn(tmp_path / "strict.db")
    with pytest.raises(RuntimeError, match="exploded"):
        run_migrations(conn, migrations, strict=True, take_lock=False)
    conn.close()


def test_dry_run_reports_without_applying(tmp_path):
    log: list[str] = []
    migrations = (_append("later", Phase.DERIVED, log),)

    conn = _conn(tmp_path / "dry.db")
    results = run_migrations(conn, migrations, dry_run=True, take_lock=False)

    assert log == []
    assert [r.status for r in results] == [Status.SKIPPED]
    assert "dry run" in results[0].detail
    assert read_marker(conn, "later") == (False, None)
    conn.close()


def test_meta_table_is_created_on_demand(tmp_path):
    conn = sqlite3.connect(tmp_path / "meta.db")
    ensure_meta_table(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='malla_meta'"
    ).fetchall()
    assert rows == [("malla_meta",)]
    assert marker_key("x") == "migration:x"
    conn.close()


def test_concurrent_runner_is_rejected_by_the_lock(tmp_path):
    """A second runner must not start while the lock row exists."""

    conn = _conn(tmp_path / "lock.db")
    ensure_meta_table(conn)
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES ('migration_lock', 'other:1', ?)",
        (time.time(),),
    )
    conn.commit()

    with pytest.raises(TimeoutError):
        run_migrations(conn, (), phases=(Phase.SCHEMA,), lock_timeout=0.1)
    conn.close()


def test_lock_from_a_dead_process_is_taken_over(tmp_path):
    """A crash mid-migration must not wedge the next start."""

    conn = _conn(tmp_path / "stale.db")
    ensure_meta_table(conn)
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES ('migration_lock', ?, ?)",
        (f"{socket.gethostname()}:999999999", time.time()),
    )
    conn.commit()

    results = run_migrations(conn, (), lock_timeout=5)
    assert results == []
    # The lock is released again after the run.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM malla_meta WHERE key = 'migration_lock'"
        ).fetchone()[0]
        == 0
    )
    conn.close()


def test_registry_is_well_formed():
    from malla.migrations.base import PHASE_ORDER

    names = [m.name for m in MIGRATIONS]
    assert len(names) == len(set(names)), (
        "migration names are progress keys: keep them unique"
    )
    for migration in MIGRATIONS:
        assert migration.phase in PHASE_ORDER
        assert migration.description, f"{migration.name} needs a description"
