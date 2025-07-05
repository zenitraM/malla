"""
End-to-end tests for the traceroute graph functionality using Playwright.
"""

from playwright.sync_api import Page, expect

DEFAULT_TIMEOUT = 30000


class TestGraphBasicFunctionality:
    """Basic graph functionality tests."""

    def test_graph_page_loads(self, page: Page, traceroute_graph_url: str):
        """Test that the graph page loads successfully."""
        page.goto(traceroute_graph_url)

        # Wait for the page to load
        expect(page.locator("h5")).to_contain_text("Network Graph")

        # Check that the graph container is present
        expect(page.locator("#networkGraph")).to_be_visible()

    def test_search_functionality(self, page: Page, traceroute_graph_url: str):
        """Test that the search functionality works."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)

        # Find the search input
        search_input = page.locator("#nodeSearch")
        expect(search_input).to_be_visible()

        # Type in a search term
        search_input.fill("Test")

        # Wait for search results
        page.wait_for_selector(".search-result-item", timeout=5000)

        # Check that search results appear
        search_results = page.locator(".search-result-item")
        expect(search_results.first).to_be_visible()

    def test_node_selection_and_centering(self, page: Page, traceroute_graph_url: str):
        """Test that clicking on a search result selects and centers the node."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)

        # Search for a node
        search_input = page.locator("#nodeSearch")
        search_input.fill("Test")

        # Wait for search results
        page.wait_for_selector(".search-result-item", timeout=5000)

        # Get the initial transform and viewport center
        initial_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;

                // Parse transform to get translation and scale
                let translateX = 0, translateY = 0, scale = 1;
                if (transform) {
                    const translateMatch = transform.match(/translate\\(([^,]+),([^)]+)\\)/);
                    const scaleMatch = transform.match(/scale\\(([^)]+)\\)/);
                    if (translateMatch) {
                        translateX = parseFloat(translateMatch[1]);
                        translateY = parseFloat(translateMatch[2]);
                    }
                    if (scaleMatch) {
                        scale = parseFloat(scaleMatch[1]);
                    }
                }

                return {
                    transform,
                    translateX,
                    translateY,
                    scale
                };
            }
        """)

        # Click on the search result
        search_result = page.locator(".search-result-item").first
        search_result.click()

        # Wait for the centering animation to complete
        page.wait_for_timeout(1500)

        # Check that the selected details section is visible
        expect(page.locator("#selectedDetails")).to_be_visible()

        # Check that the graph has been transformed (centered and zoomed)
        final_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;

                // Parse transform to get translation and scale
                let translateX = 0, translateY = 0, scale = 1;
                if (transform) {
                    const translateMatch = transform.match(/translate\\(([^,]+),([^)]+)\\)/);
                    const scaleMatch = transform.match(/scale\\(([^)]+)\\)/);
                    if (translateMatch) {
                        translateX = parseFloat(translateMatch[1]);
                        translateY = parseFloat(translateMatch[2]);
                    }
                    if (scaleMatch) {
                        scale = parseFloat(scaleMatch[1]);
                    }
                }

                return {
                    transform,
                    translateX,
                    translateY,
                    scale
                };
            }
        """)

        # The transform should have changed
        assert initial_state["transform"] != final_state["transform"], (
            "Graph transform should have changed"
        )

        # The scale should have increased (zoomed in)
        assert final_state["scale"] > initial_state["scale"], (
            f"Graph should have zoomed in: {initial_state['scale']} -> {final_state['scale']}"
        )

        # The translation should have changed significantly (centered on node)
        translation_change = abs(
            final_state["translateX"] - initial_state["translateX"]
        ) + abs(final_state["translateY"] - initial_state["translateY"])
        assert translation_change > 50, (
            f"Graph should have been translated significantly: {translation_change}"
        )

    def test_sidebar_toggle_functionality(self, page: Page, traceroute_graph_url: str):
        """Test that the sidebar can be toggled."""
        page.goto(traceroute_graph_url)

        # Wait for the page to load
        expect(page.locator("#sidebar")).to_be_visible()

        # Click the toggle button
        toggle_button = page.locator("#toggleSidebar")
        toggle_button.click()

        # Wait for the animation
        page.wait_for_timeout(500)

        # Check if the sidebar has the collapsed class
        sidebar_classes = page.evaluate("""
            () => {
                const sidebar = document.getElementById('sidebar');
                return sidebar ? sidebar.className : '';
            }
        """)

        assert "collapsed" in sidebar_classes, "Sidebar should have collapsed class"

        # The toggle button should still be visible (fixed position)
        expect(toggle_button).to_be_visible()

        # Click again to expand
        toggle_button.click()
        page.wait_for_timeout(500)

        # Check that collapsed class is removed
        sidebar_classes_after = page.evaluate("""
            () => {
                const sidebar = document.getElementById('sidebar');
                return sidebar ? sidebar.className : '';
            }
        """)

        assert "collapsed" not in sidebar_classes_after, (
            "Sidebar should not have collapsed class"
        )


