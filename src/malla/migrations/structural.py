"""Structural migrations: tables, columns and indexes.

These are re-checked on every run instead of being marked done, exactly like the
startup code they replace: adding an index to :data:`INDEX_SPECS` (or a column
to :data:`PACKET_HISTORY_ADDED_COLUMNS`) in a later release keeps working on
databases that already ran the migration once.
"""

from __future__ import annotations

import logging
import sqlite3

from .. import activity_rollup
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
    # Web UI list filters/sorts measured on production-scale (7.4M rows):
    # portnum-name listings, telemetry per node, and the rssi/snr/hop sorts.
    (
        "idx_packet_history_portnum_name",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_portnum_name ON packet_history(portnum_name)",
    ),
    (
        "idx_packet_history_portnum_name_time",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_portnum_name_time ON packet_history(portnum_name, timestamp DESC)",
    ),
    (
        "idx_packet_history_rssi",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_rssi ON packet_history(rssi)",
    ),
    (
        "idx_packet_history_snr",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_snr ON packet_history(snr)",
    ),
    (
        "idx_packet_history_hop_count",
        "packet_history",
        "CREATE INDEX IF NOT EXISTS idx_packet_history_hop_count ON packet_history((hop_start - hop_limit))",
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

#: Indexes a previous release created but no query selects. Dropping them
#: keeps the write path cheaper on databases that already ran the old spec.
OBSOLETE_INDEX_NAMES: tuple[str, ...] = ("idx_packet_history_telemetry_node_time",)


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
    if present < {"packet_history", "node_info"}:
        return True
    if _missing_columns(conn, "packet_history", PACKET_HISTORY_ADDED_COLUMNS):
        return True
    return bool(_missing_columns(conn, "node_info", NODE_INFO_ADDED_COLUMNS))


def _apply_core_tables(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    conn.execute(PACKET_HISTORY_TABLE_SQL)
    conn.execute(NODE_INFO_TABLE_SQL)
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
        name in indexes(conn) for name in (*LEGACY_INDEX_NAMES, *OBSOLETE_INDEX_NAMES)
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
        for name in (*LEGACY_INDEX_NAMES, *OBSOLETE_INDEX_NAMES):
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


def _activity_quarter_tables_pending(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    present = tables(conn)
    return any(table not in present for table in activity_rollup.TABLES)


def _apply_activity_quarter_tables(
    conn: sqlite3.Connection, _wm: Watermark
) -> Watermark:
    conn.executescript(activity_rollup.ACTIVITY_QUARTER_TABLES_SQL)
    return None


def _drop_activity_daily_rollup_pending(
    conn: sqlite3.Connection, _wm: Watermark
) -> bool:
    return "activity_daily_rollup" in tables(conn)


def _apply_drop_activity_daily_rollup(
    conn: sqlite3.Connection, _wm: Watermark
) -> Watermark:
    """Remove the per-viewer daily rollup the quarter-hour buckets replace."""
    conn.execute("DROP TABLE IF EXISTS activity_daily_rollup")
    logger.info("Dropped activity_daily_rollup (replaced by quarter-hour buckets)")
    return None


ACTIVITY_QUARTER_TABLES_MIGRATION = Migration(
    name="activity_quarter_tables",
    phase=Phase.SCHEMA,
    apply=_apply_activity_quarter_tables,
    description="quarter-hour activity buckets the timeline shifts at query time",
    pending=_activity_quarter_tables_pending,
)

DROP_ACTIVITY_DAILY_ROLLUP = Migration(
    name="drop_activity_daily_rollup",
    phase=Phase.SCHEMA,
    apply=_apply_drop_activity_daily_rollup,
    description="drop the superseded per-viewer daily activity rollup",
    pending=_drop_activity_daily_rollup_pending,
)

# Capture-maintained rollup tables backing the slow-path reads (nodes list
# aggregates, latest positions/telemetry, traceroute catalogs, longest-links).
# They are populated exclusively by :mod:`malla.capture_rollups` (completed-
# bucket rolling refresh + id-high-water merges; see that module for the
# freshness contract) and are deliberately created by the shared startup path
# so a web UI on a fresh database self-heals before first request.
ROLLUP_TABLES_SQL: tuple[str, ...] = (
    # Single-row-per-name resume cursors for the latest-state merges. This is a
    # resume cursor, not a backlog watermark: steady state scans only the
    # minutes since the last refresh and a crash redoes one interval.
    """
    CREATE TABLE IF NOT EXISTS _rollup_cursor (
        name TEXT PRIMARY KEY,
        last_packet_id INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS node_hour_rollup (
        hour_epoch  INTEGER NOT NULL,                    -- timestamp // 3600, UTC
        node_id     INTEGER NOT NULL,
        packet_count INTEGER NOT NULL DEFAULT 0,
        direct_snr_sum  REAL NOT NULL DEFAULT 0,         -- hop_start=hop_limit rows passing
        direct_snr_count INTEGER NOT NULL DEFAULT 0,     -- the signal-quality validity rule
        last_seen   REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (hour_epoch, node_id)
    ) WITHOUT ROWID
""",
    """
    CREATE INDEX IF NOT EXISTS idx_node_hour_rollup_node
        ON node_hour_rollup(node_id, hour_epoch)
""",
    """
    CREATE TABLE IF NOT EXISTS node_latest_position (
        node_id        INTEGER PRIMARY KEY,
        last_seen      REAL NOT NULL,
        packet_id      INTEGER NOT NULL,
        gateway_id     TEXT,                             -- gateway of the kept packet
        latitude       REAL,                             -- already /1e7
        longitude      REAL,
        altitude       INTEGER,                          -- raw; 0 vs NULL preserved here
        precision_bits INTEGER,
        sats_in_view   INTEGER
    )
""",
    """
    CREATE TABLE IF NOT EXISTS node_latest_telemetry (
        node_id        INTEGER PRIMARY KEY,
        last_seen      REAL NOT NULL,
        packet_id      INTEGER NOT NULL,
        battery_level  REAL,
        voltage        REAL,
        channel_utilization REAL,
        air_util_tx    REAL
    )
""",
    """
    CREATE TABLE IF NOT EXISTS traceroute_endpoint (
        node_id    INTEGER PRIMARY KEY,
        first_seen REAL NOT NULL,
        last_seen  REAL NOT NULL
    )
""",
    """
    CREATE TABLE IF NOT EXISTS link_day_rollup (
        day          TEXT NOT NULL,                      -- UTC date of packet ts
        node_a       INTEGER NOT NULL,                   -- canonical a < b
        node_b       INTEGER NOT NULL,
        packet_count INTEGER NOT NULL DEFAULT 0,
        snr_sum      REAL   NOT NULL DEFAULT 0,
        snr_count    INTEGER NOT NULL DEFAULT 0,
        snr_min      REAL,
        snr_max      REAL,
        last_seen    REAL NOT NULL DEFAULT 0,
        last_packet_id INTEGER,                          -- newest packet id folded for the pair/day
        PRIMARY KEY (day, node_a, node_b)
    ) WITHOUT ROWID
""",
    """
    CREATE INDEX IF NOT EXISTS idx_link_day_rollup_pair ON link_day_rollup(node_a, node_b, day)
""",
    # Endpoint pairs of multi-hop traceroute paths (mirrors the legacy
    # longest-links "indirect" aggregation; path shape kept for the preview).
    """
    CREATE TABLE IF NOT EXISTS route_day_rollup (
        day          TEXT NOT NULL,
        end_a        INTEGER NOT NULL,                   -- first-hop source
        end_b        INTEGER NOT NULL,                   -- last-hop target
        path_count   INTEGER NOT NULL DEFAULT 0,         -- SNR-valid paths folded
        hop_count_sum INTEGER NOT NULL DEFAULT 0,
        snr_avg_sum  REAL NOT NULL DEFAULT 0,            -- sum of per-path mean SNR
        last_seen    REAL NOT NULL DEFAULT 0,
        last_packet_id INTEGER,
        last_route   TEXT,                               -- comma ids of the newest path
        PRIMARY KEY (day, end_a, end_b)
    ) WITHOUT ROWID
""",
    """
    CREATE INDEX IF NOT EXISTS idx_route_day_rollup_pair ON route_day_rollup(end_a, end_b, day)
""",
)

#: Every table :mod:`malla.capture_rollups` reads or writes; the pending check
#: mirrors the module contract that all of them exist before it runs.
ROLLUP_TABLE_NAMES: tuple[str, ...] = (
    "_rollup_cursor",
    "node_hour_rollup",
    "node_latest_position",
    "node_latest_telemetry",
    "traceroute_endpoint",
    "link_day_rollup",
    "route_day_rollup",
)


def _capture_rollup_tables_pending(conn: sqlite3.Connection, _wm: Watermark) -> bool:
    present = tables(conn)
    return any(name not in present for name in ROLLUP_TABLE_NAMES)


def _apply_capture_rollup_tables(conn: sqlite3.Connection, _wm: Watermark) -> Watermark:
    for statement in ROLLUP_TABLES_SQL:
        conn.execute(statement)
    return None


CAPTURE_ROLLUP_TABLES = Migration(
    name="capture_rollup_tables",
    phase=Phase.SCHEMA,
    apply=_apply_capture_rollup_tables,
    description="capture-maintained rollup tables for the slow read paths",
    pending=_capture_rollup_tables_pending,
)

SCHEMA_MIGRATIONS: tuple[Migration, ...] = (
    CORE_TABLES,
    ACTIVITY_QUARTER_TABLES_MIGRATION,
    DROP_ACTIVITY_DAILY_ROLLUP,
    CAPTURE_ROLLUP_TABLES,
)
BLOCKING_MIGRATIONS: tuple[Migration, ...] = (CORE_INDEXES,)
