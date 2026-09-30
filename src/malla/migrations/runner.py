"""Execution of the migration registry against one database.

The runner owns three things the individual migrations must not re-implement:

* the ``malla_meta`` marker table (``migration:<name>`` → watermark);
* the ordering guarantee (phase order first, registry order inside a phase);
* failure isolation — a failing migration is logged and skipped, never aborts
  the process or the migrations behind it, and never advances its watermark.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from typing import Any

from .base import (
    PHASE_ORDER,
    Migration,
    MigrationResult,
    Phase,
    Status,
    Watermark,
)

logger = logging.getLogger(__name__)

MARKER_PREFIX = "migration:"
LOCK_KEY = "migration_lock"

META_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS malla_meta (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at REAL NOT NULL
    )
"""


def marker_key(name: str) -> str:
    """``malla_meta`` key holding the watermark of migration *name*."""
    return f"{MARKER_PREFIX}{name}"


def ensure_meta_table(conn: sqlite3.Connection) -> None:
    """Create the key/value table that stores migration progress."""
    conn.execute(META_TABLE_SQL)


def read_marker(conn: sqlite3.Connection, name: str) -> tuple[bool, Watermark]:
    """Return ``(recorded, watermark)`` for migration *name*.

    ``recorded`` is ``False`` only when the migration never ran. A migration that
    ran with nothing to track stores an empty watermark, which is returned as
    ``""`` so callers can tell it apart from "never ran".
    """
    try:
        row = conn.execute(
            "SELECT value FROM malla_meta WHERE key = ?", (marker_key(name),)
        ).fetchone()
    except sqlite3.OperationalError:
        return False, None
    if row is None:
        return False, None
    value = row[0]
    return True, ("" if value is None else str(value))


def write_marker(conn: sqlite3.Connection, name: str, watermark: Watermark) -> None:
    """Record that migration *name* is done, optionally up to *watermark*."""
    conn.execute(
        "INSERT INTO malla_meta (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (marker_key(name), "" if watermark is None else str(watermark), time.time()),
    )


def forget_marker(conn: sqlite3.Connection, name: str) -> bool:
    """Drop the progress record of *name* so it runs again. Returns whether
    anything was deleted. Intended for tests and operator repair."""
    cursor = conn.execute("DELETE FROM malla_meta WHERE key = ?", (marker_key(name),))
    return cursor.rowcount > 0


def _holder_is_alive(holder: str) -> bool:
    """Whether a lock holder recorded as ``host:pid`` is still running.

    Only meaningful for our own host; a remote holder (or an unparsable value)
    is assumed alive so the caller falls back to the staleness timeout.
    """
    host, _, pid_text = holder.rpartition(":")
    if host != socket.gethostname() or not pid_text.isdigit():
        return True
    try:
        os.kill(int(pid_text), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # exists but not ours
    return True


@contextmanager
def migration_lock(
    conn: sqlite3.Connection,
    *,
    timeout: float = 60.0,
    stale_after: float = 900.0,
    poll: float = 0.25,
) -> Iterator[None]:
    """Serialise migration *runners* through a row in ``malla_meta``.

    Two capture daemons pointed at the same database (a rolling deploy, a
    forgotten instance) would otherwise race on DDL. A lock whose owner is gone
    — the process died mid-migration — is taken over immediately, and one older
    than *stale_after* seconds is taken over regardless, so a crash cannot wedge
    the database.

    Scope it to the schema-changing phases: DERIVED migrations are idempotent by
    contract, and holding this lock across one that runs for minutes is how a
    live holder gets mistaken for a dead one.
    """
    owner = f"{socket.gethostname()}:{os.getpid()}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            conn.execute(
                "INSERT INTO malla_meta (key, value, updated_at) VALUES (?, ?, ?)",
                (LOCK_KEY, owner, time.time()),
            )
            conn.commit()
            break
        except sqlite3.IntegrityError:
            # The failed INSERT opened an implicit transaction (python sqlite3
            # legacy mode); end it, or every later read on this connection
            # repeats its stale snapshot and never sees the lock released.
            conn.rollback()
            row = conn.execute(
                "SELECT value, updated_at FROM malla_meta WHERE key = ?", (LOCK_KEY,)
            ).fetchone()
            holder = str(row[0]) if row else "unknown"
            age = time.time() - float(row[1] or 0) if row else 0.0
            if not _holder_is_alive(holder) or (stale_after and age > stale_after):
                logger.warning(
                    "Taking over migration lock held by %s for %.0fs", holder, age
                )
                # Guard on the previous holder: two waiters that both saw the
                # same dead owner must not both take over. Losing this race
                # just means the winner is alive — retry the loop.
                cursor = conn.execute(
                    "UPDATE malla_meta SET value = ?, updated_at = ? "
                    "WHERE key = ? AND value = ?",
                    (owner, time.time(), LOCK_KEY, holder),
                )
                conn.commit()
                if cursor.rowcount:
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"migration lock is held by {holder} (waited {timeout:.0f}s)"
                ) from None
            time.sleep(poll)
    try:
        yield
    finally:
        try:
            conn.execute(
                "DELETE FROM malla_meta WHERE key = ? AND value = ?", (LOCK_KEY, owner)
            )
            conn.commit()
        except sqlite3.Error as exc:  # pragma: no cover - best effort release
            logger.warning("Could not release migration lock: %s", exc)


