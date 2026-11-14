"""Per-link history API: parity with the capture-maintained rollups.

The endpoint must mirror a plain SQL read of ``link_day_rollup`` (direct)
/ ``route_day_rollup`` (indirect), canonicalize both node-id forms and
pair order, respect the ``days`` window, and answer unknown pairs with
200 + empty days.
"""

import sqlite3
import tempfile
import time
from datetime import UTC, datetime, timedelta

import pytest

from src.malla.config import AppConfig
from src.malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures

A = 999001
B = 999002
A_HEX = f"!{A:08x}"
B_HEX = f"!{B:08x}"


@pytest.fixture()
def link_client(monkeypatch):
    """App client on a fixture db plus the db path; rollup refresh off."""
    monkeypatch.setenv("MALLA_ROLLUP_REFRESH_SECONDS", "0")

    fd, db_path = tempfile.mkstemp(suffix=".db")

    import os

    os.close(fd)
    try:
        DatabaseFixtures().create_test_database(db_path)

        # Seed three days of direct history and two of indirect history for
        # one canonical pair, plus a second pair outside any window probe.
        conn = sqlite3.connect(db_path)
        today = datetime.now(UTC).date()
        days = [today - timedelta(offset) for offset in range(3)]
        for offset, day in enumerate(days):
            conn.execute(
                """
                INSERT OR IGNORE INTO link_day_rollup
                    (day, node_a, node_b, packet_count, snr_sum, snr_count,
                     snr_min, snr_max, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day.isoformat(),
                    min(A, B),
                    max(A, B),
                    4 + offset,
                    3.0 + offset,
                    2,
                    -2.5 + offset,
                    5.5 + offset,
                    time.mktime(day.timetuple()) + 3600,
                ),
            )
        for offset, day in enumerate(days[:2]):
            conn.execute(
                """
                INSERT OR IGNORE INTO route_day_rollup
                    (day, end_a, end_b, path_count, hop_count_sum,
                     snr_avg_sum, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day.isoformat(),
                    min(A, B),
                    max(A, B),
                    3,
                    6,
                    7.5 - offset,
                    time.mktime(day.timetuple()) + 7200,
                ),
            )
        conn.commit()
        conn.close()

        app = create_app(
            AppConfig(database_file=db_path, host="127.0.0.1", port=0, debug=False)
        )
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client, db_path
    finally:
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass


def _get(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    return response.get_json()


def _expected_direct(db_path: str, since_day: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT day, packet_count, snr_sum, snr_count, snr_min, snr_max, last_seen
        FROM link_day_rollup WHERE node_a = ? AND node_b = ? AND day >= ?
        ORDER BY day
        """,
        (min(A, B), max(A, B), since_day),
    ).fetchall()
    conn.close()
    return [
        {
            "day": row["day"],
            "packet_count": row["packet_count"],
            "snr_min": row["snr_min"],
            "snr_max": row["snr_max"],
            "snr_avg": round(row["snr_sum"] / row["snr_count"], 2),
            "last_seen": row["last_seen"],
        }
        for row in rows
    ]


@pytest.mark.integration
class TestLinkHistoryParity:
    def test_matches_direct_sql_both_orders_and_id_forms(self, link_client):
        client, db_path = link_client
        window = (datetime.now(UTC).date() - timedelta(days=89)).isoformat()
        expected = _expected_direct(db_path, window)
        assert len(expected) == 3  # seeded sanity

        for path in (
            f"/api/v1/links/{A}/{B}/history?days=90",
            f"/api/v1/links/{B}/{A}/history?days=90",
            f"/api/v1/links/{A_HEX}/{B_HEX}/history?days=90",
            f"/api/v1/links/{B_HEX}/{A}/history?days=90",
            f"/api/v1/links/{A:08x}/{B:08x}/history?days=90",  # bare hex
        ):
            body = _get(client, path)
            assert body["data"]["days"] == expected, path

    def test_range_filter_respected(self, link_client):
        client, _ = link_client
        today = datetime.now(UTC).date()

        one_day = _get(client, f"/api/v1/links/{A}/{B}/history?days=1")
        assert [row["day"] for row in one_day["data"]["days"]] == [today.isoformat()]

        two_days = _get(client, f"/api/v1/links/{A}/{B}/history?days=2")
        assert [row["day"] for row in two_days["data"]["days"]] == [
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
        ]

    def test_indirect_uses_route_rollup_shape(self, link_client):
        client, db_path = link_client
        window = (datetime.now(UTC).date() - timedelta(days=89)).isoformat()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT day, path_count, snr_avg_sum, last_seen FROM route_day_rollup
            WHERE end_a = ? AND end_b = ? AND day >= ? ORDER BY day
            """,
            (min(A, B), max(A, B), window),
        ).fetchall()
        conn.close()
        assert len(rows) == 2

        body = _get(client, f"/api/v1/links/{A}/{B}/history?days=90&indirect=true")
        days = body["data"]["days"]
        assert len(days) == 2
        for row, seed in zip(days, rows, strict=True):
            assert row["day"] == seed["day"]
            assert row["packet_count"] == seed["path_count"]
            assert row["snr_min"] is None and row["snr_max"] is None
            assert row["snr_avg"] == round(seed["snr_avg_sum"] / seed["path_count"], 2)
            assert row["last_seen"] == seed["last_seen"]

    def test_unknown_pair_is_200_empty(self, link_client):
        client, _ = link_client
        body = _get(client, "/api/v1/links/424242/424243/history")
        assert body["data"]["days"] == []

    @pytest.mark.parametrize(
        "path",
        (
            "/api/v1/links/notanid/2/history",
            "/api/v1/links/1/zz!history",
            "/api/v1/links/1/2/history?days=0",
            "/api/v1/links/1/2/history?days=91",
            "/api/v1/links/1/2/history?days=abc",
        ),
    )
    def test_bad_input_is_coded_4xx(self, link_client, path):
        client, _ = link_client
        response = client.get(path)
        assert 400 <= response.status_code < 500, path
        assert response.status_code != 500
