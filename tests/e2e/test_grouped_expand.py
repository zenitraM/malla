"""E2E: grouped-row reception expansion on the packets/traceroutes tables.

The grouped views (group by mesh packet id) render a chevron next to the
reception badge; activating it inserts a full-width row with every reception
of that mesh packet, lazy-loaded once from GET /api/v1/packets/{id}.
"""

import re
import sqlite3

import pytest
from playwright.sync_api import Page, expect

from tests.conftest import TestFlaskApp


class TracerouteDupServer(TestFlaskApp):
    """Real test app plus one duplicated traceroute reception.

    The stock fixtures never emit a traceroute heard by two gateways, so the
    traceroutes page has no expandable grouped row; this subclass adds a
    second reception (same mesh packet id, other gateway) to the temp db
    before the app boots.
    """

    def _setup_test_data(self):
        super()._setup_test_data()
        conn = sqlite3.connect(self.temp_db.name)
        conn.row_factory = sqlite3.Row
        try:
            source = conn.execute(
                """
                SELECT * FROM packet_history
                WHERE portnum_name = 'TRACEROUTE_APP'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            assert source is not None, "fixture db has no traceroute to duplicate"

            record = dict(source)
            record["id"] = (
                conn.execute("SELECT MAX(id) FROM packet_history").fetchone()[0] + 1
            )
            record["gateway_id"] = "!11110009"
            record["timestamp"] = record["timestamp"] + 1

            columns = list(record)
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO packet_history ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                tuple(record[column] for column in columns),
            )
            conn.commit()
        finally:
            conn.close()


@pytest.fixture(scope="module")
def traceroute_dup_server_url(worker_id):
    """Module-scoped server whose db has an expandable traceroute row."""
    del worker_id  # unique port comes from the ephemeral bind in TestFlaskApp
    server = TracerouteDupServer()
    server.start()
    return server.url


def test_packets_grouped_row_expands_and_collapses(page: Page, test_server_url: str):
    """Click expands an inline reception row; a second click removes it."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    # Live locator re-resolution pitfall: bind to the first toggle, never
    # filter by state (aria-expanded changes under the locator).
    toggle = page.locator(".group-expand-btn").first
    expect(toggle).to_be_visible()

    rows = page.locator(".modern-table > tbody > tr")
    base_count = rows.count()
    assert page.locator(".group-receptions-row").count() == 0

    toggle.click()
    expansion = page.locator(".group-receptions-row")
    expect(expansion).to_have_count(1)
    expect(rows).to_have_count(base_count + 1)

    # Full-width row: one cell spanning the whole table.
    colspan = int(expansion.locator("td").first.get_attribute("colspan"))
    header_cells = page.locator(".modern-table > thead th").count()
    assert colspan == header_cells

    # Reception identity: signal readings for every reception.
    expect(expansion).to_contain_text("RSSI")
    expect(expansion).to_contain_text("SNR")

    # Expanded state is on the toggle; collapse removes the row again.
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(page.locator(".group-receptions-row")).to_have_count(0)
    expect(rows).to_have_count(base_count)
    expect(toggle).to_have_attribute("aria-expanded", "false")


def test_packets_grouped_expand_keyboard_toggle(page: Page, test_server_url: str):
    """Enter on the focused chevron toggles the expansion."""
    page.goto(f"{test_server_url}/packets")
    toggle = page.locator(".group-expand-btn").first
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    toggle.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".group-receptions-row")).to_have_count(1)
    expect(toggle).to_have_attribute("aria-expanded", "true")

    page.keyboard.press("Enter")
    expect(page.locator(".group-receptions-row")).to_have_count(0)