def run_migrations(
    conn: sqlite3.Connection,
    migrations: Iterable[Migration] | None = None,
    *,
    phases: Sequence[Phase] | None = None,
    strict: bool = False,
    dry_run: bool = False,
    take_lock: bool = True,
    lock_timeout: float = 60.0,
) -> list[MigrationResult]:
    """Apply every pending migration in phase order.

    ``phases`` restricts the run (used to split the work around the MQTT
    connect). ``strict`` re-raises instead of recording a failure.

    ``dry_run`` reports what would run and writes nothing at all — not even the
    marker table or the advisory lock.

    The advisory lock guards against a second *runner* (a rolling deploy, a
    forgotten instance) performing DDL at the same time, so it is taken per
    phase and only for the phases that change the schema. DERIVED migrations are
    idempotent by contract and run unlocked: they may be duplicated by another
    instance, and a multi-minute phase must not hold a lock that a second runner
    could steal as stale. ``take_lock=False`` disables it entirely.
    """
    if migrations is None:
        from .registry import MIGRATIONS

        registry: Iterable[Migration] = MIGRATIONS
    else:
        registry = migrations

    selected = set(phases) if phases else set(PHASE_ORDER)

    if not dry_run:
        ensure_meta_table(conn)
        conn.commit()

    results: list[MigrationResult] = []
    for phase in PHASE_ORDER:
        if phase not in selected:
            continue
        phase_migrations = [m for m in registry if m.phase is phase]
        if not phase_migrations:
            continue
        # Schema-changing phases are serialised across runners; DERIVED work is
        # idempotent, so it runs unlocked (see the docstring).
        guard: Any = (
            migration_lock(conn, timeout=lock_timeout)
            if (take_lock and not dry_run and phase is not Phase.DERIVED)
            else nullcontext()
        )
        with guard:
            for migration in phase_migrations:
                results.append(
                    _run_one(conn, migration, strict=strict, dry_run=dry_run)
                )
    return results


def _run_one(
    conn: sqlite3.Connection,
    migration: Migration,
    *,
    strict: bool,
    dry_run: bool,
) -> MigrationResult:
    started = time.monotonic()
    _recorded, watermark = read_marker(conn, migration.name)

    def result(status: Status, detail: str = "") -> MigrationResult:
        return MigrationResult(
            name=migration.name,
            phase=migration.phase,
            status=status,
            detail=detail,
            seconds=time.monotonic() - started,
        )

    try:
        if not migration.pending(conn, watermark):
            return result(Status.SKIPPED, "up to date")
    except Exception as exc:  # noqa: BLE001 - a broken check must not abort the run
        logger.error("Migration %s: check failed: %s", migration.name, exc)
        if strict:
            raise
        return result(Status.FAILED, f"check failed: {exc}")

    if dry_run:
        return result(Status.SKIPPED, "pending (dry run)")

    try:
        if conn.in_transaction:
            conn.commit()
        new_watermark = migration.apply(conn, watermark)
        write_marker(conn, migration.name, new_watermark)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - keep the daemon and the rest of the run alive
        conn.rollback()
        logger.error(
            "Migration %s failed (will retry on the next start): %s",
            migration.name,
            exc,
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        if strict:
            raise
        return result(Status.FAILED, str(exc))

    logger.info(
        "Applied migration %s: %s", migration.name, result(Status.APPLIED).seconds
    )
    return result(Status.APPLIED)
