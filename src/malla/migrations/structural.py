"""Structural migrations: tables, columns and indexes.

These are re-checked on every run instead of being marked done, exactly like the
startup code they replace: adding an index to :data:`INDEX_SPECS` (or a column
to :data:`PACKET_HISTORY_ADDED_COLUMNS`) in a later release keeps working on
databases that already ran the migration once.
"""

from __future__ import annotations

import logging
import sqlite3

from .base import Migration, Phase, Watermark

logger = logging.getLogger(__name__)

PACKET_HISTORY_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS packet_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        topic TEXT NOT NULL,
        from_node_id INTEGER,
        to_node_id INTEGER,
        portnum INTEGER,
        portnum_name TEXT,
        gateway_id TEXT,
        channel_id TEXT,
        mesh_packet_id INTEGER,
        rssi INTEGER,
        snr REAL,
        hop_limit INTEGER,
        hop_start INTEGER,
        payload_length INTEGER,
        raw_payload BLOB,
        processed_successfully BOOLEAN DEFAULT TRUE,
        message_type TEXT,
        raw_service_envelope BLOB,
        parsing_error TEXT
    )
"""

NODE_INFO_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS node_info (
        node_id INTEGER PRIMARY KEY,
        hex_id TEXT,
        long_name TEXT,
        short_name TEXT,
        hw_model TEXT,
        role TEXT,
        primary_channel TEXT,
        is_licensed BOOLEAN,
        mac_address TEXT,
        first_seen REAL NOT NULL,
        last_updated REAL NOT NULL
    )
"""

# Per-local-day activity aggregates for the dashboard timeline. Completed days
# never change (packet_history is append-only and rows are stamped with insert
# time), so each (tz_offset, day) is computed once and reused forever; only the
# current day is recomputed live. Without this, the "All" range re-aggregates
# the entire multi-million-row packet_history on every view.
ACTIVITY_ROLLUP_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS activity_daily_rollup (
        tz_offset_minutes INTEGER NOT NULL,
        day TEXT NOT NULL,
        total_packets INTEGER NOT NULL DEFAULT 0,
        active_nodes INTEGER NOT NULL DEFAULT 0,
        gateway_count INTEGER NOT NULL DEFAULT 0,
        new_nodes INTEGER NOT NULL DEFAULT 0,
        computed_at REAL NOT NULL,
        PRIMARY KEY (tz_offset_minutes, day)
    )
"""

# Columns added after packet_history first shipped; older databases get them
# one by one.
PACKET_HISTORY_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("mesh_packet_id", "INTEGER"),
    ("via_mqtt", "BOOLEAN"),
    ("want_ack", "BOOLEAN"),
    ("priority", "INTEGER"),
    ("delayed", "INTEGER"),
    ("channel_index", "INTEGER"),
    ("rx_time", "INTEGER"),
    ("pki_encrypted", "BOOLEAN"),
    ("next_hop", "INTEGER"),
    ("relay_node", "INTEGER"),
    ("tx_after", "INTEGER"),
    ("message_type", "TEXT"),
    ("raw_service_envelope", "BLOB"),
    ("parsing_error", "TEXT"),
)

NODE_INFO_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (("primary_channel", "TEXT"),)

INDEX_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "idx_packet_history_stats",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_stats ON packet_history(timestamp, from_node_id)",
    ),
    (
        "idx_packet_history_gateway_stats",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_stats ON packet_history(timestamp, gateway_id)",
    ),
    (
        "idx_packet_history_portnum_time",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_portnum_time ON packet_history(timestamp, portnum_name)",
    ),
    (
        "idx_packet_history_direct_hops",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_hops ON packet_history(timestamp, from_node_id, gateway_id, hop_start, hop_limit) WHERE hop_start = hop_limit",
    ),
    (
        "idx_packet_history_direct_gateway_from",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_gateway_from ON packet_history(gateway_id, from_node_id) WHERE hop_start = hop_limit AND from_node_id IS NOT NULL",
    ),
    (
        "idx_packet_history_direct_gateway_lastbyte",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_gateway_lastbyte ON packet_history(gateway_id, (from_node_id & 255)) WHERE hop_start = hop_limit AND from_node_id IS NOT NULL",
    ),
    (
        "idx_packet_history_direct_from_gateway",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_from_gateway ON packet_history(from_node_id, gateway_id) WHERE hop_start = hop_limit AND gateway_id IS NOT NULL",
    ),
    (
        "idx_packet_history_direct_from_gateway_suffix",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_from_gateway_suffix ON packet_history(from_node_id, lower(substr(gateway_id, -2))) WHERE hop_start = hop_limit AND gateway_id IS NOT NULL",
    ),
    (
        "idx_packet_history_direct_from_gateway_time_desc",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_direct_from_gateway_time_desc ON packet_history(from_node_id, gateway_id, timestamp DESC) WHERE hop_start = hop_limit AND from_node_id IS NOT NULL AND gateway_id IS NOT NULL",
    ),
    (
        "idx_packet_history_from_time_desc",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_from_time_desc ON packet_history(from_node_id, timestamp DESC)",
    ),
    (
        "idx_packet_history_gateway_time_desc",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_time_desc ON packet_history(gateway_id, timestamp DESC) WHERE gateway_id IS NOT NULL",
    ),
    (
        "idx_packet_history_gateway_relay",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_relay ON packet_history(gateway_id, relay_node) WHERE gateway_id IS NOT NULL AND relay_node IS NOT NULL AND relay_node != 0",
    ),
    (
        "idx_packet_history_gateway_relay_time_desc",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_gateway_relay_time_desc ON packet_history(gateway_id, relay_node, timestamp DESC) WHERE gateway_id IS NOT NULL AND relay_node IS NOT NULL AND relay_node != 0",
    ),
    (
        "idx_packet_history_relay_time",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_relay_time ON packet_history(timestamp, relay_node) WHERE relay_node IS NOT NULL AND relay_node != 0",
    ),
    (
        "idx_packet_history_position_lookup_time",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_position_lookup_time ON packet_history(portnum, timestamp DESC, from_node_id) WHERE portnum = 3 AND raw_payload IS NOT NULL AND from_node_id IS NOT NULL",
    ),
    (
        # Node telemetry-history charts: fetch one node's telemetry packets in a
        # time window. Without this, the query falls back to the (from_node_id,
        # timestamp) index and scans ALL of the node's packets to filter out the
        # telemetry ones — slow for nodes where telemetry is a small share.
        "idx_packet_history_telemetry_lookup",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_telemetry_lookup ON packet_history(from_node_id, timestamp) WHERE portnum = 67 AND raw_payload IS NOT NULL AND from_node_id IS NOT NULL",
    ),
    (
        "idx_packet_mesh_id",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_mesh_id ON packet_history(mesh_packet_id)",
    ),
    (
        "idx_packet_history_channel_id",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_channel_id ON packet_history(channel_id) WHERE channel_id IS NOT NULL AND channel_id != ''",
    ),
    (
        "idx_packet_history_chat_channel",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_chat_channel ON packet_history(portnum_name, channel_id, id DESC) WHERE raw_payload IS NOT NULL AND payload_length > 0",
    ),
    (
        "idx_node_hex_id",
        "node_info",
        "CREATE INDEX IF NOT EXISTS idx_node_hex_id ON node_info(hex_id)",
    ),
    (
        "idx_node_primary_channel",
        "node_info",
        "CREATE INDEX IF NOT EXISTS idx_node_primary_channel ON node_info(primary_channel)",
    ),
)

LEGACY_INDEX_NAMES: tuple[str, ...] = (
    "idx_packet_timestamp",
    "idx_packet_from_node",
)


def tables(conn: sqlite3.Connection) -> set[str]:
    """Names of every table in the database."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IS NOT NULL"
        )
    }


