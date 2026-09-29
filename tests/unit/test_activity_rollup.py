"""Quarter-hour activity buckets: exactness for any offset, increments, migration."""

import sqlite3
import time

from malla import activity_rollup
from malla.migrations import MIGRATIONS, Phase, Status, run_migrations
from malla.migrations.derived import ACTIVITY_QUARTER_BACKFILL
from malla.services.analytics_service import AnalyticsService

HOUR = 3600
DAY = 86400
#: Fixed clock in the past, aligned to a bucket boundary, so the fixtures are
#: deterministic and older than the real clock the migrations compare against.
NOW = 1_699_999_200.0
#: Whole-hour offsets plus the ones that are not: +05:30, +05:45, +09:30, +12:45.
OFFSETS = (0, 60, 120, 330, 345, 570, 765, -300, -720)


def _make_db(path, *, start: float = NOW - 2 * DAY, end: float = NOW - HOUR):
    """packet_history with a packet every ~7 minutes from 40 rotating nodes."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn, MIGRATIONS, phases=(Phase.SCHEMA,), take_lock=False)
    rows = []
    timestamp = start
    node = 1
    while timestamp < end:
        rows.append(
            (
                timestamp,
                "msh/x",
                node,
                "!gwA" if node % 2 else "!gwB",
                3,
                3,
                1,
            )
        )
        timestamp += 421
        node = node % 40 + 1
    conn.executemany(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, gateway_id, "
        "hop_start, hop_limit, processed_successfully) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return conn, len(rows)


def test_buckets_reproduce_the_live_aggregation_for_every_offset(tmp_path):
    """Shifting the stored buckets must match the per-day aggregation exactly.

    Includes the offsets that are not whole hours: with 15-minute buckets the
    local day always starts on a bucket boundary, so nothing is mis-assigned.
    """
    conn, packets = _make_db(tmp_path / "rollup.db")
    assert packets > 100
    assert activity_rollup.refresh(conn, until=NOW) > 0

    start_utc = activity_rollup.bucket_start(NOW - 2 * DAY)
    end_utc = activity_rollup.bucket_start(NOW)  # only completed buckets
    cursor = conn.cursor()

    for offset_minutes in OFFSETS:
        offset_sec = offset_minutes * 60
        live = AnalyticsService._compute_daily_span(
            cursor, offset_sec, start_utc + offset_sec, end_utc + offset_sec
        )
        stored = activity_rollup.daily_buckets(
            conn,
            tz_offset_minutes=offset_minutes,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        assert set(stored) == set(live), f"offset {offset_minutes} days differ"
        for day, expected in live.items():
            for metric in ("total_packets", "active_nodes", "gateway_count"):
                assert stored[day][metric] == expected[metric], (
                    offset_minutes,
                    day,
                    metric,
                )
    conn.close()


def test_new_nodes_by_day_matches_the_live_aggregation(tmp_path):
    """new_nodes comes from node_info, so it is exact for any offset too."""

    conn, _packets = _make_db(tmp_path / "nodes.db")
    conn.executemany(
        "INSERT INTO node_info (node_id, first_seen, last_updated) VALUES (?, ?, ?)",
        [(i, NOW - 2 * DAY + i * 601, NOW) for i in range(1, 30)],
    )
    conn.commit()

    start_utc = activity_rollup.bucket_start(NOW - 2 * DAY)
    end_utc = activity_rollup.bucket_start(NOW)
    cursor = conn.cursor()
    for offset_minutes in OFFSETS:
        offset_sec = offset_minutes * 60
        live = AnalyticsService._compute_daily_span(
            cursor, offset_sec, start_utc + offset_sec, end_utc + offset_sec
        )
        stored = activity_rollup.new_nodes_by_day(
            conn,
            tz_offset_minutes=offset_minutes,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        for day in set(live) | set(stored):
            assert live.get(day, {}).get("new_nodes", 0) == stored.get(day, 0), (
                offset_minutes,
                day,
            )
    conn.close()


def test_refresh_is_idempotent_and_only_adds_new_buckets(tmp_path):
    conn, _packets = _make_db(tmp_path / "incremental.db")

    first = activity_rollup.refresh(conn, until=NOW)
    assert first > 0
    newest = activity_rollup.latest_bucket(conn)
    assert newest is not None
    assert newest < activity_rollup.bucket_start(NOW)  # only completed buckets

    # Same window again: no new rows, nothing pending.
    assert activity_rollup.refresh(conn, until=NOW) == 0
    assert activity_rollup.pending(conn, until=NOW) is False

    # A packet in a completed bucket after the newest one reopens the work and
    # adds exactly that bucket.
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, processed_successfully)"
        " VALUES (?, 'msh/x', 7, 1)",
        (NOW - 1800,),
    )
    conn.commit()
    assert activity_rollup.pending(conn, until=NOW) is True
    assert activity_rollup.refresh(conn, until=NOW) > 0
    assert activity_rollup.pending(conn, until=NOW) is False

    # A packet in the still-open bucket changes nothing yet.
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, processed_successfully)"
        " VALUES (?, 'msh/x', 8, 1)",
        (NOW + 60,),
    )
    conn.commit()
    assert activity_rollup.pending(conn, until=NOW) is False
    conn.close()


def test_pending_ignores_a_quiet_mesh(tmp_path):
    """No packets in the gap means nothing to store, regardless of the clock."""

    conn, _packets = _make_db(tmp_path / "quiet.db", end=NOW - 2 * DAY + HOUR)
    activity_rollup.refresh(conn, until=NOW)
    assert activity_rollup.pending(conn, until=NOW) is False
    assert activity_rollup.pending(conn, until=NOW + 30 * DAY) is False
    conn.close()


def test_activity_backfill_migration_runs_once_then_self_heals(tmp_path):
    conn, _packets = _make_db(tmp_path / "migration.db")

    first = run_migrations(
        conn, (ACTIVITY_QUARTER_BACKFILL,), phases=(Phase.DERIVED,), take_lock=False
    )
    assert [result.status for result in first] == [Status.APPLIED]
    assert activity_rollup.latest_bucket(conn) is not None

    second = run_migrations(
        conn, (ACTIVITY_QUARTER_BACKFILL,), phases=(Phase.DERIVED,), take_lock=False
    )
    assert [result.status for result in second] == [Status.SKIPPED]

    # New completed history makes it pending again: the migration is data-aware,
    # so a restart after downtime fills the gap without a marker to manage.
    conn.execute(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, processed_successfully)"
        " VALUES (?, 'msh/x', 3, 1)",
        (time.time() - 2 * HOUR,),
    )
    conn.commit()
    third = run_migrations(
        conn, (ACTIVITY_QUARTER_BACKFILL,), phases=(Phase.DERIVED,), take_lock=False
    )
    assert [result.status for result in third] == [Status.APPLIED]
    conn.close()


def test_timeline_snaps_viewer_offsets_to_a_quarter_hour(tmp_path, monkeypatch):
    """Offsets that are not multiples of 15 minutes are snapped, not mis-served.

    The packet below sits one minute before the +05:30 local midnight, so a
    request that honoured a raw +05:33 offset would count it in the next day and
    return different daily totals.
    """

    db = str(tmp_path / "snap.db")
    conn = sqlite3.connect(db)
    run_migrations(conn, MIGRATIONS, phases=(Phase.SCHEMA,), take_lock=False)

    now = time.time()
    offset_minutes = 330
    now_local = now + offset_minutes * 60
    day_start_local = (int(now_local) // DAY) * DAY
    boundary_utc = day_start_local - offset_minutes * 60  # local midnight, in UTC
    conn.executemany(
        "INSERT INTO packet_history (timestamp, topic, from_node_id, processed_successfully)"
        " VALUES (?, 'msh/x', ?, 1)",
        [(boundary_utc - 60, 1), (boundary_utc - 3 * HOUR, 2)],
    )
    conn.commit()
    activity_rollup.refresh(conn, until=now)
    conn.close()

    monkeypatch.setenv("MALLA_DATABASE_FILE", db)
    AnalyticsService._TIMELINE_CACHE.clear()
    snapped = AnalyticsService.get_activity_timeline("7d", offset_minutes)
    AnalyticsService._TIMELINE_CACHE.clear()
    raw_offset = AnalyticsService.get_activity_timeline("7d", offset_minutes + 3)

    assert snapped["buckets"] == raw_offset["buckets"]
