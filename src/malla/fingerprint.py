"""Firmware fingerprinting for Meshtastic nodes.

Nodes never broadcast their firmware version, but each firmware generation
leaves traces in what it sends. This module turns those traces into a
version *band* ("≥ 2.8", "2.6.0 – 2.6.7", …). Markers, each verified
against the protobuf tag in which it first appeared:

* ``hop_start`` set at all                       → 2.3+
* NodeInfo ``User.public_key``                    → 2.5.0+
* own transmissions carry ``relay_node``          → 2.6.0+ (next-hop routing)
* NodeInfo ``User.is_unmessagable`` present       → 2.6.8+ (firmware always
  sets ``has_is_unmessagable`` once the field exists)
* role ``CLIENT_BASE``                            → 2.7.8+
* node number == CRC32(public key)                → 2.8.0+ (key-derived ids)
* ``Data.xeddsa_signature`` (64 bytes) on packets → 2.8.0+ (packet signing)
* AES-CCM (``use_aead``) channel traffic, ``PAGING_APP`` (38) or
  ``Telemetry.soil_water_metrics`` (tag 11)      → 2.8.1+

Positive evidence always wins over absence: an old gateway that strips
``relay_node`` cannot make a 2.6+ node look older, it can only leave it
unclassified. ``MAP_REPORT_APP`` packets carry an exact
``firmware_version`` and take precedence when they are at least as new as
what the fingerprint implies.

Only pure functions live here; the capture daemon and the web app supply the
storage.
"""

from __future__ import annotations

import sqlite3
import time
import zlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from typing import Any

BROADCAST_NODE_ID = 0xFFFFFFFF
XEDDSA_SIGNATURE_LEN = 64
DATA_XEDDSA_SIGNATURE_TAG = 10
TELEMETRY_SOIL_WATER_TAG = 11  # Telemetry.soil_water_metrics, protobufs after v2.8.0
PAGING_APP_PORTNUM = 38  # PortNum.PAGING_APP, protobufs after v2.8.0

# Evidence thresholds: a handful of first-hop packets is enough to prove the
# relay_node behaviour, while claiming its *absence* needs more packets.
MIN_RELAY_SELF_PACKETS = 3
MIN_RELAY_NONE_PACKETS = 10
MIN_SOFTWARE_CLIENT_PACKETS = 10
# A MapReport older than this may predate an upgrade; the fingerprint decides.
REPORTED_VERSION_MAX_AGE_SECONDS = 180 * 86400

SOFTWARE_CLIENT_HW_MODELS = frozenset({"PRIVATE_HW"})


@dataclass
class FirmwareEvidence:
    """Accumulated per-node observations. Counters add, flags OR, mask ORs."""

    nodeinfo_count: int = 0
    has_public_key: bool = False
    has_unmessagable_field: bool = False
    id_from_public_key: bool = False
    mac_mismatch: bool = False
    relay_self_count: int = 0
    relay_none_count: int = 0
    xeddsa_signed_count: int = 0
    hop_start_zero_count: int = 0
    hop_start_set_count: int = 0
    hop_start_mask: int = 0
    aead_count: int = 0
    soil_water_count: int = 0
    paging_count: int = 0
    firmware_version: str | None = None
    firmware_version_at: float | None = None

    def is_empty(self) -> bool:
        return not any(v for v in asdict(self).values())

    def merge(self, other: FirmwareEvidence) -> None:
        """Fold *other* into this evidence (same semantics as the SQL upsert)."""
        for name in COUNTER_FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for name in FLAG_FIELDS:
            setattr(self, name, getattr(self, name) or getattr(other, name))
        self.hop_start_mask |= other.hop_start_mask
        if other.firmware_version and (
            self.firmware_version_at is None
            or (other.firmware_version_at or 0) >= self.firmware_version_at
        ):
            self.firmware_version = other.firmware_version
            self.firmware_version_at = other.firmware_version_at

    @classmethod
    def from_row(cls, row: Any) -> FirmwareEvidence:
        """Build evidence from a ``node_fingerprint`` row (dict or sqlite3.Row)."""
        if row is None:
            return cls()
        keys = row.keys() if hasattr(row, "keys") else ()
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in keys:
                continue
            value = row[f.name]
            if f.type == "bool":
                value = bool(value)
            elif f.type == "int":
                value = int(value or 0)
            values[f.name] = value
        return cls(**values)


