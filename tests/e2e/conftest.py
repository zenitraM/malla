"""
Pytest configuration for Playwright end-to-end tests.
"""

import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserType, Playwright, sync_playwright


def _configure_playwright_nodejs_path() -> None:
    """Force Playwright to use a system Node runtime when available.

    The bundled Playwright Node binary inside the Python wheel is not executable
    on NixOS, so prefer an existing PATH-resolved runtime unless the user has
    already provided an explicit override.
    """

    if os.environ.get("PLAYWRIGHT_NODEJS_PATH"):
        return

    node_path = shutil.which("node")
    if node_path:
        os.environ["PLAYWRIGHT_NODEJS_PATH"] = node_path


_configure_playwright_nodejs_path()


def _discover_playwright_chromium_executable() -> str | None:
    """Return a packaged Chromium executable if one is available."""

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browsers_path:
        return None

    browser_root = Path(browsers_path)
    patterns = [
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-linux64/chrome",
    ]
    for pattern in patterns:
        for candidate in sorted(browser_root.glob(pattern)):
            if candidate.is_file():
                return str(candidate)

    return None


@pytest.fixture(scope="session")
def playwright() -> Playwright:
    """Override the plugin fixture to avoid the broken context-manager startup path."""
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser_type(playwright: Playwright) -> BrowserType:
    """Pin e2e tests to Chromium, which is the only browser used in this suite."""
    return playwright.chromium


@pytest.fixture(scope="session")
def browser(browser_type: BrowserType, browser_type_launch_args: dict) -> Browser:
    """Launch the browser with repo-controlled arguments instead of plugin defaults."""
    browser = browser_type.launch(**browser_type_launch_args)
    yield browser
    browser.close()


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context arguments."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Configure browser launch arguments."""
    launch_args = {
        "channel": "chromium",
        "headless": True,  # Run in headless mode for CI/testing
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
        ],
    }

    chromium_executable = _discover_playwright_chromium_executable()
    if chromium_executable:
        launch_args.pop("channel", None)
        launch_args["executable_path"] = chromium_executable

    return launch_args


@pytest.fixture(scope="function")
def page(browser: Browser):
    """Create a new page for each test."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
