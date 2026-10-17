"""E2E: saved views for the table filter sidebars.

Flow: filter via the real UI, save under a name, reload plain, apply from
the Views dropdown -> identical row count plus URL params restored; delete
works; the share action flashes the copied-link toast. A smoke check proves
the widget mounts on nodes/traceroutes too.
"""

import re

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
    filtered_count = _wait_table_ready(page)

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
    page.locator(".sv-sidebar-section .sv-apply", has_text=VIEW_NAME).first.click()
    page.wait_for_url(re.compile(r"hop_count=0"), timeout=10000)
    expect(page.locator("#hop_count")).to_have_value("0")
    # The apply refetches; wait for the count to land instead of racing it.
    expect(page.locator(".modern-table tbody tr")).to_have_count(
        filtered_count, timeout=10000
    )

    # Delete the view; it leaves storage and the menu.
    _open_views_menu(page)
    page.locator(".sv-sidebar-section .sv-delete").first.click()
    page.wait_for_timeout(200)
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
