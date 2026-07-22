"""Tests pinning the plausibility guards for RSSI/SNR signal metrics.

Corrupt gateway frames occasionally survive protobuf parsing and land in
packet_history with garbage signal values (observed in production: rssi
-1386841926, snr 2.8e-36, from a text frame misparsed as a MeshPacket).
One such row dragged the dashboard's 24h average RSSI to -29606 dBm.
These tests pin the fix: packet_history stores whatever the frame
contained (the faithful raw record — ingest does NOT sanitize), and every
read-side aggregate ignores implausible values.
"""

import sqlite3
import time

import malla.database.repositories as repositories
from malla.database.repositories import DashboardRepository
from malla.services.analytics_service import AnalyticsService
from malla.utils.signal_quality import (
    TRACEROUTE_UNKNOWN_SNR,
    is_plausible_rssi,
    is_plausible_snr,
    is_plausible_traceroute_snr,
    rssi_valid_sql,
    snr_valid_sql,
)

HOUR = 3600

# The exact garbage values observed in the production database.
GARBAGE_RSSI = -1386841926
GARBAGE_SNR = 2.8616148667626044e-36


def _insert_packets(db_path: str, rows):
    """Insert (timestamp, from_node_id, rssi, snr) rows into packet_history."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM packet_history")
    cursor.executemany(
        """INSERT INTO packet_history
           (timestamp, topic, from_node_id, gateway_id, rssi, snr,
            processed_successfully)
           VALUES (?, 'test', ?, '!gw1', ?, ?, 1)""",
        rows,
    )
    conn.commit()
    conn.close()


class TestPlausibilityPredicates:
    def test_real_values_are_plausible(self):
        assert is_plausible_rssi(-98)
        assert is_plausible_rssi(-137)
        assert is_plausible_rssi(-1)
        assert is_plausible_snr(-21.25)
        assert is_plausible_snr(15.5)
        assert is_plausible_snr(0.0)

    def test_sentinels_and_garbage_are_not_plausible_rssi(self):
        assert not is_plausible_rssi(None)
        assert not is_plausible_rssi(0)  # "not provided" sentinel
        assert not is_plausible_rssi(255)
        assert not is_plausible_rssi(GARBAGE_RSSI)
        assert not is_plausible_rssi(1070308180)
        assert not is_plausible_rssi(float("nan"))
        assert not is_plausible_rssi(float("-inf"))

    def test_garbage_is_not_plausible_snr(self):
        assert not is_plausible_snr(None)
        assert not is_plausible_snr(1e9)
        assert not is_plausible_snr(-1e9)
        assert not is_plausible_snr(float("nan"))
        assert not is_plausible_snr(float("inf"))

    def test_traceroute_unknown_snr_sentinel_is_kept(self):
        """Firmware encodes 'SNR unknown' as -128 (scaled -32.0 dB); traceroute
        consumers must keep those hops while the column-level predicate stays
        strict."""
        assert TRACEROUTE_UNKNOWN_SNR == -32.0
        assert is_plausible_traceroute_snr(TRACEROUTE_UNKNOWN_SNR)
        assert is_plausible_traceroute_snr(5.25)
        assert is_plausible_traceroute_snr(0.0)
        assert not is_plausible_traceroute_snr(None)
        assert not is_plausible_traceroute_snr(-1e9)
        assert not is_plausible_traceroute_snr(3.5e8)
        assert not is_plausible_snr(TRACEROUTE_UNKNOWN_SNR)

    def test_sql_predicates_match_python_predicates(self):
        """The SQL fragments must agree with the Python predicates."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (rssi INTEGER, snr REAL)")
        values = [
            (-98, 5.25),
            (-150, -30.0),
            (-1, 30.0),
            (0, 0.0),
            (None, None),
            (GARBAGE_RSSI, GARBAGE_SNR),
            (1070308180, 1e9),
            (255, -1e9),
        ]
        conn.executemany("INSERT INTO t VALUES (?, ?)", values)
        for rssi, _snr in values:
            sql_rssi = conn.execute(
                f"SELECT COUNT(*) FROM t WHERE {rssi_valid_sql()} AND rssi IS ?",
                (rssi,),
            ).fetchone()[0]
            assert bool(sql_rssi) == is_plausible_rssi(rssi), f"rssi={rssi}"
        # GARBAGE_SNR (2.8e-36) is within [-30, 30]: numerically harmless,
        # so the range predicate deliberately lets it through.
        for _rssi, snr in values:
            sql_snr = conn.execute(
                f"SELECT COUNT(*) FROM t WHERE {snr_valid_sql()} AND snr IS ?",
                (snr,),
            ).fetchone()[0]
            assert bool(sql_snr) == is_plausible_snr(snr), f"snr={snr}"
        conn.close()


