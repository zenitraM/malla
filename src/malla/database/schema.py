"""Shared startup schema and index helpers."""

import logging
import sqlite3

logger = logging.getLogger(__name__)


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


def _get_existing_tables(cursor: sqlite3.Cursor) -> set[str]:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IS NOT NULL"
    )
    return {row[0] for row in cursor.fetchall()}


def _get_existing_indexes(cursor: sqlite3.Cursor) -> set[str]:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL"
    )
    return {row[0] for row in cursor.fetchall()}


def ensure_startup_schema(
    cursor: sqlite3.Cursor, *, drop_legacy_indexes: bool = False
) -> None:
    """Ensure shared schema columns and startup indexes exist."""

    existing_tables = _get_existing_tables(cursor)
    existing_indexes = _get_existing_indexes(cursor)

    if "node_info" in existing_tables:
        cursor.execute("PRAGMA table_info(node_info)")
        node_info_columns = {row[1] for row in cursor.fetchall()}
        if "primary_channel" not in node_info_columns:
            cursor.execute("ALTER TABLE node_info ADD COLUMN primary_channel TEXT")
            logger.info("Added primary_channel column to node_info table")

    for index_name, table_name, sql in INDEX_SPECS:
        if table_name not in existing_tables or index_name in existing_indexes:
            continue
        cursor.execute(sql)
        existing_indexes.add(index_name)

    if drop_legacy_indexes and "packet_history" in existing_tables:
        for index_name in LEGACY_INDEX_NAMES:
            cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
