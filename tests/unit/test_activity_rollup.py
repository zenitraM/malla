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

    cursor = conn.cursor()

    for offset_minutes in OFFSETS:
        window = activity_rollup.viewer_window(offset_minutes, now=NOW, days=2)
        assert window.end_utc <= NOW  # only completed buckets
        live = AnalyticsService._compute_daily_span(
            cursor, window.offset_sec, window.start_local, window.today_local
        )
        stored = activity_rollup.daily_buckets(conn, window)
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

    cursor = conn.cursor()
    for offset_minutes in OFFSETS:
        window = activity_rollup.viewer_window(offset_minutes, now=NOW, days=2)
        live = AnalyticsService._compute_daily_span(
            cursor, window.offset_sec, window.start_local, window.today_local
        )
        stored = activity_rollup.new_nodes_by_day(conn, window)
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


def test_viewer_window_carries_the_floored_offset_and_aligned_bounds():
    """A window is the only way the readers see an offset, so they cannot disagree."""
    window = activity_rollup.viewer_window(333, now=NOW, days=7)

    assert window.offset_minutes == 330  # floored, not the raw 333
    assert window.offset_sec == 330 * 60
    assert window.end_utc % activity_rollup.BUCKET_SECONDS == 0
    assert window.start_utc % activity_rollup.BUCKET_SECONDS == 0
    assert window.day_epochs[0] == window.start_local
    assert window.day_epochs[-1] == window.today_local
    assert len(window.day_epochs) == 8  # seven completed days plus today

    # "all" starts at the first packet's local day, never after today.
    window_all = activity_rollup.viewer_window(0, now=NOW, since=NOW - 3 * DAY)
    assert len(window_all.day_epochs) == 4
    future = activity_rollup.viewer_window(0, now=NOW, since=NOW + DAY)
    assert future.start_local == future.today_local


def test_snap_offset_floors_to_a_quarter_hour():
    assert activity_rollup.snap_offset_minutes(0) == 0
    assert activity_rollup.snap_offset_minutes(330) == 330
    assert activity_rollup.snap_offset_minutes(333) == 330
    assert activity_rollup.snap_offset_minutes(-32) == -45  # floored, not nearest
    assert activity_rollup.snap_offset_minutes(33) == 30


def test_prune_before_removes_only_old_buckets(tmp_path):
    conn, _packets = _make_db(tmp_path / "prune.db")
    activity_rollup.refresh(conn, until=NOW)
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in activity_rollup.TABLES
    }
    assert all(count > 0 for count in before.values())

    # Cutting in the middle of the retained window removes the older buckets
    # only; newer buckets and packet_history are untouched.
    cutoff = NOW - DAY
    assert activity_rollup.prune_before(conn, cutoff) > 0

    for table in activity_rollup.TABLES:
        newest_old = conn.execute(
            f"SELECT MAX(bucket) FROM {table} WHERE bucket < ?", (cutoff,)
        ).fetchone()[0]
        assert newest_old is None
    assert conn.execute("SELECT COUNT(*) FROM packet_history").fetchone()[0] > 0
    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in activity_rollup.TABLES
    }
    assert all(after[table] < before[table] for table in activity_rollup.TABLES)
    conn.close()


def test_chunked_refresh_matches_the_unchunked_result(tmp_path):
    """max_bucket_span only slices the transactions; the store is identical."""
    conn_a, _ = _make_db(tmp_path / "whole.db")
    conn_b, _ = _make_db(tmp_path / "chunked.db")

    assert activity_rollup.refresh(conn_b, until=NOW, max_bucket_span=3) > 0
    assert activity_rollup.refresh(conn_a, until=NOW) > 0

    for table in activity_rollup.TABLES:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        assert rows_a == rows_b, table

    # And the chunked store is complete: nothing pending, idempotent again.
    assert activity_rollup.pending(conn_b, until=NOW) is False
    assert activity_rollup.refresh(conn_b, until=NOW, max_bucket_span=3) == 0
    conn_a.close()
    conn_b.close()


