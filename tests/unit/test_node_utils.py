"""
Unit tests for node utility functions.
"""

import pytest

from src.malla.utils.node_utils import (
    cache_lock,
    clear_node_name_cache,
    convert_node_id,
    get_cache_stats,
    node_name_cache,
    start_cache_cleanup,
    stop_cache_cleanup,
    transform_nodes_for_template,
)


class TestTransformNodesForTemplate:
    """Test the transform_nodes_for_template function."""

    @pytest.mark.unit
    def test_transform_with_long_name(self):
        """Test transformation when long_name is available."""
        raw_nodes = [
            {
                "node_id": 305419896,
                "long_name": "Alpha Gateway",
                "short_name": "Alpha",
                "hex_id": "!12345678",
                "packet_count": 150,
            }
        ]

        result = transform_nodes_for_template(raw_nodes)

        assert len(result) == 1
        assert result[0]["id"] == 305419896
        assert result[0]["name"] == "Alpha Gateway (150 packets)"
        assert result[0]["packet_count"] == 150

    @pytest.mark.unit
    def test_transform_with_short_name_fallback(self):
        """Test transformation when long_name is missing, falls back to short_name."""
        raw_nodes = [
            {
                "node_id": 2271560481,
                "long_name": None,
                "short_name": "Alpha",
                "hex_id": "!87654321",
                "packet_count": 50,
            },
            {
                "node_id": 286331153,
                "long_name": "",
                "short_name": "Beta",
                "hex_id": "!11111111",
                "packet_count": 25,
            },
        ]

        result = transform_nodes_for_template(raw_nodes)

        assert len(result) == 2
        assert result[0]["id"] == 2271560481
        assert result[0]["name"] == "Alpha (50 packets)"
        assert result[0]["packet_count"] == 50

        assert result[1]["id"] == 286331153
        assert result[1]["name"] == "Beta (25 packets)"
        assert result[1]["packet_count"] == 25

    @pytest.mark.unit
    def test_transform_with_hex_fallback(self):
        """Test transformation when both long_name and short_name are missing, falls back to hex_id."""
        raw_nodes = [
            {
                "node_id": 305419896,
                "long_name": None,
                "short_name": "",
                "hex_id": "!12345678",
                "packet_count": 10,
            }
        ]

        result = transform_nodes_for_template(raw_nodes)

        assert len(result) == 1
        assert result[0]["id"] == 305419896
        assert result[0]["name"] == "!12345678 (10 packets)"
        assert result[0]["packet_count"] == 10

    @pytest.mark.unit
    def test_transform_mixed_name_scenarios(self):
        """Test transformation with mixed naming scenarios."""
        raw_nodes = [
            {
                "node_id": 1,
                "long_name": "Full Name Node",
                "short_name": "Short",
                "hex_id": "!00000001",
                "packet_count": 100,
            },
            {
                "node_id": 2,
                "long_name": None,
                "short_name": "Only Short",
                "hex_id": "!00000002",
                "packet_count": 75,
            },
            {
                "node_id": 3,
                "long_name": "",
                "short_name": "",
                "hex_id": "!00000003",
                "packet_count": 50,
            },
        ]

        result = transform_nodes_for_template(raw_nodes)

        assert len(result) == 3
        assert result[0]["name"] == "Full Name Node (100 packets)"  # Uses long_name
        assert result[1]["name"] == "Only Short (75 packets)"  # Uses short_name
        assert result[2]["name"] == "!00000003 (50 packets)"  # Uses hex_id

    @pytest.mark.unit
    def test_transform_empty_list(self):
        """Test transformation with empty input."""
        result = transform_nodes_for_template([])
        assert result == []

    @pytest.mark.unit
    def test_transform_preserves_packet_count(self):
        """Test that packet counts are preserved correctly."""
        raw_nodes = [
            {
                "node_id": 305419896,
                "long_name": "Test Node",
                "short_name": "Test",
                "hex_id": "!12345678",
                "packet_count": 0,  # Zero packets
            },
            {
                "node_id": 2271560481,
                "long_name": "Active Node",
                "short_name": "Active",
                "hex_id": "!87654321",
                "packet_count": 9999,  # High packet count
            },
        ]

        result = transform_nodes_for_template(raw_nodes)

        assert result[0]["packet_count"] == 0
        assert result[1]["packet_count"] == 9999


