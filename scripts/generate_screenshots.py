#!/usr/bin/env python3
"""Generate up-to-date screenshots of the web-UI for the README.

This helper script
1. Builds a **deterministic** demo database using the existing test fixtures.
2. Launches a Flask app instance (in-memory) that serves the UI backed by that
   demo database.
3. Uses Playwright (headless Chromium) to visit representative pages and
   capture screenshots.
4. Stores the jpg files in the project root's ``.screenshots/`` directory.
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
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

from meshtastic import portnums_pb2
from meshtastic.protobuf import mqtt_pb2
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

# The list of (route, output filename) to capture – order matters for README.
# JPEG is used for smaller, README-friendly assets.
PAGES: list[tuple[str, str]] = [
    ("/", "dashboard.jpg"),
    ("/nodes", "nodes.jpg"),
    ("/packets", "packets.jpg"),
    ("/chat", "chat.jpg"),
    ("/traceroute", "traceroutes.jpg"),
    ("/map", "map.jpg"),
    ("/traceroute-graph", "traceroute_graph.jpg"),
    ("/traceroute-hops", "hop_analysis.jpg"),
    ("/gateway/compare", "gateway_compare.jpg"),
    ("/longest-links", "longest_links.jpg"),
    ("/line-of-sight", "line_of_sight.jpg"),
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
    _seed_demo_chat_examples(db_path)


def _ensure_packet_history_column(
    cursor: sqlite3.Cursor, column_name: str, column_type: str
) -> None:
    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(packet_history)")
    }
    if column_name not in existing_columns:
        cursor.execute(
            f"ALTER TABLE packet_history ADD COLUMN {column_name} {column_type}"
        )


def _build_service_envelope(
    *,
    mesh_packet_id: int,
    timestamp: float,
    from_node_id: int,
    to_node_id: int,
    channel_index: int,
    hop_limit: int,
    hop_start: int,
    gateway_id: str,
    text: str,
    reply_id: int | None = None,
    is_emoji: bool = False,
    channel_id: str | None = None,
) -> bytes:
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.gateway_id = gateway_id
    if channel_id is not None:
        envelope.channel_id = channel_id

    packet = envelope.packet
    packet.id = mesh_packet_id
    setattr(packet, "from", from_node_id)
    packet.to = to_node_id
    packet.channel = channel_index
    packet.hop_limit = hop_limit
    packet.hop_start = hop_start
    packet.rx_time = int(timestamp)
    packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    packet.decoded.payload = text.encode("utf-8")

    if reply_id is not None:
        packet.decoded.reply_id = reply_id
    if is_emoji:
        packet.decoded.emoji = 1

    return envelope.SerializeToString()


def _seed_demo_chat_examples(db_path: Path) -> None:
    _LOG.info("Seeding demo chat thread examples")

    now = time.time()
    base_timestamp = now - 90
    gateway_id = "!433d0c24"
    channel_id = "LongFast"
    channel_index = 0
    broadcast_id = 0xFFFFFFFF
    thread_root_mesh_id = 910000101

    thread_packets = [
        {
            "timestamp": base_timestamp,
            "from_node_id": 1128074277,
            "to_node_id": broadcast_id,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -67,
            "snr": 8.5,
            "hop_limit": 3,
            "hop_start": 4,
            "mesh_packet_id": thread_root_mesh_id,
            "text": "Battery swap finished at Cerro Azul. Link margin is stable again and the hill relay is back on the primary channel.",
            "reply_id": None,
            "is_emoji": False,
        },
        {
            "timestamp": base_timestamp + 8,
            "from_node_id": 1128074278,
            "to_node_id": 1128074277,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -71,
            "snr": 6.8,
            "hop_limit": 3,
            "hop_start": 5,
            "mesh_packet_id": 910000102,
            "text": "Confirmed from the repeater. Traceroutes are back to two hops and telemetry is flowing normally.",
            "reply_id": thread_root_mesh_id,
            "is_emoji": False,
        },
        {
            "timestamp": base_timestamp + 14,
            "from_node_id": 2883444196,
            "to_node_id": 1128074277,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -74,
            "snr": 5.9,
            "hop_limit": 4,
            "hop_start": 6,
            "mesh_packet_id": 910000103,
            "text": "Map looks clean now. I can add a note in the ops channel if we want to close the incident.",
            "reply_id": thread_root_mesh_id,
            "is_emoji": False,
        },
        {
            "timestamp": base_timestamp + 19,
            "from_node_id": 1128074276,
            "to_node_id": 1128074277,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -65,
            "snr": 9.3,
            "hop_limit": 3,
            "hop_start": 4,
            "mesh_packet_id": 910000104,
            "text": "👍",
            "reply_id": thread_root_mesh_id,
            "is_emoji": True,
        },
        {
            "timestamp": base_timestamp + 22,
            "from_node_id": 3735928559,
            "to_node_id": 1128074277,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -78,
            "snr": 4.7,
            "hop_limit": 4,
            "hop_start": 6,
            "mesh_packet_id": 910000105,
            "text": "🔥",
            "reply_id": thread_root_mesh_id,
            "is_emoji": True,
        },
        {
            "timestamp": base_timestamp + 30,
            "from_node_id": 1128074277,
            "to_node_id": broadcast_id,
            "gateway_id": gateway_id,
            "channel_id": channel_id,
            "channel_index": channel_index,
            "rssi": -66,
            "snr": 8.0,
            "hop_limit": 3,
            "hop_start": 4,
            "mesh_packet_id": 910000106,
            "text": "Closing this out after the next capture window. Keep an eye on the west ridge gateway for another ten minutes.",
            "reply_id": None,
            "is_emoji": False,
        },
    ]

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        _ensure_packet_history_column(cursor, "raw_service_envelope", "BLOB")

        next_packet_id = cursor.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM packet_history"
        ).fetchone()[0]

        for offset, packet in enumerate(thread_packets):
            raw_payload = packet["text"].encode("utf-8")
            raw_service_envelope = _build_service_envelope(
                mesh_packet_id=packet["mesh_packet_id"],
                timestamp=packet["timestamp"],
                from_node_id=packet["from_node_id"],
                to_node_id=packet["to_node_id"],
                channel_index=packet["channel_index"],
                channel_id=packet["channel_id"],
                hop_limit=packet["hop_limit"],
                hop_start=packet["hop_start"],
                gateway_id=packet["gateway_id"],
                text=packet["text"],
                reply_id=packet["reply_id"],
                is_emoji=packet["is_emoji"],
            )

            cursor.execute(
                """
                INSERT INTO packet_history (
                    id, timestamp, topic, from_node_id, to_node_id, portnum, portnum_name,
                    gateway_id, channel_id, rssi, snr, hop_limit, hop_start,
                    payload_length, raw_payload, mesh_packet_id, processed_successfully,
                    via_mqtt, want_ack, priority, delayed, channel_index, rx_time,
                    pki_encrypted, next_hop, relay_node, tx_after, raw_service_envelope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_packet_id + offset,
                    packet["timestamp"],
                    f"msh/US/{packet['gateway_id']}/e/{packet['channel_id']}/{packet['gateway_id']}",
                    packet["from_node_id"],
                    packet["to_node_id"],
                    int(portnums_pb2.PortNum.TEXT_MESSAGE_APP),
                    "TEXT_MESSAGE_APP",
                    packet["gateway_id"],
                    packet["channel_id"],
                    packet["rssi"],
                    packet["snr"],
                    packet["hop_limit"],
                    packet["hop_start"],
                    len(raw_payload),
                    raw_payload,
                    packet["mesh_packet_id"],
                    True,
                    True,
                    False,
                    0,
                    0,
                    packet["channel_index"],
                    int(packet["timestamp"]),
                    False,
                    None,
                    None,
                    None,
                    raw_service_envelope,
                ),
            )

        conn.commit()


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
        context = browser.new_context(
            viewport={
                "width": 1920,
                "height": 1200,
            },  # Standard FHD viewport that works well with Chart.js
            device_scale_factor=2,  # HiDPI rendering
        )
        page = context.new_page()

        # Enable console logging for debugging
        page.on(
            "console",
            lambda msg: _LOG.info(f"BROWSER CONSOLE [{msg.type}]: {msg.text}"),
        )
        page.on("pageerror", lambda error: _LOG.error(f"BROWSER ERROR: {error}"))

        for route, filename in PAGES:
            url = f"{base_url}{route}"
            _LOG.info("Capturing %s → %s", url, filename)
            screenshot_kwargs: dict[str, Any] = {
                "full_page": True,
                "type": "jpeg",
                "quality": 90,
            }

            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                _LOG.info(f"Successfully loaded {url}")
            except Exception as e:
                _LOG.error(f"Error loading {url}: {e}")
                # Try with a different wait strategy
                try:
                    page.goto(url, wait_until="load", timeout=15_000)
                    _LOG.info(f"Successfully loaded {url} with 'load' strategy")
                except Exception as e2:
                    _LOG.error(f"Failed to load {url} even with 'load' strategy: {e2}")
                    continue  # Skip this page

            # Special handling for different page types
            try:
                if route == "/":
                    # Dashboard - wait for stats cards and analytics to load
                    try:
                        _LOG.info("Dashboard: Waiting for metric cards...")
                        page.wait_for_selector(
                            ".card-metric .metric-value", timeout=10000
                        )
                        _LOG.info("Dashboard: Metric cards loaded")

                        page.wait_for_function(
                            "() => window.analyticsData !== undefined",
                            timeout=15000,
                        )
                        _LOG.info("Dashboard: analyticsData is available")

                        page.wait_for_function(
                            """() => {
                                const chartKeys = [
                                    'timeSeriesChart',
                                    'nodeActivityChart',
                                    'gatewayActivityChart',
                                    'signalDistributionChart',
                                    'hopDistributionChart',
                                    'packetTypesChart',
                                ];
                                const chartInstances = window.chartInstances || {};
                                const spinnersHidden = Array.from(document.querySelectorAll('[id$="Loading"]')).every(spinner => spinner.style.display === 'none');
                                const chartsReady = chartKeys.every(key => {
                                    const chart = chartInstances[key];
                                    const canvas = document.getElementById(key);
                                    if (!chart || !canvas) return false;
                                    const datasets = chart.data?.datasets || [];
                                    const hasData = datasets.some(dataset => Array.isArray(dataset.data) && dataset.data.length > 0);
                                    return hasData && canvas.style.display !== 'none' && canvas.offsetParent !== null && canvas.width > 0 && canvas.height > 0;
                                });
                                const topNodesTable = document.getElementById('topNodesTableContainer');
                                const topNodesRows = topNodesTable ? topNodesTable.querySelectorAll('tbody tr').length : 0;
                                return spinnersHidden && chartsReady &&
                                       topNodesTable &&
                                       topNodesTable.style.display !== 'none' &&
                                       topNodesTable.offsetParent !== null &&
                                       topNodesRows > 0;
                            }""",
                            timeout=20000,
                        )
                        _LOG.info("Dashboard: Charts, table, and loading state are ready")

                        # Give Chart.js animations time to finish drawing every panel.
                        page.wait_for_timeout(6000)
                        _LOG.info("Dashboard: Final settle wait completed")

                        _LOG.info("Dashboard analytics charts loaded")
                    except Exception as e:
                        _LOG.error(f"Dashboard loading failed: {e}")
                        # Continue with screenshot even if charts don't load

                elif route in [
                    "/traceroute-hops",
                    "/gateway/compare",
                    "/longest-links",
                ]:
                    # For hop analysis, select nodes and trigger analysis
                    if route == "/traceroute-hops":
                        try:
                            # Wait for the node picker to be fully initialized
                            page.wait_for_selector("#node1-select", timeout=10000)
                            # Wait for the node picker to be interactive (not disabled)
                            page.wait_for_function(
                                "() => !document.getElementById('node1-select').disabled",
                                timeout=5000,
                            )

                            # Method 1: Try direct JavaScript execution approach
                            # Execute JavaScript directly to trigger the analysis
                            try:
                                # Set the node values directly in the page
                                page.evaluate("""
                                    () => {
                                        // Set the hidden input values for the nodes
                                        const node1Input = document.getElementById('node1-select_value');
                                        const node2Input = document.getElementById('node2-select');

                                        if (node1Input && node2Input) {
                                            node1Input.value = '1819569748';
                                            node2Input.value = '2147483647';

                                            // Update the visible display
                                            const node1Display = document.getElementById('node1-select');
                                            if (node1Display) {
                                                node1Display.value = 'Tomate Base';
                                            }

                                            // Add an option for the second node and select it
                                            const option = document.createElement('option');
                                            option.value = '2147483647';
                                            option.textContent = 'Central Hub Node';
                                            node2Input.appendChild(option);
                                            node2Input.value = '2147483647';

                                            // Enable the analyze button
                                            const analyzeBtn = document.getElementById('analyze-btn');
                                            if (analyzeBtn) {
                                                analyzeBtn.disabled = false;
                                            }

                                            return true;
                                        }
                                        return false;
                                    }
                                """)

                                # Wait for the analyze button to be enabled
                                page.wait_for_function(
                                    "() => !document.getElementById('analyze-btn').disabled",
                                    timeout=3000,
                                )

                                # Now trigger the analysis by calling the JavaScript function directly
                                page.evaluate("""
                                    () => {
                                        // Call the analyzeHop function directly
                                        if (typeof analyzeHop === 'function') {
                                            analyzeHop();
                                            return true;
                                        }
                                        return false;
                                    }
                                """)

                                _LOG.info("Triggered hop analysis via JavaScript")

                                # Wait for results to appear and be populated
                                page.wait_for_selector(
                                    "#results-section", timeout=15000
                                )
                                page.wait_for_function(
                                    "() => document.getElementById('results-section').style.display === 'block'",
                                    timeout=10000,
                                )

                                # Wait for actual content to load in results
                                page.wait_for_selector(
                                    "#results-section .traceroute-item, #results-section .hop-analysis-card, #results-section table",
                                    timeout=8000,
                                )

                                # Wait for Chart.js charts to finish rendering
                                page.wait_for_function(
                                    """() => {
                                        const charts = Object.values(Chart.instances || {});
                                        return charts.length === 0 || charts.every(chart => chart.isReady !== false);
                                    }""",
                                    timeout=5000,
                                )

                                page.wait_for_timeout(timeout=3000)

                                _LOG.info(
                                    "Results section is now visible with content and charts loaded"
                                )

                            except Exception as js_e:
                                _LOG.warning(
                                    f"JavaScript approach failed: {js_e}, trying fallback"
                                )
                                raise js_e

                        except Exception as e:
                            _LOG.warning(f"Primary hop analysis approach failed: {e}")
                            # Fallback: Manual node selection
                            try:
                                # Go back to the base page
                                page.goto(
                                    f"{base_url}/traceroute-hops",
                                    wait_until="networkidle",
                                )

                                # Wait for the node picker to be ready and interactive
                                page.wait_for_selector("#node1-select", timeout=5000)
                                page.wait_for_function(
                                    "() => !document.getElementById('node1-select').disabled",
                                    timeout=3000,
                                )

                                # Method 2: Try to select "Tomate" (which should match our test node)
                                node1_input = page.query_selector("#node1-select")
                                if node1_input:
                                    node1_input.click()
                                    node1_input.fill("Tomate")  # Search for Tomate Base

                                    # Wait for search results to appear
                                    page.wait_for_selector(
                                        ".node-picker-dropdown .node-option:first-child",
                                        timeout=5000,
                                    )

                                    # Try to click the first option
                                    first_option = page.query_selector(
                                        ".node-picker-dropdown .node-option:first-child"
                                    )
                                    if first_option:
                                        first_option.click()

                                        # Wait for second node dropdown to populate with options
                                        page.wait_for_function(
                                            "() => document.getElementById('node2-select').options.length > 1",
                                            timeout=5000,
                                        )

                                        # Select second node
                                        node2_options = page.query_selector_all(
                                            "#node2-select option"
                                        )
                                        if len(node2_options) > 1:
                                            # Try to find "Central Hub" or use first available
                                            central_hub_option = None
                                            for option in node2_options[
                                                1:
                                            ]:  # Skip placeholder
                                                option_text = option.inner_text()
                                                if (
                                                    "Central" in option_text
                                                    or "Hub" in option_text
                                                ):
                                                    central_hub_option = option
                                                    break

                                            if central_hub_option:
                                                central_hub_option.click()
                                            else:
                                                page.select_option(
                                                    "#node2-select", index=1
                                                )

                                            # Wait for analyze button to be enabled
                                            page.wait_for_function(
                                                "() => !document.getElementById('analyze-btn').disabled",
                                                timeout=3000,
                                            )

                                            # Trigger analysis
                                            analyze_btn = page.query_selector(
                                                "#analyze-btn"
                                            )
                                            if (
                                                analyze_btn
                                                and not analyze_btn.is_disabled()
                                            ):
                                                _LOG.info(
                                                    "Triggering hop analysis via manual selection"
                                                )
                                                analyze_btn.click()

                                                # Wait for results to appear with content
                                                try:
                                                    page.wait_for_selector(
                                                        "#results-section",
                                                        timeout=10000,
                                                    )
                                                    page.wait_for_function(
                                                        "() => document.getElementById('results-section').style.display === 'block'",
                                                        timeout=8000,
                                                    )
                                                    page.wait_for_selector(
                                                        "#results-section .traceroute-item, #results-section table",
                                                        timeout=5000,
                                                    )
                                                    # Wait for Chart.js charts to load
                                                    page.wait_for_function(
                                                        """() => {
                                                            const charts = Object.values(Chart.instances || {});
                                                            return charts.length === 0 || charts.every(chart => chart.isReady !== false);
                                                        }""",
                                                        timeout=5000,
                                                    )
                                                except Exception:
                                                    _LOG.warning(
                                                        "Results section never appeared"
                                                    )
                                                    pass
                                    else:
                                        _LOG.warning(
                                            "Could not find node picker options"
                                        )

                            except Exception as fallback_e:
                                _LOG.warning(
                                    f"Fallback hop analysis also failed: {fallback_e}"
                                )
                                pass  # Continue with whatever we have

                    # For gateway compare, select gateways and trigger comparison
                    elif route == "/gateway/compare":
                        try:
                            # Wait for gateway dropdowns to populate with options
                            page.wait_for_selector("#gateway1", timeout=5000)
                            page.wait_for_function(
                                "() => document.getElementById('gateway1').options.length > 1",
                                timeout=5000,
                            )

                            # Select first gateway
                            gateway1_options = page.query_selector_all(
                                "#gateway1 option"
                            )
                            if len(gateway1_options) > 1:  # Skip placeholder
                                page.select_option("#gateway1", index=1)

                            # Wait for second gateway dropdown to populate
                            page.wait_for_function(
                                "() => document.getElementById('gateway2').options.length > 1",
                                timeout=5000,
                            )

                            # Select second gateway (different from first)
                            gateway2_options = page.query_selector_all(
                                "#gateway2 option"
                            )
                            if (
                                len(gateway2_options) > 2
                            ):  # Skip placeholder and first option
                                page.select_option("#gateway2", index=2)
                            elif len(gateway2_options) > 1:  # Fallback to second option
                                page.select_option("#gateway2", index=1)

                            # Wait for compare button to be enabled
                            page.wait_for_function(
                                "() => { const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Compare Gateways')); return btn && !btn.disabled; }",
                                timeout=3000,
                            )

                            # Click the Compare Gateways button
                            compare_btn = page.query_selector(
                                "button:has-text('Compare Gateways')"
                            )
                            if compare_btn:
                                compare_btn.click()
                            else:
                                # Alternative: submit the form directly
                                form = page.query_selector("#gatewayForm")
                                if form:
                                    form.evaluate("form => form.submit()")

                            # Wait for comparison results to appear
                            page.wait_for_selector(
                                ".stats-card, .chart-container, #commonPacketsTable",
                                timeout=10000,
                            )

                            # Wait for Plotly charts to finish rendering
                            page.wait_for_function(
                                """() => {
                                    if (typeof Plotly === 'undefined') return true;
                                    const plotlyDivs = document.querySelectorAll('.js-plotly-plot');
                                    return Array.from(plotlyDivs).every(div => {
                                        return div._fullLayout && div._fullData;
                                    });
                                }""",
                                timeout=10000,
                            )

                            # Wait for DataTables to initialize
                            page.wait_for_function(
                                """() => {
                                    if (typeof $ === 'undefined' || typeof $.fn.DataTable === 'undefined') return true;
                                    const table = document.getElementById('commonPacketsTable');
                                    return !table || $.fn.DataTable.isDataTable(table);
                                }""",
                                timeout=5000,
                            )

                            _LOG.info("Gateway comparison charts and tables loaded")

                        except Exception as e:
                            _LOG.warning(f"Gateway compare selection failed: {e}")
                            pass  # Continue if gateway selection fails

                    # For longest links, wait for the analysis to complete
                    elif route == "/longest-links":
                        try:
                            # Wait for the longest links table to populate with data
                            page.wait_for_selector("table tbody tr", timeout=8000)

                            # Wait for DataTables to initialize if present
                            page.wait_for_function(
                                """() => {
                                    if (typeof $ === 'undefined' || typeof $.fn.DataTable === 'undefined') return true;
                                    const tables = document.querySelectorAll('table');
                                    return Array.from(tables).every(table =>
                                        !table.id || $.fn.DataTable.isDataTable(table)
                                    );
                                }""",
                                timeout=5000,
                            )
                        except Exception:
                            pass  # Continue if table doesn't populate

                elif route == "/line-of-sight":
                    # Line of Sight Analysis - set nodes and trigger analysis
                    try:
                        # Wait for node pickers to be ready
                        page.wait_for_selector("#fromNode", timeout=5000)
                        page.wait_for_selector("#toNode", timeout=5000)
                        page.wait_for_timeout(2000)  # Wait for caches to load

                        # Use JavaScript to set node values directly (avoids dropdown z-index issues)
                        page.evaluate("""
                            () => {
                                // Set from node (Tomate Base)
                                document.getElementById('fromNode_value').value = '1819569748';
                                document.getElementById('fromNode').value = 'Tomate Base';
                                document.getElementById('fromNode_value').dispatchEvent(new Event('change'));

                                // Set to node (Central Hub Node)
                                document.getElementById('toNode_value').value = '2147483647';
                                document.getElementById('toNode').value = 'Central Hub Node';
                                document.getElementById('toNode_value').dispatchEvent(new Event('change'));
                            }
                        """)

                        # Wait for handlers to process
                        page.wait_for_timeout(1000)

                        # Wait for analyze button to be enabled
                        page.wait_for_function(
                            "() => !document.getElementById('analyzeBtn').disabled",
                            timeout=3000,
                        )

                        # Click analyze button
                        analyze_btn = page.query_selector("#analyzeBtn")
                        if analyze_btn and not analyze_btn.is_disabled():
                            _LOG.info("Triggering line-of-sight analysis")
                            analyze_btn.click()

                            # Wait for results to appear
                            try:
                                page.wait_for_selector(
                                    "#resultsContainer", timeout=15000
                                )
                                page.wait_for_function(
                                    "() => document.getElementById('resultsContainer').style.display !== 'none'",
                                    timeout=10000,
                                )

                                # Wait for map to render
                                page.wait_for_selector(
                                    "#line-of-sight-map", timeout=5000
                                )

                                # Wait for chart to render
                                page.wait_for_selector("#elevationChart", timeout=5000)

                                # Wait for Chart.js to finish rendering
                                page.wait_for_function(
                                    """() => {
                                        if (typeof Chart === 'undefined') return false;
                                        const charts = Object.values(Chart.instances || {});
                                        return charts.length > 0 && charts.every(chart =>
                                            chart.canvas &&
                                            chart.canvas.width > 0 &&
                                            chart.canvas.height > 0 &&
                                            chart.isReady !== false
                                        );
                                    }""",
                                    timeout=10000,
                                )

                                # Wait for map tiles to load
                                page.wait_for_function(
                                    "() => document.querySelectorAll('.leaflet-tile-loaded').length > 0",
                                    timeout=8000,
                                )

                                _LOG.info("Line-of-sight analysis results loaded")

                                # Additional wait for stability
                                page.wait_for_timeout(2000)

                            except Exception as results_e:
                                _LOG.warning(
                                    f"Line-of-sight results didn't load: {results_e}"
                                )

                    except Exception as e:
                        _LOG.warning(f"Line-of-sight setup failed: {e}")
                        pass  # Continue with screenshot even if analysis fails

                elif route == "/chat":
                    try:
                        page.wait_for_function(
                            """() => {
                                const loading = document.getElementById('chatLoading');
                                const lines = document.querySelectorAll('#chatMessages .chat-line');
                                return (!loading || loading.style.display === 'none' || !loading.isConnected) && lines.length > 0;
                            }""",
                            timeout=15000,
                        )

                        page.wait_for_timeout(2000)

                        chat_state = page.evaluate("""() => {
                            const filters = document.querySelector('.chat-filters');
                            const container = document.querySelector('.chat-container');
                            const messages = document.getElementById('chatMessages');
                            const lines = Array.from(document.querySelectorAll('#chatMessages .chat-line'));
                            const scored = lines
                                .map((line, index) => {
                                    const children = line.querySelectorAll('.chat-child').length;
                                    const replies = line.querySelectorAll('.chat-child-reply').length;
                                    const reactions = line.querySelectorAll('.chat-child-reaction').length;
                                    const textLength = (line.querySelector('.chat-text')?.textContent || '').trim().length;
                                    const score = (children * 10) + (replies * 6) + (reactions * 8) + Math.min(textLength, 120) + index;
                                    return { line, children, replies, reactions, score };
                                })
                                .sort((a, b) => b.score - a.score);
                            const richest = scored[0] || null;
                            const target = richest?.line || lines[Math.max(0, lines.length - 8)] || null;

                            if (messages && target) {
                                const targetOffset = target.offsetTop - 96;
                                messages.scrollTop = Math.max(0, targetOffset);
                                target.scrollIntoView({ block: 'center', inline: 'nearest' });
                            }

                            let clip = null;
                            if (container && target) {
                                const containerRect = container.getBoundingClientRect();
                                const targetRect = target.getBoundingClientRect();
                                const clipTop = 0;
                                const desiredBottom = Math.min(containerRect.bottom - 8, targetRect.bottom + 140);
                                const clipHeight = Math.max(520, Math.min(desiredBottom - clipTop, window.innerHeight - clipTop - 8));
                                clip = {
                                    x: Math.max(containerRect.left - 6, 0) + window.scrollX,
                                    y: clipTop + window.scrollY,
                                    width: Math.min(containerRect.width + 12, window.innerWidth - Math.max(containerRect.left - 6, 0) - 8),
                                    height: clipHeight,
                                };
                            }

                            return {
                                lineCount: lines.length,
                                replyCount: document.querySelectorAll('#chatMessages .chat-child-reply').length,
                                reactionCount: document.querySelectorAll('#chatMessages .chat-child-reaction').length,
                                highlightedRichThread: !!richest,
                                selectedChildren: richest?.children || 0,
                                selectedReplies: richest?.replies || 0,
                                selectedReactions: richest?.reactions || 0,
                                clip,
                            };
                        }""")

                        _LOG.info("Chat screenshot state: %s", chat_state)
                        if chat_state.get("clip"):
                            screenshot_kwargs["full_page"] = False
                            screenshot_kwargs["clip"] = chat_state["clip"]
                    except Exception as e:
                        _LOG.warning(f"Chat page setup failed: {e}")
                        pass

                elif route in ["/traceroute", "/packets", "/nodes"]:
                    # Table pages - wait for content to load
                    try:
                        # Wait for table content to load
                        page.wait_for_selector("table tbody tr", timeout=8000)

                        # Wait for DataTables to initialize
                        page.wait_for_function(
                            """() => {
                                if (typeof $ === 'undefined' || typeof $.fn.DataTable === 'undefined') return true;
                                const tables = document.querySelectorAll('table');
                                return Array.from(tables).every(table =>
                                    !table.id || $.fn.DataTable.isDataTable(table)
                                );
                            }""",
                            timeout=5000,
                        )
                    except Exception:
                        pass  # Continue if table doesn't populate

                elif route == "/traceroute-graph":
                    # Network graph - wait for visualization to render
                    try:
                        # Wait for the network graph SVG to be drawn
                        page.wait_for_selector("svg", timeout=10000)
                        # Wait for nodes to appear in the graph
                        page.wait_for_selector("svg circle, svg g.node", timeout=8000)

                        # Wait for D3 simulation to stabilize

                        page.wait_for_timeout(timeout=3000)

                        page.wait_for_function(
                            """() => {
                                // Check if D3 simulation has finished or stabilized
                                return window.simulation === undefined ||
                                       window.simulation.alpha() < 0.01;
                            }""",
                            timeout=15000,
                        )

                        _LOG.info("D3 network graph stabilized")
                    except Exception:
                        pass  # Continue if graph doesn't render

                elif route == "/map":
                    # Map - wait for tiles and markers to load
                    try:
                        # Wait for map markers to appear
                        page.wait_for_selector(".leaflet-marker-icon", timeout=10000)
                        # Wait for map tiles to load
                        page.wait_for_function(
                            "() => document.querySelectorAll('.leaflet-tile-loaded').length > 0",
                            timeout=8000,
                        )
                        # Wait for Leaflet map to be fully loaded
                        page.wait_for_function(
                            """() => {
                                return window.map !== undefined &&
                                       document.querySelectorAll('.leaflet-loading').length === 0;
                            }""",
                            timeout=10000,
                        )
                    except Exception:
                        pass  # Continue if map doesn't load markers

            except Exception:  # noqa: BLE001
                pass  # Continue with screenshot even if special handling fails

            dest = out_dir / filename
            page.screenshot(path=str(dest), **screenshot_kwargs)
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
        help="Where to place the generated JPG files.",
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
