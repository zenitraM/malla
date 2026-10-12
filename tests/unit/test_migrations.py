"""Tests for the migration runner: ordering, markers, phases, failure isolation."""

import socket
import sqlite3
import threading
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
from malla.migrations.runner import migration_lock


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


def _noop(phase: Phase) -> Migration:
    """A migration that does nothing, for exercising the runner's locking."""
    return Migration(name=f"noop_{phase.value}", phase=phase, apply=lambda _c, wm: wm)


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
    # One-shot migrations record "applied, nothing to track": the stored
    # value is the empty-string sentinel.
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
    # A dry run writes nothing at all: no marker table, no advisory lock.
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "malla_meta" not in tables
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
        run_migrations(
            conn, (_noop(Phase.SCHEMA),), phases=(Phase.SCHEMA,), lock_timeout=0.1
        )
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

    results = run_migrations(conn, (_noop(Phase.SCHEMA),), lock_timeout=5)
    assert [r.status for r in results] == [Status.APPLIED]
    # The lock is released again after the run.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM malla_meta WHERE key = 'migration_lock'"
        ).fetchone()[0]
        == 0
    )
    conn.close()


def test_concurrent_takeover_of_a_dead_holder_elects_one_winner(tmp_path):
    """Two waiters that saw the same dead owner must not both take the lock.

    Regression: the takeover used to be an unguarded UPDATE, so both waiters
    overwrote the holder row and both entered the critical section.
    """

    conn = _conn(tmp_path / "takeover.db")
    ensure_meta_table(conn)
    dead = f"{socket.gethostname()}:999999999"
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES ('migration_lock', ?, ?)",
        (dead, time.time()),
    )
    conn.commit()

    lock = threading.Lock()
    acquired: list[int] = []
    finished: list[int] = []

    def contender(tag: int) -> None:
        own = sqlite3.connect(tmp_path / "takeover.db", timeout=30)
        try:
            with migration_lock(own, timeout=30, stale_after=0):
                with lock:
                    acquired.append(tag)
                time.sleep(0.1)  # widen the overlap window: a concurrent
                # second holder would finish while this sleep is still running
                with lock:
                    finished.append(tag)
        finally:
            own.close()

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Both threads ran (the first holder is dead and stale_after=0 makes the
    # takeover immediate), but the second could only enter after the first
    # released: no overlap means the guarded takeover elected one winner.
    assert sorted(acquired) == [0, 1]
    assert sorted(finished) == [0, 1]
    assert acquired == finished  # strictly sequential critical sections
    conn.close()


def test_lock_from_a_remote_holder_is_respected_then_taken_over(tmp_path):
    """A holder we cannot inspect is freed by the staleness timeout, not by pid.

    The dead-owner path only applies to holders on this host; anything else has
    to go through ``stale_after``, which this pins.
    """

    conn = _conn(tmp_path / "remote.db")
    ensure_meta_table(conn)
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES ('migration_lock', ?, ?)",
        ("elsewhere.example:1", time.time()),
    )
    conn.commit()

    # Fresh: respected, so a short wait gives up.
    with pytest.raises(TimeoutError):
        run_migrations(
            conn, (_noop(Phase.SCHEMA),), phases=(Phase.SCHEMA,), lock_timeout=0.2
        )

    # Old: taken over even though the holder looks alive.
    conn.execute(
        "UPDATE malla_meta SET updated_at = ? WHERE key = 'migration_lock'",
        (time.time() - 3600,),
    )
    conn.commit()
    with migration_lock(conn, timeout=5, stale_after=60):
        pass
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
