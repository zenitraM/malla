"""Unit tests for malla.fingerprint (pure firmware-fingerprint logic)."""

import sqlite3
import zlib
from types import SimpleNamespace

from meshtastic import config_pb2, mesh_pb2, mqtt_pb2, portnums_pb2

from malla.fingerprint import (
    NODE_FINGERPRINT_ADDED_COLUMNS,
    NODE_FINGERPRINT_TABLE_SQL,
    NODE_FINGERPRINT_UPSERT_SQL,
    FirmwareEvidence,
    data_has_xeddsa_signature,
    distribution_segment,
    ensure_node_fingerprint_table,
    estimate,
    evidence_row,
    observe_map_report,
    observe_packet,
    observe_user,
    parse_version,
    relay_marker_for,
    segment_label,
    summarize_distribution,
    telemetry_has_soil_water,
)

NODE = 0x0400CE8C
PUBKEY = bytes(range(32))


def _signed_data(portnum=portnums_pb2.PortNum.NODEINFO_APP) -> bytes:
    """Serialized Data with the 2.8 xeddsa_signature (tag 10, 64 bytes) appended."""
    data = mesh_pb2.Data()
    data.portnum = portnum
    data.payload = b"payload"
    data.bitfield = 1
    return data.SerializeToString() + bytes([0x52, 64]) + bytes(64)


def _user(node_id=NODE, public_key=b"", unmessagable=None, macaddr=None, role=None):
    user = mesh_pb2.User()
    user.id = f"!{node_id:08x}"
    user.long_name = "Test"
    user.public_key = public_key
    if unmessagable is not None:
        user.is_unmessagable = unmessagable
    if macaddr is not None:
        user.macaddr = macaddr
    if role is not None:
        user.role = role
    return user


class TestWireHelpers:
    def test_relay_marker_uses_last_byte_and_maps_zero_to_ff(self):
        assert relay_marker_for(0x1234AB) == 0xAB
        assert relay_marker_for(0x9EA1F700) == 0xFF

    def test_detects_64_byte_signature_on_tag_10(self):
        assert data_has_xeddsa_signature(_signed_data()) is True

    def test_ignores_unsigned_data_and_wrong_length(self):
        plain = mesh_pb2.Data(portnum=1, payload=b"x").SerializeToString()
        assert data_has_xeddsa_signature(plain) is False
        # tag 10 but only 8 bytes: not a signature
        assert data_has_xeddsa_signature(plain + bytes([0x52, 8]) + bytes(8)) is False

    def test_malformed_bytes_never_raise(self):
        assert data_has_xeddsa_signature(b"\xff\xff\xff") is False
        assert data_has_xeddsa_signature(b"") is False
        assert data_has_xeddsa_signature(None) is False

    def test_parse_version(self):
        assert parse_version("2.7.15.567b8ea") == (2, 7, 15)
        assert parse_version("2.8.0") == (2, 8, 0)
        assert parse_version("2.6") == (2, 6, 0)
        assert parse_version("garbage") is None
        assert parse_version("") is None