class TestDashboardStatsGuard:
    def test_garbage_rssi_does_not_poison_avg(self, temp_database, monkeypatch):
        """Reproduces the -29606 dBm bug: one garbage row must not move the avg."""
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
        repositories._dashboard_stats_cache.clear()

        now = time.time()
        _insert_packets(
            temp_database,
            [
                (now - HOUR, 1, -80, 5.0),
                (now - HOUR, 2, -100, -3.5),
                (now - HOUR, 3, GARBAGE_RSSI, GARBAGE_SNR),
                (now - HOUR, 4, 0, 0.0),  # "not provided" sentinel row
            ],
        )

        stats = DashboardRepository.get_stats()

        assert stats["avg_rssi"] == -90.0
        # snr averages over the two real rows plus the 0.0 sentinel and the
        # in-range garbage denormal (~0): (5.0 - 3.5 + 0 + 0) / 4
        assert stats["avg_snr"] == round((5.0 - 3.5 + 0.0 + GARBAGE_SNR) / 4, 1)

    def test_all_rows_garbage_yields_zero_avg(self, temp_database, monkeypatch):
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)
        repositories._dashboard_stats_cache.clear()

        now = time.time()
        _insert_packets(temp_database, [(now - HOUR, 1, GARBAGE_RSSI, 1e9)])

        stats = DashboardRepository.get_stats()

        # No valid measurement -> the pre-existing "or 0" fallback applies.
        assert stats["avg_rssi"] == 0
        assert stats["avg_snr"] == 0


class TestAnalyticsSignalQualityGuard:
    def test_distribution_excludes_garbage_and_sentinel(
        self, temp_database, monkeypatch
    ):
        """rssi=0 sentinel and garbage rows must not count as 'excellent'."""
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

        now = time.time()
        _insert_packets(
            temp_database,
            [
                (now - HOUR, 1, -65, 12.0),  # excellent
                (now - HOUR, 2, -95, -2.0),  # poor
                (now - HOUR, 3, 0, 0.0),  # sentinel: previously "excellent"
                (now - HOUR, 4, GARBAGE_RSSI, 1e9),  # garbage
                (now - HOUR, 5, 1070308180, -1e9),  # positive garbage
            ],
        )

        stats = AnalyticsService._get_signal_quality_statistics({}, now - 24 * HOUR)

        assert stats["avg_rssi"] == -80.0
        assert stats["rssi_distribution"] == {
            "excellent": 1,
            "good": 0,
            "fair": 0,
            "poor": 1,
        }
        # snr keeps its existing "0.0 included" semantics: 12.0, -2.0 and the
        # sentinel 0.0 are counted, the +/-1e9 garbage is not.
        assert stats["total_measurements"] == 3
        snr_dist = stats["snr_distribution"]
        assert snr_dist["excellent"] == 1
        assert snr_dist["poor"] == 2  # -2.0 and the 0.0 sentinel; garbage excluded


