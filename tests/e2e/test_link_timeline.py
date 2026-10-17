"""E2E: the link-timeline drawer on the longest-links page.

The drawer needs rollup rows (the fixture db ships none), so the test seeds
one pair's daily history plus endpoints positions into the running server's
database, then drives the real UI: open from a row, chips + chart, empty
state for an unknown pair, ESC to close.
"""

import sqlite3
import time
from datetime import UTC, datetime, timedelta

from playwright.sync_api import Page, expect

A = 999001
B = 999002


def _seed_history(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO node_latest_position"
            " (node_id, last_seen, packet_id, gateway_id, latitude, longitude,"
            "  altitude) VALUES (?,?,?,?,?,?,?)",
            (A, now, 1, "!11110000", 60.10, 24.90, 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO node_latest_position"
            " (node_id, last_seen, packet_id, gateway_id, latitude, longitude,"
            "  altitude) VALUES (?,?,?,?,?,?,?)",
            (B, now, 2, "!11110001", 60.20, 24.98, 0),
        )
        today = datetime.now(UTC).date()
        for offset in range(5):
            day = today - timedelta(days=offset)
            conn.execute(
                "INSERT OR REPLACE INTO link_day_rollup"
                " (day, node_a, node_b, packet_count, snr_sum, snr_count,"
                "  snr_min, snr_max, last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    day.isoformat(),
                    min(A, B),
                    max(A, B),
                    3,
                    4.5,
                    3,
                    -1.5,
                    6.5,
                    now - 86400 * offset,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_drawer_opens_with_chart_and_esc_closes(
    page: Page, test_server, test_server_url: str
):
    _seed_history(test_server.temp_db.name)

    page.goto(f"{test_server_url}/longest-links")
    history_btn = page.locator("button:has-text('History')").first
    page.wait_for_selector("button:has-text('History')", timeout=15000)
    history_btn.click()

    drawer = page.locator(".lt-drawer")
    expect(drawer).to_be_visible()

    # Summary chips: days seen / packets / avg / best / worst.
    expect(page.locator(".lt-chip")).to_have_count(5)

    # Seeded days render the Plotly chart, not the empty state.
    expect(page.locator(".lt-drawer .js-plotly-plot")).to_be_visible(timeout=10000)

    # Focus lands in the dialog for keyboard users.
    assert page.evaluate(
        "!!document.activeElement && document.activeElement.getAttribute"
        "('aria-label') === 'Close link history'"
    )

    page.keyboard.press("Escape")
    expect(page.locator(".lt-drawer")).to_have_count(0)


def test_drawer_empty_state_for_unknown_pair(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/longest-links")
    page.wait_for_function("!!window.MallaLinkTimeline", timeout=15000)

    page.evaluate("window.MallaLinkTimeline.show(424242, 424243)")
    drawer = page.locator(".lt-drawer")
    expect(drawer).to_be_visible()
    expect(page.locator(".lt-empty")).to_contain_text("No link history")

    # Backdrop click closes as well.
    page.locator(".lt-backdrop").click(position={"x": 5, "y": 5})
    expect(page.locator(".lt-drawer")).to_have_count(0)