def test_prune_refold_keeps_bucket_sums_exact(tmp_path):
    """After a retention cut, buckets agree with the surviving packet rows.

    The boundary bucket keeps packets from both sides of the cutoff in the
    store; the prune must re-fold it from what retention left behind, or its
    counts silently include the deleted ones forever.
    """
    conn, _packets = _make_db(tmp_path / "refold.db")
    assert activity_rollup.refresh(conn, until=NOW) > 0

    # Cut just after a packet that shares its bucket with the next one, so the
    # boundary bucket definitely loses rows to the retention delete.
    bucket, first_ts = conn.execute(
        "SELECT CAST(timestamp / ? AS INT) * ?, MIN(timestamp) FROM packet_history "
        "GROUP BY 1 HAVING COUNT(*) >= 2 ORDER BY 1 DESC LIMIT 1",
        (activity_rollup.BUCKET_SECONDS, activity_rollup.BUCKET_SECONDS),
    ).fetchone()
    cutoff = first_ts + 1
    cutoff_bucket = bucket
    conn.execute("DELETE FROM packet_history WHERE timestamp < ?", (cutoff,))

    # Pre-refold, the boundary bucket still counts the deleted packets.
    stale = dict(
        conn.execute(
            "SELECT bucket, total_packets FROM activity_packet_quarter WHERE bucket = ?",
            (cutoff_bucket,),
        ).fetchone()
    )

    activity_rollup.prune_before(conn, cutoff)
    conn.commit()

    live = dict(
        conn.execute(
            "SELECT CAST(timestamp / ? AS INT) * ? AS b, COUNT(*) "
            "FROM packet_history GROUP BY b",
            (activity_rollup.BUCKET_SECONDS, activity_rollup.BUCKET_SECONDS),
        ).fetchall()
    )
    stored = dict(
        conn.execute("SELECT bucket, total_packets FROM activity_packet_quarter")
    )
    assert stored == live
    assert (
        stale["total_packets"] > stored[cutoff_bucket]
    )  # refold dropped the gone ones

    # Same for the identity buckets: every stored node/gateway is still there.
    for table, stored_col, live_col in (
        (activity_rollup.NODE_TABLE, "node_id", "from_node_id"),
        (activity_rollup.GATEWAY_TABLE, "gateway_id", "gateway_id"),
    ):
        live_ids = dict(
            conn.execute(
                f"SELECT CAST(timestamp / ? AS INT) * ? AS b, COUNT(DISTINCT {live_col}) "
                f"FROM packet_history WHERE {live_col} IS NOT NULL GROUP BY b",
                (activity_rollup.BUCKET_SECONDS, activity_rollup.BUCKET_SECONDS),
            ).fetchall()
        )
        stored_ids = dict(
            conn.execute(
                f"SELECT bucket, COUNT(DISTINCT {stored_col}) FROM {table} "
                "GROUP BY bucket"
            ).fetchall()
        )
        assert stored_ids == live_ids, table
    conn.close()


def test_hourly_timeline_matches_the_live_aggregation(tmp_path):
    """The bucket-backed hourly view equals the live SQL, hour for hour."""
    from malla.services.analytics_service import AnalyticsService

    # Packets running into the current hour so the live tail is exercised too.
    conn, _packets = _make_db(tmp_path / "hourly.db", end=NOW - 61)
    assert activity_rollup.refresh(conn, until=NOW) > 0
    cursor = conn.cursor()

    for offset_minutes in OFFSETS:
        offset_sec = offset_minutes * 60
        current_hour_local = (int(NOW + offset_sec) // 3600) * 3600
        start_local = current_hour_local - 23 * 3600
        start_utc = start_local - offset_sec

        got = AnalyticsService._hourly_buckets_in_window(
            cursor, offset_sec, start_local, current_hour_local
        )

        # The historical live-only shape: zeros for every hour, then the
        # packet/gateway/new-node aggregates by local hour label.
        expected: dict[str, dict[str, int]] = {}
        for i in range(24):
            key = time.strftime("%Y-%m-%d %H:00", time.gmtime(start_local + i * 3600))
            expected[key] = {
                "bucket": key,
                "total_packets": 0,
                "active_nodes": 0,
                "gateway_count": 0,
                "new_nodes": 0,
            }
        for row in cursor.execute(
            """
            SELECT strftime('%Y-%m-%d %H:00', timestamp + ?, 'unixepoch') AS bucket,
                   COUNT(*) AS total_packets,
                   COUNT(DISTINCT from_node_id) AS active_nodes
            FROM packet_history WHERE timestamp >= ? GROUP BY bucket
            """,
            (offset_sec, start_utc),
        ):
            entry = expected.get(row["bucket"])
            if entry:
                entry["total_packets"] = row["total_packets"]
                entry["active_nodes"] = row["active_nodes"]
        for row in cursor.execute(
            """
            SELECT strftime('%Y-%m-%d %H:00', timestamp + ?, 'unixepoch') AS bucket,
                   COUNT(DISTINCT gateway_id) AS gateway_count
            FROM packet_history
            WHERE gateway_id IS NOT NULL AND timestamp >= ? GROUP BY bucket
            """,
            (offset_sec, start_utc),
        ):
            entry = expected.get(row["bucket"])
            if entry:
                entry["gateway_count"] = row["gateway_count"]
        for row in cursor.execute(
            """
            SELECT strftime('%Y-%m-%d %H:00', first_seen + ?, 'unixepoch') AS bucket,
                   COUNT(*) AS new_nodes
            FROM node_info WHERE first_seen >= ? GROUP BY bucket
            """,
            (offset_sec, start_utc),
        ):
            entry = expected.get(row["bucket"])
            if entry:
                entry["new_nodes"] = row["new_nodes"]

        assert got == list(expected.values()), offset_minutes

    conn.close()