class TestSignalHistograms:
    def test_histograms_bin_and_zero_fill(self, temp_database, monkeypatch):
        """5 dB RSSI / 2 dB SNR bins, zero-filled gaps, garbage excluded."""
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

        now = time.time()
        _insert_packets(
            temp_database,
            [
                (now - HOUR, 1, -87, 5.5),  # rssi bin -90, snr bin 4
                (now - HOUR, 2, -86, 5.0),  # rssi bin -90, snr bin 4
                (now - HOUR, 3, -71, -3.25),  # rssi bin -75, snr bin -4
                (now - HOUR, 4, 0, 9.0),  # sentinel: excluded from both
                (now - HOUR, 5, GARBAGE_RSSI, 1e9),  # garbage: excluded
            ],
        )

        stats = AnalyticsService._get_signal_quality_statistics({}, now - 24 * HOUR)

        rssi_hist = stats["rssi_histogram"]
        assert rssi_hist["bin_width"] == 5
        by_start = {b["start"]: b["count"] for b in rssi_hist["bins"]}
        assert by_start[-90] == 2
        assert by_start[-75] == 1
        # Dense range with zero-filled gaps between the observed extremes.
        starts = [b["start"] for b in rssi_hist["bins"]]
        assert starts == list(range(-90, -70, 5))
        assert by_start[-85] == 0 and by_start[-80] == 0

        snr_hist = stats["snr_histogram"]
        assert snr_hist["bin_width"] == 2
        snr_by_start = {b["start"]: b["count"] for b in snr_hist["bins"]}
        assert snr_by_start[4] == 2
        assert snr_by_start[-4] == 1
        assert snr_hist["rf_avg_snr"] == round((5.5 + 5.0 - 3.25) / 3, 2)

    def test_rssi_edge_bins_accumulate_both_tails(self, temp_database, monkeypatch):
        """>= -60 dBm collapses into one right accumulator, < -130 dBm into one
        left accumulator, so stray readings can't stretch the axis."""
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

        now = time.time()
        _insert_packets(
            temp_database,
            [
                (now - HOUR, 1, -95, 3.0),
                (now - HOUR, 2, -58, 8.0),  # already in the [-60,-55) bin
                (now - HOUR, 3, -30, 9.0),  # co-located node
                (now - HOUR, 4, -12, 10.0),  # co-located node
                (now - HOUR, 5, -133, -19.0),  # below sensitivity floor
                (now - HOUR, 6, -141, -20.0),  # below sensitivity floor
            ],
        )

        stats = AnalyticsService._get_signal_quality_statistics({}, now - 24 * HOUR)

        hist = stats["rssi_histogram"]
        assert hist["overflow_start"] == -60
        assert hist["underflow_end"] == -130
        starts = [b["start"] for b in hist["bins"]]
        # Dense from the underflow accumulator ([-135) = "< -130") through
        # the overflow accumulator ([-60] = ">= -60"), nothing beyond either.
        assert starts == list(range(-135, -55, 5))
        by_start = {b["start"]: b["count"] for b in hist["bins"]}
        assert by_start[-135] == 2  # both sub-floor readings
        assert by_start[-60] == 3
        assert by_start[-95] == 1

    def test_snr_histogram_ignores_snr_only_sentinel_rows(
        self, temp_database, monkeypatch
    ):
        """Rows without a real RSSI (gateway self-uplinks) must not spike at 0."""
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

        now = time.time()
        _insert_packets(
            temp_database,
            [(now - HOUR, 1, -80, 7.0)] + [(now - HOUR, n, 0, 0.0) for n in range(50)],
        )

        stats = AnalyticsService._get_signal_quality_statistics({}, now - 24 * HOUR)

        snr_bins = {b["start"]: b["count"] for b in stats["snr_histogram"]["bins"]}
        assert snr_bins == {6: 1}
        assert stats["snr_histogram"]["rf_avg_snr"] == 7.0

    def test_histograms_empty_when_no_valid_measurements(
        self, temp_database, monkeypatch
    ):
        monkeypatch.setenv("MALLA_DATABASE_FILE", temp_database)

        now = time.time()
        _insert_packets(temp_database, [(now - HOUR, 1, GARBAGE_RSSI, 1e9)])

        stats = AnalyticsService._get_signal_quality_statistics({}, now - 24 * HOUR)

        assert stats["rssi_histogram"]["bins"] == []
        assert stats["snr_histogram"]["bins"] == []
        assert stats["snr_histogram"]["rf_avg_snr"] is None