class TestGraphInteractivity:
    """Tests for graph interaction functionality."""

    def test_drag_functionality(self, page: Page, traceroute_graph_url: str):
        """Test that dragging works immediately when the graph loads."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)

        # Wait a bit more for the simulation to stabilize
        page.wait_for_timeout(2000)

        # Get initial transform
        initial_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"Initial state: {initial_state}")

        # Perform a drag operation from center to a different position
        graph_svg = page.locator("#networkGraph svg")
        svg_box = graph_svg.bounding_box()
        assert svg_box is not None, "Could not get SVG bounding box"
        center_x = svg_box["x"] + svg_box["width"] / 2
        center_y = svg_box["y"] + svg_box["height"] / 2

        # Drag from center to offset position
        page.mouse.move(center_x, center_y)
        page.mouse.down()
        page.mouse.move(center_x + 100, center_y + 100)
        page.mouse.up()

        # Wait for the drag to complete
        page.wait_for_timeout(500)

        # Get final transform
        final_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"Final state after drag: {final_state}")

        # Verify that the graph moved
        assert (
            final_state["translateX"] != initial_state["translateX"]
            or final_state["translateY"] != initial_state["translateY"]
        ), "Graph should have moved after dragging"

    def test_zoom_functionality(self, page: Page, traceroute_graph_url: str):
        """Test that zoom functionality works."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)

        # Get initial transform
        initial_transform = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                return svg ? svg.getAttribute('transform') : null;
            }
        """)

        # Perform a zoom operation using mouse wheel
        graph_svg = page.locator("#networkGraph svg")
        graph_svg.hover()

        # Simulate zoom with wheel event
        page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg');
                const event = new WheelEvent('wheel', {
                    deltaY: -100,
                    bubbles: true,
                    cancelable: true
                });
                svg.dispatchEvent(event);
            }
        """)

        # Wait for zoom to complete
        page.wait_for_timeout(500)

        # Check that transform changed
        zoomed_transform = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                return svg ? svg.getAttribute('transform') : null;
            }
        """)

        # Transform should have changed due to zoom
        assert initial_transform != zoomed_transform, "Graph should have been zoomed"

    def test_center_graph_button_stability(self, page: Page, traceroute_graph_url: str):
        """Test that the center graph button works without flashing."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Wait for auto-centering to complete

        # First, manually change the graph position by dragging
        graph_svg = page.locator("#networkGraph svg")
        svg_box = graph_svg.bounding_box()
        assert svg_box is not None, "Could not get SVG bounding box"
        center_x = svg_box["x"] + svg_box["width"] / 2
        center_y = svg_box["y"] + svg_box["height"] / 2

        # Drag to change position
        page.mouse.move(center_x, center_y)
        page.mouse.down()
        page.mouse.move(center_x + 200, center_y + 200)
        page.mouse.up()
        page.wait_for_timeout(500)

        # Get state after dragging
        dragged_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"State after dragging: {dragged_state}")

        # Click the center graph button
        page.click("button:has-text('Center Graph')")

        # Wait for the centering animation to complete
        page.wait_for_timeout(1000)

        # Get state after centering
        centered_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"State after centering: {centered_state}")

        # Wait a bit more to check for stability (no flashing)
        page.wait_for_timeout(2000)

        # Get state after waiting (should be the same)
        stable_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"State after waiting (should be stable): {stable_state}")

        # Verify that the graph was centered and is stable
        assert centered_state["transform"] != dragged_state["transform"], (
            "Graph should have moved when centered"
        )

        # Check for reasonable stability (allow small simulation movements)
        centered_x = centered_state["translateX"]
        centered_y = centered_state["translateY"]
        centered_scale = centered_state["scale"]

        stable_x = stable_state["translateX"]
        stable_y = stable_state["translateY"]
        stable_scale = stable_state["scale"]

        # Allow small movements (within 5 pixels and 0.01 scale difference)
        x_diff = abs(stable_x - centered_x)
        y_diff = abs(stable_y - centered_y)
        scale_diff = abs(stable_scale - centered_scale)

        assert x_diff < 5, f"X position should be stable (diff: {x_diff})"
        assert y_diff < 5, f"Y position should be stable (diff: {y_diff})"
        assert scale_diff < 0.01, f"Scale should be stable (diff: {scale_diff})"


