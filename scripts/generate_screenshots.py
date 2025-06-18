#!/usr/bin/env python3
"""Generate up-to-date screenshots of the web-UI for the README.

This helper script
1. Builds a **deterministic** demo database using the existing test fixtures.
2. Launches a Flask app instance (in-memory) that serves the UI backed by that
   demo database.
3. Uses Playwright (headless Chromium) to visit representative pages and
   capture screenshots.
4. Stores the PNG files in the project root's ``.screenshots/`` directory.
5. Updates *README.md* in-place, replacing everything between the markers
   ``<!-- screenshots:start -->`` and ``<!-- screenshots:end -->`` with fresh
   Markdown links to the generated images.

Run manually:

```bash
uv run python scripts/generate_screenshots.py
```

Note: Playwright **must** have been previously installed – for CI you typically
execute:

```bash
playwright install chromium --with-deps
```

The script is safe to re-run; it overwrites existing screenshots and keeps the
Flask server confined to a random free port for parallel execution.
"""

from __future__ import annotations

import argparse
import http.client
import logging
import socket
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Local imports – *defer* until after the project root is on sys.path
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

# Ensure both the project root *and* the PEP-517 src/ directory are importable
for _p in (str(PROJECT_ROOT), str(SRC_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.malla.config import AppConfig  # noqa: E402
from src.malla.web_ui import create_app  # noqa: E402  – needs path trickery above
from tests.fixtures.database_fixtures import DatabaseFixtures  # noqa: E402

# ---------------------------------------------------------------------------

_LOG = logging.getLogger("generate_screenshots")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)8s %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)

# The list of (route, output filename) to capture – order matters for README
PAGES: list[tuple[str, str]] = [
    ("/", "dashboard.png"),
    ("/nodes", "nodes.png"),
    ("/packets", "packets.png"),
    ("/map", "map.png"),
    ("/traceroute-graph", "traceroute_graph.png"),
]

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Ask the OS for a free TCP port and *immediately* release it again."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _sock:
        _sock.bind(("127.0.0.1", 0))
        return _sock.getsockname()[1]


def _wait_until_healthy(host: str, port: int, timeout: float = 10.0) -> None:
    """Poll ``/health`` until the Flask server responds or *timeout* sec pass."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            if resp.status == 200:
                _LOG.info(
                    "Flask server is up (%.2fs)", timeout - (deadline - time.time())
                )
                return
        except OSError:
            pass  # Port not accepting yet
        time.sleep(0.1)
    raise RuntimeError("Timed-out waiting for the Flask server to come online")


# ---------------------------------------------------------------------------
# Main orchestration steps
# ---------------------------------------------------------------------------


def _build_demo_database(db_path: Path) -> None:
    """Create a fresh demo SQLite DB at *db_path* using the fixtures."""

    if db_path.exists():
        db_path.unlink()
    _LOG.info("Creating demo database → %s", db_path)
    fixtures = DatabaseFixtures()
    fixtures.create_test_database(str(db_path))


def _launch_app_thread(cfg: AppConfig):
    """Run *create_app* in a background daemon thread and return it."""

    app = create_app(cfg)

    def _serve():
        app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)

    t = threading.Thread(target=_serve, daemon=True, name="FlaskDemoServer")
    t.start()
    return t


def _capture_screenshots(base_url: str, out_dir: Path) -> list[Path]:
    """Use Playwright to capture screenshots for all *PAGES*.

    Returns the list of created image paths.
    """

    images: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        for route, filename in PAGES:
            url = f"{base_url}{route}"
            _LOG.info("Capturing %s → %s", url, filename)
            page.goto(url, wait_until="networkidle", timeout=30_000)

            # Ensure dynamic tables have rendered (best-effort, ignore errors)
            try:
                page.wait_for_timeout(1500)  # simple grace period
            except Exception:  # noqa: BLE001
                pass

            dest = out_dir / filename
            page.screenshot(path=str(dest))
            images.append(dest)

        browser.close()

    return images


def _update_readme(out_dir: Path, images: list[Path]) -> None:
    """Replace the screenshots section in README.md with the fresh list."""

    readme = PROJECT_ROOT / "README.md"
    if not readme.exists():
        _LOG.warning("README.md not found – skipping update")
        return

    md_rel_dir = out_dir.relative_to(PROJECT_ROOT)

    start_tag = "<!-- screenshots:start -->"
    end_tag = "<!-- screenshots:end -->"
    new_lines: list[str] = [start_tag]

    for img in images:
        rel_path = md_rel_dir / img.name
        new_lines.append(f"![{img.stem}]({rel_path.as_posix()})")

    new_lines.append(end_tag)

    content = readme.read_text().splitlines()

    if start_tag in content and end_tag in content:
        start_idx = content.index(start_tag)
        end_idx = content.index(end_tag)
        updated = content[:start_idx] + new_lines + content[end_idx + 1 :]
    else:
        # Append a new section at the end
        updated = (
            content
            + [
                "",
                "## Screenshots",
                "",
            ]
            + new_lines
        )

    readme.write_text("\n".join(updated) + "\n")
    _LOG.info("Updated README.md with %d screenshot links", len(images))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:  # noqa: D401 (simple function)
    parser = argparse.ArgumentParser(description="Generate README screenshots.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / ".screenshots",
        help="Where to place the generated PNG files.",
    )
    args = parser.parse_args()

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1 – demo database
    # ------------------------------------------------------------------
    demo_db = out_dir / "demo.db"
    _build_demo_database(demo_db)

    # ------------------------------------------------------------------
    # Step 2 – launch the Flask server
    # ------------------------------------------------------------------
    port = _find_free_port()
    cfg = AppConfig(
        database_file=str(demo_db), host="127.0.0.1", port=port, debug=False
    )
    _server_thread = _launch_app_thread(cfg)

    try:
        _wait_until_healthy(cfg.host, cfg.port)
    except Exception:
        _LOG.exception("The demo Flask server failed to start")
        sys.exit(1)

    base_url = f"http://{cfg.host}:{cfg.port}"

    # ------------------------------------------------------------------
    # Step 3 – screenshots
    # ------------------------------------------------------------------
    images = _capture_screenshots(base_url, out_dir)

    # ------------------------------------------------------------------
    # Step 4 – update README
    # ------------------------------------------------------------------
    _update_readme(out_dir, images)

    _LOG.info("Done. Generated %d screenshots in %s", len(images), out_dir)


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    finally:
        # Attempt to flush logging *before* the daemon thread exits (best-effort)
        logging.shutdown()
