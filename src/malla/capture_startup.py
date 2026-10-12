"""Capture-daemon startup: connect first, migrate around the connection.

The daemon's startup order is what makes the migration phases useful:

1. ``SCHEMA`` migrations run before the MQTT connect, so the ingest path can
   always write;
2. the daemon connects and subscribes next, so packets published while the
   write-locking migrations run are buffered instead of lost
   (see :mod:`malla.ingest_buffer`);
3. ``BLOCKING`` migrations run with ingestion paused — their packets wait in
   the buffer — and the buffer is drained through the normal ingest path when
   they finish;
4. ``DERIVED`` migrations run in a background thread. They only touch stored
   rows and are idempotent by contract, so they need neither a drained buffer
   nor the daemon's writer lock.

Keeping the sequence in one module lets ``main()`` read like that list, and
lets each phase be exercised without the MQTT stack.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import nullcontext

from . import activity_rollup
from .migrations import MIGRATIONS, MigrationResult, Phase, Status, run_migrations

logger = logging.getLogger(__name__)


def configure_connection(conn: sqlite3.Connection, *, cache_kib: int = 65536) -> None:
    """Apply the daemon's SQLite tuning pragmas to *conn*.

    ``cache_kib`` is passed to ``PRAGMA cache_size`` negated because SQLite reads
    a negative value as KiB rather than a page count. mmap is intentionally left
    off: with continuous writes, memory-mapped readers can report "database disk
    image is malformed" during WAL checkpoints.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA cache_size=-{cache_kib}")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA analysis_limit=1000")  # bound ANALYZE / optimize work


def _log_results(results: list[MigrationResult]) -> None:
    for result in results:
        if result.status is Status.FAILED:
            logger.error("Migration %s failed: %s", result.name, result.detail)
        elif result.status is Status.APPLIED:
            logger.info("Migration %s", result.describe())
        else:
            logger.debug("Migration %s: %s", result.name, result.detail)


def run_phase(
    db_path: str,
    phase: Phase,
    *,
    lock: threading.Lock | None = None,
) -> list[MigrationResult]:
    """Apply every migration of *phase* on its own connection.

    *lock* is the daemon's writer lock; only the phases that run while ingestion
    is paused should pass it. Holding it during DERIVED work (a bounded ANALYZE,
    a bucket backfill) would stall packet inserts for minutes. The runner's own
    advisory lock needs no decision here: it is taken for the schema-changing
    phases only.
    """
    guard = lock if lock is not None else nullcontext()
    with guard:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            configure_connection(conn)
            results = run_migrations(conn, MIGRATIONS, phases=(phase,))
        finally:
            conn.close()
    _log_results(results)
    return results


def init_database(
    db_path: str, *, lock: threading.Lock | None = None
) -> list[MigrationResult]:
    """Apply the cheap SCHEMA migrations so the ingest path can write."""
    started = time.time()
    results = run_phase(db_path, Phase.SCHEMA, lock=lock)
    logger.info("Database schema ready: %s (%.3fs)", db_path, time.time() - started)
    return results


def run_write_locking_migrations(
    db_path: str, *, lock: threading.Lock | None = None
) -> list[MigrationResult]:
    """Apply the BLOCKING migrations: DDL that cannot run while packets are written."""
    return run_phase(db_path, Phase.BLOCKING, lock=lock)


def refresh_activity_buckets(db_path: str, *, lock: threading.Lock) -> int:
    """Append completed quarter-hour activity buckets. Returns rows inserted.

    Called from the daemon's steady-state loop, where it is normally one
    ``MAX(bucket)`` plus one indexed existence check: a bucket only completes
    every 15 minutes.
    """
    with lock:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            if not activity_rollup.pending(conn):
                return 0
            return activity_rollup.refresh(conn)
        finally:
            conn.close()


def start_background_migrations(db_path: str) -> threading.Thread:
    """Apply the DERIVED migrations in a daemon thread, alongside ingestion."""

    def _worker() -> None:
        try:
            run_phase(db_path, Phase.DERIVED)
        except Exception as exc:  # noqa: BLE001 - must never kill the daemon
            logger.warning("Background migrations failed: %s", exc)

    thread = threading.Thread(target=_worker, name="db-migrations", daemon=True)
    thread.start()
    return thread
