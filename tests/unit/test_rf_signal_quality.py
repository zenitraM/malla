"""Unit tests for LoRa presets, demodulation thresholds, and link quality metrics."""

from src.malla.utils.signal_quality import (
    calculate_estimated_reliability,
    calculate_fade_margin,
    classify_link_balance,
    classify_signal_quality,
    get_demodulation_snr_limit,
    get_quality_color,
    resolve_spreading_factor,
)


class TestSignalQualityModels:
    """Test preset resolution and demodulation thresholds."""

    def test_resolve_spreading_factor_standard_presets(self):
        assert resolve_spreading_factor("ShortFast") == 7
        assert resolve_spreading_factor("shortturbo") == 7
        assert resolve_spreading_factor("ShortSlow") == 8
        assert resolve_spreading_factor("MediumFast") == 9
        assert resolve_spreading_factor("MediumSlow") == 10
        assert resolve_spreading_factor("LongFast") == 11
        assert resolve_spreading_factor("LongSlow") == 12

    def test_resolve_spreading_factor_custom_presets(self):
        # Spain SFNarrow is SF7
        assert resolve_spreading_factor("SFNarrow") == 7
        assert resolve_spreading_factor("sfnarrow") == 7
        assert resolve_spreading_factor("sfnarrow8") == 8
        assert resolve_spreading_factor("eunarrow") == 8

    def test_resolve_spreading_factor_numeric_and_substring(self):
        assert resolve_spreading_factor(7) == 7
        assert resolve_spreading_factor(12) == 12
        assert resolve_spreading_factor("my-custom-sf8-network") == 8
        assert resolve_spreading_factor("SF9") == 9

    def test_get_demodulation_snr_limit(self):
        # -2.5 * (SF - 4)
        assert get_demodulation_snr_limit(7) == -7.5
        assert get_demodulation_snr_limit(8) == -10.0
        assert get_demodulation_snr_limit(9) == -12.5
        assert get_demodulation_snr_limit(10) == -15.0
        assert get_demodulation_snr_limit(11) == -17.5
        assert get_demodulation_snr_limit(12) == -20.0

    def test_calculate_fade_margin(self):
        # On LongFast (SF11, limit = -17.5)
        # SNR = -7.5 -> margin = -7.5 - (-17.5) = +10.0 dB
        assert calculate_fade_margin(-7.5, sf=11) == 10.0
        # On ShortFast / SFNarrow (SF7, limit = -7.5)
        # SNR = -7.0 -> margin = -7.0 - (-7.5) = +0.5 dB (marginal!)
        assert calculate_fade_margin(-7.0, sf="SFNarrow") == 0.5
        # Invalid SNR
        assert calculate_fade_margin(None) is None
        assert calculate_fade_margin(100.0) is None  # Above plausible range

    def test_classify_signal_quality_presets(self):
        # On SFNarrow (SF7, limit -7.5):
        # SNR +4.0 -> margin = 11.5 dB -> good
        assert classify_signal_quality(4.0, sf="sfnarrow") == "good"
        # SNR -1.0 -> margin = 6.5 dB -> fair
        assert classify_signal_quality(-1.0, sf="sfnarrow") == "fair"
        # SNR -7.0 -> margin = 0.5 dB -> marginal
        assert classify_signal_quality(-7.0, sf="sfnarrow") == "marginal"

        # On LongFast (SF11, limit -17.5):
        # SNR -7.0 -> margin = 10.5 dB -> good on LongFast!
        assert classify_signal_quality(-7.0, sf="LongFast") == "good"
        # SNR -12.0 -> margin = 5.5 dB -> fair
        assert classify_signal_quality(-12.0, sf="LongFast") == "fair"
        # SNR -15.0 -> margin = 2.5 dB -> marginal
        assert classify_signal_quality(-15.0, sf="LongFast") == "marginal"

    def test_calculate_estimated_reliability(self):
        # Strong margin (margin >= 10 dB) -> > 98%
        rel_strong = calculate_estimated_reliability(4.0, sf="sfnarrow")
        assert rel_strong is not None and rel_strong >= 98.0

        # Fair margin (margin ~ 6.5 dB) -> ~ 90%
        rel_fair = calculate_estimated_reliability(-1.0, sf="sfnarrow")
        assert rel_fair is not None and 80.0 <= rel_fair <= 95.0

        # Fragile margin (margin = 0.5 dB) -> < 30%
        rel_fragile = calculate_estimated_reliability(-7.0, sf="sfnarrow")
        assert rel_fragile is not None and rel_fragile < 30.0

        # None on invalid
        assert calculate_estimated_reliability(None) is None

    def test_classify_link_balance_practical(self):
        # On SFNarrow (SF7): +4 dB (good) and -7 dB (marginal)
        # Exactly one is marginal -> asymmetric_marginal!
        assert classify_link_balance(4.0, -7.0, sf="sfnarrow") == "asymmetric_marginal"
        assert classify_link_balance(-7.0, 4.0, sf="sfnarrow") == "asymmetric_marginal"

        # Both good -> balanced
        assert classify_link_balance(4.0, 2.8, sf="sfnarrow") == "balanced"

        # Both fair -> balanced
        assert classify_link_balance(-1.0, -2.0, sf="sfnarrow") == "balanced"

        # Both marginal -> marginal_both
        assert classify_link_balance(-6.5, -7.0, sf="sfnarrow") == "marginal_both"

        # One-way
        assert classify_link_balance(4.0, None, sf="sfnarrow") == "unidirectional"
        assert classify_link_balance(None, 4.0, sf="sfnarrow") == "unidirectional"
        assert classify_link_balance(None, None, sf="sfnarrow") == "unknown"

    def test_get_quality_color(self):
        assert get_quality_color("good") == "#28a745"
        assert get_quality_color("fair") == "#ffc107"
        assert get_quality_color("marginal") == "#dc3545"
        assert get_quality_color("unknown") == "#888888"
