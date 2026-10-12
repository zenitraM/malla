"""Tests for the 7-day rolling network-coverage denominator and daily activity.

node_info only ever grows (it remembers every node ever seen), so the old
coverage ratio active_nodes_24h / total_nodes decayed toward zero as the
roster aged. These tests pin the replacement: both sides of the ratio come
from packet_history, with a trailing-7-day roster as the denominator, plus
the per-local-day activity buckets that feed the dashboard trends chart.
"""

import sqlite3
import time

import malla.database.repositories as repositories
from malla import activity_rollup
from malla.database.repositories import DashboardRepository
from malla.services.analytics_service import AnalyticsService

HOUR = 3600
DAY = 86400


def _reset_data(db_path: str, packets, nodes):
    """Replace fixture data with a controlled set of packets and nodes."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM packet_history")
    cursor.execute("DELETE FROM node_info")
    cursor.executemany(
        """INSERT INTO packet_history
           (timestamp, topic, from_node_id, gateway_id, hop_start, hop_limit,
            processed_successfully)
           VALUES (?, 'test', ?, ?, ?, ?, 1)""",
        packets,
    )
    cursor.executemany(
        "INSERT INTO node_info (node_id, first_seen, last_updated) VALUES (?, ?, ?)",
        nodes,
    )
    conn.commit()
    conn.close()


def _build_buckets(db_path: str) -> None:
    """Fill the activity buckets the way the capture daemon does.

    Completed days are served from this store, so tests that assert numbers for
    days before today have to seed it (exactly like seeding packet_history).
    """
    conn = sqlite3.connect(db_path)
    activity_rollup.refresh(conn)
    conn.close()


def test_nodes_seen_7d_rolling_window(temp_database, monkeypatch):
    """Coverage denominator counts distinct senders in 7d, not the all-time roster."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    repositories._dashboard_stats_cache.clear()

    now = time.time()
    _reset_data(
        temp_database,
        packets=[
            (now - HOUR, 1, "!gw1", 3, 3),  # node 1: active in 24h and 7d
            (now - 3 * DAY, 2, "!gw1", 3, 3),  # node 2: in 7d only
            (now - 10 * DAY, 3, "!gw1", 3, 3),  # node 3: outside the window
        ],
        nodes=[
            (1, now - 10 * DAY, now),
            (2, now - 10 * DAY, now),
            (3, now - 10 * DAY, now),
        ],
    )

    stats = DashboardRepository.get_stats()

    assert stats["total_nodes"] == 3
    assert stats["active_nodes_24h"] == 1
    assert stats["nodes_seen_7d"] == 2


