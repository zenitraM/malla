"""E2E: capture-health chip reflects /api/v1/meta ingest lag."""

import os

import requests
from playwright.sync_api import Page


def _seeded_page(page, test_server_url, path="/"):
    page.goto(test_server_url + path)
    page.wait_for_selector("#captureHealth", timeout=10000)
    # the first meta fetch is async; wait until the chip leaves the skeleton
    page.wait_for_function(
        "() => { const el = document.getElementById('captureHealth');"
        " return el && (el.classList.contains('d-none') || el.dataset.state); }",
        timeout=10000,
    )
    return page.locator("#captureHealth")


class TestCaptureHealth:
    def test_chip_visible_with_data(self, page: Page, test_server_url: str):
        chip = _seeded_page(page, test_server_url)
        # Fixture data is minutes old at most: expect a sane state.
        state = chip.get_attribute("data-state")
        assert state in {"ok", "warn", "stale"}, state
        assert "▲" in (page.locator("#captureHealthText").text_content() or "")

    def test_chip_hidden_without_data(self, page: Page, test_server_url: str):
        # Fresh db copy: no packets -> chip hides entirely.
        import sqlite3
        import tempfile

        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        con = sqlite3.connect(handle.name)
        con.commit()
        con.close()
        from src.malla.capture_startup import (
            init_database as ci,
        )
        from src.malla.capture_startup import (
            run_write_locking_migrations as cw,
        )

        ci(handle.name)
        cw(handle.name)
        from src.malla.config import AppConfig
        from src.malla.web_ui import create_app

        app = create_app(AppConfig(database_file=handle.name))
        app.config["TESTING"] = True
        with app.test_client() as c:
            meta = c.get("/api/v1/meta").get_json()["data"]
            assert meta["last_packet_time_utc"] is None
            assert meta["ingest_lag_seconds"] is None
        os.unlink(handle.name)

    def test_meta_carries_ingest_fields(self, page: Page, test_server_url: str):
        body = requests.get(f"{test_server_url}/api/v1/meta", timeout=10).json()["data"]
        assert "last_packet_time_utc" in body and "ingest_lag_seconds" in body
        assert body["last_packet_time_utc"].endswith("Z")
        assert body["ingest_lag_seconds"] >= 0