class TestIngestStoresRawValues:
    def test_log_packet_stores_garbage_signal_fields_verbatim(
        self, tmp_path, monkeypatch
    ):
        """packet_history is the faithful raw record: even garbage rx_rssi/rx_snr
        from a corrupt frame is stored as-is; filtering happens read-side only."""
        import malla.mqtt_capture as mqtt_capture

        db_path = str(tmp_path / "capture.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, topic TEXT, from_node_id INTEGER,
                to_node_id INTEGER, portnum INTEGER, portnum_name TEXT,
                gateway_id TEXT, channel_id TEXT, mesh_packet_id INTEGER,
                rssi INTEGER, snr REAL, hop_limit INTEGER, hop_start INTEGER,
                payload_length INTEGER, raw_payload BLOB,
                processed_successfully INTEGER, via_mqtt INTEGER,
                want_ack INTEGER, priority INTEGER, delayed INTEGER,
                channel_index INTEGER, rx_time INTEGER, pki_encrypted INTEGER,
                next_hop INTEGER, relay_node INTEGER, tx_after INTEGER,
                message_type TEXT, raw_service_envelope BLOB,
                parsing_error TEXT
            )"""
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)

        class FakeDecoded:
            portnum = 1
            payload = b"x"

        class FakeMeshPacket:
            id = 42
            hop_limit = 3
            hop_start = 3
            rx_rssi = GARBAGE_RSSI
            rx_snr = 1e9
            decoded = FakeDecoded()

        setattr(FakeMeshPacket, "from", 123)
        FakeMeshPacket.to = 456

        mqtt_capture.log_packet_to_database(
            topic="msh/TW/2/e/LongFast/!deadbeef",
            service_envelope=None,
            mesh_packet=FakeMeshPacket(),
        )

        conn = sqlite3.connect(db_path)
        rssi, snr = conn.execute("SELECT rssi, snr FROM packet_history").fetchone()
        conn.close()
        assert rssi == GARBAGE_RSSI
        assert snr == 1e9

    def test_log_packet_keeps_real_signal_values(self, tmp_path, monkeypatch):
        import malla.mqtt_capture as mqtt_capture

        db_path = str(tmp_path / "capture.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE packet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, topic TEXT, from_node_id INTEGER,
                to_node_id INTEGER, portnum INTEGER, portnum_name TEXT,
                gateway_id TEXT, channel_id TEXT, mesh_packet_id INTEGER,
                rssi INTEGER, snr REAL, hop_limit INTEGER, hop_start INTEGER,
                payload_length INTEGER, raw_payload BLOB,
                processed_successfully INTEGER, via_mqtt INTEGER,
                want_ack INTEGER, priority INTEGER, delayed INTEGER,
                channel_index INTEGER, rx_time INTEGER, pki_encrypted INTEGER,
                next_hop INTEGER, relay_node INTEGER, tx_after INTEGER,
                message_type TEXT, raw_service_envelope BLOB,
                parsing_error TEXT
            )"""
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(mqtt_capture, "DATABASE_FILE", db_path)

        class FakeDecoded:
            portnum = 1
            payload = b"x"

        class FakeMeshPacket:
            id = 43
            hop_limit = 3
            hop_start = 3
            rx_rssi = -87
            rx_snr = 6.75
            decoded = FakeDecoded()

        setattr(FakeMeshPacket, "from", 123)
        FakeMeshPacket.to = 456

        mqtt_capture.log_packet_to_database(
            topic="msh/TW/2/e/LongFast/!deadbeef",
            service_envelope=None,
            mesh_packet=FakeMeshPacket(),
        )

        conn = sqlite3.connect(db_path)
        rssi, snr = conn.execute("SELECT rssi, snr FROM packet_history").fetchone()
        conn.close()
        assert rssi == -87
        assert snr == 6.75
