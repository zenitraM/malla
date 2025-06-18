"""
Pytest configuration for Playwright end-to-end tests.
"""

import pytest
from playwright.sync_api import Browser


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
    return {
        "headless": True,  # Run in headless mode for CI/testing
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
        ],
    }


@pytest.fixture(scope="function")
def page(browser: Browser):
    """Create a new page for each test."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