def test_node_activity_statistics_use_7d_roster(temp_database, monkeypatch):
    """Analytics activity rate and 'inactive' compare 24h activity to the 7d roster."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

    now = time.time()
    _reset_data(
        temp_database,
        packets=[
            (now - HOUR, 1, "!gw1", 3, 3),
            (now - 3 * DAY, 2, "!gw1", 3, 3),
            (now - 10 * DAY, 3, "!gw1", 3, 3),
        ],
        nodes=[
            (1, now - 10 * DAY, now),
            (2, now - 10 * DAY, now),
            (3, now - 10 * DAY, now),
        ],
    )

    stats = AnalyticsService._get_node_activity_statistics(
        {}, now - 24 * HOUR, now - 7 * DAY
    )

    assert stats["active_nodes"] == 1
    assert stats["nodes_seen_7d"] == 2
    assert stats["inactive_nodes"] == 1
    assert stats["activity_rate"] == 50.0
    assert stats["activity_distribution"]["inactive"] == 1
    # The all-time roster is still reported for reference.
    assert stats["total_nodes"] == 3


def test_timeline_7d_buckets_align_to_local_days(temp_database, monkeypatch):
    """Packets either side of a local midnight land in different buckets."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()

    tz_offset_minutes = 480  # UTC+8
    offset_sec = tz_offset_minutes * 60
    now = time.time()
    local_today_start = (int(now + offset_sec) // DAY) * DAY
    ts_today = local_today_start - offset_sec + 1800  # 00:30 local today
    ts_yesterday = local_today_start - offset_sec - 1800  # 23:30 local yesterday

    _reset_data(
        temp_database,
        packets=[
            (ts_today, 1, "!gw1", 3, 3),
            (ts_yesterday, 2, "!gw2", 3, 3),
            (ts_yesterday - 60, 2, "!gw2", 3, 3),
        ],
        nodes=[(1, ts_today, now), (2, ts_yesterday, now)],
    )

    _build_buckets(temp_database)

    timeline = AnalyticsService.get_activity_timeline("7d", tz_offset_minutes)
    days = timeline["buckets"]

    assert timeline["granularity"] == "day"
    assert len(days) == 8  # 7 complete local days + today so far
    assert days == sorted(days, key=lambda d: d["bucket"])

    today, yesterday = days[-1], days[-2]
    assert today["total_packets"] == 1
    assert today["active_nodes"] == 1
    assert today["gateway_count"] == 1
    assert today["new_nodes"] == 1
    assert yesterday["total_packets"] == 2
    assert yesterday["active_nodes"] == 1
    assert yesterday["gateway_count"] == 1
    assert yesterday["new_nodes"] == 1
    assert all(d["total_packets"] == 0 and d["active_nodes"] == 0 for d in days[:-2])


def test_timeline_completed_days_come_from_buckets(temp_database, monkeypatch):
    """Completed days are served from the activity buckets, today is recomputed."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()

    tz_offset_minutes = 0
    now = time.time()
    local_today_start = (int(now) // DAY) * DAY
    ts_yesterday = local_today_start - 12 * HOUR

    _reset_data(
        temp_database,
        packets=[
            (ts_yesterday, 1, "!gw1", 3, 3),
            (ts_yesterday + 60, 2, "!gw1", 3, 3),
            (now, 3, "!gw1", 3, 3),
        ],
        nodes=[(1, ts_yesterday, now)],
    )

    _build_buckets(temp_database)

    first = AnalyticsService.get_activity_timeline("7d", tz_offset_minutes)
    assert first["buckets"][-2]["total_packets"] == 2
    assert "pending" not in first and "days_remaining" not in first

    # The completed day comes from the bucket store the capture maintains.
    conn = sqlite3.connect(temp_database)
    stored_buckets = conn.execute(
        "SELECT MIN(bucket), MAX(bucket) FROM activity_packet_quarter"
    ).fetchone()
    conn.close()
    assert stored_buckets[0] is not None

    # A packet backdated into a completed day must NOT change it — the bucket
    # was built from the packets seen at the time and is not rescanned — while
    # today stays live.
    conn = sqlite3.connect(temp_database)
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, gateway_id, "
        "hop_start, hop_limit, processed_successfully) VALUES (?, 'test', 9, '!gw9', 3, 3, 1)",
        (ts_yesterday + 120,),
    )
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, gateway_id, "
        "hop_start, hop_limit, processed_successfully) VALUES (?, 'test', 4, '!gw1', 3, 3, 1)",
        (now,),
    )
    conn.commit()
    conn.close()

    AnalyticsService._TIMELINE_CACHE.clear()
    second = AnalyticsService.get_activity_timeline("7d", tz_offset_minutes)
    assert second["buckets"][-2]["total_packets"] == 2  # unchanged, from rollup
    assert second["buckets"][-1]["total_packets"] == 2  # today recomputed live


def test_timeline_24h_hourly_buckets(temp_database, monkeypatch):
    """The 24h range returns 24 hourly buckets ending at the current hour."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()

    now = time.time()
    # Clamp into the current hour: a plain ``now - 60`` lands in the previous
    # hour's bucket when the test runs within the first minute of an hour.
    ts_current_hour = max(now - 60, (int(now) // HOUR) * HOUR + 1)
    _reset_data(
        temp_database,
        packets=[
            (ts_current_hour, 1, "!gw1", 3, 3),  # current hour
            (now - 5 * HOUR, 2, "!gw1", 3, 3),
            (now - 5 * HOUR + 30, 2, "!gw1", 3, 3),
            (now - 30 * HOUR, 3, "!gw1", 3, 3),  # outside the window
        ],
        nodes=[(1, ts_current_hour, now)],
    )

    timeline = AnalyticsService.get_activity_timeline("24h", 0)
    buckets = timeline["buckets"]

    assert timeline["granularity"] == "hour"
    assert len(buckets) == 24
    assert buckets[-1]["total_packets"] == 1
    five_hours_ago = buckets[-6]
    assert five_hours_ago["total_packets"] == 2
    assert five_hours_ago["active_nodes"] == 1
    assert sum(b["total_packets"] for b in buckets) == 3


def test_timeline_all_starts_at_first_packet(temp_database, monkeypatch):
    """The all range spans from the first packet's local day through today."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()

    now = time.time()
    _reset_data(
        temp_database,
        packets=[
            (now - 3 * DAY, 1, "!gw1", 3, 3),
            (now, 2, "!gw1", 3, 3),
        ],
        nodes=[(1, now - 3 * DAY, now)],
    )

    _build_buckets(temp_database)

    timeline = AnalyticsService.get_activity_timeline("all", 0)
    buckets = timeline["buckets"]

    # 3 days ago .. today inclusive = 4 or 5 buckets depending on where "now"
    # sits inside the day; the first bucket must hold the oldest packet.
    assert 4 <= len(buckets) <= 5
    assert buckets[0]["total_packets"] == 1
    assert buckets[-1]["total_packets"] == 1
    assert sum(b["total_packets"] for b in buckets) == 2


def test_timeline_read_path_never_writes(temp_database, monkeypatch):
    """A timeline request is read-only and carries no backfill contract.

    The web UI used to aggregate and persist missing days per request, which is
    why responses had ``pending``/``days_remaining`` and why the process needed
    write access. The capture daemon owns the bucket store now.
    """
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()

    now = time.time()
    local_today_start = (int(now) // DAY) * DAY
    _reset_data(
        temp_database,
        packets=[
            (local_today_start - d * DAY + HOUR, d, "!gw1", 3, 3) for d in (1, 2, 3)
        ]
        + [(now, 9, "!gw9", 3, 3)],
        nodes=[(1, now - 10 * DAY, now)],
    )

    def snapshot() -> tuple[int, set[str]]:
        conn = sqlite3.connect(temp_database)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM activity_packet_quarter"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            return count, tables
        finally:
            conn.close()

    before = snapshot()
    assert before[0] == 0  # nothing built yet: the request must not build it
    assert "activity_daily_rollup" not in before[1]

    timeline = AnalyticsService.get_activity_timeline("7d", 0)

    assert "pending" not in timeline and "days_remaining" not in timeline
    assert snapshot() == before  # a request writes nothing at all

    # With the store filled (as the capture does), completed days carry data.
    _build_buckets(temp_database)
    AnalyticsService._TIMELINE_CACHE.clear()
    filled = AnalyticsService.get_activity_timeline("7d", 0)
    days = filled["buckets"]
    assert len(days) == 8
    assert days[-1]["total_packets"] == 1  # today, computed live
    assert all(day["total_packets"] == 1 for day in days[-4:-1])

def test_hop_distribution_counts_real_hops(temp_database, monkeypatch):
    """Hop distribution reflects hop_start - hop_limit, excluding malformed rows."""
    monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

    now = time.time()
    _reset_data(
        temp_database,
        packets=[
            (now - HOUR, 1, "!gw1", 3, 3),  # 0 hops
            (now - HOUR, 1, "!gw1", 3, 3),  # 0 hops
            (now - HOUR, 2, "!gw1", 3, 2),  # 1 hop
            (now - HOUR, 3, "!gw1", 5, 2),  # 3 hops
            (now - HOUR, 4, "!gw1", 2, 3),  # malformed (negative), excluded
            (now - HOUR, 5, "!gw1", None, None),  # unknown hops, excluded
            (now - HOUR, 7, "!gw1", 173, 0),  # corrupt frame (3-bit field), excluded
            (now - 2 * DAY, 6, "!gw1", 3, 3),  # outside 24h window
        ],
        nodes=[(1, now - DAY, now)],
    )

    distribution = AnalyticsService._get_hop_distribution({}, now - 24 * HOUR)
    counts = {row["hops"]: row["count"] for row in distribution}

    assert counts == {0: 2, 1: 1, 3: 1}
