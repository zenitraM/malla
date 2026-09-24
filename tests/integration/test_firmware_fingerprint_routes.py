"""Firmware estimate and same-MAC linking on the node page, nodes API and service."""

import os
import sqlite3
import tempfile
import time

import pytest

from malla.config import AppConfig, _clear_config_cache
from malla.fingerprint import (
    NODE_FINGERPRINT_TABLE_SQL,
    NODE_FINGERPRINT_UPSERT_SQL,
    FirmwareEvidence,
    evidence_row,
)
from malla.services.node_service import NodeService
from malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures

ALPHA = 1128074276  # fixture node "Test Gateway Alpha", MAC 24:6f:28:43:45:67
ALPHA_MAC = "24:6f:28:43:45:67"
REKEYED = 0x0AA479BC  # the same radio after a 2.8 upgrade (new node number)


@pytest.fixture()
def fp_client():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    DatabaseFixtures().create_test_database(tmp.name)

    now = time.time()
    conn = sqlite3.connect(tmp.name)
    conn.execute(NODE_FINGERPRINT_TABLE_SQL)
    # ALPHA: reported version + consistent fingerprint
    conn.execute(
        NODE_FINGERPRINT_UPSERT_SQL,
        evidence_row(
            ALPHA,
            FirmwareEvidence(
                nodeinfo_count=3,
                has_public_key=True,
                has_unmessagable_field=True,
                relay_self_count=12,
                hop_start_set_count=40,
                hop_start_mask=0b1000,
                firmware_version="2.7.26.54e0d8d",
                firmware_version_at=now - 3600,
            ),
            now,
        ),
    )
    # REKEYED: same MAC as ALPHA, signs its packets (2.8)
    conn.execute(
        """
        INSERT INTO node_info (node_id, hex_id, long_name, short_name, hw_model, role,
                               is_licensed, mac_address, first_seen, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            REKEYED,
            f"!{REKEYED:08x}",
            "Test Gateway Alpha",
            "TGA",
            "TBEAM",
            "CLIENT",
            ALPHA_MAC,
            now - 600,
            now - 60,
        ),
    )
    conn.execute(
        NODE_FINGERPRINT_UPSERT_SQL,
        evidence_row(
            REKEYED,
            FirmwareEvidence(
                nodeinfo_count=1,
                has_public_key=True,
                has_unmessagable_field=True,
                id_from_public_key=True,
                mac_mismatch=True,
                relay_self_count=4,
                xeddsa_signed_count=2,
                hop_start_set_count=10,
            ),
            now,
        ),
    )
    conn.commit()
    conn.close()

    _clear_config_cache()
    app = create_app(AppConfig(database_file=tmp.name))
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        _clear_config_cache()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def test_node_page_shows_reported_firmware_and_rekeyed_sibling(fp_client):
    html = fp_client.get(f"/node/{ALPHA}").get_data(as_text=True)
    assert "Firmware Version:" in html
    assert "2.7.26.54e0d8d" in html
    assert "reported 20" in html
    assert "Same Device:" in html
    assert f"!{REKEYED:08x}" in html
    assert "newer</span> id" in html or "newer id" in html.replace("</span>", "")


def test_node_page_shows_fingerprint_band_and_older_sibling(fp_client):
    html = fp_client.get(f"/node/{REKEYED}").get_data(as_text=True)
    assert "≥ 2.8" in html
    assert ">estimated<" in html
    assert "XEdDSA" in html
    assert "2.8+" in html
    assert f"!{ALPHA:08x}" in html
    assert "older" in html


def test_node_page_without_evidence_still_renders(fp_client):
    # Another fixture node with no fingerprint row and a unique MAC
    html = fp_client.get("/node/1128074277").get_data(as_text=True)
    assert "Firmware Version:" in html
    assert "Unknown" in html
    assert "no evidence yet" in html
    assert "Same Device:" not in html


def test_nodes_api_carries_firmware_label(fp_client):
    data = fp_client.get("/api/nodes?limit=500").get_json()
    by_id = {n["node_id"]: n for n in data["nodes"]}
    assert by_id[ALPHA]["firmware_label"] == "2.7.26.54e0d8d"
    assert by_id[ALPHA]["firmware_source"] == "reported"
    assert by_id[REKEYED]["firmware_label"] == "≥ 2.8"
    assert by_id[REKEYED]["firmware_source"] == "fingerprint"
    assert isinstance(by_id[REKEYED]["firmware_reasons"], list)
    # raw evidence columns are not leaked into the API payload
    assert "relay_self_count" not in by_id[ALPHA]
    unknown = next(n for n in data["nodes"] if n["node_id"] not in (ALPHA, REKEYED))
    assert unknown["firmware_label"] == "Unknown"


def test_nodes_table_endpoint_carries_firmware_label(fp_client):
    data = fp_client.get("/api/nodes/data?limit=500&page=1").get_json()
    by_id = {n["node_id"]: n for n in data["data"]}
    assert by_id[ALPHA]["firmware_label"] == "2.7.26.54e0d8d"
    assert by_id[ALPHA]["firmware_source"] == "reported"
    assert by_id[REKEYED]["firmware_label"] == "≥ 2.8"
    assert by_id[REKEYED]["firmware_reasons"]
    assert "XEdDSA signature ×2 (2.8+)" in by_id[REKEYED]["firmware_evidence"]


def test_hover_card_api_exposes_firmware_version(fp_client):
    alpha = fp_client.get(f"/api/node/{ALPHA}/info").get_json()["node"]
    assert alpha["firmware_version"] == "2.7.26.54e0d8d"
    assert alpha["firmware_source"] == "reported"
    rekeyed = fp_client.get(f"/api/node/{REKEYED}/info").get_json()["node"]
    assert rekeyed["firmware_version"] == "≥ 2.8"
    unknown = fp_client.get("/api/node/1128074277/info").get_json()["node"]
    assert "firmware_version" not in unknown


def test_node_service_exposes_firmware_and_same_mac(fp_client):
    info = NodeService.get_node_info(ALPHA)
    assert info["firmware"]["label"] == "2.7.26.54e0d8d"
    siblings = info["same_mac_nodes"]
    assert [s["node_id"] for s in siblings] == [REKEYED]
    assert siblings[0]["relation"] == "newer"
    assert info["node"]["mac_address"] == ALPHA_MAC


def test_firmware_distribution_api(fp_client):
    import malla.database.repositories as repositories

    repositories._firmware_distribution_cache.clear()
    data = fp_client.get("/api/firmware-distribution?days=30").get_json()
    assert data["days"] == 30
    assert data["total_nodes"] >= 1
    by_key = {b["key"]: b for b in data["buckets"]}
    # ALPHA has recent fixture packets and a reported 2.7.26 -> 2.7.8 segment
    assert by_key["2.7.8"]["reported"] >= 1
    assert by_key["2.7.8"]["label"] == "≥ 2.7.8"
    assert ".x" not in by_key["2.7.8"]["label"]
    # every other fixture node has no fingerprint -> Unknown
    assert by_key["unknown"]["other"] >= 1
    assert by_key["unknown"]["label"] == "Unknown"
    # newest first, Unknown last
    assert data["buckets"][-1]["key"] == "unknown"
    assert sum(b["count"] for b in data["buckets"]) == data["total_nodes"]
    # clamped window
    assert (
        fp_client.get("/api/firmware-distribution?days=9999").get_json()["days"] == 90
    )


def test_dashboard_page_has_firmware_chart(fp_client):
    html = fp_client.get("/").get_data(as_text=True)
    assert 'id="firmwareDistributionCanvas"' in html
    assert "/api/firmware-distribution" in html
    # firmware / hardware toggle on the same card
    assert 'id="distributionModeButtons"' in html
    assert 'data-mode="hardware"' in html
    assert "/api/hardware-distribution" in html
    assert 'id="firmwareDistributionExpand"' in html


def test_hardware_distribution_api(fp_client):
    import malla.database.repositories as repositories

    repositories._hardware_distribution_cache.clear()
    data = fp_client.get("/api/hardware-distribution?days=30").get_json()
    assert data["days"] == 30
    assert data["total_nodes"] >= 1
    assert sum(b["count"] for b in data["buckets"]) == data["total_nodes"]
    labels = [b["label"] for b in data["buckets"]]
    assert "TBEAM" in labels  # fixture hardware
    kinds = {b["kind"] for b in data["buckets"]}
    assert kinds <= {"hardware", "other", "unknown"}
    hardware = [b for b in data["buckets"] if b["kind"] == "hardware"]
    assert [b["count"] for b in hardware] == sorted(
        (b["count"] for b in hardware), reverse=True
    )
    assert data["models"] >= len(hardware)

    # a large `top` lists every model with no Other bucket
    full = fp_client.get("/api/hardware-distribution?days=30&top=500").get_json()
    assert not [b for b in full["buckets"] if b["kind"] == "other"]
    assert (
        len([b for b in full["buckets"] if b["kind"] == "hardware"]) == full["models"]
    )

    # a small `top` folds the tail into one Other bucket
    small = fp_client.get("/api/hardware-distribution?days=30&top=1").get_json()
    assert len([b for b in small["buckets"] if b["kind"] == "hardware"]) == 1
    other = [b for b in small["buckets"] if b["kind"] == "other"]
    assert other and other[0]["label"].startswith("Other (")
    assert sum(b["count"] for b in small["buckets"]) == data["total_nodes"]
