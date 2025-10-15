"""Integration tests for the chat feature."""

import sqlite3
import time


class TestChatFeature:
    """Validate chat API and page rendering."""

    def test_chat_page_loads(self, client):
        """The chat page should render successfully."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert b"Chat" in response.data
        assert b"Recent messages" in response.data

    def test_chat_messages_api(self, client):
        """API should return chat messages and channel metadata."""
        response = client.get("/api/chat/messages?limit=5")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, dict)
        assert "messages" in data
        assert "channels" in data
        assert "total" in data
        assert "limit" in data
        assert "senders" in data
        assert "counts" in data
        assert data["limit"] == 5
        assert "selected_audience" in data

        if data["messages"]:
            message = data["messages"][0]
            assert message["portnum_name"] == "TEXT_MESSAGE_APP"
            assert "message" in message
            assert "from_name" in message
            assert "from_node_id" in message
            assert "to_is_broadcast" in message
            assert "gateway_nodes" in message
            assert "gateway_count" in message
            assert "gateway_tooltip" in message
            if message.get("to_name") == "Broadcast":
                assert message["to_is_broadcast"] is True
            else:
                assert message["to_is_broadcast"] in (True, False)
            if message["gateway_nodes"]:
                assert message["gateway_count"] == len(message["gateway_nodes"])
                node = message["gateway_nodes"][0]
                assert "raw_id" in node
                assert "name" in node

        # If channel filters are available ensure they work
        for channel in data["channels"]:
            channel_id = channel["id"]
            if channel_id:
                filtered = client.get(f"/api/chat/messages?channel={channel_id}")
                assert filtered.status_code == 200
                filtered_data = filtered.get_json()
                assert filtered_data["selected_channel"] == channel_id
                for message in filtered_data["messages"]:
                    if channel_id == "__primary__":
                        assert message["channel_id"] in (None, "", "0")
                    else:
                        assert message["channel_key"] == channel_id
                break

        # Audience filter should respect direct/broadcast separation
        audience_filtered = client.get("/api/chat/messages?audience=broadcast&limit=20")
        assert audience_filtered.status_code == 200
        audience_payload = audience_filtered.get_json()
        assert audience_payload["selected_audience"] == "broadcast"
        for message in audience_payload["messages"]:
            assert message["to_is_broadcast"] is True

        # Counts payload should contain hour/day metrics
        counts = data["counts"]
        assert "last_hour" in counts
        assert "last_day" in counts

    def test_chat_filters_iso_timestamp_messages(self, client):
        """Timestamp-only payloads should be filtered out of chat results."""

        cfg = client.application.config["APP_CONFIG"]
        iso_text = "2025-10-15T16:17:01+03:00"
        now = time.time()

        conn = sqlite3.connect(cfg.database_file)
        conn.execute(
            """
            INSERT INTO packet_history (
                timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                gateway_id, channel_id, raw_payload, processed_successfully, mesh_packet_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                "msh/msk/2/e/LongFast",
                0x9EE9A33C,
                0x9EE70D3C,
                1,
                "TEXT_MESSAGE_APP",
                "!test_gateway",
                "LongFast",
                iso_text.encode("utf-8"),
                1,
                int(now),
            ),
        )
        conn.commit()
        conn.close()

        response = client.get("/api/chat/messages?limit=50")
        assert response.status_code == 200

        data = response.get_json()
        for message in data["messages"]:
            assert message["message"] != iso_text

    def test_chat_message_search(self, client):
        """Search parameter should filter messages within limited scope."""

        cfg = client.application.config["APP_CONFIG"]
        now = time.time()
        unique_text = "meshworks-search-marker"

        conn = sqlite3.connect(cfg.database_file)
        conn.execute(
            """
            INSERT INTO packet_history (
                timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                gateway_id, channel_id, raw_payload, processed_successfully, mesh_packet_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                "msh/msk/2/e/LongFast",
                0x9EE9A33C,
                0x9EE70D3C,
                1,
                "TEXT_MESSAGE_APP",
                "!search_gateway",
                "LongFast",
                unique_text.encode("utf-8"),
                1,
                int(now),
            ),
        )
        conn.commit()
        conn.close()

        response = client.get("/api/chat/messages?limit=25&q=search-marker")
        assert response.status_code == 200
        data = response.get_json()
        assert any(unique_text in message["message"] for message in data["messages"])
