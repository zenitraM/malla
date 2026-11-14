"""E2E: saved views for the table filter sidebars.

Flow: filter via the real UI, save under a name, reload plain, apply from
the Views dropdown -> identical row count plus URL params restored; delete
works; the share action flashes the copied-link toast. A smoke check proves
the widget mounts on nodes/traceroutes too.
"""

import re
import time

from playwright.sync_api import Page, expect

VIEW_NAME = "mine"
_TABLE_READY = (
    "() => document.querySelectorAll('.modern-table tbody tr').length > 0"
    " && !document.querySelector('.loading-spinner')"
)


def _wait_table_ready(page: Page) -> int:
    page.wait_for_function(_TABLE_READY, timeout=15000)
    return page.locator(".modern-table tbody tr").count()


def _open_views_menu(page: Page) -> None:
    page.locator(".sv-sidebar-section .sv-toggle").first.click()
    page.locator(".sv-sidebar-section .sv-menu").first.wait_for(state="visible")


def test_save_apply_delete_roundtrip(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/packets")
    _wait_table_ready(page)

    # Filter: direct-only hops, through the real form + apply path.
    page.locator("#hop_count").select_option("0")
    page.locator("#applyFilters").click()
    page.wait_for_url(re.compile(r"hop_count=0"), timeout=10000)
    _wait_table_ready(page)

    # Save current as 'mine' (inline name input, Enter confirms).
    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-save-btn").first.click()
    name_input = page.locator(".sv-sidebar-section .sv-name-input").first
    name_input.fill(VIEW_NAME)
    name_input.press("Enter")

    stored = page.evaluate(
        "JSON.parse(localStorage.getItem('malla.savedViews.packets') || '[]')"
    )
    assert stored and stored[0]["name"] == VIEW_NAME, stored
    assert stored[0]["filters"].get("hop_count") == "0", stored

    # Reload without params: the view must restore both rows and URL.
    page.goto(f"{test_server_url}/packets")
    _wait_table_ready(page)

    _open_views_menu(page)
    # Apply can race the page's initial unfiltered load; the table must issue
    # the filtered request and keep its response, so bind the assertion to the
    # request the click actually produced rather than to a pre-apply count.
    with page.expect_request(
        lambda r: "/api/v1/packets" in r.url and "hop_count=0" in r.url,
        timeout=10000,
    ) as applied:
        page.locator(".sv-sidebar-section .sv-apply", has_text=VIEW_NAME).first.click()
    page.wait_for_url(re.compile(r"hop_count=0"), timeout=10000)
    expect(page.locator("#hop_count")).to_have_value("0")
    expect(page.locator("#group_packets")).to_be_checked()
    applied_body = page.request.get(applied.value.url).json()
    expected_rows = min(applied_body["meta"]["pagination"]["total"], 100)
    expect(page.locator(".modern-table tbody tr")).to_have_count(
        expected_rows, timeout=10000
    )

    # Delete the view; it leaves storage and the menu.
    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-delete").first.click()
    expect(page.locator(".toast-body", has_text="Deleted view")).to_be_visible(
        timeout=5000
    )
    stored_after = page.evaluate(
        "JSON.parse(localStorage.getItem('malla.savedViews.packets') || '[]')"
    )
    assert stored_after == [], stored_after


def test_share_link_copies_current_url(page: Page, test_server_url: str):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{test_server_url}/packets?hop_count=0")
    _wait_table_ready(page)

    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-share").first.click()

    expect(page.locator(".toast-body", has_text="Link copied")).to_be_visible(
        timeout=5000
    )
    assert "hop_count=0" in page.url
    clip = page.evaluate("navigator.clipboard.readText()")
    assert "hop_count=0" in clip


def test_widget_mounts_on_nodes_and_traceroutes(page: Page, test_server_url: str):
    for path in ("/nodes", "/traceroute"):
        page.goto(f"{test_server_url}{path}")
        page.wait_for_selector(".sv-sidebar-section .sv-toggle", timeout=15000)
        assert page.locator(".sv-sidebar-section .sv-toggle").count() == 1, path


def test_escape_cancels_naming(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/packets")
    _wait_table_ready(page)

    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-save-btn").first.click()
    name_input = page.locator(".sv-sidebar-section .sv-name-input").first
    name_input.fill("abandoned")
    name_input.press("Escape")
    page.wait_for_timeout(300)

    stored = page.evaluate(
        "JSON.parse(localStorage.getItem('malla.savedViews.packets') || '[]')"
    )
    assert stored == [], stored


def test_summary_chips_ignore_false_and_count_once(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/packets")
    page.evaluate(
        """localStorage.setItem('malla.savedViews.packets', JSON.stringify([{
            name: 'x',
            filters: {
                hop_count: '0', portnum: '1', channel_id: 'c', search: 's',
                gateway_id: '!abc', exclude_self: false, group_packets: true
            }
        }]))"""
    )
    page.reload()
    _wait_table_ready(page)

    _open_views_menu(page)
    chips = page.locator(".sv-sidebar-section .sv-item .sv-chip").all_text_contents()
    # Five real filters: four chips plus exactly one overflow chip.
    assert "+1" in chips, chips
    assert "+2" not in chips, chips
    assert all("exclude_self" not in chip for chip in chips), chips
    assert "grouped" in chips, chips


def test_apply_view_does_not_clear_saved_picker(page: Page, test_server_url: str):
    node = page.request.get(f"{test_server_url}/api/v1/nodes?page_size=1").json()[
        "data"
    ][0]
    node_id = str(node["node_id"])

    page.goto(f"{test_server_url}/packets")
    _wait_table_ready(page)
    page.evaluate(
        "(value) => { document.querySelector('input[name=from_node]').value = value; }",
        node_id,
    )
    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-save-btn").first.click()
    name_input = page.locator(".sv-sidebar-section .sv-name-input").first
    name_input.fill("nodeview")
    name_input.press("Enter")

    page.goto(f"{test_server_url}/packets")
    _wait_table_ready(page)

    def slow_node(route):
        time.sleep(1.5)
        route.continue_()

    page.route(f"**/api/v1/nodes/{node_id}", slow_node)
    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-apply", has_text="nodeview").first.click()
    page.wait_for_url(re.compile(r"from_node=" + node_id), timeout=10000)

    # The saved hidden input is restored synchronously with the view; it must
    # not be cleared while the visible-label lookup is still in flight.
    hidden = page.locator("input[name=from_node]")
    assert hidden.input_value() == node_id
    page.wait_for_timeout(2500)
    assert hidden.input_value() == node_id
    assert page.locator("#from_node").input_value()
