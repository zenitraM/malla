"""
Gateway service for comparing gateway performance and signal quality.
"""

import logging
from typing import Any

from ..database.repositories import PacketRepository
from ..utils.node_utils import get_bulk_node_names

logger = logging.getLogger(__name__)


class GatewayService:
    """Service for gateway comparison and analysis."""

    @staticmethod
    def get_available_gateways() -> list[dict[str, Any]]:
        """
        Get list of available gateways with their display names.

        Returns:
            List of gateway dictionaries with id and display_name
        """
        try:
            gateway_ids = PacketRepository.get_unique_gateway_ids()

            # Convert gateway IDs to node IDs for name lookup where possible
            gateway_node_ids = []
            gateway_id_to_node_id = {}

            for gw_id in gateway_ids:
                if gw_id and gw_id.startswith("!"):
                    try:
                        node_id = int(gw_id[1:], 16)
                        gateway_node_ids.append(node_id)
                        gateway_id_to_node_id[gw_id] = node_id
                    except ValueError:
                        pass

            # Get node names for gateway IDs that are node IDs
            node_names = {}
            if gateway_node_ids:
                node_names = get_bulk_node_names(gateway_node_ids)

            # Build gateway list with display names
            gateways = []
            for gw_id in gateway_ids:
                if gw_id in gateway_id_to_node_id:
                    node_id = gateway_id_to_node_id[gw_id]
                    display_name = node_names.get(node_id, gw_id)
                else:
                    display_name = gw_id

                gateways.append({"id": gw_id, "display_name": display_name})

            # Sort by display name
            gateways.sort(key=lambda x: x["display_name"])

            return gateways

        except Exception as e:
            logger.error(f"Error getting available gateways: {e}")
            raise

    @staticmethod
    def compare_gateways(
        gateway1_id: str, gateway2_id: str, filters: dict | None = None
    ) -> dict[str, Any]:
        """
        Compare two gateways by analyzing their common received packets.

        Args:
            gateway1_id: First gateway ID
            gateway2_id: Second gateway ID
            filters: Optional filters for the comparison

        Returns:
            Dictionary containing comparison data and visualizations
        """
        try:
            # Get comparison data from repository
            comparison_data = PacketRepository.get_gateway_comparison_data(
                gateway1_id, gateway2_id, filters
            )

            common_packets = comparison_data["common_packets"]
            statistics = comparison_data["statistics"]

            # Get gateway display names
            gateways = GatewayService.get_available_gateways()
            gateway_names = {gw["id"]: gw["display_name"] for gw in gateways}

            gateway1_name = gateway_names.get(gateway1_id, gateway1_id)
            gateway2_name = gateway_names.get(gateway2_id, gateway2_id)

            # Get node names for the packets
            if common_packets:
                node_ids = list(
                    {p["from_node_id"] for p in common_packets if p["from_node_id"]}
                )
                node_names = get_bulk_node_names(node_ids)

                # Add node names to packets
                for packet in common_packets:
                    packet["from_node_name"] = node_names.get(
                        packet["from_node_id"], f"!{packet['from_node_id']:08x}"
                    )

            # Prepare chart data
            chart_data = GatewayService._prepare_chart_data(
                common_packets, gateway1_name, gateway2_name
            )

            # Add display names to statistics
            statistics["gateway1_name"] = gateway1_name
            statistics["gateway2_name"] = gateway2_name

            return {
                "common_packets": common_packets,
                "statistics": statistics,
                "chart_data": chart_data,
                "gateway1_name": gateway1_name,
                "gateway2_name": gateway2_name,
            }

        except Exception as e:
            logger.error(
                f"Error comparing gateways {gateway1_id} and {gateway2_id}: {e}"
            )
            raise

    @staticmethod
    def _prepare_chart_data(
        common_packets: list[dict], gateway1_name: str, gateway2_name: str
    ) -> dict[str, Any]:
        """
        Prepare data for charts and visualizations.

        Args:
            common_packets: List of common packets
            gateway1_name: Display name for gateway 1
            gateway2_name: Display name for gateway 2

        Returns:
            Dictionary containing chart data
        """
        if not common_packets:
            return {
                "rssi_scatter": {"x": [], "y": []},
                "snr_scatter": {"x": [], "y": []},
                "rssi_diff_histogram": {"values": []},
                "snr_diff_histogram": {"values": []},
                "timeline_rssi": {"timestamps": [], "gateway1": [], "gateway2": []},
                "timeline_snr": {"timestamps": [], "gateway1": [], "gateway2": []},
            }

        # Extract data for charts
        gateway1_rssi = [
            p["gateway1_rssi"] for p in common_packets if p["gateway1_rssi"] is not None
        ]
        gateway2_rssi = [
            p["gateway2_rssi"] for p in common_packets if p["gateway2_rssi"] is not None
        ]
        gateway1_snr = [
            p["gateway1_snr"] for p in common_packets if p["gateway1_snr"] is not None
        ]
        gateway2_snr = [
            p["gateway2_snr"] for p in common_packets if p["gateway2_snr"] is not None
        ]

        rssi_diffs = [
            p["rssi_diff"] for p in common_packets if p["rssi_diff"] is not None
        ]
        snr_diffs = [p["snr_diff"] for p in common_packets if p["snr_diff"] is not None]

        timestamps = [p["timestamp_str"] for p in common_packets]

        # Prepare scatter plot data (gateway1 vs gateway2)
        rssi_scatter_data = {
            "x": gateway1_rssi,
            "y": gateway2_rssi,
            "text": [
                f"Packet from {p.get('from_node_name', 'Unknown')}<br>Time: {p['timestamp_str']}"
                for p in common_packets
                if p["gateway1_rssi"] is not None and p["gateway2_rssi"] is not None
            ],
        }

        snr_scatter_data = {
            "x": gateway1_snr,
            "y": gateway2_snr,
            "text": [
                f"Packet from {p.get('from_node_name', 'Unknown')}<br>Time: {p['timestamp_str']}"
                for p in common_packets
                if p["gateway1_snr"] is not None and p["gateway2_snr"] is not None
            ],
        }

        # Timeline data
        timeline_rssi = {
            "timestamps": timestamps,
            "gateway1": [p["gateway1_rssi"] for p in common_packets],
            "gateway2": [p["gateway2_rssi"] for p in common_packets],
        }

        timeline_snr = {
            "timestamps": timestamps,
            "gateway1": [p["gateway1_snr"] for p in common_packets],
            "gateway2": [p["gateway2_snr"] for p in common_packets],
        }

        return {
            "rssi_scatter": rssi_scatter_data,
            "snr_scatter": snr_scatter_data,
            "rssi_diff_histogram": {"values": rssi_diffs},
            "snr_diff_histogram": {"values": snr_diffs},
            "timeline_rssi": timeline_rssi,
            "timeline_snr": timeline_snr,
            "gateway1_name": gateway1_name,
            "gateway2_name": gateway2_name,
        }
