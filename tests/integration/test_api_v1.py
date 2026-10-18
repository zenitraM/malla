"""Integration tests for the versioned JSON API (``/api/v1``).

Covers the response-envelope contract (data/meta success shape, error shape),
pagination math, filters, the canonical node-id forms, the OpenAPI document
and cache headers. Deterministic: runs against the shared fixture database
via the standard ``client`` fixture.
"""

import math

import pytest


def _get(client, path):
    return client.get(path)


def _assert_envelope(data) -> None:
    assert isinstance(data, dict)
    assert set(data.keys()) == {"data", "meta"}
    assert isinstance(data["meta"], dict)


def _error_body(response):
    assert response.content_type.startswith("application/json")
    body = response.get_json()
    assert isinstance(body, dict)
    assert "error" in body
    error = body["error"]
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


def _iso_from_epoch(ts: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


NODE_CANONICAL = "!433d0c24"
NODE_DECIMAL = 1128074276


class TestApiV1Envelope:
    @pytest.mark.integration
    def test_packets_list_envelope(self, client):
        response = _get(client, "/api/v1/packets")
        assert response.status_code == 200
        assert response.content_type.startswith("application/json")
        body = response.get_json()
        _assert_envelope(body)
        assert isinstance(body["data"], list)
        assert body["data"], "fixture database must contain packets"
        assert isinstance(body["meta"]["query"], dict)

    @pytest.mark.integration
    def test_packets_pagination_math(self, client):
        first = _get(client, "/api/v1/packets?page_size=3&page=1").get_json()
        second = _get(client, "/api/v1/packets?page_size=3&page=2").get_json()
        for body in (first, second):
            _assert_envelope(body)
        total = first["meta"]["pagination"]["total"]
        assert total > 0
        for body, page in ((first, 1), (second, 2)):
            pagination = body["meta"]["pagination"]
            assert pagination["page"] == page
            assert pagination["page_size"] == 3
            assert pagination["total"] == total
            assert pagination["total_pages"] == math.ceil(total / 3)
            assert pagination["has_next"] == (page * 3 < total)
            assert pagination["has_prev"] == (page > 1)
        assert len(first["data"]) == min(3, total)
        assert len(second["data"]) == max(0, min(3, total - 3))

        beyond = _get(client, "/api/v1/packets?page_size=3&page=99").get_json()
        assert beyond["data"] == []
        assert beyond["meta"]["pagination"]["has_next"] is False

    @pytest.mark.integration
    def test_packet_detail_envelope(self, client):
        response = _get(client, "/api/v1/packets/1")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        data = body["data"]
        assert data["packet"]["id"] == 1
        assert "other_receptions" in data
        assert body["meta"]["query"] == {"packet_id": 1}

    @pytest.mark.integration
    def test_traceroutes_list_envelope(self, client):
        response = _get(client, "/api/v1/traceroutes")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        assert isinstance(body["data"], list)
        assert "pagination" in body["meta"]

    @pytest.mark.integration
    def test_gateways_list_envelope(self, client):
        response = _get(client, "/api/v1/gateways")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        assert isinstance(body["data"], list)
        assert body["data"], "fixture database must contain gateways"
        assert "gateway_id" in body["data"][0]

    @pytest.mark.integration
    def test_stats_summary_envelope(self, client):
        response = _get(client, "/api/v1/stats/summary?range=24h")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        data = body["data"]
        for key in (
            "range",
            "totals",
            "activity",
            "top_nodes",
            "signal_quality",
            "transport_types",
        ):
            assert key in data
        totals = data["totals"]
        for key in ("total_nodes", "active_nodes_24h", "total_packets"):
            assert isinstance(totals[key], int)
        assert data["range"] == "24h"
        assert "buckets" in data["activity"]

    @pytest.mark.integration
    def test_meta_envelope(self, client):
        response = _get(client, "/api/v1/meta")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        data = body["data"]
        for key in (
            "name",
            "version",
            "node_count",
            "database_size_bytes",
            "server_time_utc",
        ):
            assert key in data
        assert isinstance(data["node_count"], int)
        assert data["node_count"] >= 0
        assert isinstance(data["database_size_bytes"], int)
        assert data["database_size_bytes"] > 0
        assert data["server_time_utc"].endswith("Z")


class TestApiV1Nodes:
    @pytest.mark.integration
    def test_node_id_forms_are_equivalent(self, client):
        canonical = _get(client, f"/api/v1/nodes/{NODE_CANONICAL}").get_json()
        bare_hex = _get(client, "/api/v1/nodes/433d0c24").get_json()
        decimal = _get(client, f"/api/v1/nodes/{NODE_DECIMAL}").get_json()
        for body in (canonical, bare_hex, decimal):
            assert body["data"]["node"]["node_id"] == NODE_DECIMAL
        assert canonical["data"]["node"]["node_id"] == NODE_DECIMAL

    @pytest.mark.integration
    def test_node_detail_shape(self, client):
        response = _get(client, f"/api/v1/nodes/{NODE_CANONICAL}")
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["node"]["hex_id"] == NODE_CANONICAL
        assert "traceroute_stats" in data

    @pytest.mark.integration
    def test_node_not_found(self, client):
        response = _get(client, "/api/v1/nodes/12345678")
        assert response.status_code == 404
        assert _error_body(response)["code"] == "node_not_found"

    @pytest.mark.integration
    def test_role_filter(self, client):
        response = _get(client, "/api/v1/nodes?role=CLIENT")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        assert body["data"], "fixture contains CLIENT nodes"
        assert all(node["role"] == "CLIENT" for node in body["data"])
        assert body["meta"]["query"]["role"] == "CLIENT"

    @pytest.mark.integration
    def test_q_filter_matches_names(self, client):
        response = _get(client, "/api/v1/nodes?q=Test")
        assert response.status_code == 200
        body = response.get_json()
        assert body["meta"]["pagination"]["total"] >= 1
        assert len(body["data"]) >= 1

    @pytest.mark.integration
    def test_has_position_filter(self, client):
        response = _get(client, "/api/v1/nodes?has_position=true")
        assert response.status_code == 200
        body = response.get_json()
        assert all(node["has_position"] is True for node in body["data"])

    @pytest.mark.integration
    def test_sort_keys_accepted(self, client):
        for sort in ("name", "last_seen", "snr", "battery"):
            response = _get(client, f"/api/v1/nodes?sort={sort}")
            assert response.status_code == 200
            body = response.get_json()
            assert body["meta"]["query"]["sort"] == sort
        names = [
            node["long_name"]
            for node in _get(client, "/api/v1/nodes?sort=name&order=asc").get_json()[
                "data"
            ]
        ]
        present = [name for name in names if name is not None]
        assert present == sorted(present, key=str.casefold)

    @pytest.mark.integration
    def test_invalid_params_rejected(self, client):
        for query, code in (
            ("last_seen_since=not-a-date", "invalid_parameter"),
            ("page=0", "invalid_page"),
            ("page_size=99999", "invalid_page_size"),
            ("sort=popularity", "invalid_parameter"),
        ):
            response = _get(client, f"/api/v1/nodes?{query}")
            assert response.status_code == 400, query
            assert _error_body(response)["code"] == code, query

    @pytest.mark.integration
    def test_malformed_node_id(self, client):
        response = _get(client, "/api/v1/nodes/abc!extra")
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_node_id"


class TestApiV1NodePacketsAndTelemetry:
    @pytest.mark.integration
    def test_node_packets_scope(self, client):
        response = _get(client, f"/api/v1/nodes/{NODE_DECIMAL}/packets?direction=sent")
        assert response.status_code == 200
        body = response.get_json()
        _assert_envelope(body)
        assert body["data"], "node 1128074277 sent packets in fixtures? see sent"
        assert all(packet["from_node_id"] == NODE_DECIMAL for packet in body["data"])

    @pytest.mark.integration
    def test_node_packets_unknown_node(self, client):
        response = _get(client, "/api/v1/nodes/12345678/packets")
        assert response.status_code == 404
        assert _error_body(response)["code"] == "node_not_found"

    @pytest.mark.integration
    def test_telemetry_shape(self, client):
        response = _get(client, f"/api/v1/nodes/{NODE_DECIMAL}/telemetry")
        assert response.status_code == 200
        data = response.get_json()["data"]
        for key in ("node_id", "hex_id", "window", "series", "count"):
            assert key in data
        assert data["hex_id"] == NODE_CANONICAL

    @pytest.mark.integration
    def test_telemetry_metric_filter(self, client):
        response = _get(
            client, f"/api/v1/nodes/{NODE_DECIMAL}/telemetry?metric=battery_level"
        )
        assert response.status_code == 200
        series = response.get_json()["data"]["series"]
        assert set(series.keys()) <= {"battery_level"}

    @pytest.mark.integration
    def test_telemetry_unknown_metric(self, client):
        response = _get(
            client, f"/api/v1/nodes/{NODE_DECIMAL}/telemetry?metric=fluffiness"
        )
        assert response.status_code == 400
        error = _error_body(response)
        assert error["code"] == "invalid_metric"
        assert "battery_level" in error["message"]

    @pytest.mark.integration
    def test_telemetry_unknown_node(self, client):
        response = _get(client, "/api/v1/nodes/12345678/telemetry")
        assert response.status_code == 404


class TestApiV1Errors:
    @pytest.mark.integration
    def test_packet_not_found(self, client):
        response = _get(client, "/api/v1/packets/999999")
        assert response.status_code == 404
        assert response.content_type.startswith("application/json")
        assert _error_body(response)["code"] == "packet_not_found"

    @pytest.mark.integration
    def test_traceroute_not_found(self, client):
        response = _get(client, "/api/v1/traceroutes/999999")
        assert response.status_code == 404
        assert _error_body(response)["code"] == "traceroute_not_found"

    @pytest.mark.integration
    def test_gateway_not_found(self, client):
        response = _get(client, "/api/v1/gateways/does-not-exist")
        assert response.status_code == 404
        assert _error_body(response)["code"] == "gateway_not_found"

    @pytest.mark.integration
    def test_unknown_route_within_versioned_prefix(self, client):
        response = _get(client, "/api/v1/definitely/not/a/route")
        assert response.status_code == 404
        assert response.content_type.startswith("application/json")
        assert _error_body(response)["code"] == "not_found"

    @pytest.mark.integration
    def test_invalid_stats_range(self, client):
        response = _get(client, "/api/v1/stats/summary?range=2h")
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_parameter"


class TestApiV1OpenAPI:
    @pytest.mark.integration
    def test_openapi_document_is_valid_structure(self, client):
        response = _get(client, "/api/v1/openapi.json")
        assert response.status_code == 200
        spec = response.get_json()
        assert spec["openapi"].startswith("3.1")
        assert spec["info"]["title"]
        assert spec["info"]["version"]
        assert isinstance(spec["paths"], dict) and spec["paths"]

    @pytest.mark.integration
    def test_every_documented_path_declares_responses(self, client):
        spec = _get(client, "/api/v1/openapi.json").get_json()
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                assert "responses" in operation, (path, method)
                assert operation["responses"], (path, method)
                for status, response in operation["responses"].items():
                    assert "description" in response, (path, method, status)

    @pytest.mark.integration
    def test_resource_paths_documented(self, client):
        spec = _get(client, "/api/v1/openapi.json").get_json()
        expected = {
            "/api/v1/nodes",
            "/api/v1/nodes/{node_id}",
            "/api/v1/nodes/{node_id}/telemetry",
            "/api/v1/nodes/{node_id}/packets",
            "/api/v1/packets",
            "/api/v1/packets/{packet_id}",
            "/api/v1/traceroutes",
            "/api/v1/traceroutes/{packet_id}",
            "/api/v1/gateways",
            "/api/v1/gateways/{gateway_id}",
            "/api/v1/stats/summary",
            "/api/v1/meta",
        }
        assert expected <= set(spec["paths"])

    @pytest.mark.integration
    def test_openapi_matches_registered_routes(self, client, app):
        import re

        def normalize(path: str) -> str:
            return re.sub(r"<[^>]+>|\{[^}]+\}", "{}", path)

        spec = _get(client, "/api/v1/openapi.json").get_json()
        documented = {normalize(path) for path in spec["paths"]}
        registered = {
            normalize(rule.rule)
            for rule in app.url_map.iter_rules()
            if rule.rule.startswith("/api/v1") and "static" not in rule.endpoint
        }
        assert documented == registered


class TestApiV1CacheHeaders:
    @pytest.mark.integration
    def test_packet_and_traceroute_listings_cached(self, client):
        for path in (
            "/api/v1/packets",
            "/api/v1/traceroutes",
            f"/api/v1/nodes/{NODE_DECIMAL}/packets",
        ):
            response = _get(client, path)
            assert response.headers.get("Cache-Control") == "public, max-age=30", path

    @pytest.mark.integration
    def test_stats_and_meta_uncached(self, client):
        for path in ("/api/v1/stats/summary", "/api/v1/meta", "/api/v1/nodes"):
            response = _get(client, path)
            assert "Cache-Control" not in response.headers, path


class TestApiV1Docs:
    @pytest.mark.integration
    def test_docs_page_removed(self, client):
        """The HTML reference page is gone; the v1 API is internal-only."""
        response = _get(client, "/api/v1/docs")
        assert response.status_code == 404


class TestApiV1Enrichment:
    """Phase-3 additive enrichment: names + text preview on list rows."""

    @pytest.mark.integration
    def test_packet_rows_carry_name_enrichment(self, client):
        body = client.get("/api/v1/packets?page_size=5").get_json()
        for packet in body["data"]:
            names = packet["names"]
            assert set(names.keys()) == {"from", "to", "gateway"}
            for side in ("from", "to"):
                entry = names[side]
                if entry is None:
                    continue
                assert entry["hex_id"] == f"!{entry['node_id']:08x}"
                assert isinstance(entry["display_name"], str)
                assert isinstance(entry["short_name"], str)
            gateway = names["gateway"]
            if gateway is not None:
                assert gateway["hex_id"] == packet["gateway_id"]

    @pytest.mark.integration
    def test_packet_text_preview_matches_legacy_helper(self, client):
        rows = client.get(
            "/api/v1/packets?portnum=TEXT_MESSAGE_APP&page_size=5"
        ).get_json()["data"]
        assert rows, "fixtures contain text messages"
        for packet in rows:
            assert isinstance(packet["text_content"], str)
            assert len(packet["text_content"]) <= 100

    @pytest.mark.integration
    def test_non_text_packets_have_null_preview(self, client):
        rows = client.get("/api/v1/packets?page_size=50").get_json()["data"]
        assert rows
        for packet in rows:
            if packet["portnum_name"] != "TEXT_MESSAGE_APP":
                assert packet["text_content"] is None

    @pytest.mark.integration
    def test_node_packets_share_enrichment_shape(self, client):
        body = client.get("/api/v1/nodes/1128074276/packets?direction=sent").get_json()
        assert body["data"]
        for packet in body["data"]:
            assert packet["names"]["from"]["node_id"] == 1128074276
            assert "text_content" in packet

    @pytest.mark.integration
    def test_traceroute_rows_carry_name_enrichment(self, client):
        rows = client.get("/api/v1/traceroutes?page_size=5").get_json()["data"]
        assert rows, "fixtures contain traceroutes"
        for row in rows:
            names = row["names"]
            assert set(names.keys()) == {"from", "to", "gateway", "route"}
            assert names["from"] is None or isinstance(
                names["from"]["display_name"], str
            )
            for entry in names["route"]:
                assert entry["hex_id"] == f"!{entry['node_id']:08x}"

    @pytest.mark.integration
    def test_traceroute_detail_carries_name_enrichment(self, client):
        rows = client.get("/api/v1/traceroutes?page_size=1").get_json()["data"]
        packet_id = rows[0]["id"]
        data = client.get(f"/api/v1/traceroutes/{packet_id}").get_json()["data"]
        assert "names" in data
        assert data["names"]["from"] is None or isinstance(
            data["names"]["from"]["node_id"], int
        )


class TestApiV1NodeDetailEnrichment:
    """Phase-3b: detail-only gateway_count_24h (legacy parity)."""

    @pytest.mark.integration
    def test_detail_gateway_count_matches_legacy_node_info(self, client):
        detail = client.get(f"/api/v1/nodes/{NODE_DECIMAL}").get_json()["data"]
        legacy = client.get(f"/api/node/{NODE_DECIMAL}/info").get_json()
        count = detail["node"]["gateway_count_24h"]
        assert isinstance(count, int)
        assert count == legacy["node"]["gateway_count_24h"]

    @pytest.mark.integration
    def test_detail_packet_count_matches_legacy_node_info(self, client):
        detail = client.get(f"/api/v1/nodes/{NODE_DECIMAL}").get_json()["data"]
        legacy = client.get(f"/api/node/{NODE_DECIMAL}/info").get_json()
        packets = detail["node"]["packet_count_24h"]
        assert isinstance(packets, int)
        assert packets == legacy["node"]["packet_count_24h"]

    @pytest.mark.integration
    def test_gateway_count_is_non_negative(self, client):
        detail = client.get(f"/api/v1/nodes/{NODE_CANONICAL}").get_json()["data"]
        assert detail["node"]["gateway_count_24h"] >= 0

    def test_firmware_absent_without_column(self, client):
        # node_info carries no firmware column; the detail node object must
        # not pretend one exists until the schema grows it.
        node = client.get(f"/api/v1/nodes/{NODE_DECIMAL}").get_json()["data"]["node"]
        assert "firmware_version" not in node

    def test_list_rows_remain_unchanged(self, client):
        rows = client.get("/api/v1/nodes?page_size=5").get_json()["data"]
        assert rows
        for row in rows:
            assert "gateway_count_24h" not in row


class TestApiV1SortAndTimeParams:
    """Phase-5 additive sort keys / time bounds (index-gated)."""

    @pytest.mark.integration
    def test_packets_sort_by_portnum_name(self, client):
        response = client.get(
            "/api/v1/packets?sort=portnum_name&order=asc&page_size=20"
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["meta"]["query"]["sort"] == "portnum_name"
        names = [p["portnum_name"] for p in body["data"]]
        present = [n for n in names if n is not None]
        assert present == sorted(present)

    @pytest.mark.integration
    def test_packets_skipped_sort_keys_rejected(self, client):
        # channel_id / relay_node failed the EXPLAIN QUERY PLAN gate and are
        # intentionally not part of the vocabulary.
        for key in ("channel_id", "relay_node"):
            response = client.get(f"/api/v1/packets?sort={key}")
            assert response.status_code == 400, key
            assert _error_body(response)["code"] == "invalid_parameter"

    @pytest.mark.integration
    def test_node_packets_sort_by_portnum_name(self, client):
        response = client.get(
            f"/api/v1/nodes/{NODE_DECIMAL}/packets?direction=sent&sort=portnum_name"
        )
        assert response.status_code == 200
        assert response.get_json()["meta"]["query"]["sort"] == "portnum_name"

    @pytest.mark.integration
    def test_traceroutes_until_filter(self, client):
        # A bound in the distant past excludes every fixture traceroute.
        response = client.get("/api/v1/traceroutes?until=2001-01-01T00:00:00Z")
        assert response.status_code == 200
        body = response.get_json()
        assert body["data"] == []
        assert body["meta"]["pagination"]["total"] == 0
        assert body["meta"]["query"]["until"].startswith("2001-01-01")

    @pytest.mark.integration
    def test_traceroutes_since_until_window(self, client):
        response = client.get(
            "/api/v1/traceroutes?since=2001-01-01T00:00:00Z&until=2099-01-01T00:00:00Z"
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["meta"]["query"]["since"].startswith("2001-01-01")
        assert body["meta"]["query"]["until"].startswith("2099-01-01")
        assert body["meta"]["pagination"]["total"] >= 1

    @pytest.mark.integration
    def test_traceroutes_sort_by_id(self, client):
        response = client.get("/api/v1/traceroutes?sort=id&order=asc&page_size=20")
        assert response.status_code == 200
        body = response.get_json()
        assert body["meta"]["query"] == {
            "page": 1,
            "page_size": 20,
            "sort": "id",
            "order": "asc",
        }
        ids = [row["id"] for row in body["data"]]
        assert ids == sorted(ids)

    @pytest.mark.integration
    def test_traceroutes_invalid_params(self, client):
        for query, code in (
            ("sort=payload_length", "invalid_parameter"),
            ("order=sideways", "invalid_parameter"),
            ("until=not-a-date", "invalid_parameter"),
        ):
            response = client.get(f"/api/v1/traceroutes?{query}")
            assert response.status_code == 400, query
            assert _error_body(response)["code"] == code, query


class TestApiV1MetaFilters:
    """Phase-8: dropdown enumerations in one call, byte-identical to legacy."""

    @pytest.mark.integration
    def test_filters_parity_with_legacy_endpoints(self, client):
        data = client.get("/api/v1/meta/filters").get_json()["data"]
        assert (
            data["hardware_models"]
            == client.get("/api/meshtastic/hardware-models").get_json()[
                "hardware_models"
            ]
        )
        assert (
            data["roles"]
            == client.get("/api/meshtastic/node-roles").get_json()["node_roles"]
        )
        assert (
            data["channels"]
            == client.get("/api/meshtastic/channels").get_json()["channels"]
        )
        assert (
            data["packet_types"]
            == client.get("/api/meshtastic/packet-types").get_json()["packet_types"]
        )
        assert (
            data["packet_channels"]
            == client.get("/api/meshtastic/packet-channels").get_json()["channels"]
        )

    @pytest.mark.integration
    def test_filters_non_empty_on_fixture_database(self, client):
        data = client.get("/api/v1/meta/filters").get_json()["data"]
        assert len(data["hardware_models"]) > 0
        assert len(data["roles"]) > 0
        assert data["channels"], "fixture nodes declare primary channels"
        assert len(data["packet_types"]) > 0
        assert data["packet_channels"], "fixture packets carry channel ids"


class TestApiV1Locations:
    """Phase-8: bulk latest positions (legacy row shape) + node history."""

    @pytest.mark.integration
    def test_bulk_locations_legacy_row_shape(self, client):
        body = client.get("/api/v1/locations").get_json()
        assert body["data"], "fixture nodes have positions"
        assert body["meta"]["pagination"]["total"] == len(body["data"])
        for row in body["data"]:
            for key in ("node_id", "hex_id", "latitude", "longitude", "timestamp"):
                assert key in row, key
            assert row["timestamp"].endswith("Z")
            assert "timestamp_str" not in row

    @pytest.mark.integration
    def test_bulk_locations_pagination(self, client):
        body = client.get("/api/v1/locations?page_size=5").get_json()
        assert len(body["data"]) == min(5, body["meta"]["pagination"]["total"])
        assert body["meta"]["query"]["page_size"] == 5

    @pytest.mark.integration
    def test_bulk_locations_gateway_filter_narrows(self, client):
        everything = client.get("/api/v1/locations?page_size=5000").get_json()
        filtered_response = client.get("/api/v1/locations?gateway_id=1128074276")
        assert filtered_response.status_code == 200
        filtered = filtered_response.get_json()
        assert (
            filtered["meta"]["pagination"]["total"]
            <= everything["meta"]["pagination"]["total"]
        )
        assert filtered["meta"]["query"]["gateway_id"] == "!433d0c24"

    @pytest.mark.integration
    def test_bulk_locations_invalid_params(self, client):
        for query, code in (
            ("page=0", "invalid_page"),
            ("page_size=999999", "invalid_page_size"),
            (
                "since=2099-01-01T00:00:00Z&until=2001-01-01T00:00:00Z",
                "invalid_parameter",
            ),
            ("since=garbage", "invalid_parameter"),
        ):
            response = client.get(f"/api/v1/locations?{query}")
            assert response.status_code == 400, query
            assert _error_body(response)["code"] == code, query

    @pytest.mark.integration
    def test_node_locations_default_and_limit(self, client):
        default = client.get(f"/api/v1/nodes/{NODE_DECIMAL}/locations").get_json()
        assert default["data"]["hex_id"] == NODE_CANONICAL
        assert default["meta"]["query"]["limit"] == 10
        assert len(default["data"]["locations"]) <= 10

        limited = client.get(
            f"/api/v1/nodes/{NODE_DECIMAL}/locations?limit=5"
        ).get_json()
        assert limited["meta"]["query"]["limit"] == 5
        assert len(limited["data"]["locations"]) <= 5

    @pytest.mark.integration
    def test_node_locations_matches_legacy_history(self, client):
        v1_rows = client.get(
            f"/api/v1/nodes/{NODE_DECIMAL}/locations?limit=5"
        ).get_json()["data"]["locations"]
        legacy_rows = client.get(
            f"/api/node/{NODE_DECIMAL}/location-history?limit=5"
        ).get_json()["location_history"]
        assert len(v1_rows) == len(legacy_rows)
        for v1_row, legacy_row in zip(v1_rows, legacy_rows, strict=True):
            assert v1_row["latitude"] == legacy_row["latitude"]
            assert v1_row["longitude"] == legacy_row["longitude"]
            assert v1_row["timestamp"] == _iso_from_epoch(legacy_row["timestamp"])

    @pytest.mark.integration
    def test_node_locations_bounds(self, client):
        for limit in ("0", "3000", "abc"):
            response = client.get(
                f"/api/v1/nodes/{NODE_DECIMAL}/locations?limit={limit}"
            )
            assert response.status_code == 400, limit
            assert _error_body(response)["code"] == "invalid_parameter"
        missing = client.get("/api/v1/nodes/12345678/locations")
        assert missing.status_code == 404
        assert _error_body(missing)["code"] == "node_not_found"

    @pytest.mark.integration
    def test_include_links_default_payload_unchanged(self, client):
        body = client.get("/api/v1/locations").get_json()
        assert set(body.keys()) == {"data", "meta"}
        assert "include_links" not in body["meta"]["query"]

    @pytest.mark.integration
    def test_include_links_adds_legacy_link_arrays(self, client):
        plain = client.get("/api/v1/locations?page_size=5000").get_json()
        with_links = client.get(
            "/api/v1/locations?page_size=5000&include_links=true"
        ).get_json()
        assert set(with_links.keys()) == {"data", "meta", "links"}
        assert with_links["meta"]["query"]["include_links"] is True
        # Positions payload is byte-identical regardless of the flag.
        assert with_links["data"] == plain["data"]

        legacy = client.get("/api/locations").get_json()
        assert with_links["links"]["traceroute_links"] == legacy["traceroute_links"]
        assert with_links["links"]["packet_links"] == legacy["packet_links"]

    @pytest.mark.integration
    def test_include_links_invalid_value(self, client):
        response = client.get("/api/v1/locations?include_links=maybe")
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_parameter"


class TestApiV1PacketDetailRobustness:
    """Regression: packet detail must never 500 on traceroute payloads."""

    @pytest.mark.integration
    def test_traceroute_packet_details_return_200(self, client):
        for packet_id in (10000, 10001, 10002):
            response = client.get(f"/api/v1/packets/{packet_id}")
            assert response.status_code == 200, packet_id
            data = response.get_json()["data"]
            assert data["packet"]["id"] == packet_id
            payload_data = data["payload_info"]["data"]
            assert "traceroute_packet" not in payload_data
            for derived in ("route_nodes", "has_return_path", "is_complete"):
                assert derived in payload_data, (packet_id, derived)

    @pytest.mark.integration
    def test_every_fixture_packet_detail_returns_200(self, client, app):
        import sqlite3

        connection = sqlite3.connect(app.config["DATABASE_FILE"])
        try:
            packet_ids = [
                row[0] for row in connection.execute("SELECT id FROM packet_history")
            ]
        finally:
            connection.close()
        assert packet_ids, "fixture database must contain packets"
        failures = []
        for packet_id in packet_ids:
            if client.get(f"/api/v1/packets/{packet_id}").status_code != 200:
                failures.append(packet_id)
        assert failures == []


class TestApiV1NodeCountsAndFastLocations:
    """Phase-11: cheap count strategy + positions-only locations fast path."""

    @pytest.mark.integration
    def test_node_total_matches_rows_for_filtered_queries(self, client):
        for query in ("", "role=CLIENT", "has_position=true", "q=Test"):
            body = client.get(f"/api/v1/nodes?page_size=500&{query}").get_json()
            total = body["meta"]["pagination"]["total"]
            assert total == len(body["data"]), query

    @pytest.mark.integration
    def test_node_totals_are_pagination_stable(self, client):
        first = client.get("/api/v1/nodes?page_size=5&page=1").get_json()
        second = client.get("/api/v1/nodes?page_size=5&page=2").get_json()
        assert (
            first["meta"]["pagination"]["total"]
            == second["meta"]["pagination"]["total"]
        )
        assert first["meta"]["pagination"]["total"] > 0

    @pytest.mark.integration
    def test_locations_enrich_false_matches_positions(self, client):
        default = client.get("/api/v1/locations").get_json()
        fast = client.get("/api/v1/locations?enrich=false").get_json()
        assert fast["meta"]["query"]["enrich"] is False
        assert "enrich" not in default["meta"]["query"]
        assert [row["node_id"] for row in fast["data"]] == [
            row["node_id"] for row in default["data"]
        ]
        for fast_row, default_row in zip(fast["data"], default["data"], strict=True):
            for key in ("latitude", "longitude", "timestamp", "hex_id"):
                assert fast_row[key] == default_row[key]
        # neighbour enrichment is what the fast path deliberately skips
        assert all(row.get("direct_neighbors", 0) == 0 for row in fast["data"])

    @pytest.mark.integration
    def test_locations_cache_header(self, client):
        assert (
            client.get("/api/v1/locations").headers.get("Cache-Control")
            == "public, max-age=30"
        )
        assert (
            client.get("/api/v1/locations?enrich=false").headers.get("Cache-Control")
            == "public, max-age=30"
        )

    @pytest.mark.integration
    def test_locations_invalid_enrich_value(self, client):
        response = client.get("/api/v1/locations?enrich=sometimes")
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_parameter"


class TestApiV1LegacyParityEndpoints:
    """Phase-13: v1 mirrors of the remaining internal endpoints, byte-equal."""

    PARITY_CASES = [
        ("/api/v1/chat/messages?limit=5", "/api/chat/messages?limit=5"),
        ("/api/v1/chat/relay-filters", "/api/chat/relay-filters"),
        ("/api/v1/longest-links?max_results=5", "/api/longest-links?max_results=5"),
        ("/api/v1/traceroute-graph?hours=24", "/api/traceroute/graph?hours=24"),
        ("/api/v1/traceroute-hops/nodes", "/api/traceroute-hops/nodes"),
        (
            "/api/v1/traceroute-link/1128074276/1128074277",
            "/api/traceroute/link/1128074276/1128074277",
        ),
        (
            "/api/v1/related-nodes/1128074276",
            "/api/traceroute/related-nodes/1128074276",
        ),
        (
            "/api/v1/nodes/1128074276/direct-receptions?limit=5",
            "/api/node/1128074276/direct-receptions?limit=5",
        ),
        (
            "/api/v1/nodes/1128074276/relay-node-analysis?limit=5",
            "/api/node/1128074276/relay-node-analysis?limit=5",
        ),
    ]

    @pytest.mark.integration
    @pytest.mark.parametrize("v1_path,legacy_path", PARITY_CASES)
    def test_payload_matches_legacy(self, client, v1_path, legacy_path):
        v1_response = client.get(v1_path)
        legacy_response = client.get(legacy_path)
        assert v1_response.status_code == 200, v1_path
        assert legacy_response.status_code == 200, legacy_path
        body = v1_response.get_json()
        assert set(body.keys()) == {"data", "meta"}
        assert body["data"] == legacy_response.get_json(), v1_path

    @pytest.mark.integration
    def test_chat_messages_shape(self, client):
        data = client.get("/api/v1/chat/messages?limit=5").get_json()["data"]
        for key in ("packets", "nodes"):
            assert key in data

    @pytest.mark.integration
    def test_direct_receptions_direction_validation(self, client):
        response = client.get(
            "/api/v1/nodes/1128074276/direct-receptions?direction=sideways"
        )
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_parameter"

    @pytest.mark.integration
    def test_traceroute_link_malformed_node(self, client):
        response = client.get("/api/v1/traceroute-link/abc!x/1128074277")
        assert response.status_code == 400
        assert _error_body(response)["code"] == "invalid_parameter"

    @pytest.mark.integration
    def test_related_nodes_unknown_node_matches_legacy(self, client):
        # The legacy handler treats unknown nodes as "no connections" (200 with
        # an empty list) rather than 404; the mirror keeps that behaviour.
        v1_body = client.get("/api/v1/related-nodes/12345678").get_json()
        legacy = client.get("/api/traceroute/related-nodes/12345678").get_json()
        assert v1_body["data"] == legacy
        assert v1_body["data"]["related_nodes"] == []


class TestApiV1GroupedModes:
    """Server-side grouping: group_by=mesh_packet_id must have honest totals."""

    @staticmethod
    def _fetch_all(client: object, base: str) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            body = client.get(f"{base}page={page}&page_size=500").get_json()
            rows.extend(body["data"])
            if not body["meta"]["pagination"]["has_next"]:
                return rows
            page += 1

    @staticmethod
    def _distinct_mesh(rows: list[dict]) -> int:
        return len(
            {
                row["mesh_packet_id"]
                for row in rows
                if row["mesh_packet_id"] is not None and row["mesh_packet_id"] != 0
            }
        )

    @pytest.mark.integration
    def test_grouped_packet_total_equals_distinct_mesh_ids(self, client):
        ungrouped = self._fetch_all(client, "/api/v1/packets?")
        expected = self._distinct_mesh(ungrouped)
        assert expected < len(ungrouped), "fixture must contain shared mesh ids"

        body = client.get("/api/v1/packets?group_by=mesh_packet_id&page_size=500")
        assert body.status_code == 200
        body = body.get_json()
        assert body["meta"]["pagination"]["total"] == expected
        assert body["meta"]["query"]["group_by"] == "mesh_packet_id"
        assert len(body["data"]) == min(expected, 500)
        for row in body["data"]:
            assert row["mesh_packet_id"] is not None
            assert set(row["group"].keys()) == {"reception_count", "gateways"}

    @pytest.mark.integration
    def test_grouped_reception_counts_sum_to_ungrouped_rows(self, client):
        ungrouped = self._fetch_all(client, "/api/v1/packets?")
        meshed = [
            row
            for row in ungrouped
            if row["mesh_packet_id"] is not None and row["mesh_packet_id"] != 0
        ]

        grouped = self._fetch_all(client, "/api/v1/packets?group_by=mesh_packet_id&")
        assert sum(row["group"]["reception_count"] for row in grouped) == len(meshed)

        multi = [row for row in grouped if row["group"]["reception_count"] > 1]
        assert multi, "fixture must contain multi-reception mesh ids"
        for row in multi:
            assert len(row["group"]["gateways"]) >= 2
            entry = row["group"]["gateways"][0]
            assert entry["hex_id"].startswith("!")

    @pytest.mark.integration
    def test_grouped_rows_carry_ungrouped_shape_plus_group(self, client):
        ungrouped = client.get("/api/v1/packets?page_size=5").get_json()["data"]
        grouped = client.get(
            "/api/v1/packets?group_by=mesh_packet_id&page_size=5"
        ).get_json()["data"]
        assert grouped
        assert set(grouped[0].keys()) == set(ungrouped[0].keys()) | {"group"}
        assert grouped[0]["is_grouped"] is True

    @pytest.mark.integration
    def test_grouped_traceroutes_mirror_ungrouped_counts(self, client):
        ungrouped = self._fetch_all(client, "/api/v1/traceroutes?")
        expected = self._distinct_mesh(ungrouped)

        grouped = self._fetch_all(
            client, "/api/v1/traceroutes?group_by=mesh_packet_id&"
        )
        total = client.get(
            "/api/v1/traceroutes?group_by=mesh_packet_id&page_size=1"
        ).get_json()["meta"]["pagination"]["total"]
        assert total == expected
        assert len(grouped) == expected
        assert sum(row["group"]["reception_count"] for row in grouped) == len(
            [
                row
                for row in ungrouped
                if row["mesh_packet_id"] is not None and row["mesh_packet_id"] != 0
            ]
        )

    @pytest.mark.integration
    @pytest.mark.parametrize("path", ["/api/v1/packets", "/api/v1/traceroutes"])
    def test_unknown_group_by_rejected(self, client, path):
        response = client.get(f"{path}?group_by=banana")
        assert response.status_code == 400
        error = response.get_json()["error"]
        assert error["code"] == "invalid_parameter"
        assert error["details"] == {"group_by": "banana"}


class TestPacketDetailReceptionFilters:
    """The detail endpoint must interpret the same filters as the list."""

    @pytest.mark.integration
    def test_decimal_gateway_id_matches_hex(self, client):
        grouped = client.get(
            "/api/v1/packets?group_by=mesh_packet_id&page_size=500"
        ).get_json()["data"]
        row = next(r for r in grouped if r["group"]["reception_count"] > 1)
        gateway_hex = row["gateway_id"]
        gateway_decimal = int(gateway_hex[1:], 16)

        by_hex = client.get(
            f"/api/v1/packets/{row['id']}?gateway_id={gateway_hex}"
        ).get_json()["data"]
        by_decimal = client.get(
            f"/api/v1/packets/{row['id']}?gateway_id={gateway_decimal}"
        ).get_json()["data"]

        assert by_decimal["other_receptions"] == by_hex["other_receptions"]
        assert by_decimal["reception_count"] == by_hex["reception_count"]

    @pytest.mark.integration
    def test_min_rssi_narrows_the_expanded_receptions(self, client):
        grouped = client.get(
            "/api/v1/packets?group_by=mesh_packet_id&page_size=500"
        ).get_json()["data"]
        row = next(r for r in grouped if r["group"]["reception_count"] > 1)
        all_receptions = client.get(f"/api/v1/packets/{row['id']}").get_json()["data"]
        rssis = [
            r["rssi"]
            for r in all_receptions["other_receptions"]
            if r["rssi"] is not None
        ]
        assert rssis
        threshold = min(rssis) + 1
        expected = 1 + sum(
            1
            for r in all_receptions["other_receptions"]
            if r["rssi"] is not None and r["rssi"] >= threshold
        )

        filtered = client.get(
            f"/api/v1/packets/{row['id']}?min_rssi={threshold}"
        ).get_json()["data"]
        assert filtered["reception_count"] == expected

    @pytest.mark.integration
    def test_database_error_handler_maps_missing_index(self, client):
        import sqlite3

        from src.malla.routes.api_v1 import _handle_database_error

        with client.application.app_context():
            response = _handle_database_error(
                sqlite3.OperationalError(
                    "no such index: idx_packet_history_from_time_desc"
                )
            )
        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "database_not_initialized"


class TestLocationsWindowBound:
    @pytest.mark.integration
    def test_explicit_all_time_window_is_clamped(self, client):
        from src.malla.routes.api_v1 import LOCATIONS_MAX_WINDOW_DAYS

        body = client.get("/api/v1/locations?since=0&until=9999999999").get_json()
        query = body["meta"]["query"]
        from datetime import datetime

        since = datetime.fromisoformat(query["since"].replace("Z", "+00:00"))
        until = datetime.fromisoformat(query["until"].replace("Z", "+00:00"))
        assert (until - since).total_seconds() <= LOCATIONS_MAX_WINDOW_DAYS * 86400 + 1