class TestObservers:
    def test_first_hop_packet_with_own_relay_byte_counts_as_relay_self(self):
        ev = FirmwareEvidence()
        observe_packet(
            ev, NODE, to_node_id=0xFFFFFFFF, hop_start=3, hop_limit=3, relay_node=0x8C
        )
        assert ev.relay_self_count == 1
        assert ev.relay_none_count == 0
        assert ev.hop_start_set_count == 1
        assert ev.hop_start_mask == 1 << 3

    def test_node_ending_in_zero_writes_ff(self):
        ev = FirmwareEvidence()
        observe_packet(
            ev,
            0x9EA1F700,
            to_node_id=0xFFFFFFFF,
            hop_start=3,
            hop_limit=3,
            relay_node=0xFF,
        )
        assert ev.relay_self_count == 1

    def test_first_hop_without_relay_byte_counts_as_relay_none(self):
        ev = FirmwareEvidence()
        observe_packet(ev, NODE, to_node_id=1, hop_start=3, hop_limit=3, relay_node=0)
        observe_packet(
            ev, NODE, to_node_id=1, hop_start=3, hop_limit=3, relay_node=None
        )
        assert ev.relay_none_count == 2

    def test_relayed_packets_and_foreign_relay_bytes_are_ignored(self):
        ev = FirmwareEvidence()
        # hop_limit already decremented: not the first hop
        observe_packet(ev, NODE, to_node_id=1, hop_start=3, hop_limit=2, relay_node=0)
        # first hop but some other node's byte (zero-cost-hop router)
        observe_packet(
            ev, NODE, to_node_id=1, hop_start=3, hop_limit=3, relay_node=0x11
        )
        assert ev.relay_self_count == 0
        assert ev.relay_none_count == 0

    def test_hop_start_zero_is_counted_separately(self):
        ev = FirmwareEvidence()
        observe_packet(ev, NODE, to_node_id=1, hop_start=0, hop_limit=3, relay_node=0)
        observe_packet(
            ev, NODE, to_node_id=1, hop_start=None, hop_limit=3, relay_node=0
        )
        assert ev.hop_start_zero_count == 2
        assert ev.hop_start_set_count == 0

    def test_signature_in_data_bytes_increments_counter(self):
        ev = FirmwareEvidence()
        observe_packet(
            ev,
            NODE,
            to_node_id=0xFFFFFFFF,
            hop_start=3,
            hop_limit=3,
            relay_node=0x8C,
            data_bytes=_signed_data(),
        )
        assert ev.xeddsa_signed_count == 1

    def test_user_public_key_and_crc32_identity(self):
        node_id = zlib.crc32(PUBKEY) & 0xFFFFFFFF
        ev = FirmwareEvidence()
        observe_user(ev, node_id, _user(node_id, public_key=PUBKEY))
        assert ev.nodeinfo_count == 1
        assert ev.has_public_key is True
        assert ev.id_from_public_key is True

    def test_user_public_key_without_crc_match(self):
        ev = FirmwareEvidence()
        observe_user(ev, NODE, _user(public_key=PUBKEY))
        assert ev.has_public_key is True
        assert ev.id_from_public_key is False

    def test_user_unmessagable_presence_is_detected_even_when_false(self):
        ev = FirmwareEvidence()
        observe_user(ev, NODE, _user(unmessagable=False))
        assert ev.has_unmessagable_field is True
        ev2 = FirmwareEvidence()
        observe_user(ev2, NODE, _user())
        assert ev2.has_unmessagable_field is False

    def test_user_mac_mismatch(self):
        ev = FirmwareEvidence()
        observe_user(
            ev, NODE, _user(macaddr=bytes([0x24, 0x6F, 0x04, 0x00, 0xCE, 0x8C]))
        )
        assert ev.mac_mismatch is False
        ev2 = FirmwareEvidence()
        observe_user(
            ev2, NODE, _user(macaddr=bytes([0x24, 0x6F, 0x11, 0x22, 0x33, 0x44]))
        )
        assert ev2.mac_mismatch is True

    def test_map_report_records_version(self):
        ev = FirmwareEvidence()
        report = mqtt_pb2.MapReport()
        report.firmware_version = "2.7.15.567b8ea"
        observe_map_report(ev, report, 1_700_000_000.0)
        assert ev.firmware_version == "2.7.15.567b8ea"
        assert ev.firmware_version_at == 1_700_000_000.0
        observe_map_report(ev, mqtt_pb2.MapReport(), 1_700_000_001.0)
        assert ev.firmware_version == "2.7.15.567b8ea"


