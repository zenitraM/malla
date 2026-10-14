"""
End-to-end tests for the node detail page.
"""

import pytest


class TestNodeDetailPage:
    """Test the node detail page functionality."""

    @pytest.mark.e2e
    def test_node_detail_page_loads_without_errors(self, client):
        """Test that node detail pages load without template errors."""
        # Test with a known test node ID (1128074276 = 0x43456724)
        response = client.get("/node/1128074276")
        assert response.status_code == 200

        # Should not contain error messages about missing filters
        response_text = response.get_data(as_text=True)
        assert "No filter named 'format_rssi' found" not in response_text
        assert "No filter named 'format_snr' found" not in response_text
        assert "Node detail error:" not in response_text

    @pytest.mark.e2e
    def test_node_detail_page_with_hex_id(self, client):
        """Test node detail page with hex format node ID."""
        response = client.get("/node/!43456724")
        # The node may or may not exist in test data, but should not have filter errors
        if response.status_code == 200:
            response_text = response.get_data(as_text=True)
            assert "No filter named 'format_rssi' found" not in response_text
            assert "Node detail error:" not in response_text
        else:
            # If node doesn't exist, should return 404, not 500 with filter error
            assert response.status_code == 404

    @pytest.mark.e2e
    def test_node_detail_page_template_filters_work(self, client):
        """Test that template filters work correctly with any existing node."""
        # First get a list of nodes to find one that exists
        response = client.get("/api/nodes?limit=1")
        assert response.status_code == 200

        data = response.get_json()
        if data.get("nodes") and len(data["nodes"]) > 0:
            # Use the first available node
            test_node_id = data["nodes"][0]["node_id"]

            response = client.get(f"/node/{test_node_id}")
            assert response.status_code == 200

            response_text = response.get_data(as_text=True)
            assert "No filter named 'format_rssi' found" not in response_text
            assert "No filter named 'format_snr' found" not in response_text
            assert "Node detail error:" not in response_text

    @pytest.mark.e2e
    def test_node_detail_page_has_expected_content(self, client):
        """Test that node detail page contains expected content."""
        response = client.get("/node/1128074276")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should contain basic node information sections
        assert "Node Information" in response_text
        assert "Total Packets" in response_text
        assert "Avg RSSI" in response_text

        # Should not have template errors
        assert (
            "format_rssi" not in response_text
        )  # Should not show filter name in rendered output
        assert (
            "format_snr" not in response_text
        )  # Should not show filter name in rendered output

    @pytest.mark.e2e
    def test_node_detail_page_handles_missing_node(self, client):
        """Test node detail page with non-existent node."""
        response = client.get("/node/999999999")
        assert response.status_code == 404

    @pytest.mark.e2e
    def test_node_detail_page_handles_invalid_node_id(self, client):
        """Test node detail page with invalid node ID format."""
        response = client.get("/node/invalid")
        assert response.status_code == 400

    @pytest.mark.e2e
    def test_node_detail_page_rssi_snr_formatting(self, client):
        """Test that RSSI and SNR values are properly formatted when present."""
        # Get a node that exists and check if RSSI/SNR formatting works
        response = client.get("/node/1128074276")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Check that if RSSI values are present, they are formatted correctly
        # Look for patterns like "-XX.X dBm" or "N/A"
        import re

        # Should not contain the raw filter name
        assert "format_rssi" not in response_text
        assert "format_snr" not in response_text

        # If RSSI values are present, they should be formatted
        rssi_patterns = re.findall(r"-?\d+\.\d+ dBm", response_text)
        # If we find RSSI patterns, they should be properly formatted (X.X format)
        for pattern in rssi_patterns:
            # Extract the number part
            number = pattern.replace(" dBm", "")
            # Should have exactly one decimal place for RSSI
            assert "." in number
            decimal_part = number.split(".")[1]
            # RSSI should be formatted to 1 decimal place
            assert len(decimal_part) == 1

        # Similar check for SNR values (should be X.XX format)
        snr_patterns = re.findall(
            r"-?\d+\.\d+ dB(?!\w)", response_text
        )  # dB but not dBm
        for pattern in snr_patterns:
            number = pattern.replace(" dB", "")
            if "." in number:
                decimal_part = number.split(".")[1]
                # SNR should be formatted to 2 decimal places
                assert len(decimal_part) <= 2  # Allow 1 or 2 decimal places
