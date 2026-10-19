"""Firmware 2.8 renumbering and coordinate-less positions on the map, node page and nodes API."""

import os
import sqlite3
import tempfile
import time
import zlib

import pytest
from meshtastic import mesh_pb2

from malla.config import AppConfig, _clear_config_cache
from malla.database import repositories
from malla.fingerprint import (
    NODE_FINGERPRINT_TABLE_SQL,
    NODE_FINGERPRINT_UPSERT_SQL,
    FirmwareEvidence,
    evidence_row,
)
from tests.fixtures.database_fixtures import DatabaseFixtures

DAY = 86400
PUBKEY = bytes(range(32, 64))
OLD = 0x11112222  # MAC-derived id, went quiet at the 2.8 upgrade
NEW = zlib.crc32(PUBKEY) & 0xFFFFFFFF  # the same radio since 2.8
NOFIX = 0x33334444  # newest position packet carries no coordinates
OLD2 = 0x55556666  # key says renumbered, but still transmitting → stays
NEW2 = 0x77778888

FIX_A = (25_000_000, 121_500_000)
FIX_B = (25_100_000, 121_600_000)
FIX_C = (24_900_000, 121_400_000)
FIX_D = (24_800_000, 121_300_000)


def _position(fix=None, when=0):
    pos = mesh_pb2.Position()
    if fix:
        pos.latitude_i, pos.longitude_i = fix
        pos.altitude = 10
    pos.time = int(when)
    return pos.SerializeToString()


def _add_node(conn, node_id, name, first_seen, last_updated, mac=None):
    conn.execute(
        """
        INSERT INTO node_info (node_id, hex_id, long_name, short_name, hw_model, role,
                               is_licensed, mac_address, first_seen, last_updated)
        VALUES (?, ?, ?, ?, 'TBEAM', 'CLIENT', 0, ?, ?, ?)
        """,
        (node_id, f"!{node_id:08x}", name, name[:4], mac, first_seen, last_updated),
    )


def _add_position(conn, node_id, ts, fix):
    conn.execute(
        """
        INSERT INTO packet_history
            (timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
             gateway_id, payload_length, raw_payload, processed_successfully)
        VALUES (?, 'msh/test', ?, 4294967295, 3, 'POSITION_APP', '!00000001', ?, ?, 1)
        """,
        (ts, node_id, 10, _position(fix, ts)),
    )