def test_packets_grouped_expand_focus_visible(page: Page, test_server_url: str):
    """The chevron is keyboard-reachable and shows a focus ring (a11y)."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    # Tab-targeting: compute the expander's position in the sequential focus
    # order, walk there with real Tab presses, then verify the ring.
    stops = page.evaluate(
        """() => {
            const tabbable = [...document.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]),'
                + ' select:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
            )].filter((node) => node.offsetParent !== null && node.tabIndex >= 0);
            const row = [...document.querySelectorAll('.modern-table > tbody > tr')]
                .find((tr) => tr.querySelector('.group-expand-btn'));
            return {
                index: tabbable.indexOf(row.querySelector('.group-expand-btn')),
                total: tabbable.length,
            };
        }"""
    )
    assert stops["index"] >= 0, "no expandable grouped row rendered"

    for _ in range(stops["index"] + 1):
        page.keyboard.press("Tab")
    for _ in range(20):  # correction budget for tabbable-set drift
        if page.evaluate(
            "!!document.activeElement && "
            "document.activeElement.classList.contains('group-expand-btn')"
        ):
            break
        page.keyboard.press("Tab")
    else:
        page.fail("group expander not reached by keyboard")

    toggle = page.locator(".group-expand-btn").first
    assert toggle.evaluate("el => el.matches(':focus-visible')") is True
    outline = toggle.evaluate("el => getComputedStyle(el).outlineStyle")
    assert outline != "none"

    page.keyboard.press("Enter")  # keyboard activation toggles the expansion
    expect(page.locator(".group-receptions-row")).to_have_count(1)


def test_traceroutes_grouped_row_expands(page: Page, traceroute_dup_server_url: str):
    """The traceroutes table gets the same expander on grouped rows."""
    page.goto(f"{traceroute_dup_server_url}/traceroute")
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    toggle = page.locator(".group-expand-btn").first
    rows = page.locator(".modern-table > tbody > tr")
    base_count = rows.count()

    toggle.click()
    expansion = page.locator(".group-receptions-row")
    expect(expansion).to_have_count(1)
    expect(rows).to_have_count(base_count + 1)
    expect(expansion).to_contain_text("RSSI")
    expect(expansion).to_contain_text("SNR")

    toggle.click()
    expect(page.locator(".group-receptions-row")).to_have_count(0)


def test_expansion_receptions_link_to_individual_packets(
    page: Page, test_server_url: str
):
    """Every listed reception deep-links to its own /packet/{id} page."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_selector(".modern-table tbody tr", timeout=15000)
    # Toggles render with the grouped re-render, after the first body rows:
    # without this wait the count below reads zero and skips a passing test.
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    expand_buttons = page.locator(".group-expand-btn")
    if expand_buttons.count() == 0:
        pytest.skip("fixture has no multi-reception groups to expand")
    expand_buttons.first.click()
    page.wait_for_selector(".group-receptions-row tbody tr", timeout=10000)

    links = page.locator(".group-receptions-row a.group-reception-open")
    assert links.count() >= 1, "expansion must offer per-reception packet links"
    href = links.first.get_attribute("href")
    assert re.match(r"^/packet/\d+$", href or ""), href

    # The link target renders a real packet page.
    response = page.request.get(f"{test_server_url}{href}")
    assert response.ok


def test_grouped_expansion_columns_sort(page: Page, test_server_url: str):
    """Clicking the SNR header re-orders reception rows within the expansion."""
    page.goto(f"{test_server_url}/packets")
    page.wait_for_selector(".modern-table tbody tr", timeout=15000)
    # Toggles render with the grouped re-render, after the first body rows:
    # without this wait the count below reads zero and skips a passing test.
    page.wait_for_selector(".group-expand-btn", timeout=15000)

    buttons = page.locator(".group-expand-btn")
    if not buttons.count():
        pytest.skip("fixture has no multi-reception groups to expand")
    # find a group with >=3 receptions so sorting is observable; collapse
    # every probe so exactly one receptions table exists at assert time.
    chosen = None
    for i in range(min(buttons.count(), 25)):
        buttons.nth(i).click()
        try:
            page.wait_for_selector(".group-receptions-table tbody tr", timeout=4000)
        except TimeoutError:
            pass
        else:
            if page.locator(".group-receptions-table tbody tr").count() >= 3:
                chosen = i
                break
        # Toggle the probe closed with a real click: setAttribute returns
        # undefined so a chained && click() never fires.
        page.locator(".group-expand-btn").nth(i).click()
    assert chosen is not None, "no group with >=3 receptions to sort"

    # Scope to the visible receptions table: a second (hidden) copy would
    # trip strict mode.
    snr_header = page.locator(
        '.group-receptions-table:visible th.group-sortable[data-key="snr"]'
    )

    snr_header.click()  # asc
    page.wait_for_timeout(150)
    first_asc = page.locator(
        ".group-receptions-table tbody tr td:nth-child(4)"
    ).first.text_content()
    assert snr_header.get_attribute("aria-sort") == "ascending"

    snr_header.click()  # desc
    page.wait_for_timeout(150)
    first_desc = page.locator(
        ".group-receptions-table tbody tr td:nth-child(4)"
    ).first.text_content()
    assert snr_header.get_attribute("aria-sort") == "descending"

    def parse(txt):
        digits = re.findall(r"-?\d+\.\d+|\d+", txt or "0")
        return float(digits[0]) if digits else 0.0

    vals = [
        parse(
            page.locator(".group-receptions-table tbody tr td:nth-child(4)")
            .nth(i)
            .text_content()
        )
        for i in range(page.locator(".group-receptions-table tbody tr").count())
    ]
    assert vals == sorted(vals, reverse=True), f"desc order violated: {vals}"
    assert first_asc != first_desc, "second click must reorder"


def test_grouped_expansion_uses_the_active_filters(page: Page, test_server_url: str):
    """The detail request must carry the table's filter set, not just the id."""
    detail_urls: list[str] = []
    page.on(
        "request",
        lambda request: detail_urls.append(request.url)
        if "/api/v1/packets/" in request.url
        else None,
    )

    page.goto(f"{test_server_url}/packets?group_packets=true&min_rssi=-200")
    page.wait_for_selector(".group-expand-btn", timeout=15000)
    page.locator(".group-expand-btn").first.click()
    page.wait_for_selector(".group-receptions-row tbody tr", timeout=10000)

    assert detail_urls, "expansion did not request packet detail"
    assert "min_rssi=-200" in detail_urls[-1], detail_urls[-1]