class TestEstimate:
    def test_no_evidence_is_unknown(self):
        verdict = estimate(FirmwareEvidence())
        assert verdict["label"] == "Unknown"
        assert verdict["source"] == "none"
        assert verdict["evidence"] == ["no evidence yet"]

    def test_evidence_tags_are_terse(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            xeddsa_signed_count=2,
            id_from_public_key=True,
            hop_start_mask=0b10101000,
        )
        verdict = estimate(ev)
        assert verdict["evidence"] == [
            "XEdDSA signature ×2 (2.8+)",
            "node id = CRC32(public key) (2.8+)",
            "variable hop limit (2.8 trait)",
        ]
        assert verdict["evidence_items"][0] == {
            "trait": "XEdDSA signature ×2",
            "range": "2.8+",
        }
        assert all(len(tag) <= 40 for tag in verdict["evidence"])
        assert len(verdict["reasons"]) == len(verdict["evidence"])

    def test_every_band_carries_a_range(self):
        cases = [
            (
                FirmwareEvidence(
                    nodeinfo_count=1, has_public_key=True, has_unmessagable_field=True
                ),
                "CLIENT_BASE",
                "2.7.8+",
            ),
            (
                FirmwareEvidence(
                    nodeinfo_count=1, has_public_key=True, has_unmessagable_field=True
                ),
                None,
                "2.6.8+",
            ),
            (
                FirmwareEvidence(
                    nodeinfo_count=1, has_public_key=True, relay_self_count=4
                ),
                None,
                "< 2.6.8",
            ),
            (
                FirmwareEvidence(
                    nodeinfo_count=1, has_public_key=True, relay_none_count=20
                ),
                None,
                "< 2.6",
            ),
            (
                FirmwareEvidence(nodeinfo_count=1, relay_none_count=20),
                None,
                "< 2.5 or PKI off",
            ),
        ]
        for ev, role, expected_range in cases:
            ranges = [
                item["range"] for item in estimate(ev, role=role)["evidence_items"]
            ]
            assert expected_range in ranges, (ranges, expected_range)
        soft = estimate(
            FirmwareEvidence(hop_start_zero_count=50), hw_model="PRIVATE_HW"
        )
        assert soft["evidence_items"] == [
            {"trait": "PRIVATE_HW, no hop_start", "range": "not a radio"}
        ]

    def test_reported_evidence_tag_leads(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            has_unmessagable_field=True,
            firmware_version="2.7.15.567b8ea",
            firmware_version_at=86400.0,
        )
        verdict = estimate(ev, now=2 * 86400.0)
        assert verdict["evidence"][0] == "MapReport 1970-01-02 (exact)"
        stale = estimate(
            FirmwareEvidence(
                nodeinfo_count=1,
                has_public_key=True,
                xeddsa_signed_count=1,
                firmware_version="2.7.15.567b8ea",
                firmware_version_at=1.0,
            ),
            now=100.0,
        )
        assert stale["evidence"][-1] == "reported 2.7.15.567b8ea earlier (superseded)"

    def test_signature_means_2_8(self):
        ev = FirmwareEvidence(
            xeddsa_signed_count=2, nodeinfo_count=1, has_public_key=True
        )
        verdict = estimate(ev)
        assert verdict["label"] == "≥ 2.8"
        assert verdict["source"] == "fingerprint"
        assert any("XEdDSA" in r for r in verdict["reasons"])

    def test_crc32_identity_means_2_8(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1, has_public_key=True, id_from_public_key=True
        )
        assert estimate(ev)["label"] == "≥ 2.8"

    def test_client_base_role_means_2_7_8(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1, has_public_key=True, has_unmessagable_field=True
        )
        assert estimate(ev, role="CLIENT_BASE")["label"] == "≥ 2.7.8"

    def test_unmessagable_field_means_2_6_8(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1, has_public_key=True, has_unmessagable_field=True
        )
        assert estimate(ev, role="CLIENT")["label"] == "≥ 2.6.8"

    def test_relay_self_without_unmessagable_is_early_2_6(self):
        ev = FirmwareEvidence(nodeinfo_count=1, has_public_key=True, relay_self_count=5)
        assert estimate(ev)["label"] == "2.6.0 – 2.6.7"
        # without any NodeInfo we cannot bound it from above
        ev = FirmwareEvidence(relay_self_count=5)
        assert estimate(ev)["label"] == "≥ 2.6"

    def test_public_key_without_relay_node_is_2_5(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1, has_public_key=True, relay_none_count=20
        )
        assert estimate(ev)["label"] == "2.5.x"
        ev = FirmwareEvidence(nodeinfo_count=1, has_public_key=True)
        assert estimate(ev)["label"] == "2.5.0 – 2.6.7"

    def test_no_public_key_is_pre_2_5(self):
        ev = FirmwareEvidence(nodeinfo_count=1, relay_none_count=20)
        assert estimate(ev)["label"] == "< 2.5"
        ev = FirmwareEvidence(nodeinfo_count=1)
        assert estimate(ev)["label"] == "< 2.5 or PKI disabled"

    def test_positive_relay_evidence_beats_a_few_stripped_packets(self):
        # An old gateway may strip relay_node from some uplinks; that must not
        # drag a 2.6+ node down.
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            relay_self_count=3,
            relay_none_count=50,
        )
        assert estimate(ev)["label"] == "2.6.0 – 2.6.7"

    def test_software_client(self):
        ev = FirmwareEvidence(hop_start_zero_count=50, nodeinfo_count=3)
        verdict = estimate(ev, hw_model="PRIVATE_HW")
        assert verdict["label"] == "Software client"
        # a radio with the same traffic pattern is just old/unknown, not software
        assert estimate(ev, hw_model="HELTEC_V3")["label"] != "Software client"

    def test_variable_hop_limits_is_only_a_hint(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            has_unmessagable_field=True,
            hop_start_mask=(1 << 3) | (1 << 5) | (1 << 7),
        )
        verdict = estimate(ev)
        assert verdict["label"] == "≥ 2.6.8"
        assert any("hop limit" in r for r in verdict["reasons"])

    def test_reported_version_wins_when_consistent(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            has_unmessagable_field=True,
            firmware_version="2.7.15.567b8ea",
            firmware_version_at=1_000.0,
        )
        verdict = estimate(ev, now=2_000.0)
        assert verdict["label"] == "2.7.15.567b8ea"
        assert verdict["source"] == "reported"
        assert verdict["estimated_label"] == "≥ 2.6.8"
        assert verdict["reported_at_str"] == "1970-01-01"

    def test_newer_traits_override_stale_report(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            xeddsa_signed_count=1,
            firmware_version="2.7.15.567b8ea",
            firmware_version_at=1_000.0,
        )
        verdict = estimate(ev, now=2_000.0)
        assert verdict["label"] == "≥ 2.8"
        assert verdict["source"] == "fingerprint"
        assert any("last reported 2.7.15" in r for r in verdict["reasons"])

    def test_old_report_is_flagged(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            firmware_version="2.6.4.b89355f",
            firmware_version_at=0.0,
        )
        verdict = estimate(ev, now=400 * 86400.0)
        assert verdict["label"] == "2.6.4.b89355f"
        assert "old" in verdict["reasons"][0]