@pytest.fixture()
def client():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    DatabaseFixtures().create_test_database(tmp.name)
    now = time.time()
    conn = sqlite3.connect(tmp.name)
    conn.execute(NODE_FINGERPRINT_TABLE_SQL)

    _add_node(conn, OLD, "Rooftop", now - 30 * DAY, now - 10 * DAY, "aa:bb:cc:11:11:22")
    _add_node(conn, NEW, "Rooftop", now - 9 * DAY, now - 60, "aa:bb:cc:11:11:22")
    _add_node(conn, NOFIX, "Tracker", now - 20 * DAY, now - 60)
    _add_node(conn, OLD2, "Twin", now - 30 * DAY, now - DAY)
    _add_node(conn, NEW2, "Twin", now - 3 * DAY, now - 60)
    crc_old2 = NEW2  # pretend OLD2's key hashes to NEW2
    for node_id, ev in (
        (
            OLD,
            FirmwareEvidence(
                nodeinfo_count=2, has_public_key=True, public_key_crc32=NEW
            ),
        ),
        (
            NEW,
            FirmwareEvidence(
                nodeinfo_count=1,
                has_public_key=True,
                id_from_public_key=True,
                xeddsa_signed_count=3,
                public_key_crc32=NEW,
            ),
        ),
        (
            OLD2,
            FirmwareEvidence(
                nodeinfo_count=2, has_public_key=True, public_key_crc32=crc_old2
            ),
        ),
        (
            NEW2,
            FirmwareEvidence(
                nodeinfo_count=1,
                has_public_key=True,
                id_from_public_key=True,
                public_key_crc32=NEW2,
            ),
        ),
    ):
        conn.execute(NODE_FINGERPRINT_UPSERT_SQL, evidence_row(node_id, ev, now))

    _add_position(conn, OLD, now - 10 * DAY, FIX_A)  # stale: before NEW appeared
    _add_position(conn, NEW, now - 5 * DAY, FIX_B)
    _add_position(conn, NEW, now - 60, None)  # newest, but no coordinates
    _add_position(conn, NOFIX, now - 2 * DAY, FIX_C)
    _add_position(conn, NOFIX, now - 100, None)
    _add_position(conn, OLD2, now - DAY, FIX_D)  # after NEW2 appeared → not renumbered
    _add_position(conn, NEW2, now - 2 * DAY, None)  # 2.8 node that never shares a fix
    conn.commit()
    conn.close()

    _clear_config_cache()
    repositories._renumbered_cache = None
    from malla.web_ui import create_app

    app = create_app(AppConfig(database_file=tmp.name))
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        repositories._renumbered_cache = None
        _clear_config_cache()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def test_map_hides_old_id_and_uses_newest_fix(client):
    data = client.get("/api/locations").get_json()
    by_id = {loc["node_id"]: loc for loc in data["locations"]}
    assert OLD not in by_id, "the renumbered old id must not keep a stale marker"
    assert by_id[NEW]["latitude"] == pytest.approx(FIX_B[0] / 1e7)
    assert by_id[NEW]["timestamp"] == pytest.approx(time.time() - 5 * DAY, abs=5)
    assert by_id[NOFIX]["latitude"] == pytest.approx(FIX_C[0] / 1e7)
    assert by_id[NOFIX]["timestamp"] == pytest.approx(time.time() - 2 * DAY, abs=5)
    # a key-linked id that is still transmitting is not hidden
    assert OLD2 in by_id and by_id[OLD2]["latitude"] == pytest.approx(FIX_D[0] / 1e7)
    assert NEW2 not in by_id  # never shared coordinates


def test_explicit_node_ids_keep_old_id_for_historic_drawings(client):
    from malla.database.repositories import LocationRepository

    locations = LocationRepository.get_node_locations({"node_ids": [OLD, NEW]})
    assert {loc["node_id"] for loc in locations} == {OLD, NEW}


def test_old_node_page_points_at_successor(client):
    html = client.get(f"/node/{OLD}").get_data(as_text=True)
    assert 'id="renumbered-alert"' in html
    assert f'href="/node/{NEW}"' in html
    assert f"!{NEW:08x}" in html
    assert "linked by public key" in html
    assert 'id="position-hint-alert"' not in html


def test_new_node_page_lists_predecessor_and_fresh_position(client):
    html = client.get(f"/node/{NEW}").get_data(as_text=True)
    assert 'id="predecessor-alert"' in html
    assert f"!{OLD:08x}" in html
    assert 'id="renumbered-alert"' not in html
    # the coordinate-less newest packet must not blank the location card
    assert "Location Information" in html
    assert 'id="position-hint-alert"' not in html


def test_28_node_without_fix_gets_opt_in_hint(client):
    html = client.get(f"/node/{NEW2}").get_data(as_text=True)
    assert 'id="position-hint-alert"' in html
    assert "position precision" in html
    # OLD2 is still active, so it is not presented as this node's past identity
    assert 'id="predecessor-alert"' not in html
    html_old2 = client.get(f"/node/{OLD2}").get_data(as_text=True)
    assert 'id="renumbered-alert"' not in html_old2


def test_nodes_table_marks_renumbered_rows(client):
    data = client.get("/api/nodes/data?limit=500&page=1").get_json()
    by_id = {n["node_id"]: n for n in data["data"]}
    assert by_id[OLD]["renumbered_to"]["node_id"] == NEW
    assert by_id[OLD]["renumbered_to"]["hex_id"] == f"!{NEW:08x}"
    assert by_id[NEW]["renumbered_to"] is None
    assert by_id[OLD2]["renumbered_to"] is None
