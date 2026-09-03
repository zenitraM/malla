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
from typing import Any, TypeGuard

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


# ---------------------------------------------------------------------------
# LoRa Modem Presets, Spreading Factors, & Hardware Demodulation Limits
# ---------------------------------------------------------------------------

# Standard Meshtastic presets and known custom/regional presets (e.g. SFNarrow in Spain)
LORA_PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    # Standard Meshtastic presets
    "shortfast": {"sf": 7, "bw_khz": 250, "name": "ShortFast"},
    "shortturbo": {"sf": 7, "bw_khz": 500, "name": "ShortTurbo"},
    "shortslow": {"sf": 8, "bw_khz": 250, "name": "ShortSlow"},
    "mediumfast": {"sf": 9, "bw_khz": 250, "name": "MediumFast"},
    "mediumslow": {"sf": 10, "bw_khz": 250, "name": "MediumSlow"},
    "longfast": {"sf": 11, "bw_khz": 250, "name": "LongFast"},
    "longmoderate": {"sf": 11, "bw_khz": 125, "name": "LongModerate"},
    "longslow": {"sf": 12, "bw_khz": 125, "name": "LongSlow"},
    "verylongslow": {"sf": 12, "bw_khz": 62.5, "name": "VeryLongSlow"},
    # Known regional & custom configurations
    "sfnarrow": {"sf": 7, "bw_khz": 62.5, "name": "SFNarrow (Spain)"},
    "sfnarrow8": {"sf": 8, "bw_khz": 62.5, "name": "SFNarrow SF8"},
    "eunarrow": {"sf": 8, "bw_khz": 62.5, "name": "EU Narrow"},
}

DEFAULT_SPREADING_FACTOR = 11  # LongFast default


def resolve_spreading_factor(
    preset_or_sf: str | int | None = None,
) -> int:
    """Resolve a modem preset name, custom config name, or spreading factor integer to an SF (7-12).

    If not provided or unresolvable, falls back to application config (``lora_spreading_factor``
    or ``lora_preset``), defaulting to 11 (LongFast).
    """
    if isinstance(preset_or_sf, int):
        if 7 <= preset_or_sf <= 12:
            return preset_or_sf

    if isinstance(preset_or_sf, str) and preset_or_sf.strip():
        cleaned = preset_or_sf.strip().lower().replace("-", "").replace("_", "")
        # Check known dictionary
        if cleaned in LORA_PRESET_DEFINITIONS:
            return int(LORA_PRESET_DEFINITIONS[cleaned]["sf"])

        # Check for direct SF designation e.g. "sf7", "sf8", "sf11"
        for sf in range(7, 13):
            if f"sf{sf}" in cleaned:
                return sf

        # Check if single or double digit matches SF
        if cleaned.isdigit():
            val = int(cleaned)
            if 7 <= val <= 12:
                return val

    # Fallback to AppConfig
    try:
        from ..config import get_config

        config = get_config()
        if config.lora_spreading_factor is not None:
            if 7 <= config.lora_spreading_factor <= 12:
                return config.lora_spreading_factor

        if config.lora_preset:
            cleaned_cfg = (
                config.lora_preset.strip().lower().replace("-", "").replace("_", "")
            )
            if cleaned_cfg in LORA_PRESET_DEFINITIONS:
                return int(LORA_PRESET_DEFINITIONS[cleaned_cfg]["sf"])
            for sf in range(7, 13):
                if f"sf{sf}" in cleaned_cfg:
                    return sf
    except Exception:
        pass

    return DEFAULT_SPREADING_FACTOR


def get_demodulation_snr_limit(sf: int) -> float:
    """Theoretical LoRa hardware demodulation limit (Semtech SX1262/SX1276) for a given Spreading Factor.

    Formula: ``-2.5 * (SF - 4)`` dB.
    SF7: -7.5 dB, SF8: -10.0 dB, SF9: -12.5 dB, SF10: -15.0 dB, SF11: -17.5 dB, SF12: -20.0 dB.
    """
    clamped_sf = max(7, min(12, sf))
    return -2.5 * (clamped_sf - 4)