def indexes(conn: sqlite3.Connection) -> set[str]:
    """Names of every index in the database."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL"
        )
    }


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names of *table* (empty when the table does not exist)."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _missing_columns(
    conn: sqlite3.Connection, table: str, spec: tuple[tuple[str, str], ...]
) -> list[tuple[str, str]]:
    present = columns(conn, table)
    return [(name, decl) for name, decl in spec if name not in present]


def missing_indexes(conn: sqlite3.Connection) -> list[str]:
    """Indexes in :data:`INDEX_SPECS` whose table exists but the index does not.

    This is the read-only view both consumers share: the ``core_indexes``
    migration's ``pending`` check, and the web UI's startup verification (some
    queries reference these indexes with ``INDEXED BY``).
    """
    present_tables = tables(conn)
    present_indexes = indexes(conn)
    return [
        name
        for name, table, _sql in INDEX_SPECS
        if table in present_tables and name not in present_indexes
    ]


def _core_tables_pending(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    present = tables(conn)
    if present < {"packet_history", "node_info", "activity_daily_rollup"}:
        return True
    if _missing_columns(conn, "packet_history", PACKET_HISTORY_ADDED_COLUMNS):
        return True
    return bool(_missing_columns(conn, "node_info", NODE_INFO_ADDED_COLUMNS))


def _apply_core_tables(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    conn.execute(PACKET_HISTORY_TABLE_SQL)
    conn.execute(NODE_INFO_TABLE_SQL)
    conn.execute(ACTIVITY_ROLLUP_TABLE_SQL)
    for table, spec in (
        ("packet_history", PACKET_HISTORY_ADDED_COLUMNS),
        ("node_info", NODE_INFO_ADDED_COLUMNS),
    ):
        for name, decl in _missing_columns(conn, table, spec):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            logger.info("Added %s column to %s table", name, table)
    return None


def _core_indexes_pending(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    if missing_indexes(conn):
        return True
    return "packet_history" in tables(conn) and any(
        name in indexes(conn) for name in LEGACY_INDEX_NAMES
    )


def _apply_core_indexes(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    present_tables = tables(conn)
    present_indexes = indexes(conn)
    for index, table, sql in INDEX_SPECS:
        if table not in present_tables or index in present_indexes:
            continue
        conn.execute(sql)
        present_indexes.add(index)
    if "packet_history" in present_tables:
        for name in LEGACY_INDEX_NAMES:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
    return None


CORE_TABLES = Migration(
    name="core_tables",
    phase=Phase.SCHEMA,
    apply=_apply_core_tables,
    description="core tables and columns (packet_history, node_info, activity_daily_rollup)",
    pending=_core_tables_pending,
)

CORE_INDEXES = Migration(
    name="core_indexes",
    phase=Phase.BLOCKING,
    apply=_apply_core_indexes,
    description="shared indexes and legacy index cleanup",
    pending=_core_indexes_pending,
)

SCHEMA_MIGRATIONS: tuple[Migration, ...] = (CORE_TABLES,)
BLOCKING_MIGRATIONS: tuple[Migration, ...] = (CORE_INDEXES,)