EVIDENCE_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(FirmwareEvidence))

COUNTER_FIELDS = (
    "nodeinfo_count",
    "relay_self_count",
    "relay_none_count",
    "xeddsa_signed_count",
    "hop_start_zero_count",
    "hop_start_set_count",
    "aead_count",
    "soil_water_count",
    "paging_count",
)
FLAG_FIELDS = (
    "has_public_key",
    "has_unmessagable_field",
    "id_from_public_key",
    "mac_mismatch",
)

NODE_FINGERPRINT_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS node_fingerprint (
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
        aead_count INTEGER NOT NULL DEFAULT 0,
        soil_water_count INTEGER NOT NULL DEFAULT 0,
        paging_count INTEGER NOT NULL DEFAULT 0,
        firmware_version TEXT,
        firmware_version_at REAL,
        updated_at REAL NOT NULL
    )
"""

# Merge-upsert: the capture daemon flushes *deltas*, so counters add up,
# flags stick once seen and the newest MapReport wins.
NODE_FINGERPRINT_UPSERT_SQL = """
    INSERT INTO node_fingerprint (
        node_id, nodeinfo_count, has_public_key, has_unmessagable_field,
        id_from_public_key, mac_mismatch, relay_self_count, relay_none_count,
        xeddsa_signed_count, hop_start_zero_count, hop_start_set_count,
        hop_start_mask, aead_count, soil_water_count, paging_count,
        firmware_version, firmware_version_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(node_id) DO UPDATE SET
        nodeinfo_count = nodeinfo_count + excluded.nodeinfo_count,
        has_public_key = MAX(has_public_key, excluded.has_public_key),
        has_unmessagable_field = MAX(has_unmessagable_field, excluded.has_unmessagable_field),
        id_from_public_key = MAX(id_from_public_key, excluded.id_from_public_key),
        mac_mismatch = MAX(mac_mismatch, excluded.mac_mismatch),
        relay_self_count = relay_self_count + excluded.relay_self_count,
        relay_none_count = relay_none_count + excluded.relay_none_count,
        xeddsa_signed_count = xeddsa_signed_count + excluded.xeddsa_signed_count,
        hop_start_zero_count = hop_start_zero_count + excluded.hop_start_zero_count,
        hop_start_set_count = hop_start_set_count + excluded.hop_start_set_count,
        hop_start_mask = hop_start_mask | excluded.hop_start_mask,
        aead_count = aead_count + excluded.aead_count,
        soil_water_count = soil_water_count + excluded.soil_water_count,
        paging_count = paging_count + excluded.paging_count,
        firmware_version = CASE
            WHEN excluded.firmware_version IS NOT NULL
             AND (firmware_version_at IS NULL
                  OR COALESCE(excluded.firmware_version_at, 0) >= firmware_version_at)
            THEN excluded.firmware_version ELSE firmware_version END,
        firmware_version_at = CASE
            WHEN excluded.firmware_version IS NOT NULL
             AND (firmware_version_at IS NULL
                  OR COALESCE(excluded.firmware_version_at, 0) >= firmware_version_at)
            THEN excluded.firmware_version_at ELSE firmware_version_at END,
        updated_at = excluded.updated_at
"""


def evidence_row(
    node_id: int, ev: FirmwareEvidence, updated_at: float
) -> tuple[Any, ...]:
    """Parameter tuple for :data:`NODE_FINGERPRINT_UPSERT_SQL`."""
    return (
        node_id,
        ev.nodeinfo_count,
        int(ev.has_public_key),
        int(ev.has_unmessagable_field),
        int(ev.id_from_public_key),
        int(ev.mac_mismatch),
        ev.relay_self_count,
        ev.relay_none_count,
        ev.xeddsa_signed_count,
        ev.hop_start_zero_count,
        ev.hop_start_set_count,
        ev.hop_start_mask,
        ev.aead_count,
        ev.soil_water_count,
        ev.paging_count,
        ev.firmware_version,
        ev.firmware_version_at,
        updated_at,
    )


# Columns added after the table first shipped; older databases get them via
# ALTER TABLE so upgrades need no manual migration.
NODE_FINGERPRINT_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aead_count", "INTEGER NOT NULL DEFAULT 0"),
    ("soil_water_count", "INTEGER NOT NULL DEFAULT 0"),
    ("paging_count", "INTEGER NOT NULL DEFAULT 0"),
)


def ensure_node_fingerprint_table(cursor: sqlite3.Cursor) -> list[str]:
    """Create ``node_fingerprint`` if missing and add any newer columns.

    Returns the names of the columns that were added.
    """
    cursor.execute(NODE_FINGERPRINT_TABLE_SQL)
    cursor.execute("PRAGMA table_info(node_fingerprint)")
    present = {row[1] for row in cursor.fetchall()}
    added: list[str] = []
    for name, decl in NODE_FINGERPRINT_ADDED_COLUMNS:
        if name not in present:
            cursor.execute(f"ALTER TABLE node_fingerprint ADD COLUMN {name} {decl}")
            added.append(name)
    return added


# ---------------------------------------------------------------------------
# Wire-level helpers
# ---------------------------------------------------------------------------


def relay_marker_for(node_id: int) -> int:
    """The ``relay_node`` byte a node writes for itself.

    Firmware stores the last byte of the node number, but 0 means "unset",
    so nodes ending in 0x00 write 0xFF instead.
    """
    last = node_id & 0xFF
    return last if last else 0xFF


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result, pos
        if shift > 63:
            raise ValueError("varint too long")


def _has_length_delimited_field(
    buf: bytes | None, wanted_tag: int, wanted_length: int | None = None
) -> bool:
    """True if a serialized protobuf message carries ``wanted_tag`` as a
    length-delimited field (optionally with exactly ``wanted_length`` bytes).

    Works on the raw wire format so it does not depend on the installed
    protobuf definitions knowing the field.
    """
    if not buf:
        return False
    try:
        pos = 0
        end = len(buf)
        while pos < end:
            key, pos = _read_varint(buf, pos)
            tag, wire_type = key >> 3, key & 7
            if wire_type == 0:
                _, pos = _read_varint(buf, pos)
            elif wire_type == 1:
                pos += 8
            elif wire_type == 2:
                length, pos = _read_varint(buf, pos)
                if tag == wanted_tag and (
                    wanted_length is None or length == wanted_length
                ):
                    return True
                pos += length
            elif wire_type == 5:
                pos += 4
            else:
                return False
        return False
    except (ValueError, IndexError):
        return False


def data_has_xeddsa_signature(data_bytes: bytes | None) -> bool:
    """True if a serialized ``Data`` carries a 64-byte XEdDSA signature (2.8+)."""
    return _has_length_delimited_field(
        data_bytes, DATA_XEDDSA_SIGNATURE_TAG, XEDDSA_SIGNATURE_LEN
    )


def telemetry_has_soil_water(telemetry_bytes: bytes | None) -> bool:
    """True if a serialized ``Telemetry`` carries ``soil_water_metrics`` (2.8.1+)."""
    return _has_length_delimited_field(telemetry_bytes, TELEMETRY_SOIL_WATER_TAG)


def _user_has_unmessagable_field(user: Any) -> bool:
    descriptor = getattr(user, "DESCRIPTOR", None)
    if descriptor is None:
        return False
    field = descriptor.fields_by_name.get("is_unmessagable")
    if field is None or not getattr(field, "has_presence", False):
        return False
    try:
        return bool(user.HasField("is_unmessagable"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Observers
# ---------------------------------------------------------------------------


def observe_packet(
    ev: FirmwareEvidence,
    node_id: int,
    *,
    to_node_id: int | None,
    hop_start: int | None,
    hop_limit: int | None,
    relay_node: int | None,
    data_bytes: bytes | None = None,
    portnum: int | None = None,
    telemetry_bytes: bytes | None = None,
    aead: bool = False,
) -> None:
    """Record what one packet *sent by* ``node_id`` reveals.

    ``data_bytes`` is the serialized ``Data`` (for the 2.8 signature),
    ``telemetry_bytes`` the serialized ``Telemetry`` payload of a
    TELEMETRY_APP packet, and ``aead`` whether the packet was decrypted
    with AES-CCM (a 2.8.1 channel setting).
    """
    hop_start = hop_start or 0
    if hop_start <= 0:
        ev.hop_start_zero_count += 1
    else:
        ev.hop_start_set_count += 1
        if to_node_id == BROADCAST_NODE_ID and hop_start <= 7:
            ev.hop_start_mask |= 1 << hop_start
        # First hop as heard by the gateway: relay_node is whatever the
        # sender wrote (2.6+) or nothing at all (older firmware).
        if hop_limit == hop_start:
            if relay_node == relay_marker_for(node_id):
                ev.relay_self_count += 1
            elif not relay_node:
                ev.relay_none_count += 1
    if data_bytes and data_has_xeddsa_signature(data_bytes):
        ev.xeddsa_signed_count += 1
    if aead:
        ev.aead_count += 1
    if portnum == PAGING_APP_PORTNUM:
        ev.paging_count += 1
    if telemetry_bytes and telemetry_has_soil_water(telemetry_bytes):
        ev.soil_water_count += 1


def observe_user(ev: FirmwareEvidence, node_id: int, user: Any) -> None:
    """Record what a NodeInfo ``User`` payload from ``node_id`` reveals."""
    ev.nodeinfo_count += 1
    public_key = bytes(getattr(user, "public_key", b"") or b"")
    if public_key:
        ev.has_public_key = True
        if (zlib.crc32(public_key) & 0xFFFFFFFF) == node_id:
            ev.id_from_public_key = True
    if _user_has_unmessagable_field(user):
        ev.has_unmessagable_field = True
    macaddr = bytes(getattr(user, "macaddr", b"") or b"")
    if len(macaddr) >= 4 and any(macaddr):
        if int.from_bytes(macaddr[-4:], "big") != node_id:
            ev.mac_mismatch = True


def observe_map_report(
    ev: FirmwareEvidence, report: Any, observed_at: float | None = None
) -> None:
    """Record the exact firmware version a ``MapReport`` payload declares."""
    version = str(getattr(report, "firmware_version", "") or "").strip()
    if not version:
        return
    ev.firmware_version = version[:40]
    ev.firmware_version_at = observed_at if observed_at is not None else time.time()


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------


def parse_version(version: str | None) -> tuple[int, int, int] | None:
    """``"2.7.15.567b8ea"`` → ``(2, 7, 15)``; None if unparseable."""
    if not version:
        return None
    parts = version.strip().split(".")
    nums: list[int] = []
    for part in parts[:3]:
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        nums.append(int(digits))
    if len(nums) < 2:
        return None
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


class _Trail:
    """Collects, per finding, a full sentence plus a terse (trait, range) pair."""

    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.items: list[dict[str, str]] = []

    def add(self, reason: str, trait: str, version_range: str) -> None:
        self.reasons.append(reason)
        self.items.append({"trait": trait, "range": version_range})


def _band(ev: FirmwareEvidence, role: str | None, hw_model: str | None):
    """Return (label, band_min, trail) from fingerprint evidence alone."""
    t = _Trail()
    if (
        hw_model in SOFTWARE_CLIENT_HW_MODELS
        and ev.hop_start_set_count == 0
        and ev.hop_start_zero_count >= MIN_SOFTWARE_CLIENT_PACKETS
    ):
        t.add(
            "PRIVATE_HW and hop_start never set: not a Meshtastic radio",
            "PRIVATE_HW, no hop_start",
            "not a radio",
        )
        return "Software client", None, t

    if ev.aead_count > 0:
        t.add(
            f"{ev.aead_count} packet(s) used AES-CCM channel encryption (use_aead, 2.8.1+)",
            f"AEAD channel ×{ev.aead_count}",
            "2.8.1+",
        )
    if ev.paging_count > 0:
        t.add(
            f"{ev.paging_count} PAGING_APP packet(s) (portnum added in 2.8.1)",
            f"paging app ×{ev.paging_count}",
            "2.8.1+",
        )
    if ev.soil_water_count > 0:
        t.add(
            f"{ev.soil_water_count} soil/water telemetry packet(s) (2.8.1+)",
            f"soil/water telemetry ×{ev.soil_water_count}",
            "2.8.1+",
        )
    newest = "≥ 2.8.1" if t.items else None

    if ev.xeddsa_signed_count > 0:
        t.add(
            f"{ev.xeddsa_signed_count} packet(s) carry an XEdDSA signature (2.8+)",
            f"XEdDSA signature ×{ev.xeddsa_signed_count}",
            "2.8+",
        )
    if ev.id_from_public_key:
        t.add(
            "node number is CRC32 of its public key (2.8+)",
            "node id = CRC32(public key)",
            "2.8+",
        )
    if newest:
        return newest, (2, 8, 1), t
    if t.items:
        return "≥ 2.8", (2, 8, 0), t

    if role == "CLIENT_BASE":
        t.add("role CLIENT_BASE exists since 2.7.8", "CLIENT_BASE role", "2.7.8+")
        return "≥ 2.7.8", (2, 7, 8), t

    if ev.has_unmessagable_field:
        t.add(
            "NodeInfo carries is_unmessagable (field added in 2.6.8)",
            "is_unmessagable field",
            "2.6.8+",
        )
        return "≥ 2.6.8", (2, 6, 8), t

    if ev.relay_self_count >= MIN_RELAY_SELF_PACKETS:
        t.add(
            f"{ev.relay_self_count} own packets carry relay_node (next-hop routing, 2.6+)",
            f"relay_node ×{ev.relay_self_count}",
            "2.6+",
        )
        if ev.nodeinfo_count:
            t.add(
                "NodeInfo lacks is_unmessagable, so older than 2.6.8",
                "no is_unmessagable",
                "< 2.6.8",
            )
            return "2.6.0 – 2.6.7", (2, 6, 0), t
        return "≥ 2.6", (2, 6, 0), t

    if ev.has_public_key:
        t.add("NodeInfo carries a public key (PKI, 2.5+)", "public key", "2.5+")
        if ev.relay_none_count >= MIN_RELAY_NONE_PACKETS and not ev.relay_self_count:
            t.add(
                f"{ev.relay_none_count} own packets without relay_node, so older than 2.6",
                f"no relay_node ×{ev.relay_none_count}",
                "< 2.6",
            )
            return "2.5.x", (2, 5, 0), t
        return "2.5.0 – 2.6.7", (2, 5, 0), t

    if ev.nodeinfo_count:
        t.add("NodeInfo has no public key", "no public key", "< 2.5 or PKI off")
        if ev.relay_none_count >= MIN_RELAY_NONE_PACKETS and not ev.relay_self_count:
            t.add(
                f"{ev.relay_none_count} own packets without relay_node, so older than 2.6",
                f"no relay_node ×{ev.relay_none_count}",
                "< 2.6",
            )
            return "< 2.5", (0, 0, 0), t
        return "< 2.5 or PKI disabled", (0, 0, 0), t

    return None, None, t


def estimate(
    ev: FirmwareEvidence,
    *,
    role: str | None = None,
    hw_model: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Combine fingerprint evidence and any reported version into one verdict.

    Returns ``label`` (what to show), ``source`` (``reported`` /
    ``fingerprint`` / ``none``), the fingerprint-only ``estimated_label``,
    the ``reported_version`` with its timestamp, full-sentence ``reasons``
    (for APIs and logs), ``evidence_items`` as ``{trait, range}`` pairs and
    ``evidence`` strings ("trait (range)") for terse UIs.
    """
    now = time.time() if now is None else now
    label, band_min, trail = _band(ev, role, hw_model)
    estimated_label = label

    if bin(ev.hop_start_mask).count("1") >= 3:
        trail.add(
            "broadcast hop limit keeps changing (automatic hop limits, a 2.8 trait)",
            "variable hop limit",
            "2.8 trait",
        )

    reported = ev.firmware_version
    reported_tuple = parse_version(reported)
    reported_at = ev.firmware_version_at
    reported_at_str = (
        time.strftime("%Y-%m-%d", time.gmtime(reported_at)) if reported_at else None
    )
    reported_fresh = reported_at is None or (
        now - reported_at <= REPORTED_VERSION_MAX_AGE_SECONDS
    )

    items = list(trail.items)
    if reported and reported_tuple and label != "Software client":
        report_item = {
            "trait": "MapReport" + (f" {reported_at_str}" if reported_at_str else ""),
            "range": "exact" if reported_fresh else "exact, old report",
        }
        if band_min is None or reported_tuple >= band_min:
            label, source = reported, "reported"
            reasons = [
                "version reported by the node itself (MapReport)"
                + ("" if reported_fresh else ", but the report is old")
            ] + trail.reasons
            items = [report_item] + items
        else:
            source = "fingerprint"
            reasons = trail.reasons + [
                f"last reported {reported}, but newer traits have been seen since"
            ]
            items = items + [
                {"trait": f"reported {reported} earlier", "range": "superseded"}
            ]
    else:
        source = "fingerprint" if label else "none"
        reasons = trail.reasons
    if not items:
        items = [{"trait": "no evidence yet", "range": ""}]

    return {
        "label": label or "Unknown",
        "source": source,
        "estimated_label": estimated_label,
        "reported_version": reported,
        "reported_at": reported_at,
        "reported_at_str": reported_at_str,
        "reasons": reasons,
        "evidence_items": items,
        "evidence": [
            f"{item['trait']} ({item['range']})" if item["range"] else item["trait"]
            for item in items
        ],
    }


# ---------------------------------------------------------------------------
# Distribution (dashboard)
# ---------------------------------------------------------------------------

Version = tuple[int, int, int]

# Fingerprints prove lower bounds ("at least 2.7.8"), and a node with weaker
# evidence cannot be told apart from an older one, so the dashboard buckets
# nodes by the highest version they are proven to have reached. That is a
# strict ladder: every node sits on exactly one rung and the rungs never
# overlap. Exact (MapReport) versions land on the same rungs.
_LADDER: tuple[tuple[str, Version], ...] = (
    ("2.8.1", (2, 8, 1)),
    ("2.8", (2, 8, 0)),
    ("2.7.8", (2, 7, 8)),
    ("2.6.8", (2, 6, 8)),
    ("2.6", (2, 6, 0)),
    ("2.5", (2, 5, 0)),
)
_TAIL_SEGMENTS: tuple[tuple[str, str], ...] = (
    ("lt2.5", "< 2.5"),
    ("software", "Software client"),
    ("unknown", "Unknown"),
)
DISTRIBUTION_KEYS: tuple[str, ...] = tuple(k for k, _ in _LADDER) + tuple(
    k for k, _ in _TAIL_SEGMENTS
)

_ESTIMATE_TO_SEGMENT: dict[str, str] = {
    "≥ 2.8.1": "2.8.1",
    "≥ 2.8": "2.8",
    "≥ 2.7.8": "2.7.8",
    "≥ 2.6.8": "2.6.8",
    "≥ 2.6": "2.6",
    "2.6.0 – 2.6.7": "2.6",
    "2.5.0 – 2.6.7": "2.5",
    "2.5.x": "2.5",
    "< 2.5": "lt2.5",
    "< 2.5 or PKI disabled": "lt2.5",
    "Software client": "software",
}


def _fmt(version: Version) -> str:
    return ".".join(str(n) for n in version)


def segment_label(key: str) -> str:
    """Human label for a segment key, e.g. ``"≥ 2.7.8"``."""
    for seg_key, low in _LADDER:
        if seg_key == key:
            return f"≥ {_fmt(low)}"
    for seg_key, label in _TAIL_SEGMENTS:
        if seg_key == key:
            return label
    return key


def distribution_segment(verdict: dict[str, Any]) -> tuple[str, str]:
    """Map one verdict to ``(segment key, kind)``; kind is reported/estimated/other."""
    if verdict.get("source") == "reported":
        parsed = parse_version(verdict.get("reported_version"))
        if parsed:
            for key, low in _LADDER:
                if parsed >= low:
                    return key, "reported"
            return "lt2.5", "reported"
    label = verdict.get("label") or "Unknown"
    segment = _ESTIMATE_TO_SEGMENT.get(label, "unknown")
    if segment in ("software", "unknown"):
        return segment, "other"
    return segment, "estimated"


def summarize_distribution(
    verdicts: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Count verdicts per rung (newest first) with reported/estimated splits.

    Empty rungs are dropped.
    """
    counts: dict[str, dict[str, int]] = {
        key: {"count": 0, "reported": 0, "estimated": 0, "other": 0}
        for key in DISTRIBUTION_KEYS
    }
    for verdict in verdicts:
        segment, kind = distribution_segment(verdict)
        entry = counts[segment]
        entry["count"] += 1
        entry[kind] += 1
    return [
        {"key": key, "label": segment_label(key), **counts[key]}
        for key in DISTRIBUTION_KEYS
        if counts[key]["count"]
    ]
