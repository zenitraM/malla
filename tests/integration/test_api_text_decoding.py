"""Test text message decoding functionality in API endpoints."""


class TestAPITextDecoding:
    """Test text message decoding in API responses."""

    def test_text_message_decoding_with_real_data(self, client):
        """Test that text messages are properly decoded from raw_payload."""
        # This test uses the test database with fixture data
        response = client.get("/api/packets/data?portnum=TEXT_MESSAGE_APP&limit=5")
        assert response.status_code == 200

        data = response.get_json()
        assert "data" in data

        # If we have text messages, verify they have proper structure
        if data["data"]:  # Only test if we have data
            for packet in data["data"]:
                assert packet.get("portnum_name") == "TEXT_MESSAGE_APP"
                assert "text_content" in packet
                assert "channel" in packet

                # text_content should be either a string or None
                if packet["text_content"] is not None:
                    assert isinstance(packet["text_content"], str)
                    # If truncated, should end with "..."
                    if len(packet["text_content"]) == 100:
                        assert packet["text_content"].endswith("...")
        else:
            # If no text messages in database, that's still a valid test result
            # The important thing is that the API responds correctly
            pass

    def test_non_text_messages_have_null_text_content(self, client):
        """Test that non-text messages have null text_content."""
        # Get non-text messages
        response = client.get("/api/packets/data?portnum=POSITION_APP&limit=5")
        assert response.status_code == 200

        data = response.get_json()
        assert "data" in data

        # Position packets should not have text content
        if data["data"]:  # Only test if we have data
            for packet in data["data"]:
                if packet.get("portnum_name") == "POSITION_APP":
                    assert "text_content" in packet
                    assert packet["text_content"] is None

    def test_channel_information_always_present(self, client):
        """Test that channel information is always present in API response."""
        response = client.get("/api/packets/data?limit=10")
        assert response.status_code == 200

        data = response.get_json()
        assert "data" in data

        # All packets should have channel information
        if data["data"]:  # Only test if we have data
            for packet in data["data"]:
                assert "channel" in packet
                assert isinstance(packet["channel"], str)
                assert len(packet["channel"]) > 0

    def test_sqlite_row_to_dict_conversion(self, client):
        """Test that sqlite3.Row objects are properly converted to dicts."""
        # This tests the specific bug that was causing the 500 error
        # The bug was calling packet.get() on a sqlite3.Row object

        # Make a request that would trigger the grouped packets code path
        response = client.get("/api/packets/data?group_packets=true&limit=5")
        assert response.status_code == 200

        data = response.get_json()
        assert "data" in data

        # If we have grouped packets, they should have proper structure
        for packet in data["data"]:
            if packet.get("is_grouped"):
                assert "text_content" in packet
                assert "channel" in packet

    def test_api_backwards_compatibility(self, client):
        """Test that the old /api/packets endpoint still works."""
        response = client.get("/api/packets?limit=5")
        assert response.status_code == 200

        data = response.get_json()
        assert "packets" in data

        # Old endpoint should not have raw_payload in response (to avoid JSON serialization issues)
        for packet in data["packets"]:
            assert "raw_payload" not in packet

    def test_text_message_content_truncation(self):
        """Test that long text messages are properly truncated."""
        # Create a test scenario with a long message
        long_text = "A" * 150  # 150 characters

        # Test the truncation logic directly
        from malla.database.repositories import PacketRepository

        test_packet = {
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": long_text.encode("utf-8"),
        }

        result = PacketRepository._decode_text_content(test_packet)
        assert result is not None
        assert len(result) == 100  # Should be truncated to 100 chars
        assert result.endswith("...")  # Should end with ellipsis
        assert result.startswith("AAA")  # Should start with original content

    def test_text_message_encoding_edge_cases(self):
        """Test text message decoding with various encoding scenarios."""
        from malla.database.repositories import PacketRepository

        # Test with bytes
        test_packet_bytes = {
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": "Hello, world! 🌍".encode(),
        }
        result = PacketRepository._decode_text_content(test_packet_bytes)
        assert result == "Hello, world! 🌍"

        # Test with string (should pass through)
        test_packet_string = {
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": "Hello, string!",
        }
        result = PacketRepository._decode_text_content(test_packet_string)
        assert result == "Hello, string!"

        # Test with non-text packet type
        test_packet_position = {
            "portnum_name": "POSITION_APP",
            "raw_payload": b"some binary data",
        }
        result = PacketRepository._decode_text_content(test_packet_position)
        assert result is None

        # Test with missing raw_payload
        test_packet_no_payload = {
            "portnum_name": "TEXT_MESSAGE_APP",
            "raw_payload": None,
        }
        result = PacketRepository._decode_text_content(test_packet_no_payload)
        assert result is None
