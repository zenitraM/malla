"""Database connection management for Meshtastic Mesh Health Web UI."""

import logging
import os
import sqlite3
from typing import Any

from malla.config import get_config

# Prefer configuration loader over environment variables
from malla.migrations.structural import missing_indexes

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
    """Resolve the SQLite database path for the current context.

    Order: the Flask app being served (request/template contexts must always
    hit the DB that app was configured with, even if another fixture in the
    same process re-pointed the env var), then the env override, then config,
    then the historic default.
    """

    try:
        from flask import current_app, has_app_context

        if has_app_context():
            configured = current_app.config.get("DATABASE_FILE")
            if configured:
                return str(configured)
    except Exception:  # pragma: no cover - Flask not importable is not fatal
        pass

    return (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )


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


#: Tables the web UI's read paths hard-depend on. The capture daemon (or
#: ``malla-migrate``) creates everything else; a database from an older
#: release is missing these and every read 500s, so the preflight treats
#: them as required and serves the actionable 503 instead.
REQUIRED_TABLES: tuple[str, ...] = (
    "packet_history",
    "node_info",
    "node_hour_rollup",
    "node_latest_position",
    "node_latest_telemetry",
    "traceroute_endpoint",
    "link_day_rollup",
    "route_day_rollup",
    "activity_node_quarter",
    "activity_packet_quarter",
    "activity_gateway_quarter",
)


def _present_required_tables(cursor: sqlite3.Cursor) -> set[str]:
    placeholders = ",".join("?" * len(REQUIRED_TABLES))
    cursor.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
        REQUIRED_TABLES,
    )
    return {row[0] for row in cursor.fetchall()}


def required_tables_missing(db_path: str | None = None) -> list[str] | None:
    """Return the required tables absent from *db_path*.

    Reads the catalog on a throwaway connection (no pragmas, no WAL switch —
    this must stay cheap enough for a request handler). Returns ``None`` when
    the answer cannot be determined (missing file, locked catalog, ...): the
    caller should keep its default handling instead of trusting the check.
    An empty list means the database is initialized.
    """
    path = db_path or _resolve_db_path()
    try:
        conn = sqlite3.connect(path, timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        present = _present_required_tables(conn.cursor())
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return [table for table in REQUIRED_TABLES if table not in present]


def init_database() -> None:
    """Verify the database is reachable and already migrated.

    Schema creation and migrations belong to ``malla-capture`` (or the
    ``malla-migrate`` CLI): the web UI never writes DDL, so the daemon can never
    be blocked by a web process building an index. An uninitialized database is
    reported clearly here instead of failing one request at a time.
    """
    db_path = _resolve_db_path()

    logger.info(f"Initializing database connection to: {db_path}")

    try:
        # Test the connection
        conn = get_db_connection()

        # Test a simple query to verify the database is accessible
        cursor = conn.cursor()
        present = _present_required_tables(cursor)
        missing_idx = missing_indexes(conn)
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]

        # Check and log the journal mode
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        conn.close()

        logger.info(
            f"Database connection successful - found {table_count} tables, journal_mode: {journal_mode}"
        )

        missing = [table for table in REQUIRED_TABLES if table not in present]
        if missing:
            logger.error(
                "Database is not initialized (missing %s). Start malla-capture once "
                "(or run 'malla-migrate') to create and migrate the schema; requests "
                "will fail until then.",
                ", ".join(missing),
            )
        elif missing_idx:
            logger.error(
                "Database is missing %s index(es) (%s). Start malla-capture once (or "
                "run 'malla-migrate') to finish the migrations; some queries use "
                "INDEXED BY and will fail until then.",
                len(missing_idx),
                ", ".join(missing_idx[:3]),
            )

    except Exception as e:
        # Don't raise the exception - let the app start anyway
        logger.error(f"Database initialization failed: {e}")


def check_database_tables() -> dict[str, Any]:
    """
    Check the health of database tables.

    Returns:
        Dictionary with table health information
    """
    tables_status = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [row[0] for row in cursor.fetchall()]

        # Check each expected table
        expected_tables = [
            "packet_history",
            "node_info",
            "traceroute_table",
            "node_receptions",
        ]

        for table in expected_tables:
            if table in all_tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                tables_status[table] = {"exists": True, "count": count}
            else:
                tables_status[table] = {"exists": False, "count": 0}

        conn.close()
    except Exception as e:
        logger.error(f"Error checking database tables: {e}")
        tables_status["error"] = str(e)

    return tables_status