class TestStorage:
    def test_merge_matches_sql_upsert_semantics(self):
        a = FirmwareEvidence(
            nodeinfo_count=1,
            relay_self_count=2,
            has_public_key=True,
            hop_start_mask=0b1000,
            firmware_version="2.7.15",
            firmware_version_at=10.0,
        )
        b = FirmwareEvidence(
            nodeinfo_count=2,
            relay_self_count=3,
            has_unmessagable_field=True,
            hop_start_mask=0b0100,
            firmware_version="2.7.26",
            firmware_version_at=20.0,
        )
        a.merge(b)
        assert (a.nodeinfo_count, a.relay_self_count) == (3, 5)
        assert a.has_public_key and a.has_unmessagable_field
        assert a.hop_start_mask == 0b1100
        assert a.firmware_version == "2.7.26"
        # an older report never overwrites a newer one
        a.merge(FirmwareEvidence(firmware_version="2.6.0", firmware_version_at=5.0))
        assert a.firmware_version == "2.7.26"

    def test_upsert_accumulates_and_round_trips(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(NODE_FINGERPRINT_TABLE_SQL)
        first = FirmwareEvidence(
            nodeinfo_count=1,
            relay_self_count=2,
            has_public_key=True,
            firmware_version="2.7.15",
            firmware_version_at=10.0,
        )
        second = FirmwareEvidence(
            relay_self_count=1,
            xeddsa_signed_count=1,
            hop_start_mask=0b10,
            firmware_version="2.6.0",
            firmware_version_at=5.0,
        )
        conn.execute(NODE_FINGERPRINT_UPSERT_SQL, evidence_row(NODE, first, 100.0))
        conn.execute(NODE_FINGERPRINT_UPSERT_SQL, evidence_row(NODE, second, 200.0))
        row = conn.execute(
            "SELECT * FROM node_fingerprint WHERE node_id = ?", (NODE,)
        ).fetchone()
        ev = FirmwareEvidence.from_row(row)
        assert ev.nodeinfo_count == 1
        assert ev.relay_self_count == 3
        assert ev.xeddsa_signed_count == 1
        assert ev.has_public_key is True
        assert ev.hop_start_mask == 0b10
        assert ev.firmware_version == "2.7.15"  # newer report kept
        assert row["updated_at"] == 200.0
        assert estimate(ev, now=1_000.0)["label"] == "≥ 2.8"

    def test_from_row_accepts_dict_and_none(self):
        assert FirmwareEvidence.from_row(None) == FirmwareEvidence()
        ev = FirmwareEvidence.from_row(
            {"nodeinfo_count": 2, "has_public_key": 1, "unrelated": "x"}
        )
        assert ev.nodeinfo_count == 2 and ev.has_public_key is True


def test_role_enum_name_used_by_estimate_exists():
    # Guard: the tier rule keys off the enum *name* the capture daemon stores.
    assert config_pb2.Config.DeviceConfig.Role.Name(12) == "CLIENT_BASE"


def test_simple_namespace_user_is_tolerated():
    # Objects without a protobuf descriptor (e.g. test doubles) never crash.
    ev = FirmwareEvidence()
    observe_user(ev, NODE, SimpleNamespace(public_key=b"", macaddr=b""))
    assert ev.nodeinfo_count == 1


class TestDistribution:
    def _verdict(self, label, source="fingerprint", reported=None):
        return {"label": label, "source": source, "reported_version": reported}

    def test_reported_versions_land_on_the_highest_rung_reached(self):
        cases = {
            "2.8.1": "2.8.1",
            "2.8.0": "2.8",
            "2.7.26.54e0d8d": "2.7.8",
            "2.7.8": "2.7.8",
            "2.7.5": "2.6.8",
            "2.6.11.60ec05e": "2.6.8",
            "2.6.4.b89355f": "2.6",
            "2.5.20": "2.5",
            "2.4.3": "lt2.5",
        }
        for version, key in cases.items():
            assert distribution_segment(
                self._verdict(version, "reported", version)
            ) == (
                key,
                "reported",
            ), version

    def test_estimates_map_to_rungs(self):
        assert distribution_segment(self._verdict("≥ 2.8.1")) == ("2.8.1", "estimated")
        assert distribution_segment(self._verdict("≥ 2.8")) == ("2.8", "estimated")
        assert distribution_segment(self._verdict("≥ 2.7.8")) == ("2.7.8", "estimated")
        assert distribution_segment(self._verdict("≥ 2.6.8")) == ("2.6.8", "estimated")
        assert distribution_segment(self._verdict("≥ 2.6")) == ("2.6", "estimated")
        assert distribution_segment(self._verdict("2.6.0 – 2.6.7")) == (
            "2.6",
            "estimated",
        )
        assert distribution_segment(self._verdict("2.5.0 – 2.6.7")) == (
            "2.5",
            "estimated",
        )
        assert distribution_segment(self._verdict("< 2.5 or PKI disabled")) == (
            "lt2.5",
            "estimated",
        )
        assert distribution_segment(self._verdict("Software client")) == (
            "software",
            "other",
        )
        assert distribution_segment(self._verdict("Unknown", "none")) == (
            "unknown",
            "other",
        )

    def test_labels_are_a_non_overlapping_ladder(self):
        labels = [
            segment_label(k)
            for k in (
                "2.8",
                "2.7.8",
                "2.6.8",
                "2.6",
                "2.5",
                "lt2.5",
                "software",
                "unknown",
            )
        ]
        assert labels == [
            "≥ 2.8.0",
            "≥ 2.7.8",
            "≥ 2.6.8",
            "≥ 2.6.0",
            "≥ 2.5.0",
            "< 2.5",
            "Software client",
            "Unknown",
        ]
        assert all(".x" not in label and "–" not in label for label in labels)

    def test_summary_merges_reported_and_estimated_per_rung(self):
        verdicts = (
            [self._verdict("Unknown", "none")] * 3
            + [self._verdict("≥ 2.6.8")] * 5
            + [self._verdict("2.7.15.567b8ea", "reported", "2.7.15.567b8ea")] * 2
            + [self._verdict("≥ 2.7.8")]
            + [self._verdict("≥ 2.8")] * 4
            + [self._verdict("2.6.4.b89355f", "reported", "2.6.4.b89355f")]
            + [self._verdict("2.6.0 – 2.6.7")]
            + [self._verdict("Software client")]
            + [self._verdict("< 2.5")]
        )
        summary = summarize_distribution(verdicts)
        assert [e["key"] for e in summary] == [
            "2.8",
            "2.7.8",
            "2.6.8",
            "2.6",
            "lt2.5",
            "software",
            "unknown",
        ]
        by = {e["key"]: e for e in summary}
        assert by["2.7.8"] == {
            "key": "2.7.8",
            "label": "≥ 2.7.8",
            "count": 3,
            "reported": 2,
            "estimated": 1,
            "other": 0,
        }
        assert by["2.6"] == {
            "key": "2.6",
            "label": "≥ 2.6.0",
            "count": 2,
            "reported": 1,
            "estimated": 1,
            "other": 0,
        }
        assert by["unknown"]["other"] == 3
        assert summarize_distribution([]) == []


class TestFirmware281Markers:
    def test_soil_water_telemetry_detected_on_the_wire(self):
        from meshtastic import telemetry_pb2

        plain = telemetry_pb2.Telemetry()
        plain.device_metrics.battery_level = 90
        assert telemetry_has_soil_water(plain.SerializeToString()) is False
        # Telemetry.soil_water_metrics is tag 11 (post-2.8.0); fake a 3-byte message
        with_soil = plain.SerializeToString() + bytes([0x5A, 3, 0x08, 0x01, 0x10])
        assert telemetry_has_soil_water(with_soil) is True
        assert telemetry_has_soil_water(b"") is False

    def test_observe_packet_counts_281_markers(self):
        ev = FirmwareEvidence()
        observe_packet(
            ev, NODE, to_node_id=1, hop_start=3, hop_limit=3, relay_node=0x8C, aead=True
        )
        observe_packet(
            ev,
            NODE,
            to_node_id=1,
            hop_start=3,
            hop_limit=3,
            relay_node=0x8C,
            portnum=38,
        )
        observe_packet(
            ev,
            NODE,
            to_node_id=1,
            hop_start=3,
            hop_limit=3,
            relay_node=0x8C,
            portnum=67,
            telemetry_bytes=bytes([0x5A, 2, 0x08, 0x01]),
        )
        assert (ev.aead_count, ev.paging_count, ev.soil_water_count) == (1, 1, 1)

    def test_281_markers_outrank_28_markers(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1, has_public_key=True, aead_count=3, xeddsa_signed_count=2
        )
        verdict = estimate(ev)
        assert verdict["label"] == "≥ 2.8.1"
        assert verdict["evidence"][0] == "AEAD channel ×3 (2.8.1+)"
        assert "XEdDSA signature ×2 (2.8+)" in verdict["evidence"]
        for field in ("paging_count", "soil_water_count"):
            assert estimate(FirmwareEvidence(**{field: 1}))["label"] == "≥ 2.8.1"

    def test_reported_281_wins_over_28_band(self):
        ev = FirmwareEvidence(
            nodeinfo_count=1,
            has_public_key=True,
            xeddsa_signed_count=1,
            firmware_version="2.8.1.abc1234",
            firmware_version_at=10.0,
        )
        verdict = estimate(ev, now=20.0)
        assert verdict["label"] == "2.8.1.abc1234"
        assert verdict["source"] == "reported"

    def test_upsert_adds_281_counters(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(NODE_FINGERPRINT_TABLE_SQL)
        conn.execute(
            NODE_FINGERPRINT_UPSERT_SQL,
            evidence_row(NODE, FirmwareEvidence(aead_count=1, paging_count=2), 1.0),
        )
        conn.execute(
            NODE_FINGERPRINT_UPSERT_SQL,
            evidence_row(NODE, FirmwareEvidence(aead_count=2, soil_water_count=1), 2.0),
        )
        row = conn.execute(
            "SELECT * FROM node_fingerprint WHERE node_id = ?", (NODE,)
        ).fetchone()
        ev = FirmwareEvidence.from_row(row)
        assert (ev.aead_count, ev.paging_count, ev.soil_water_count) == (3, 2, 1)

    def test_migration_adds_missing_columns_to_an_older_table(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE node_fingerprint (
                node_id INTEGER PRIMARY KEY,
                nodeinfo_count INTEGER NOT NULL DEFAULT 0,
                has_public_key INTEGER NOT NULL DEFAULT 0,
                has_unmessagable_field INTEGER NOT NULL DEFAULT 0,
                id_from_public_key INTEGER NOT NULL DEFAULT 0,
                mac_mismatch INTEGER NOT NULL DEFAULT 0,
                relay_self_count INTEGER NOT NULL DEFAULT 0,
                relay_none_count INTEGER NOT NULL DEFAULT 0,
                xeddsa_signed_count INTEGER NOT NULL DEFAULT 0,
                hop_start_zero_count INTEGER NOT NULL DEFAULT 0,
                hop_start_set_count INTEGER NOT NULL DEFAULT 0,
                hop_start_mask INTEGER NOT NULL DEFAULT 0,
                firmware_version TEXT,
                firmware_version_at REAL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute("INSERT INTO node_fingerprint (node_id, updated_at) VALUES (1, 0)")
        added = ensure_node_fingerprint_table(conn.cursor())
        assert added == [name for name, _ in NODE_FINGERPRINT_ADDED_COLUMNS]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(node_fingerprint)")}
        assert {"aead_count", "soil_water_count", "paging_count"} <= columns
        conn.execute(
            NODE_FINGERPRINT_UPSERT_SQL,
            evidence_row(1, FirmwareEvidence(aead_count=1), 1.0),
        )
        assert (
            conn.execute(
                "SELECT aead_count FROM node_fingerprint WHERE node_id = 1"
            ).fetchone()[0]
            == 1
        )
        assert ensure_node_fingerprint_table(conn.cursor()) == []
