"""
Database connection management for Meshtastic Mesh Health Web UI.
"""

import logging
import os
import sqlite3

# Prefer configuration loader over environment variables
from malla.config import get_config

logger = logging.getLogger(__name__)


def get_db_connection() -> sqlite3.Connection:
    """
    Get a connection to the SQLite database with proper concurrency configuration.

    Returns:
        sqlite3.Connection: Database connection with row factory set and WAL mode enabled
    """
    # Resolve DB path:
    # 1. Explicit override via `MALLA_DATABASE_FILE` env-var (handy for scripts)
    # 2. Value from YAML configuration
    # 3. Fallback to hard-coded default

    db_path: str = (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )

    try:
        conn = sqlite3.connect(
            db_path, timeout=30.0
        )  # 30 second timeout for busy database
        conn.row_factory = sqlite3.Row  # Enable column access by name

        # Configure SQLite for better concurrency
        cursor = conn.cursor()

        # Enable WAL mode for better concurrent read/write performance
        cursor.execute("PRAGMA journal_mode=WAL")

        # Set synchronous to NORMAL for better performance while maintaining safety
        cursor.execute("PRAGMA synchronous=NORMAL")

        # Set busy timeout to handle concurrent access
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds

        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON")

        # Optimize for read performance
        cursor.execute("PRAGMA cache_size=10000")  # 10MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")

        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def init_database() -> None:
    """
    Initialize the database connection and verify it's accessible.
    This function is called during application startup.
    """
    # Resolve DB path:
    # 1. Explicit override via `MALLA_DATABASE_FILE` env-var (handy for scripts)
    # 2. Value from YAML configuration
    # 3. Fallback to hard-coded default

    db_path: str = (
        os.getenv("MALLA_DATABASE_FILE")
        or get_config().database_file
        or "meshtastic_history.db"
    )

    logger.info(f"Initializing database connection to: {db_path}")

    try:
        # Test the connection
        conn = get_db_connection()

        # Test a simple query to verify the database is accessible
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]

        # Check and log the journal mode
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        conn.close()

        logger.info(
            f"Database connection successful - found {table_count} tables, journal_mode: {journal_mode}"
        )

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Don't raise the exception - let the app start anyway
        # The database might not exist yet or be created by another process