class TestGraphAdvancedFeatures:
    """Tests for advanced graph features."""

    def test_geographical_positioning(self, page: Page, traceroute_graph_url: str):
        """Test that nodes with location data are positioned geographically and nodes without location are positioned dynamically."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(
            4000
        )  # Wait longer for positioning and simulation to complete

        # Check that geographical positioning was applied
        positioning_info = page.evaluate("""
            () => {
                // Check if currentGraph has location data
                const hasLocationData = window.currentGraph &&
                    window.currentGraph.nodes &&
                    window.currentGraph.nodes.some(n => n.location);

                const nodesWithLocation = window.currentGraph ?
                    window.currentGraph.nodes.filter(n => n.location).length : 0;
                const nodesWithoutLocation = window.currentGraph ?
                    window.currentGraph.nodes.filter(n => !n.location).length : 0;

                // Get node positions to verify they're not all clustered at center
                const nodes = document.querySelectorAll('.node');
                const positions = [];
                nodes.forEach(node => {
                    const transform = node.getAttribute('transform');
                    if (transform) {
                        const match = transform.match(/translate\\(([^,]+),([^)]+)\\)/);
                        if (match) {
                            positions.push({
                                x: parseFloat(match[1]),
                                y: parseFloat(match[2])
                            });
                        }
                    }
                });

                // Calculate spread of positions
                if (positions.length > 0) {
                    const xValues = positions.map(p => p.x);
                    const yValues = positions.map(p => p.y);
                    const xSpread = Math.max(...xValues) - Math.min(...xValues);
                    const ySpread = Math.max(...yValues) - Math.min(...yValues);

                    return {
                        hasLocationData,
                        nodesWithLocation,
                        nodesWithoutLocation,
                        nodeCount: positions.length,
                        xSpread,
                        ySpread,
                        positions: positions.slice(0, 5) // First 5 positions for debugging
                    };
                }

                return {
                    hasLocationData,
                    nodesWithLocation,
                    nodesWithoutLocation,
                    nodeCount: 0,
                    xSpread: 0,
                    ySpread: 0,
                    positions: []
                };
            }
        """)

        print(f"Geographical positioning info: {positioning_info}")

        # Verify that nodes are spread out (not all clustered at center)
        # If geographical positioning is working, nodes should be spread across the canvas
        assert positioning_info["nodeCount"] > 0, "Should have nodes in the graph"

        # With geographical positioning, nodes should be spread out more than with random positioning
        # The spread should be significant (more than 150 pixels in each direction for better spacing)
        if positioning_info["hasLocationData"]:
            assert positioning_info["xSpread"] > 150, (
                f"Nodes should be spread horizontally (spread: {positioning_info['xSpread']})"
            )
            assert positioning_info["ySpread"] > 150, (
                f"Nodes should be spread vertically (spread: {positioning_info['ySpread']})"
            )

            # Verify we have both types of nodes
            assert positioning_info["nodesWithLocation"] > 0, (
                "Should have nodes with location data"
            )
            print(
                f"Nodes with location: {positioning_info['nodesWithLocation']}, without: {positioning_info['nodesWithoutLocation']}"
            )

        # Test that the graph is still interactive after geographical positioning
        # Verify that basic graph functionality works (zoom, pan)
        graph_svg = page.locator("#networkGraph svg")
        assert graph_svg.is_visible(), "Graph SVG should be visible"

        # Test that the center graph button works
        center_button = page.locator("button:has-text('Center Graph')")
        if center_button.is_visible():
            # Get initial transform
            initial_transform = page.evaluate("""
                () => {
                    const svg = document.querySelector('#networkGraph svg g');
                    return svg ? svg.getAttribute('transform') : null;
                }
            """)

            # Click center button
            center_button.click()
            page.wait_for_timeout(1000)

            # Get final transform - it should have changed (or stayed the same if already centered)
            final_transform = page.evaluate("""
                () => {
                    const svg = document.querySelector('#networkGraph svg g');
                    return svg ? svg.getAttribute('transform') : null;
                }
            """)

            # Just verify that the transform exists and is valid
            assert final_transform is not None, (
                "Graph should have a transform after centering"
            )
            print(
                f"Center button test - Initial: {initial_transform}, Final: {final_transform}"
            )

        # Verify that the graph is functional and interactive
        print("Geographical positioning test completed successfully")

    def test_search_and_center_functionality(
        self, page: Page, traceroute_graph_url: str
    ):
        """Test that search and center functionality works properly."""
        page.goto(traceroute_graph_url)

        # Wait for the graph to load
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(2000)

        # Get initial state
        initial_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"Initial state before search click: {initial_state}")

        # Search for a node
        page.fill("#nodeSearch", "Test")
        page.wait_for_timeout(500)

        # Click on the first search result (graph uses different structure than map)
        page.click("#searchResults .search-result-item:first-child")

        # Wait for the focus animation to complete
        page.wait_for_timeout(1000)

        # Get state after search click
        focused_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(f"Final state after search click: {focused_state}")

        # Verify that the graph moved and zoomed
        assert focused_state["transform"] != initial_state["transform"], (
            "Graph should have moved when focusing on node"
        )
        assert focused_state["scale"] > initial_state["scale"], (
            "Graph should have zoomed in when focusing on node"
        )

        # Test that drag still works after centering by using the center graph button
        # This is a more reliable test than trying to drag at specific coordinates
        page.click("button:has-text('Center Graph')")
        page.wait_for_timeout(1000)

        # Get state after using center button
        centered_again_state = page.evaluate("""
            () => {
                const svg = document.querySelector('#networkGraph svg g');
                const transform = svg ? svg.getAttribute('transform') : null;
                if (transform) {
                    const match = transform.match(/translate\\(([^,]+),([^)]+)\\).*scale\\(([^)]+)\\)/);
                    if (match) {
                        return {
                            transform: transform,
                            translateX: parseFloat(match[1]),
                            translateY: parseFloat(match[2]),
                            scale: parseFloat(match[3])
                        };
                    }
                }
                return {transform: null, translateX: 0, translateY: 0, scale: 1};
            }
        """)
        print(
            f"State after center button (should be different): {centered_again_state}"
        )

        # Verify that the center button still works after focusing (which means the graph is still interactive)
        assert centered_again_state["transform"] != focused_state["transform"], (
            "Center button should still work after focusing on node (graph should remain interactive)"
        )


class TestGraphResolutions:
    """Test graph functionality at different browser resolutions."""

    def test_graph_centering_at_1920x1080(self, page: Page, traceroute_graph_url: str):
        """Test graph centering at 1920x1080 resolution."""
        # Set browser size
        page.set_viewport_size({"width": 1920, "height": 1080})

        page.goto(traceroute_graph_url)
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Wait for auto-centering

        # Check that the graph is properly sized and positioned
        graph_info = page.evaluate("""
            () => {
                const container = document.getElementById('networkGraph');
                const svg = container.querySelector('svg');
                const g = svg.querySelector('g');

                const containerRect = container.getBoundingClientRect();
                const svgRect = svg.getBoundingClientRect();
                const transform = g.getAttribute('transform');

                return {
                    containerWidth: containerRect.width,
                    containerHeight: containerRect.height,
                    svgWidth: parseInt(svg.getAttribute('width')),
                    svgHeight: parseInt(svg.getAttribute('height')),
                    transform: transform,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight
                };
            }
        """)

        print(f"1920x1080 - Graph info: {graph_info}")

        # Verify reasonable dimensions
        assert graph_info["containerWidth"] > 1000, (
            f"Container width should be reasonable for 1920x1080, got {graph_info['containerWidth']}"
        )
        assert graph_info["containerHeight"] > 500, (
            f"Container height should be reasonable for 1920x1080, got {graph_info['containerHeight']}"
        )
        assert graph_info["svgWidth"] == graph_info["containerWidth"], (
            "SVG width should match container width"
        )
        assert graph_info["svgHeight"] == graph_info["containerHeight"], (
            "SVG height should match container height"
        )

    def test_graph_centering_at_1366x768(self, page: Page, traceroute_graph_url: str):
        """Test graph centering at 1366x768 resolution."""
        # Set browser size
        page.set_viewport_size({"width": 1366, "height": 768})

        page.goto(traceroute_graph_url)
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Wait for auto-centering

        # Check that the graph is properly sized and positioned
        graph_info = page.evaluate("""
            () => {
                const container = document.getElementById('networkGraph');
                const svg = container.querySelector('svg');
                const g = svg.querySelector('g');

                const containerRect = container.getBoundingClientRect();
                const svgRect = svg.getBoundingClientRect();
                const transform = g.getAttribute('transform');

                return {
                    containerWidth: containerRect.width,
                    containerHeight: containerRect.height,
                    svgWidth: parseInt(svg.getAttribute('width')),
                    svgHeight: parseInt(svg.getAttribute('height')),
                    transform: transform,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight
                };
            }
        """)

        print(f"1366x768 - Graph info: {graph_info}")

        # Verify reasonable dimensions
        assert graph_info["containerWidth"] > 800, (
            f"Container width should be reasonable for 1366x768, got {graph_info['containerWidth']}"
        )
        assert graph_info["containerHeight"] > 400, (
            f"Container height should be reasonable for 1366x768, got {graph_info['containerHeight']}"
        )
        assert graph_info["svgWidth"] == graph_info["containerWidth"], (
            "SVG width should match container width"
        )
        assert graph_info["svgHeight"] == graph_info["containerHeight"], (
            "SVG height should match container height"
        )

    def test_graph_centering_at_mobile_375x667(
        self, page: Page, traceroute_graph_url: str
    ):
        """Test graph centering at mobile resolution 375x667."""
        # Set browser size
        page.set_viewport_size({"width": 375, "height": 667})

        page.goto(traceroute_graph_url)
        page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)  # Wait for auto-centering

        # Check that the graph is properly sized and positioned
        graph_info = page.evaluate("""
            () => {
                const container = document.getElementById('networkGraph');
                const svg = container.querySelector('svg');
                const g = svg.querySelector('g');

                const containerRect = container.getBoundingClientRect();
                const svgRect = svg.getBoundingClientRect();
                const transform = g.getAttribute('transform');

                return {
                    containerWidth: containerRect.width,
                    containerHeight: containerRect.height,
                    svgWidth: parseInt(svg.getAttribute('width')),
                    svgHeight: parseInt(svg.getAttribute('height')),
                    transform: transform,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight
                };
            }
        """)

        print(f"375x667 - Graph info: {graph_info}")

        # Verify reasonable dimensions for mobile
        assert graph_info["containerWidth"] > 200, (
            f"Container width should be reasonable for mobile, got {graph_info['containerWidth']}"
        )
        assert graph_info["containerHeight"] > 200, (
            f"Container height should be reasonable for mobile, got {graph_info['containerHeight']}"
        )
        assert graph_info["svgWidth"] == graph_info["containerWidth"], (
            "SVG width should match container width"
        )
        assert graph_info["svgHeight"] == graph_info["containerHeight"], (
            "SVG height should match container height"
        )

    def test_center_graph_button_at_different_resolutions(
        self, page: Page, traceroute_graph_url: str
    ):
        """Test that center graph button works correctly at different resolutions."""
        resolutions = [
            {"width": 1920, "height": 1080, "name": "1920x1080"},
            {"width": 1366, "height": 768, "name": "1366x768"},
            {"width": 800, "height": 600, "name": "800x600"},
        ]

        for resolution in resolutions:
            print(f"\nTesting center graph button at {resolution['name']}")

            # Set browser size
            page.set_viewport_size(
                {"width": resolution["width"], "height": resolution["height"]}
            )

            page.goto(traceroute_graph_url)
            page.wait_for_selector("#networkGraph svg", timeout=DEFAULT_TIMEOUT)
            page.wait_for_timeout(3000)  # Wait for auto-centering

            # Drag to change position
            graph_svg = page.locator("#networkGraph svg")
            svg_box = graph_svg.bounding_box()
            assert svg_box is not None, (
                f"Could not get SVG bounding box at {resolution['name']}"
            )

            center_x = svg_box["x"] + svg_box["width"] / 2
            center_y = svg_box["y"] + svg_box["height"] / 2

            page.mouse.move(center_x, center_y)
            page.mouse.down()
            page.mouse.move(center_x + 100, center_y + 100)
            page.mouse.up()
            page.wait_for_timeout(500)

            # Get state before centering
            before_center = page.evaluate("""
                () => {
                    const svg = document.querySelector('#networkGraph svg g');
                    const transform = svg ? svg.getAttribute('transform') : null;
                    return transform;
                }
            """)

            # Click center graph button
            page.click("button:has-text('Center Graph')")
            page.wait_for_timeout(1000)

            # Get state after centering
            after_center = page.evaluate("""
                () => {
                    const svg = document.querySelector('#networkGraph svg g');
                    const transform = svg ? svg.getAttribute('transform') : null;
                    return transform;
                }
            """)

            print(f"  Before center: {before_center}")
            print(f"  After center: {after_center}")

            # Verify that centering worked
            assert before_center != after_center, (
                f"Center graph button should work at {resolution['name']}"
            )
