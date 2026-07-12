"""
Database connection management for Meshtastic Mesh Health Web UI.
"""

import logging
import os
import sqlite3
import threading

# Prefer configuration loader over environment variables
from malla.config import get_config

from .schema import (
    ensure_query_planner_stats,
    ensure_startup_schema,
    query_planner_stats_present,
)

logger = logging.getLogger(__name__)

# A larger page cache keeps query latency flat as the database grows into the
# multi-gigabyte range. ``cache_size`` is negative so SQLite interprets it as
# KiB (here 64 MiB) instead of a page count. ``analysis_limit`` bounds ANALYZE /
# ``PRAGMA optimize`` so refreshing planner statistics stays cheap even on a
# huge ``packet_history``.
#
# NOTE: mmap (PRAGMA mmap_size) is deliberately NOT used. With the capture
# daemon writing continuously, memory-mapped readers can observe an incoherent
# view during WAL checkpoints and report "database disk image is malformed",
# so it is left at SQLite's default (off).
_CACHE_SIZE_KIB = 65536  # 64 MiB page cache (negative value => KiB, not pages)
_ANALYSIS_LIMIT = 1000  # cap ANALYZE work per index (see PRAGMA analysis_limit)


def _apply_connection_pragmas(cursor: sqlite3.Cursor) -> None:
    """Apply the shared SQLite tuning pragmas to *cursor*'s connection."""

    # Enable WAL mode for better concurrent read/write performance
    cursor.execute("PRAGMA journal_mode=WAL")

    # Set synchronous to NORMAL for better performance while maintaining safety
    cursor.execute("PRAGMA synchronous=NORMAL")

    # Set busy timeout to handle concurrent access
    cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds

    # Enable foreign key constraints
    cursor.execute("PRAGMA foreign_keys=ON")

    # Optimize for read performance on a large, long-lived database
    cursor.execute(f"PRAGMA cache_size=-{_CACHE_SIZE_KIB}")  # 64 MiB (negative => KiB)
    cursor.execute("PRAGMA temp_store=MEMORY")

    # Keep any ANALYZE / PRAGMA optimize triggered on this connection bounded.
    cursor.execute(f"PRAGMA analysis_limit={_ANALYSIS_LIMIT}")


def _resolve_db_path() -> str:
    """Resolve the SQLite database path from env override, config, then default."""

    return (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )


# Guards against spawning more than one concurrent background ANALYZE seeder
# per process. Tracks the live thread (not a latching flag) so a later startup
# call can retry if a previous seed thread died, and so tests stay isolated.
_stats_seed_lock = threading.Lock()
_stats_seed_thread: threading.Thread | None = None


def seed_query_planner_stats_async(db_path: str | None = None) -> bool:
    """Seed SQLite planner statistics in a background thread if they are missing.

    A bounded ANALYZE still reads ~1000 sample rows per index, which can take
    ~100 seconds of random I/O on a cold multi-gigabyte database. Running it
    synchronously at startup would block web request serving or packet
    ingestion for that whole time, so we do it off-thread instead. When stats
    are already present (the common case after the first run) this is a single
    fast SELECT and no thread is started.

    Returns ``True`` if a seeding thread was started.
    """

    global _stats_seed_thread

    path = db_path or _resolve_db_path()

    # Fast pre-check on the calling thread: usually stats already exist and we
    # return immediately without touching threads.
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            if query_planner_stats_present(conn.cursor()):
                return False
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not check query-planner statistics: %s", exc)
        return False

    with _stats_seed_lock:
        if _stats_seed_thread is not None and _stats_seed_thread.is_alive():
            return False

    def _worker() -> None:
        import time

        try:
            conn = sqlite3.connect(path, timeout=60.0)
            try:
                _apply_connection_pragmas(conn.cursor())
                started = time.time()
                if ensure_query_planner_stats(conn.cursor()):
                    conn.commit()
                    logger.info(
                        "Seeded query-planner statistics in %.1fs",
                        time.time() - started,
                    )
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Background ANALYZE seeding failed: %s", exc)

    thread = threading.Thread(
        target=_worker, name="malla-analyze-seed", daemon=True
    )
    with _stats_seed_lock:
        # Re-check under the lock in case a concurrent caller started one.
        if _stats_seed_thread is not None and _stats_seed_thread.is_alive():
            return False
        _stats_seed_thread = thread
        thread.start()
    return True


def get_db_connection() -> sqlite3.Connection:
    """
    Get a connection to the SQLite database with proper concurrency configuration.

    Returns:
        sqlite3.Connection: Database connection with row factory set and WAL mode enabled
    """
    db_path = _resolve_db_path()

    try:
        conn = sqlite3.connect(
            db_path, timeout=30.0
        )  # 30 second timeout for busy database
        conn.row_factory = sqlite3.Row  # Enable column access by name

        # Configure SQLite for better concurrency and large-database performance
        _apply_connection_pragmas(conn.cursor())

        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def init_database() -> None:
    """
    Initialize the database connection and verify it's accessible.
    This function is called during application startup.
    """
    db_path = _resolve_db_path()

    logger.info(f"Initializing database connection to: {db_path}")

    try:
        # Test the connection
        conn = get_db_connection()

        # Test a simple query to verify the database is accessible
        cursor = conn.cursor()
        ensure_startup_schema(cursor)
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]

        # Check and log the journal mode
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        conn.close()

        # Seed query-planner statistics on first run so the planner picks
        # index-based plans instead of full scans on a large packet_history.
        # Runs in a background thread so a cold ANALYZE (~100s on a multi-GB DB)
        # never blocks request serving.
        seed_query_planner_stats_async(db_path)

        logger.info(
            f"Database connection successful - found {table_count} tables, journal_mode: {journal_mode}"
        )

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Don't raise the exception - let the app start anyway
        # The database might not exist yet or be created by another process
