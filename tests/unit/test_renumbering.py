"""Pure-logic checks for firmware 2.8 renumbering helpers."""

from malla.database.repositories import NodeRepository
from malla.fingerprint import verdict_min_version


def _entry(node_id: int, first_seen: float) -> dict:
    return {
        "node_id": node_id,
        "hex_id": f"!{node_id:08x}",
        "node_name": "n",
        "first_seen": first_seen,
        "via": "public key",
    }


def test_successor_hidden_only_when_old_id_went_quiet():
    renumbered = {1: _entry(2, first_seen=1_000.0)}
    # last heard before the new id appeared → renumbered
    assert NodeRepository.successor_of(1, 900.0, renumbered)["node_id"] == 2
    # a little after (same reboot) still counts
    assert NodeRepository.successor_of(1, 1_000.0 + 60, renumbered) is not None
    # heard long after the successor appeared → MAC collision or downgrade
    assert NodeRepository.successor_of(1, 1_000.0 + 7_200, renumbered) is None
    # unknown activity (never heard) → trust the link
    assert NodeRepository.successor_of(1, None, renumbered) is not None
    # not in the map
    assert NodeRepository.successor_of(2, 5.0, renumbered) is None


def test_verdict_min_version_reads_reported_and_fingerprint_labels():
    assert verdict_min_version(None) is None
    assert verdict_min_version({"label": "Unknown", "source": "none"}) is None
    assert verdict_min_version({"label": "< 2.5", "source": "fingerprint"}) is None
    assert verdict_min_version({"label": "≥ 2.8", "source": "fingerprint"}) == (2, 8, 0)
    assert verdict_min_version({"label": "≥ 2.8.1", "source": "fingerprint"}) == (
        2,
        8,
        1,
    )
    assert verdict_min_version({"label": "≥ 2.7.8", "source": "fingerprint"}) < (
        2,
        8,
        0,
    )
    assert verdict_min_version(
        {
            "label": "2.8.1.8e6a88d",
            "source": "reported",
            "reported_version": "2.8.1.8e6a88d",
        }
    ) == (2, 8, 1)
    assert verdict_min_version(
        {"label": "2.7.26", "source": "reported", "reported_version": "2.7.26.54e0d8d"}
    ) < (2, 8, 0)
