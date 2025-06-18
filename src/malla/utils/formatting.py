"""
Formatting utility functions for Meshtastic Mesh Health Web UI
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def format_time_ago(dt: datetime | None) -> str:
    """Format a datetime as relative time string."""
    if not dt:
        return "Never"

    # Ensure we're comparing timestamps in the same timezone
    # If dt is naive (no timezone), assume it's UTC
    if dt.tzinfo is None:
        now = datetime.now(UTC)
    else:
        now = datetime.now(dt.tzinfo)

    diff = now - dt

    # Handle negative differences (future timestamps)
    if diff.total_seconds() < 0:
        return "In the future"

    total_seconds = int(diff.total_seconds())

    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
    elif total_seconds >= 3600:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif total_seconds >= 60:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    else:
        return "Just now"


def format_node_id(node_id: int | str) -> str:
    """Format node ID consistently."""
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    return str(node_id)


def format_node_short_name(node_id: int | str, node_name: str | None = None) -> str:
    """Format short node name, fallback to hex if not available."""
    if node_name and node_name.strip():
        return node_name.strip()

    # Format hex ID as fallback
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    elif isinstance(node_id, str) and node_id.startswith("!"):
        return node_id
    else:
        return f"!{int(node_id):08x}"


def format_node_display_name(
    node_id: int | str,
    long_name: str | None = None,
    short_name: str | None = None,
    hex_id: str | None = None,
) -> str:
    """
    Format a complete display name for a node with fallback hierarchy.

    Priority:
    1. If we have both long_name and short_name and they're different: "Long Name (short)"
    2. If we have only long_name: use long_name
    3. If we have only short_name: use short_name
    4. If we have hex_id: use hex_id
    5. Fallback to formatting node_id as hex

    Args:
        node_id: The node ID (int or string)
        long_name: The long name of the node
        short_name: The short name of the node
        hex_id: The hex ID of the node

    Returns:
        Formatted display name string
    """
    # Clean up names
    long_clean = long_name.strip() if long_name else None
    short_clean = short_name.strip() if short_name else None
    hex_clean = hex_id.strip() if hex_id else None

    # If we have both long and short names and they're different
    if long_clean and short_clean and long_clean != short_clean:
        return f"{long_clean} ({short_clean})"

    # Use single name if available
    if long_clean:
        return long_clean
    if short_clean:
        return short_clean
    if hex_clean:
        return hex_clean

    # Fallback to formatting the node_id
    return format_node_id(node_id)


def format_route_display(route_nodes: list[int], include_names: bool = True) -> str:
    """
    Format a route display string showing the path through nodes.

    Args:
        route_nodes: List of node IDs in the route
        include_names: Whether to include node names (requires database access)

    Returns:
        Formatted route string like "A → B → C"
    """
    if not route_nodes:
        return "No route"

    if include_names:
        # Import here to avoid circular imports
        from ..utils.node_utils import get_node_display_name

        route_parts = []
        for node_id in route_nodes:
            name = get_node_display_name(node_id)
            route_parts.append(name)
    else:
        route_parts = [format_node_id(node_id) for node_id in route_nodes]

    return " → ".join(route_parts)


def format_complete_traceroute_path(
    from_node_id: int,
    to_node_id: int,
    route_nodes: list[int],
    include_names: bool = True,
) -> str:
    """
    Format a complete traceroute path including the sender and final destination.

    Args:
        from_node_id: The originating node ID
        to_node_id: The destination node ID
        route_nodes: List of intermediate node IDs
        include_names: Whether to include node names

    Returns:
        Complete formatted path string
    """
    if include_names:
        from ..utils.node_utils import get_node_display_name

        from_name = get_node_display_name(from_node_id)
        to_name = get_node_display_name(to_node_id)
    else:
        from_name = format_node_id(from_node_id)
        to_name = format_node_id(to_node_id)

    # Build complete path
    path_parts = [from_name]

    if route_nodes:
        if include_names:
            # Import here to avoid circular imports
            from ..utils.node_utils import get_node_display_name

            for node_id in route_nodes:
                name = get_node_display_name(node_id)
                path_parts.append(name)
        else:
            path_parts.extend([format_node_id(node_id) for node_id in route_nodes])

    path_parts.append(to_name)

    return " → ".join(path_parts)


def create_highlighted_route_display(
    from_node_id: int,
    to_node_id: int,
    route_nodes: list[int],
    highlight_from: int,
    highlight_to: int,
    hop_index: int,
    snr_values: list[float | None] | None = None,
) -> str:
    """
    Create an HTML table display for a traceroute with highlighting for specific hops.

    Args:
        from_node_id: Origin node
        to_node_id: Destination node
        route_nodes: Intermediate nodes in route
        highlight_from: Node to highlight as source of highlighted hop
        highlight_to: Node to highlight as destination of highlighted hop
        hop_index: Index of the hop to highlight
        snr_values: Optional SNR values for each hop

    Returns:
        HTML table string with highlighted route display
    """
    from ..utils.node_utils import get_node_display_name

    # Build complete route with from/to nodes
    complete_route = [from_node_id] + route_nodes + [to_node_id]

    def get_short_name(node_id: int) -> str:
        """Get a short display name for the node."""
        full_name = get_node_display_name(node_id)
        # If it contains parentheses, extract just the first part
        if " (" in full_name and full_name.endswith(")"):
            return full_name.split(" (")[0]
        return full_name

    # Start building HTML table
    table_html = """
    <div class="route-display-table">
        <table class="table table-sm table-borderless">
            <thead>
                <tr>
                    <th width="15%"><small class="text-muted">Hop</small></th>
                    <th width="35%"><small class="text-muted">From</small></th>
                    <th width="35%"><small class="text-muted">To</small></th>
                    <th width="15%"><small class="text-muted">SNR</small></th>
                </tr>
            </thead>
            <tbody>
    """

    # Add each hop to the table
    for i in range(len(complete_route) - 1):
        from_node = complete_route[i]
        to_node = complete_route[i + 1]

        from_name = get_short_name(from_node)
        to_name = get_short_name(to_node)

        # Check if this is the highlighted hop
        is_highlighted = (from_node == highlight_from and to_node == highlight_to) or (
            from_node == highlight_to and to_node == highlight_from
        )

        # Get SNR value for this hop if available
        snr_display = "—"
        if snr_values and i < len(snr_values) and snr_values[i] is not None:
            snr_val = snr_values[i]
            # Color code SNR values - snr_val is guaranteed to be not None here
            if snr_val is not None and snr_val > 5:
                snr_display = f'<span class="text-success">{snr_val:.1f}</span>'
            elif snr_val is not None and snr_val > 0:
                snr_display = f'<span class="text-warning">{snr_val:.1f}</span>'
            elif snr_val is not None:
                snr_display = f'<span class="text-danger">{snr_val:.1f}</span>'

        # Apply highlighting styles
        row_class = ""
        from_style = ""
        to_style = ""

        if is_highlighted:
            row_class = 'class="table-primary"'
            from_style = 'style="font-weight: bold; color: #0d6efd;"'
            to_style = 'style="font-weight: bold; color: #0d6efd;"'

        table_html += f"""
                <tr {row_class}>
                    <td><small class="text-muted">#{i + 1}</small></td>
                    <td {from_style}><small>{from_name}</small></td>
                    <td {to_style}><small>{to_name}</small></td>
                    <td><small>{snr_display}</small></td>
                </tr>
        """

    table_html += """
            </tbody>
        </table>
    </div>
    """

    return table_html.strip()
