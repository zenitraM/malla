"""Plausibility bounds for LoRa signal metrics (RSSI/SNR).

Corrupt gateway frames occasionally survive protobuf parsing and land in
packet_history with garbage signal values (rx_rssi like -1386841926, rx_snr
like 2.8e-36). A single such row is enough to drag an unguarded AVG(rssi)
to five-digit nonsense. packet_history deliberately stores whatever the
frame contained — it is the faithful raw record — so every read-side
aggregate over these columns must restrict itself to the plausible LoRa
range using the predicates below.

Conventions shared with Meshtastic firmware:
- rssi == 0 means "not provided" (e.g. the gateway's own uplinked packets);
  real LoRa receptions are always negative and above the sensitivity floor.
- snr is reported in quarter-dB steps within roughly [-20, 15] dB; the
  bounds here are deliberately generous so no real reception is rejected.
"""

import math
from typing import TypeGuard

RSSI_PLAUSIBLE_MIN = -150  # dBm; below any LoRa sensitivity floor (~-137)
RSSI_PLAUSIBLE_MAX = -1  # dBm; 0 is the "not provided" sentinel, positive is garbage
SNR_PLAUSIBLE_MIN = -30.0  # dB
SNR_PLAUSIBLE_MAX = 30.0  # dB

# Traceroute RouteDiscovery payloads encode "SNR unknown" as INT8_MIN (-128),
# which parse_traceroute_payload scales to -128/4 = -32.0 dB. That sentinel
# marks a real hop whose SNR simply wasn't recorded, so traceroute-payload
# consumers must not reclassify it as garbage.
TRACEROUTE_UNKNOWN_SNR = -32.0


def rssi_valid_sql(column: str = "rssi") -> str:
    """SQL predicate matching plausible RSSI values.

    NULL and the 0 "not provided" sentinel both fail the predicate, so this
    subsumes the older ``rssi IS NOT NULL AND rssi != 0`` guards.
    """
    return f"{column} BETWEEN {RSSI_PLAUSIBLE_MIN} AND {RSSI_PLAUSIBLE_MAX}"


def snr_valid_sql(column: str = "snr") -> str:
    """SQL predicate matching plausible SNR values (NULL fails it)."""
    return f"{column} BETWEEN {SNR_PLAUSIBLE_MIN} AND {SNR_PLAUSIBLE_MAX}"


def is_plausible_rssi(value: float | int | None) -> bool:
    """True when ``value`` is a real reception RSSI (0 sentinel excluded)."""
    return (
        value is not None
        and math.isfinite(value)
        and RSSI_PLAUSIBLE_MIN <= value <= RSSI_PLAUSIBLE_MAX
    )


def is_plausible_snr(value: float | int | None) -> bool:
    """True when ``value`` is a plausible SNR (0.0 is allowed here)."""
    return (
        value is not None
        and math.isfinite(value)
        and SNR_PLAUSIBLE_MIN <= value <= SNR_PLAUSIBLE_MAX
    )


def is_plausible_traceroute_snr(value: float | int | None) -> TypeGuard[float]:
    """True for plausible traceroute hop SNR, including the -32.0 "unknown" sentinel.

    Use this (not :func:`is_plausible_snr`) when filtering SNR values parsed
    from RouteDiscovery payloads, so hops whose SNR wasn't recorded keep
    appearing in graphs exactly as they did before the plausibility guards.
    The ``TypeGuard`` return type lets callers use a passing value as a plain
    ``float`` without re-checking for ``None``.
    """
    return value is not None and (
        value == TRACEROUTE_UNKNOWN_SNR or is_plausible_snr(value)
    )