class TestNodeUtilsOtherFunctions:
    """Test other node utility functions for completeness."""

    @pytest.mark.unit
    def test_convert_node_id_decimal(self):
        """Test convert_node_id with decimal input."""
        assert convert_node_id(305419896) == 305419896
        assert convert_node_id("305419896") == 305419896

    @pytest.mark.unit
    def test_convert_node_id_hex(self):
        """Test convert_node_id with hex input."""
        assert convert_node_id("!12345678") == 305419896
        # Without ! prefix, it's treated as decimal
        assert convert_node_id("12345678") == 12345678

    @pytest.mark.unit
    def test_convert_node_id_invalid(self):
        """Test convert_node_id with invalid input."""
        with pytest.raises(ValueError):
            convert_node_id("invalid")
        with pytest.raises(ValueError):
            convert_node_id("!invalid")

    @pytest.mark.unit
    def test_convert_node_id_ambiguous_decimal_hex(self):
        """Test convert_node_id with node IDs that could be interpreted as hex or decimal."""
        # This is the bug case: "24632481" should be treated as decimal
        assert convert_node_id("24632481") == 24632481  # Decimal

        # Strings with ! prefix should be treated as hex
        assert convert_node_id("!ABCDEF12") == int("ABCDEF12", 16)  # Hex
        assert convert_node_id("!12ABCDEF") == int("12ABCDEF", 16)  # Hex
        assert (
            convert_node_id("!0177dca1") == 24632481
        )  # Hex representation of decimal 24632481

        # Strings without ! prefix should be treated as decimal
        assert convert_node_id("99999999") == 99999999  # Decimal
        assert convert_node_id("12345689") == 12345689  # Decimal
        assert convert_node_id("87654321") == 87654321  # Decimal

        # Invalid decimal strings should raise ValueError
        with pytest.raises(ValueError):
            convert_node_id("ABCDEF12")  # Invalid decimal


class TestCacheCleanupFunctionality:
    """Test the periodic cache cleanup functionality."""

    def test_start_stop_cache_cleanup(self):
        """Test that cache cleanup thread can be started and stopped."""
        # Ensure cleanup is stopped initially
        stop_cache_cleanup()

        # Start cleanup
        start_cache_cleanup()

        # Verify thread is running
        import src.malla.utils.node_utils as node_utils

        assert node_utils._cache_cleanup_thread is not None
        assert node_utils._cache_cleanup_thread.is_alive()

        # Stop cleanup
        stop_cache_cleanup()

        # Verify thread is stopped
        assert not node_utils._cache_cleanup_thread.is_alive()

    def test_cache_cleanup_clears_cache(self):
        """Test that cache cleanup actually clears the cache."""
        # Ensure cleanup is stopped
        stop_cache_cleanup()

        # Clear any existing cache data first
        clear_node_name_cache()

        # Add some data to cache
        with cache_lock:
            node_name_cache[123] = "Test Node"
            node_name_cache[456] = "Another Node"

        # Verify cache has data
        stats = get_cache_stats()
        assert stats["cached_nodes"] == 2

        # Manually clear cache using the clear function
        clear_node_name_cache()

        # Verify cache is cleared
        stats = get_cache_stats()
        assert stats["cached_nodes"] == 0

    def test_start_cache_cleanup_idempotent(self):
        """Test that starting cache cleanup multiple times doesn't create multiple threads."""
        # Ensure cleanup is stopped initially
        stop_cache_cleanup()

        # Start cleanup twice
        start_cache_cleanup()
        start_cache_cleanup()

        # Should still have only one thread
        import src.malla.utils.node_utils as node_utils

        assert node_utils._cache_cleanup_thread is not None
        assert node_utils._cache_cleanup_thread.is_alive()

        # Clean up
        stop_cache_cleanup()

    def test_stop_cache_cleanup_when_not_running(self):
        """Test that stopping cache cleanup when not running doesn't cause errors."""
        # Ensure cleanup is stopped
        stop_cache_cleanup()

        # Stop again - should not cause errors
        stop_cache_cleanup()

        # Should be safe to call multiple times
        stop_cache_cleanup()
        stop_cache_cleanup()