def calculate_fade_margin(
    snr: float | None, sf: int | str | None = None
) -> float | None:
    """Calculate the fade margin (dB above hardware demodulation limit) for a given SNR.

    Returns None if SNR is None or invalid.
    """
    if snr is None or not is_plausible_snr(snr):
        return None
    effective_sf = resolve_spreading_factor(sf)
    snr_limit = get_demodulation_snr_limit(effective_sf)
    return round(snr - snr_limit, 1)


def classify_signal_quality(snr: float | None, sf: int | str | None = None) -> str:
    """Classify SNR into quality tiers relative to the modem preset's demodulation limit:

    - 'good': Margin >= +10.0 dB (robust link margin)
    - 'fair': +4.0 dB <= Margin < +10.0 dB (usable, moderate fade margin)
    - 'marginal': Margin < +4.0 dB (fragile, high packet drop probability)
    - 'unknown': Missing or invalid SNR
    """
    margin = calculate_fade_margin(snr, sf)
    if margin is None:
        return "unknown"
    if margin >= 10.0:
        return "good"
    if margin >= 4.0:
        return "fair"
    return "marginal"


def calculate_estimated_reliability(
    snr: float | None, sf: int | str | None = None
) -> float | None:
    """Estimate packet delivery reliability (0.0 to 100.0%) from SNR fade margin using LoRa sigmoid model.

    Returns None if SNR is None or invalid.
    """
    margin = calculate_fade_margin(snr, sf)
    if margin is None:
        return None

    # Sigmoid function centered around Margin = 2.5 dB with steepness k = 0.6
    # Margin >= 10 dB -> ~99%
    # Margin = 6 dB -> ~89%
    # Margin = 4 dB -> ~71%
    # Margin = 2 dB -> ~43%
    # Margin = 0 dB (at cliff) -> ~18%
    # Margin < 0 dB (below cliff) -> < 10%
    exponent = -0.6 * (margin - 2.5)
    # Clamp exponent to prevent overflow
    exponent = max(-20.0, min(20.0, exponent))
    reliability = 100.0 / (1.0 + math.exp(exponent))
    return round(max(0.0, min(100.0, reliability)), 1)


def classify_link_balance(
    forward_snr: float | None,
    return_snr: float | None,
    sf: int | str | None = None,
) -> str:
    """Classify the practical operational balance between forward and return links:

    - 'balanced': Both directions observed and neither is marginal.
    - 'asymmetric_marginal': Both directions observed, but exactly one is marginal while the other is viable.
    - 'marginal_both': Both directions observed and both are marginal.
    - 'unidirectional': Only one direction has observed SNR.
    - 'unknown': Neither direction has valid SNR.
    """
    has_f = forward_snr is not None and is_plausible_snr(forward_snr)
    has_r = return_snr is not None and is_plausible_snr(return_snr)

    if not has_f and not has_r:
        return "unknown"
    if has_f and not has_r:
        return "unidirectional"
    if has_r and not has_f:
        return "unidirectional"

    q_f = classify_signal_quality(forward_snr, sf)
    q_r = classify_signal_quality(return_snr, sf)

    if q_f == "marginal" and q_r == "marginal":
        return "marginal_both"
    if (q_f == "marginal" and q_r != "marginal") or (
        q_r == "marginal" and q_f != "marginal"
    ):
        return "asymmetric_marginal"
    return "balanced"


def get_quality_color(quality: str) -> str:
    """Return standard hex color for a given quality tier."""
    colors = {
        "good": "#28a745",  # Green
        "fair": "#ffc107",  # Yellow/Amber
        "marginal": "#dc3545",  # Red
        "unknown": "#888888",  # Muted grey
    }
    return colors.get(quality, "#888888")
