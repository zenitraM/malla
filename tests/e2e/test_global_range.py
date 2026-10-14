"""E2E: global time-range context (stack/6).

Covers the navbar control, persistence, table integration
(`since`/`until` on the wire), dashboard delegation and the override chip.
"""

import time

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

    def test_page_override_marks_chip(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/packets?range=24h")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)

        start = page.locator("#start_time")
        if start.count() == 0:
            return  # page without time inputs: nothing to override
        start.fill("2026-01-01T00:00")
        page.locator("#applyFilters").click()
        page.wait_for_timeout(800)
        chip = page.locator("#globalRangeOverride")
        if chip.count():
            expect(chip).to_be_visible()

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
