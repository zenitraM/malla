"""Rebuildable traceroute tables and pending records for raw-only writers."""

import sqlite3

TRACEROUTE_PORT = 70
TRACEROUTE_PREDICATE = "(portnum = 70 OR portnum_name = 'TRACEROUTE_APP')"


def ensure_traceroute_schema(cursor: sqlite3.Cursor) -> None:
    """Create empty derived tables; historical decoding is always explicit.

    Triggers leave raw-only inserts/updates pending, including imports and older
    capture versions. The shared writer replaces the pending record in the same
    transaction. These triggers never decode payloads or examine packet history.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traceroute_routes (
            packet_id INTEGER PRIMARY KEY REFERENCES packet_history(id) ON DELETE CASCADE,
            timestamp REAL NOT NULL,
            mesh_packet_id INTEGER,
            from_node_id INTEGER,
            to_node_id INTEGER,
            route_nodes_json TEXT NOT NULL DEFAULT '[]',
            snr_towards_json TEXT NOT NULL DEFAULT '[]',
            route_back_json TEXT NOT NULL DEFAULT '[]',
            snr_back_json TEXT NOT NULL DEFAULT '[]',
            forward_complete INTEGER NOT NULL DEFAULT 0 CHECK (forward_complete IN (0, 1)),
            return_complete INTEGER NOT NULL DEFAULT 0 CHECK (return_complete IN (0, 1)),
            parse_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (parse_status IN ('pending', 'parsed', 'valid_empty', 'invalid_payload')),
            parse_error TEXT,
            parser_version INTEGER NOT NULL DEFAULT 0,
            materialized_at REAL,
            CHECK ((parse_status = 'pending' AND parser_version = 0)
                OR (parse_status != 'pending' AND parser_version > 0)),
            CHECK ((parse_status = 'invalid_payload' AND parse_error IS NOT NULL)
                OR (parse_status != 'invalid_payload' AND parse_error IS NULL))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traceroute_hops (
            packet_id INTEGER NOT NULL REFERENCES traceroute_routes(packet_id) ON DELETE CASCADE,
            mesh_packet_id INTEGER NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('forward', 'return')),
            hop_index INTEGER NOT NULL CHECK (hop_index >= 0),
            timestamp REAL NOT NULL,
            from_node_id INTEGER NOT NULL,
            to_node_id INTEGER NOT NULL,
            snr REAL,
            channel_id TEXT,
            reception_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (mesh_packet_id, direction, hop_index, from_node_id, to_node_id)
        )
    """)

    for name, table, columns in (
        ("routes_time", "traceroute_routes", "timestamp"),
        ("routes_source_time", "traceroute_routes", "from_node_id, timestamp"),
        ("routes_target_time", "traceroute_routes", "to_node_id, timestamp"),
        (
            "routes_group_time",
            "traceroute_routes",
            "mesh_packet_id, from_node_id, to_node_id, timestamp",
        ),
        ("routes_version", "traceroute_routes", "parser_version"),
        ("hops_link_time", "traceroute_hops", "from_node_id, to_node_id, timestamp"),
        ("hops_time_link", "traceroute_hops", "timestamp, from_node_id, to_node_id"),
        ("hops_source_time", "traceroute_hops", "from_node_id, timestamp"),
        ("hops_target_time", "traceroute_hops", "to_node_id, timestamp"),
        ("hops_packet", "traceroute_hops", "packet_id"),
    ):
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS idx_traceroute_{name} ON {table} ({columns})"
        )

    # Explicit child deletion also handles raw import connections with foreign
    # keys disabled, and INSERT OR REPLACE reusing a packet row ID.
    for event, operation in (
        ("insert", "INSERT"),
        (
            "update",
            "UPDATE OF id, timestamp, mesh_packet_id, from_node_id, to_node_id, "
            "portnum, portnum_name, raw_payload, hop_start, hop_limit",
        ),
    ):
        old_cleanup = (
            "UPDATE traceroute_hops SET packet_id = ("
            "    SELECT r.packet_id FROM traceroute_routes r "
            "    WHERE r.mesh_packet_id = traceroute_hops.mesh_packet_id "
            "      AND r.packet_id != OLD.id "
            "    LIMIT 1"
            ") WHERE packet_id = OLD.id AND EXISTS ("
            "    SELECT 1 FROM traceroute_routes r "
            "    WHERE r.mesh_packet_id = traceroute_hops.mesh_packet_id "
            "      AND r.packet_id != OLD.id"
            "); "
            "DELETE FROM traceroute_hops WHERE packet_id = OLD.id; "
            "DELETE FROM traceroute_routes WHERE packet_id = OLD.id;"
            if event == "update"
            else ""
        )
        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS traceroute_packet_{event}
            AFTER {operation} ON packet_history
            BEGIN
                {old_cleanup}
                DELETE FROM traceroute_routes WHERE packet_id = NEW.id;
                INSERT INTO traceroute_routes
                    (packet_id, timestamp, mesh_packet_id, from_node_id, to_node_id)
                SELECT NEW.id, NEW.timestamp, NEW.mesh_packet_id,
                       NEW.from_node_id, NEW.to_node_id
                WHERE NEW.portnum = {TRACEROUTE_PORT} OR NEW.portnum_name = 'TRACEROUTE_APP';
            END
        """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS traceroute_packet_delete
        AFTER DELETE ON packet_history
        BEGIN
            UPDATE traceroute_hops SET packet_id = (
                SELECT r.packet_id FROM traceroute_routes r
                WHERE r.mesh_packet_id = traceroute_hops.mesh_packet_id
                  AND r.packet_id != OLD.id
                LIMIT 1
            ) WHERE packet_id = OLD.id AND EXISTS (
                SELECT 1 FROM traceroute_routes r
                WHERE r.mesh_packet_id = traceroute_hops.mesh_packet_id
                  AND r.packet_id != OLD.id
            );
            DELETE FROM traceroute_hops WHERE packet_id = OLD.id;
            DELETE FROM traceroute_routes WHERE packet_id = OLD.id;
        END
    """)
