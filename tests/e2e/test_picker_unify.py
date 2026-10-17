"""E2E: shared node picker drives map selection and graph jump."""

from playwright.sync_api import Page


def _pick_first(page, timeout_ms=8000):
    page.locator(".node-picker-input").first.click()
    page.wait_for_timeout(400)
    item = page.locator(".node-picker-item").first
    item.wait_for(state="visible", timeout=timeout_ms)
    item.click()
    page.wait_for_timeout(400)
    return page.evaluate(
        "()=>Number(document.getElementById('nodeSearch_value').value)"
    )


def test_map_picker_selects_node(page: Page, test_server_url: str):
    page.goto(f"{test_server_url}/map")
    page.wait_for_selector(".node-picker-input", timeout=10000)
    page.wait_for_timeout(1500)  # node cache + map data
    nid = _pick_first(page)
    assert nid, "picker must populate the hidden node id"
    page.wait_for_timeout(400)
    # map selection surfaces the hop-depth controls
    assert page.locator("#hopDepthSection").is_visible()


def test_graph_picker_jump_or_explain(page: Page, test_server_url: str):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{test_server_url}/traceroute-graph")
    page.wait_for_selector(".node-picker-input", timeout=10000)
    page.wait_for_timeout(2000)  # graph data
    nid = _pick_first(page)
    assert nid, "picker must populate the hidden node id"
    page.wait_for_timeout(400)
    in_graph = page.evaluate(
        "(id)=>!!(window.currentGraph&&currentGraph.nodes.some(n=>n.id===id))", nid
    )
    assert page.locator("#selectedDetails").is_visible() or not in_graph
    assert not errors, errors[:2]
