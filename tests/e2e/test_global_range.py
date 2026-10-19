"""E2E: global time-range context (stack/6).

Covers the navbar control, persistence, table integration
(`since`/`until` on the wire), dashboard delegation and the override chip.
"""

import re
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect


def _nav_button(page):
    return page.locator("#globalRangeButton")


def _recent_packets_since(page, hours_lo, hours_hi):
    """True when the last /api/v1/packets carry a since hours old in-band."""
    return page.evaluate(
        """([lo, hi]) => {
            const links = performance.getEntriesByType('resource')
                .map(e => e.name).filter(u => u.includes('/api/v1/packets'));
            if (!links.length) return false;
            const last = new URL(links[links.length - 1]);
            const since = last.searchParams.get('since');
            if (!since) return false;
            const age = Date.now() - new Date(since).getTime();
            return age > lo * 3600e3 && age < hi * 3600e3;
        }""",
        [hours_lo, hours_hi],
    )


class TestGlobalRange:
    def test_control_present_and_default(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/packets")
        expect(_nav_button(page)).to_be_visible()

    def test_table_receives_since_on_range_change(
        self, page: Page, test_server_url: str
    ):
        page.goto(f"{test_server_url}/packets")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)

        _nav_button(page).click()
        page.get_by_role("button", name="Last 24 hours").click()
        deadline = time.time() + 8
        ok = False
        while time.time() < deadline:
            if _recent_packets_since(page, 20, 26):
                ok = True
                break
            page.wait_for_timeout(250)
        assert ok, "expected since ≈24h ago on the wire"
        assert "range=24h" in page.url

    def test_dashboard_follows_global_range(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/?range=7d")
        page.wait_for_selector("#timelineRangeButtons", timeout=10000)
        _nav_button(page).click()
        page.get_by_role("button", name="Last 24 hours").click()
        page.wait_for_timeout(600)
        active = page.locator("#timelineRangeButtons button.active")
        assert active.get_attribute("data-range") == "24h"
        assert "range=24h" in page.url

    def test_dashboard_navbar_preset_keeps_global_key(
        self, page: Page, test_server_url: str
    ):
        """The dashboard may map 6h to its 24h tile, but must not rewrite the
        shared URL to 24h."""
        page.goto(f"{test_server_url}/?range=7d")
        page.wait_for_selector("#timelineRangeButtons", timeout=10000)
        _nav_button(page).click()
        page.get_by_role("button", name="Last 6 hours").click()
        page.wait_for_timeout(600)
        assert "range=6h" in page.url
        assert "6h" in (page.locator("#globalRangeLabel").text_content() or "")
        active = page.locator("#timelineRangeButtons button.active")
        assert active.get_attribute("data-range") == "24h"

    def test_filter_apply_preserves_global_range_url(
        self, page: Page, test_server_url: str
    ):
        page.goto(f"{test_server_url}/packets?range=24h")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)
        page.locator("#hop_count").select_option("0")
        page.locator("#applyFilters").click()
        page.wait_for_url(re.compile(r"hop_count=0"), timeout=10000)
        assert "range=24h" in page.url
        assert "24h" in (page.locator("#globalRangeLabel").text_content() or "")

    def test_page_override_marks_chip(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/packets?range=24h")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)

        start = page.locator("#start_time")
        expect(start).to_have_count(1)
        start.fill("2026-01-01T00:00")
        page.locator("#applyFilters").click()
        page.wait_for_timeout(800)
        expect(page.locator("#globalRangeOverride")).to_be_visible()

    def test_range_persists_across_pages(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/packets")
        _nav_button(page).click()
        page.get_by_role("button", name="Last 6 hours").click()
        page.wait_for_timeout(300)

        page.goto(f"{test_server_url}/traceroute")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)
        # init() reflects the stored range into the URL and the label.
        assert "range=6h" in page.url
        label = page.locator("#globalRangeLabel")
        assert "6h" in (label.text_content() or "")


def test_relative_preset_advances_between_reads(page: Page, test_server_url: str):
    """A preset's since must track now, not freeze at first resolution."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_function("!!window.MallaRange", timeout=15000)
    first = page.evaluate("window.MallaRange.get().sinceEpoch")
    page.wait_for_timeout(1200)
    second = page.evaluate("window.MallaRange.get().sinceEpoch")
    assert second > first, (first, second)


def test_dashboard_preserves_shared_range_url_on_load(page: Page, test_server_url: str):
    """A shared ?range=6h link must not be rewritten to the stored default."""
    page.goto(f"{test_server_url}/?range=6h")
    page.wait_for_selector("#timelineRangeButtons", timeout=10000)
    page.wait_for_timeout(600)
    assert "range=6h" in page.url
    active = page.locator("#timelineRangeButtons button.active")
    assert active.get_attribute("data-range") == "24h"


def test_stored_custom_without_bounds_degrades_to_default(
    page: Page, test_server_url: str
):
    """A bare persisted 'custom' (no URL bounds) must not produce NaN since."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_function("!!window.MallaRange", timeout=15000)
    page.evaluate("localStorage.setItem('malla.range', 'custom')")
    with page.expect_request(
        lambda r: "/api/v1/packets" in r.url and "since=" in r.url,
        timeout=15000,
    ) as request:
        page.reload()

    since_raw = parse_qs(urlparse(request.value.url).query)["since"][0]
    since = datetime.fromisoformat(since_raw.replace("Z", "+00:00"))
    age_hours = (datetime.now(UTC) - since).total_seconds() / 3600
    assert 166 < age_hours < 170, since_raw
    state = page.evaluate("window.MallaRange.get()")
    assert state["key"] == "7d"
    assert "range=custom" not in page.url


def test_custom_until_only_writes_no_epoch_since(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/packets")
    page.wait_for_function("!!window.MallaRange", timeout=15000)
    until = int(time.time())
    page.evaluate(
        "(until) => window.MallaRange.set('custom', {sinceEpoch: null, untilEpoch: until})",
        until,
    )
    assert "range_since=1970" not in page.url
    assert "range_until=" in page.url
    state = page.evaluate("window.MallaRange.get()")
    assert state["key"] == "custom"
    assert state["sinceEpoch"] is None
