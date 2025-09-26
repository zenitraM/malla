"""
Database fixtures for testing.

This module creates a test database with known fixture data that can be used
for integration testing of the API endpoints and services.
"""

import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)


class DatabaseFixtures:
    """
    Creates and manages test database fixtures.

    This class sets up a complete test database with realistic data that
    mirrors the production schema and provides known data for testing.
    """

    def __init__(self):
        # Initialize counters
        self.packet_counter = 1

        # Create test data
        self.test_nodes = self.create_sample_nodes()
        self.test_packets = self.create_sample_packets()
        self.test_traceroutes = self.create_sample_traceroutes()
        self.test_node_info = self.create_sample_node_info()

    def create_test_database(self, db_path: str):
        """Create a complete test database with fixture data."""
        logger.info(f"Creating test database at {db_path}")

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Create the schema
            self._create_schema(cursor)

            # Insert fixture data
            self._insert_node_info(cursor)
            self._insert_packets(cursor)

            conn.commit()

        logger.info(
            f"Test database created with {len(self.test_packets) + len(self.test_traceroutes)} packets and {len(self.test_nodes)} nodes"
        )

    def _create_schema(self, cursor: sqlite3.Cursor):
        """Create the database schema matching the production database."""

        # Packet history table - main table for packets
        cursor.execute("""
            CREATE TABLE packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                topic TEXT NOT NULL,
                from_node_id INTEGER,
                to_node_id INTEGER,
                portnum INTEGER,
                portnum_name TEXT,
                gateway_id TEXT,
                channel_id TEXT,
                rssi INTEGER,
                snr REAL,
                hop_limit INTEGER,
                hop_start INTEGER,
                payload_length INTEGER,
                raw_payload BLOB,
                mesh_packet_id INTEGER,
                processed_successfully BOOLEAN DEFAULT TRUE,
                via_mqtt BOOLEAN,
                want_ack BOOLEAN,
                priority INTEGER,
                delayed INTEGER,
                channel_index INTEGER,
                rx_time INTEGER,
                pki_encrypted BOOLEAN,
                next_hop INTEGER,
                relay_node INTEGER,
                tx_after INTEGER
            )
        """)

        # Node info table
        cursor.execute("""
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
                first_seen REAL,
                last_updated REAL,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # Forum topics table (for compatibility)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forum_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # Create indexes for performance
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_timestamp ON packet_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_from_node ON packet_history(from_node_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_to_node ON packet_history(to_node_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_portnum ON packet_history(portnum)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_gateway ON packet_history(gateway_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_portnum_name ON packet_history(portnum_name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mesh_packet_id ON packet_history(mesh_packet_id)"
        )

    def create_sample_nodes(self) -> list[dict[str, Any]]:
        """Create test node data with variety of node types."""
        import time

        now = time.time()

        return [
            {
                "node_id": 1128074276,  # 0x433d0c24
                "hex_id": "!433d0c24",
                "long_name": "Test Gateway Alpha",
                "short_name": "TGA",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "is_licensed": False,
                "mac_address": "24:6f:28:43:45:67",
                "first_seen": now - 86400,  # 24 hours ago
                "last_updated": now - 300,  # 5 minutes ago
                "last_seen": now - 300,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 1128074277,  # 0x433d0c25
                "hex_id": "!433d0c25",
                "long_name": "Test Mobile Beta",
                "short_name": "TMB",
                "hw_model": "HELTEC_V3",
                "role": "CLIENT",
                "is_licensed": False,
                "mac_address": "24:6f:28:43:45:68",
                "first_seen": now - 43200,  # 12 hours ago
                "last_updated": now - 600,  # 10 minutes ago
                "last_seen": now - 600,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 1128074278,  # 0x433d0c26
                "hex_id": "!433d0c26",
                "long_name": "Test Repeater Gamma",
                "short_name": "TRG",
                "hw_model": "TBEAM",
                "role": "REPEATER",
                "is_licensed": True,
                "mac_address": "24:6f:28:43:45:69",
                "first_seen": now - 172800,  # 48 hours ago
                "last_updated": now - 1800,  # 30 minutes ago
                "last_seen": now - 60,  # 1 minute ago
                "primary_channel": "LongFast",
            },
            # Additional nodes for comprehensive testing
            {
                "node_id": 2883444196,  # 0xabdddde4
                "hex_id": "!abdddde4",
                "long_name": "Test Node Beta Router",
                "short_name": "TNBR",
                "hw_model": "HELTEC_V3",
                "role": "ROUTER",
                "is_licensed": False,
                "mac_address": "24:6f:28:ab:dd:dd",
                "first_seen": now - 21600,  # 6 hours ago
                "last_updated": now - 720,  # 12 minutes ago
                "last_seen": now - 720,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 3735928559,  # 0xdeadbeef
                "hex_id": "!deadbeef",
                "long_name": "Test Node Gamma Client",
                "short_name": "TNGC",
                "hw_model": "RAK4631",
                "role": "CLIENT",
                "is_licensed": False,
                "mac_address": "24:6f:28:de:ad:be",
                "first_seen": now - 10800,  # 3 hours ago
                "last_updated": now - 180,  # 3 minutes ago
                "last_seen": now - 180,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0xDDDDDDDD,  # Changed from 0xffffffff to avoid broadcast filtering
                "hex_id": "!dddddddd",
                "long_name": "Test Edge Node Delta",
                "short_name": "TEND",
                "hw_model": "TBEAM",
                "role": "CLIENT_MUTE",
                "is_licensed": False,
                "mac_address": "24:6f:28:dd:dd:dd",
                "first_seen": now - 7200,  # 2 hours ago
                "last_updated": now - 3600,  # 1 hour ago
                "last_seen": now - 3600,
                "primary_channel": "LongFast",
            },
            # Node with unknown role - should display with red color
            {
                "node_id": 0x66666666,
                "hex_id": "!66666666",
                "long_name": "Test Unknown Role Node",
                "short_name": "TURN",
                "hw_model": "HELTEC_V3",
                "role": None,  # Unknown role
                "is_licensed": False,
                "mac_address": "24:6f:28:66:66:66",
                "first_seen": now - 1800,  # 30 minutes ago
                "last_updated": now - 120,  # 2 minutes ago
                "last_seen": now - 120,
                "primary_channel": "LongFast",
            },
            # Additional nodes for enhanced traceroute scenarios
            {
                "node_id": 0x77777777,
                "hex_id": "!77777777",
                "long_name": "Test Mesh Node Hotel",
                "short_name": "TMNH",
                "hw_model": "RAK4631",
                "role": "ROUTER",
                "is_licensed": False,
                "mac_address": "24:6f:28:77:77:77",
                "first_seen": now - 3600,  # 1 hour ago
                "last_updated": now - 180,  # 3 minutes ago
                "last_seen": now - 180,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0x88888888,
                "hex_id": "!88888888",
                "long_name": "Test Bridge Node India",
                "short_name": "TBNI",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "is_licensed": True,
                "mac_address": "24:6f:28:88:88:88",
                "first_seen": now - 7200,  # 2 hours ago
                "last_updated": now - 300,  # 5 minutes ago
                "last_seen": now - 300,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0xCCCCCCCC,  # Changed from 0x99999999 to avoid conflict with test
                "hex_id": "!cccccccc",
                "long_name": "Test Relay Node Juliet",
                "short_name": "TRNJ",
                "hw_model": "HELTEC_V3",
                "role": "REPEATER",
                "is_licensed": False,
                "mac_address": "24:6f:28:cc:cc:cc",  # Updated MAC to match
                "first_seen": now - 5400,  # 1.5 hours ago
                "last_updated": now - 240,  # 4 minutes ago
                "last_seen": now - 240,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0xAAAAAAAA,
                "hex_id": "!aaaaaaaa",
                "long_name": "Test Hub Node Kilo",
                "short_name": "THNK",
                "hw_model": "RAK4631",
                "role": "ROUTER",
                "is_licensed": False,
                "mac_address": "24:6f:28:aa:aa:aa",
                "first_seen": now - 10800,  # 3 hours ago
                "last_updated": now - 420,  # 7 minutes ago
                "last_seen": now - 420,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0xBBBBBBBB,
                "hex_id": "!bbbbbbbb",
                "long_name": "Test Edge Node Lima",
                "short_name": "TENL",
                "hw_model": "TBEAM",
                "role": "CLIENT",
                "is_licensed": False,
                "mac_address": "24:6f:28:bb:bb:bb",
                "first_seen": now - 1800,  # 30 minutes ago
                "last_updated": now - 90,  # 1.5 minutes ago
                "last_seen": now - 90,
                "primary_channel": "LongFast",
            },
        ]

    def create_sample_node_info(self) -> list[dict[str, Any]]:
        """Create additional node info entries."""
        import time

        now = time.time()

        return [
            {
                "node_id": 0x11111111,
                "hex_id": "!11111111",
                "long_name": "Test Node Delta",
                "short_name": "TND",
                "hw_model": "HELTEC_V2",
                "role": "CLIENT",
                "is_licensed": False,
                "mac_address": "24:6f:28:11:11:11",
                "first_seen": now - 7200,  # 2 hours ago
                "last_updated": now - 900,  # 15 minutes ago
                "last_seen": now - 900,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0x22222222,
                "hex_id": "!22222222",
                "long_name": "Test Node Echo",
                "short_name": "TNE",
                "hw_model": "TBEAM",
                "role": "ROUTER",
                "is_licensed": False,
                "mac_address": "24:6f:28:22:22:22",
                "first_seen": now - 14400,  # 4 hours ago
                "last_updated": now - 1200,  # 20 minutes ago
                "last_seen": now - 1200,
                "primary_channel": "LongFast",
            },
            # Additional nodes for comprehensive testing
            {
                "node_id": 0x33333333,
                "hex_id": "!33333333",
                "long_name": "Test Sensor Node Foxtrot",
                "short_name": "TSNF",
                "hw_model": "RAK4631",
                "role": "SENSOR",
                "is_licensed": False,
                "mac_address": "24:6f:28:33:33:33",
                "first_seen": now - 5400,  # 1.5 hours ago
                "last_updated": now - 450,  # 7.5 minutes ago
                "last_seen": now - 450,
                "primary_channel": "LongFast",
            },
            {
                "node_id": 0x44444444,
                "hex_id": "!44444444",
                "long_name": "Test Router Client Golf",
                "short_name": "TRCG",
                "hw_model": "HELTEC_V3",
                "role": "ROUTER_CLIENT",
                "is_licensed": True,
                "mac_address": "24:6f:28:44:44:44",
                "first_seen": now - 9000,  # 2.5 hours ago
                "last_updated": now - 240,  # 4 minutes ago
                "last_seen": now - 240,
                "primary_channel": "LongFast",
            },
            # Node with no names - should generate "Node {hex_id}" display name
            {
                "node_id": 0x55555555,
                "hex_id": "!55555555",
                "long_name": None,  # No long name
                "short_name": None,  # No short name
                "hw_model": "TBEAM",
                "role": "CLIENT",
                "is_licensed": False,
                "mac_address": "24:6f:28:55:55:55",
                "first_seen": now - 3600,  # 1 hour ago
                "last_updated": now - 300,  # 5 minutes ago
                "last_seen": now - 300,
                "primary_channel": "LongFast",
            },
        ]

    def _insert_node_info(self, cursor: sqlite3.Cursor):
        """Insert node info fixture data."""
        for node in self.test_nodes:
            cursor.execute(
                """
                INSERT INTO node_info
                (node_id, hex_id, long_name, short_name, hw_model, role, primary_channel, is_licensed, mac_address, first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    node["node_id"],
                    node["hex_id"],
                    node["long_name"],
                    node["short_name"],
                    node["hw_model"],
                    node["role"],
                    node["primary_channel"],
                    node["is_licensed"],
                    node["mac_address"],
                    node["first_seen"],
                    node["last_updated"],
                ),
            )

        # Insert additional node info
        for node in self.test_node_info:
            cursor.execute(
                """
                INSERT INTO node_info
                (node_id, hex_id, long_name, short_name, hw_model, role, primary_channel, is_licensed, mac_address, first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    node["node_id"],
                    node["hex_id"],
                    node["long_name"],
                    node["short_name"],
                    node["hw_model"],
                    node["role"],
                    node["primary_channel"],
                    node["is_licensed"],
                    node["mac_address"],
                    node["first_seen"],
                    node["last_updated"],
                ),
            )

    def _insert_packets(self, cursor: sqlite3.Cursor):
        """Insert packet fixture data including traceroutes."""
        all_packets = self.test_packets + self.test_traceroutes

        for packet in all_packets:
            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully,
                    via_mqtt, want_ack, priority, delayed, channel_index, rx_time,
                    pki_encrypted, next_hop, relay_node, tx_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    packet["id"],
                    packet["timestamp"],
                    packet["topic"],
                    packet["from_node_id"],
                    packet["to_node_id"],
                    packet["portnum"],
                    packet["portnum_name"],
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    packet["payload_length"],
                    packet["raw_payload"],
                    packet["mesh_packet_id"],
                    packet["processed_successfully"],
                    packet.get("via_mqtt"),
                    packet.get("want_ack"),
                    packet.get("priority"),
                    packet.get("delayed"),
                    packet.get("channel_index"),
                    packet.get("rx_time"),
                    packet.get("pki_encrypted"),
                    packet.get("next_hop"),
                    packet.get("relay_node"),
                    packet.get("tx_after"),
                ),
            )

    def get_test_data_summary(self) -> dict[str, int]:
        """Get a summary of test data counts."""
        return {
            "nodes": len(self.test_nodes),
            "packets": len(self.test_packets),
            "traceroutes": len(self.test_traceroutes),
            "total_packets": len(self.test_packets) + len(self.test_traceroutes),
        }

    def create_test_packet(
        self,
        packet_id=None,
        from_node_id=None,
        to_node_id=None,
        portnum=None,
        portnum_name=None,
        timestamp=None,
        gateway_id=None,
        channel_id=None,
        rssi=None,
        snr=None,
        hop_limit=None,
        hop_start=None,
        payload_data=None,
        mesh_packet_id=None,
    ):
        """Create a test packet with realistic data."""
        import os

        # Generate realistic defaults
        packet_id = packet_id or self.packet_counter
        timestamp = timestamp or time.time() - (
            3600 * 24 * (self.packet_counter % 30)
        )  # Spread over 30 days
        from_node_id = from_node_id or (0x12340000 + (packet_id % 100))
        to_node_id = to_node_id or (
            0xFFFFFFFF if packet_id % 3 == 0 else 0x56780000 + ((packet_id + 10) % 100)
        )
        portnum = portnum or (
            1
            if packet_id % 4 != 0
            else 3
            if packet_id % 4 == 1
            else 4
            if packet_id % 4 == 2
            else 70
        )
        portnum_name = portnum_name or (
            "TEXT_MESSAGE_APP"
            if portnum == 1
            else "POSITION_APP"
            if portnum == 3
            else "NODEINFO_APP"
            if portnum == 4
            else "TRACEROUTE_APP"
        )
        gateway_id = gateway_id or f"!{(0x11110000 + (packet_id % 50)):08x}"
        channel_id = channel_id or "LongFast"
        mesh_packet_id = mesh_packet_id or int.from_bytes(
            os.urandom(4), "big"
        )  # Generate random 32-bit packet ID
        rssi = rssi or (-60 - (packet_id % 40))  # RSSI between -60 and -100
        snr = snr or (10.0 - (packet_id % 20))  # SNR between 10 and -10
        hop_limit = hop_limit or (3 if packet_id % 5 != 0 else 7)
        hop_start = hop_start or (hop_limit + (packet_id % 3))

        if portnum == 1:  # TEXT_MESSAGE_APP
            message = payload_data or f"Test message {packet_id}"
            raw_payload = message.encode("utf-8")
            payload_length = len(raw_payload)
        elif portnum == 3:  # POSITION_APP
            # Create protobuf position payload
            try:
                from meshtastic import mesh_pb2

                position = mesh_pb2.Position()

                # Use provided payload_data or defaults
                if payload_data:
                    position.latitude_i = int(
                        payload_data.get("latitude", 37.7749) * 1e7
                    )
                    position.longitude_i = int(
                        payload_data.get("longitude", -122.4194) * 1e7
                    )
                    position.altitude = payload_data.get("altitude", 100)
                    position.sats_in_view = payload_data.get("sats_in_view", 8)
                else:
                    # Default San Francisco coordinates
                    position.latitude_i = int(37.7749 * 1e7)
                    position.longitude_i = int(-122.4194 * 1e7)
                    position.altitude = 100
                    position.sats_in_view = 8

                raw_payload = position.SerializeToString()
                payload_length = len(raw_payload)
            except ImportError:
                # Fallback if protobuf not available
                raw_payload = b"\x08\x64\x10\x08"  # Simple position data
                payload_length = len(raw_payload)
        elif portnum == 4:  # NODEINFO_APP
            # Create protobuf nodeinfo payload
            try:
                from meshtastic import mesh_pb2

                user = mesh_pb2.User()
                user.id = f"!{from_node_id:08x}"
                user.long_name = (
                    payload_data.get("long_name", f"Test Node {from_node_id}")
                    if payload_data
                    else f"Test Node {from_node_id}"
                )
                user.short_name = (
                    payload_data.get("short_name", f"TN{from_node_id % 100:02d}")
                    if payload_data
                    else f"TN{from_node_id % 100:02d}"
                )
                user.hw_model = mesh_pb2.HardwareModel.TBEAM

                raw_payload = user.SerializeToString()
                payload_length = len(raw_payload)
            except ImportError:
                # Fallback if protobuf not available
                raw_payload = b"\x0a\x09!12345678\x12\x0bTest Node\x1a\x04TN01"
                payload_length = len(raw_payload)
        elif portnum == 70:  # TRACEROUTE_APP
            # Create traceroute payload using proper protobuf encoding
            try:
                from meshtastic import mesh_pb2

                route_discovery = mesh_pb2.RouteDiscovery()

                if payload_data:
                    # Add route nodes
                    route_nodes = payload_data.get("route_nodes", [])
                    if route_nodes:
                        route_discovery.route.extend(route_nodes)

                    # Add SNR towards (scaled by 4 as per Meshtastic protocol)
                    snr_towards = payload_data.get("snr_towards", [])
                    if snr_towards:
                        scaled_snr = [int(snr * 4.0) for snr in snr_towards]
                        route_discovery.snr_towards.extend(scaled_snr)

                    # Add route back
                    route_back = payload_data.get("route_back", [])
                    if route_back:
                        route_discovery.route_back.extend(route_back)

                    # Add SNR back (scaled by 4 as per Meshtastic protocol)
                    snr_back = payload_data.get("snr_back", [])
                    if snr_back:
                        scaled_snr_back = [int(snr * 4.0) for snr in snr_back]
                        route_discovery.snr_back.extend(scaled_snr_back)
                else:
                    # Default test case - single SNR value
                    route_discovery.snr_towards.extend([int(-5.0 * 4)])

                raw_payload = route_discovery.SerializeToString()
                payload_length = len(raw_payload)
            except ImportError:
                # Fallback if protobuf not available - create minimal valid protobuf data
                # Field 2 (snr_towards) with single float value -5.0 (scaled to -20)
                raw_payload = (
                    b"\x15\xec\xff\xff\xff"  # Wire type 5 (fixed32), field 2, value -20
                )
                payload_length = len(raw_payload)
        elif portnum == 71:  # NEIGHBORINFO_APP
            # Create protobuf neighborinfo payload
            try:
                from meshtastic import mesh_pb2

                neighbor_info = mesh_pb2.NeighborInfo()
                neighbor_info.node_id = from_node_id
                neighbor_info.last_sent_by_id = (
                    payload_data.get("last_sent_by_id", 0) if payload_data else 0
                )
                neighbor_info.node_broadcast_interval_secs = (
                    payload_data.get("node_broadcast_interval_secs", 0)
                    if payload_data
                    else 0
                )

                # Add neighbors if provided
                if payload_data and "neighbors" in payload_data:
                    for neighbor_data in payload_data["neighbors"]:
                        neighbor = neighbor_info.neighbors.add()
                        neighbor.node_id = neighbor_data.get("node_id", 0)
                        neighbor.snr = neighbor_data.get("snr", 0.0)
                        neighbor.last_rx_time = neighbor_data.get("last_rx_time", 0)
                        neighbor.node_broadcast_interval_secs = neighbor_data.get(
                            "node_broadcast_interval_secs", 0
                        )

                raw_payload = neighbor_info.SerializeToString()
                payload_length = len(raw_payload)
            except ImportError:
                # Fallback if protobuf not available
                raw_payload = b"\x08\x01\x10\x00\x18\x00"  # Simple neighbor info data
                payload_length = len(raw_payload)
        else:
            # Default case for unknown portnums
            raw_payload = b"\x00\x01\x02\x03"  # Generic test payload
            payload_length = len(raw_payload)

        # Create MQTT topic
        topic = f"msh/US/2/e/{channel_id}"

        packet_data = {
            "id": packet_id,
            "timestamp": timestamp,
            "topic": topic,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "portnum": portnum,
            "portnum_name": portnum_name,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "mesh_packet_id": mesh_packet_id,
            "rssi": rssi,
            "snr": snr,
            "hop_limit": hop_limit,
            "hop_start": hop_start,
            "payload_length": payload_length,
            "raw_payload": raw_payload,
            "processed_successfully": True,
            "via_mqtt": packet_id % 4 == 0,  # 25% of packets via MQTT
            "want_ack": packet_id % 3 == 0,  # 33% want acknowledgment
            "priority": packet_id % 4,  # Priority 0-3
            "delayed": packet_id % 3,  # Delay status 0-2
            "channel_index": packet_id % 8,  # Channel index 0-7
            "rx_time": int(timestamp),  # Receive time as integer timestamp
            "pki_encrypted": packet_id % 10 == 0,  # 10% PKI encrypted
            "next_hop": (0x12340000 + ((packet_id + 5) % 100))
            if packet_id % 5 == 0
            else None,  # 20% have next hop
            "relay_node": (0x12340000 + ((packet_id + 10) % 100))
            if packet_id % 7 == 0
            else None,  # ~14% have relay node
            "tx_after": (packet_id * 100)
            if packet_id % 6 == 0
            else None,  # ~17% have tx_after delay
        }

        self.packet_counter += 1
        return packet_data

    def create_sample_packets(self):
        """Create sample packet data for testing."""
        import time

        base_time = time.time() - 3600  # 1 hour ago

        # Create various types of packets using the new method
        packets = []

        # Text message packets
        for i in range(5):
            packet = self.create_test_packet(
                packet_id=i + 1,
                from_node_id=1128074276 + i,
                portnum=1,
                portnum_name="TEXT_MESSAGE_APP",
                timestamp=base_time + (i * 300),  # 5 minutes apart
                payload_data=f"Test message {i + 1}",
            )
            packets.append(packet)

        # Position packets for original test nodes
        for i in range(3):
            packet = self.create_test_packet(
                packet_id=i + 6,
                from_node_id=1128074276 + i,
                portnum=3,
                portnum_name="POSITION_APP",
                timestamp=base_time + (i * 600),  # 10 minutes apart
                payload_data={
                    "latitude": 37.7749 + (i * 0.01),
                    "longitude": -122.4194 + (i * 0.01),
                    "altitude": 100 + (i * 10),
                    "sats_in_view": 8 + i,
                },
            )
            packets.append(packet)

        # Position packets for additional test nodes
        additional_nodes_with_location = [
            {
                "node_id": 2883444196,  # Test Node Beta Router
                "latitude": 37.7849,
                "longitude": -122.4094,
                "altitude": 120,
            },
            {
                "node_id": 3735928559,  # Test Node Gamma Client
                "latitude": 37.7649,
                "longitude": -122.4294,
                "altitude": 80,
            },
            {
                "node_id": 0xDDDDDDDD,  # Test Edge Node Delta
                "latitude": 37.7549,
                "longitude": -122.4394,
                "altitude": 60,
            },
            {
                "node_id": 0x11111111,  # Test Node Delta
                "latitude": 37.7449,
                "longitude": -122.4494,
                "altitude": 90,
            },
            {
                "node_id": 0x22222222,  # Test Node Echo
                "latitude": 37.7349,
                "longitude": -122.4594,
                "altitude": 110,
            },
            {
                "node_id": 0x33333333,  # Test Sensor Node Foxtrot
                "latitude": 37.7249,
                "longitude": -122.4694,
                "altitude": 70,
            },
            {
                "node_id": 0x44444444,  # Test Router Client Golf
                "latitude": 37.7149,
                "longitude": -122.4794,
                "altitude": 130,
            },
            {
                "node_id": 0x55555555,  # Node with no names - should show "Node 55555555"
                "latitude": 37.7049,
                "longitude": -122.4894,
                "altitude": 140,
            },
            {
                "node_id": 0x66666666,  # Node with unknown role - should show red color
                "latitude": 37.6949,
                "longitude": -122.4994,
                "altitude": 150,
            },
        ]

        for i, node_location in enumerate(additional_nodes_with_location):
            packet = self.create_test_packet(
                packet_id=i + 100,  # Start from packet ID 100 to avoid conflicts
                from_node_id=node_location["node_id"],
                portnum=3,
                portnum_name="POSITION_APP",
                timestamp=base_time + (i * 300),  # 5 minutes apart
                payload_data={
                    "latitude": node_location["latitude"],
                    "longitude": node_location["longitude"],
                    "altitude": node_location["altitude"],
                    "sats_in_view": 8 + (i % 4),  # Vary satellite count
                },
            )
            packets.append(packet)

        # Position packets for traceroute graph test nodes (NYC area coordinates)
        traceroute_nodes_with_location = [
            {
                "node_id": 1819569748,  # Tomate Base
                "latitude": 40.7128,
                "longitude": -74.0060,
                "altitude": 10,
            },
            {
                "node_id": 2147483647,  # Central Hub Node
                "latitude": 40.7589,
                "longitude": -73.9851,
                "altitude": 25,
            },
            {
                "node_id": 3735928559,  # Edge Node Alpha
                "latitude": 40.6782,
                "longitude": -73.9442,
                "altitude": 5,
            },
            {
                "node_id": 0xDDDDDDDD,  # Edge Node Beta (TEND)
                "latitude": 40.7505,
                "longitude": -73.9934,
                "altitude": 15,
            },
            {
                "node_id": 1234567890,  # Relay Station Gamma
                "latitude": 40.7282,
                "longitude": -74.0776,
                "altitude": 30,
            },
            {
                "node_id": 987654321,  # Remote Node Delta
                "latitude": 40.6892,
                "longitude": -74.0445,
                "altitude": 8,
            },
            {
                "node_id": 555666777,  # Mesh Node Epsilon
                "latitude": 40.7831,
                "longitude": -73.9712,
                "altitude": 20,
            },
            # Note: 111222333 (Gateway Node Zeta) intentionally has no location
        ]

        for i, node_location in enumerate(traceroute_nodes_with_location):
            packet = self.create_test_packet(
                packet_id=i + 20,  # Start from packet ID 20 to avoid conflicts
                from_node_id=node_location["node_id"],
                portnum=3,
                portnum_name="POSITION_APP",
                timestamp=base_time + (i * 300),  # 5 minutes apart
                payload_data={
                    "latitude": node_location["latitude"],
                    "longitude": node_location["longitude"],
                    "altitude": node_location["altitude"],
                    "sats_in_view": 8 + (i % 4),  # Vary satellite count
                },
            )
            packets.append(packet)

        # Node info packets
        for i in range(2):
            packet = self.create_test_packet(
                packet_id=i + 9,
                from_node_id=1128074276 + i,
                portnum=4,
                portnum_name="NODEINFO_APP",
                timestamp=base_time + (i * 900),  # 15 minutes apart
                payload_data={
                    "long_name": f"Test Gateway {i + 1}",
                    "short_name": f"TG{i + 1:02d}",
                },
            )
            packets.append(packet)

        # Enhanced gateway comparison data - create multiple packets received by both gateways
        import random

        random.seed(42)  # For consistent test data

        gateway1_id = "!11110000"  # First gateway
        gateway2_id = "!11110001"  # Second gateway

        # Create 20 packets with varied RSSI/SNR values for gateway comparison
        for i in range(20):
            base_packet_id = 5000 + i
            timestamp = base_time + (i * 120)  # 2 minutes apart
            from_node = 1128074276 + (i % 5)  # Cycle through different source nodes

            # Create the original packet
            packet = self.create_test_packet(
                packet_id=base_packet_id,
                from_node_id=from_node,
                portnum=1,
                portnum_name="TEXT_MESSAGE_APP",
                timestamp=timestamp,
                gateway_id=gateway1_id,
                rssi=random.randint(-120, -60),  # Varied RSSI values
                snr=random.uniform(-15.0, 10.0),  # Varied SNR values
                hop_limit=3,
                payload_data=f"Gateway comparison test message {i + 1}",
            )
            packets.append(packet)

            # Create duplicate reception by second gateway with different signal values
            packet2 = self.create_test_packet(
                packet_id=base_packet_id
                + 1000,  # Different packet ID but same mesh_packet_id
                from_node_id=from_node,
                portnum=1,
                portnum_name="TEXT_MESSAGE_APP",
                timestamp=timestamp + random.uniform(0.1, 2.0),  # Slight time offset
                gateway_id=gateway2_id,
                rssi=random.randint(-125, -55),  # Different RSSI range
                snr=random.uniform(-20.0, 15.0),  # Different SNR range
                hop_limit=3,
                payload_data=f"Gateway comparison test message {i + 1}",
                mesh_packet_id=packet[
                    "mesh_packet_id"
                ],  # Same mesh packet ID for comparison
            )
            packets.append(packet2)

        # Add more multi-gateway packets for better showcase
        # Create some packets received by 3+ gateways to show more complex scenarios
        gateway3_id = "!11110002"  # Third gateway
        gateway4_id = "!11110003"  # Fourth gateway
        gateway5_id = "!11110004"  # Fifth gateway

        # Create 10 packets received by multiple gateways (3-5 gateways each)
        for i in range(10):
            base_packet_id = 50000 + i
            timestamp = base_time + 1800 + (i * 180)  # 3 minutes apart
            from_node = 1128074276 + (i % 3)  # Cycle through different source nodes
            mesh_id = f"multi_gw_{i:03d}"

            # Base message
            base_message = f"Multi-gateway broadcast message {i + 1}"

            # Create reception by first gateway
            packet1 = self.create_test_packet(
                packet_id=base_packet_id,
                from_node_id=from_node,
                portnum=1,
                portnum_name="TEXT_MESSAGE_APP",
                timestamp=timestamp,
                gateway_id=gateway1_id,
                rssi=random.randint(-85, -65),  # Good signal
                snr=random.uniform(2.0, 12.0),  # Good SNR
                hop_limit=3,
                payload_data=base_message,
                mesh_packet_id=mesh_id,
            )
            packets.append(packet1)

            # Create reception by second gateway with different signal
            packet2 = self.create_test_packet(
                packet_id=base_packet_id + 1000,
                from_node_id=from_node,
                portnum=1,
                portnum_name="TEXT_MESSAGE_APP",
                timestamp=timestamp + random.uniform(0.1, 1.5),
                gateway_id=gateway2_id,
                rssi=random.randint(-95, -70),  # Slightly worse signal
                snr=random.uniform(-2.0, 8.0),  # More varied SNR
                hop_limit=3,
                payload_data=base_message,
                mesh_packet_id=mesh_id,
            )
            packets.append(packet2)

            # Create reception by third gateway (for first 8 packets)
            if i < 8:
                packet3 = self.create_test_packet(
                    packet_id=base_packet_id + 2000,
                    from_node_id=from_node,
                    portnum=1,
                    portnum_name="TEXT_MESSAGE_APP",
                    timestamp=timestamp + random.uniform(0.2, 2.0),
                    gateway_id=gateway3_id,
                    rssi=random.randint(-100, -75),  # Weaker signal
                    snr=random.uniform(-5.0, 5.0),  # Lower SNR
                    hop_limit=3,
                    payload_data=base_message,
                    mesh_packet_id=mesh_id,
                )
                packets.append(packet3)

            # Create reception by fourth gateway (for first 5 packets)
            if i < 5:
                packet4 = self.create_test_packet(
                    packet_id=base_packet_id + 3000,
                    from_node_id=from_node,
                    portnum=1,
                    portnum_name="TEXT_MESSAGE_APP",
                    timestamp=timestamp + random.uniform(0.3, 2.5),
                    gateway_id=gateway4_id,
                    rssi=random.randint(-110, -80),  # Even weaker signal
                    snr=random.uniform(-8.0, 3.0),  # Lower SNR range
                    hop_limit=3,
                    payload_data=base_message,
                    mesh_packet_id=mesh_id,
                )
                packets.append(packet4)

            # Create reception by fifth gateway (for first 2 packets only)
            if i < 2:
                packet5 = self.create_test_packet(
                    packet_id=base_packet_id + 4000,
                    from_node_id=from_node,
                    portnum=1,
                    portnum_name="TEXT_MESSAGE_APP",
                    timestamp=timestamp + random.uniform(0.4, 3.0),
                    gateway_id=gateway5_id,
                    rssi=random.randint(-115, -85),  # Weakest signal
                    snr=random.uniform(-10.0, 1.0),  # Lowest SNR range
                    hop_limit=3,
                    payload_data=base_message,
                    mesh_packet_id=mesh_id,
                )
                packets.append(packet5)

        return packets

    def create_sample_traceroutes(self) -> list[dict[str, Any]]:
        """Create test traceroute packets."""
        traceroutes = []
        import time

        now = time.time()
        packet_id = 10000

        # Create various traceroute scenarios with rich multi-hop data
        scenarios = [
            {
                "from_node": 0x12345678,
                "to_node": 0x87654321,
                "route_nodes": [0x11111111, 0x22222222],  # Two intermediate nodes
                "snr_towards": [
                    -5.0,
                    -8.0,
                    -12.0,
                ],  # Three hops: source -> intermediate1 -> intermediate2 -> destination
                "route_back": [
                    0x22222222,
                    0x11111111,
                ],  # Return path through same intermediates
                "snr_back": [-10.0, -7.0, -6.0],
                "description": "Complex multi-hop traceroute with return path",
            },
            {
                "from_node": 0x87654321,
                "to_node": 0x22222222,
                "route_nodes": [
                    0x11111111,
                    0x33333333,
                    0x44444444,
                ],  # Three intermediate nodes
                "snr_towards": [-6.0, -9.0, -12.0, -15.0],  # Four hops total
                "route_back": [],
                "snr_back": [],
                "description": "Four-hop traceroute without return path",
            },
            {
                "from_node": 0x33333333,
                "to_node": 0x12345678,
                "route_nodes": [0x55555555],  # Single intermediate node
                "snr_towards": [
                    -4.0,
                    -7.0,
                ],  # Two hops: source -> intermediate -> destination
                "route_back": [0x55555555],
                "snr_back": [-8.0, -5.0],
                "description": "Two-hop traceroute with return path",
            },
            {
                "from_node": 0x44444444,
                "to_node": 0x66666666,
                "route_nodes": [],  # Direct connection
                "snr_towards": [-4.0],
                "route_back": [],
                "snr_back": [],
                "description": "Direct single-hop traceroute",
            },
            {
                "from_node": 0x55555555,
                "to_node": 0x77777777,
                "route_nodes": [
                    0x88888888,
                    0xCCCCCCCC,  # Changed from 0x99999999 to avoid conflict with test
                    0xAAAAAAAA,
                    0xBBBBBBBB,
                ],  # Four intermediate nodes
                "snr_towards": [-8.0, -12.0, -15.0, -18.0, -22.0],  # Five total hops
                "route_back": [
                    0xBBBBBBBB,
                    0xAAAAAAAA,
                    0xCCCCCCCC,  # Changed from 0x99999999 to avoid conflict with test
                ],  # Partial return path
                "snr_back": [-20.0, -16.0, -13.0, -9.0],
                "description": "Five-hop traceroute with partial return path",
            },
        ]

        # Add enhanced traceroute scenarios for the traceroute graph test nodes
        traceroute_graph_scenarios = [
            {
                "from_node": 1819569748,  # Tomate Base
                "to_node": 2147483647,  # Central Hub Node
                "route_nodes": [555666777],  # Via Mesh Node Epsilon
                "snr_towards": [-15.2, -18.5],
                "route_back": [555666777],
                "snr_back": [-17.0, -14.8],
                "description": "Tomate to Central Hub via Epsilon",
            },
            {
                "from_node": 2147483647,  # Central Hub Node
                "to_node": 3735928559,  # Edge Node Alpha
                "route_nodes": [
                    111222333,
                    1234567890,
                ],  # Via Gateway Zeta and Relay Gamma
                "snr_towards": [-12.7, -25.8, -35.2],
                "route_back": [],
                "snr_back": [],
                "description": "Central Hub to Edge Alpha via Gateway and Relay",
            },
            {
                "from_node": 2147483647,  # Central Hub Node
                "to_node": 0xDDDDDDDD,  # Edge Node Beta (TEND)
                "route_nodes": [],  # Direct connection
                "snr_towards": [-18.5],
                "route_back": [],
                "snr_back": [],
                "description": "Direct connection Central Hub to Edge Beta",
            },
            {
                "from_node": 1234567890,  # Relay Station Gamma
                "to_node": 2147483647,  # Central Hub Node
                "route_nodes": [1819569748],  # Via Tomate Base
                "snr_towards": [-32.4, -15.2],
                "route_back": [1819569748],
                "snr_back": [-16.0, -30.8],
                "description": "Relay to Central Hub via Tomate Base",
            },
            {
                "from_node": 987654321,  # Remote Node Delta
                "to_node": 1234567890,  # Relay Station Gamma
                "route_nodes": [1819569748, 555666777],  # Via Tomate and Epsilon
                "snr_towards": [-45.0, -32.4, -28.9],
                "route_back": [],
                "snr_back": [],
                "description": "Remote Delta to Relay via Tomate and Epsilon",
            },
            {
                "from_node": 555666777,  # Mesh Node Epsilon
                "to_node": 987654321,  # Remote Node Delta
                "route_nodes": [
                    2147483647,
                    1234567890,
                    1819569748,
                ],  # Complex path via Central Hub, Relay, and Tomate
                "snr_towards": [-20.3, -25.8, -32.4, -45.0],
                "route_back": [1819569748, 1234567890, 2147483647],
                "snr_back": [-43.2, -31.0, -24.5, -19.8],
                "description": "Epsilon to Remote Delta via complex path",
            },
        ]

        # Combine all scenarios
        all_scenarios = scenarios + traceroute_graph_scenarios

        for _i, scenario in enumerate(all_scenarios):
            for hour in range(0, 12, 3):  # Every 3 hours for last 12 hours
                timestamp = now - (hour * 3600)

                # Calculate hop_limit based on route complexity
                total_hops = (
                    len(scenario["route_nodes"]) + 1
                )  # +1 for source to first intermediate or destination
                hop_limit = max(
                    1, 7 - total_hops
                )  # Start with 7, subtract consumed hops
                hop_start = 7  # Standard starting hop limit

                # Create traceroute using the new method
                traceroute = self.create_test_packet(
                    packet_id=packet_id,
                    from_node_id=scenario["from_node"],
                    to_node_id=scenario["to_node"],
                    portnum=70,  # TRACEROUTE_APP
                    portnum_name="TRACEROUTE_APP",
                    timestamp=timestamp,
                    hop_limit=hop_limit,
                    hop_start=hop_start,
                    payload_data=scenario,  # Pass the scenario data for traceroute encoding
                )

                traceroutes.append(traceroute)
                packet_id += 1

        return traceroutes
