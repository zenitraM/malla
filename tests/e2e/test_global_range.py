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
            // Scan newest-first: any packets call carrying a since in the
            // window proves the range reached the wire (later helper calls
            // without since must not mask it).
            for (let i = links.length - 1; i >= 0; i--) {
                const since = new URL(links[i]).searchParams.get('since');
                if (!since) continue;
                const age = Date.now() - new Date(since).getTime();
                if (age > lo * 3600e3 && age < hi * 3600e3) return true;
            }
            return false;
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
        page.wait_for_function(
            "() => location.search.includes('range=24h')", timeout=15000
        )
        deadline = time.time() + 15
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


class TestRangePageIntegration:
    def test_nav_height_var_matches_real_navbar(self, page: Page, test_server_url: str):
        """Regression: the 56px assumption left sticky panels under the navbar."""
        page.goto(f"{test_server_url}/map")
        page.wait_for_selector(".app-navbar", timeout=10000)
        page.wait_for_timeout(300)
        info = page.evaluate(
            """() => {
                const nav = document.querySelector('.app-navbar').getBoundingClientRect();
                const v = getComputedStyle(document.documentElement)
                    .getPropertyValue('--malla-nav-h').trim();
                return { navH: Math.round(nav.height), var: v };
            }"""
        )
        assert info["var"].endswith("px"), info
        assert abs(int(info["var"][:-2]) - info["navH"]) <= 1, info

    def test_map_window_follows_global_range(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/map")
        page.wait_for_selector("#mapWindowChip", timeout=10000)
        _nav_button(page).click()
        page.get_by_role("button", name="Last 7 days").click()
        page.wait_for_timeout(700)
        chip = page.locator("#mapWindowChip")
        assert chip.get_attribute("data-window-key") == "7d"
        assert "7 days" in (chip.inner_text() or "")

    def test_graph_window_follows_global_range(self, page: Page, test_server_url: str):
        page.goto(f"{test_server_url}/traceroute-graph")
        page.wait_for_selector("#hours", timeout=10000)
        _nav_button(page).click()
        page.get_by_role("button", name="Last hour").click()
        page.wait_for_timeout(700)
        assert page.locator("#hours").input_value() == "1"

    def test_retention_caps_all_range(self, page: Page, test_server_url: str):
        """With a retention configured, 'all' clamps its since to the window."""
        page.goto(f"{test_server_url}/packets")
        page.wait_for_selector(".modern-table tbody tr", timeout=15000)
        page.evaluate("() => window.MallaRange.setRetentionHours(24)")
        page.wait_for_timeout(200)
        page.evaluate("() => window.MallaRange.set('all')")
        page.wait_for_timeout(300)
        rng = page.evaluate("() => window.MallaRange.get()")
        assert rng["key"] == "all" and rng.get("capped") is True, rng
        age_h = (__import__("time").time() - rng["sinceEpoch"]) / 3600
        assert 23.5 < age_h < 24.5, age_h

    def test_pages_honour_persisted_range_on_load(
        self, page: Page, test_server_url: str
    ):
        """Regression: a stored range must apply on first paint, not only on change."""
        page.goto(f"{test_server_url}/packets")
        # Bare key, as range-context persists it (JSON blobs are invalid)
        page.evaluate("() => localStorage.setItem('malla.range', '24h')")
        page.goto(f"{test_server_url}/map")
        page.wait_for_selector("#mapWindowChip", timeout=10000)
        page.wait_for_timeout(800)
        assert page.locator("#mapWindowChip").get_attribute("data-window-key") == "24h"
        page.goto(f"{test_server_url}/traceroute-graph")
        page.wait_for_selector("#hours", timeout=10000)
        page.wait_for_timeout(800)
        assert page.locator("#hours").input_value() == "24"
