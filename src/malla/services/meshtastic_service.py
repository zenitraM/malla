"""
Meshtastic service for getting hardware models and packet types from protobuf definitions.
"""

import logging

logger = logging.getLogger(__name__)


class MeshtasticService:
    """Service for interacting with Meshtastic protobuf definitions."""

    _hardware_models_cache = None
    _packet_types_cache = None

    @classmethod
    def get_hardware_models(cls) -> list[tuple[str, str]]:
        """Get all available hardware models from Meshtastic protobuf definitions.

        Returns:
            List of tuples (value, display_name) for hardware models
        """
        if cls._hardware_models_cache is not None:
            return cls._hardware_models_cache

        try:
            from meshtastic import mesh_pb2

            # Get all hardware model enum values
            hardware_models = []

            # Get the HardwareModel enum descriptor
            hw_model_enum = mesh_pb2.HardwareModel.DESCRIPTOR

            for value in hw_model_enum.values:
                # Skip UNSET value
                if value.name == "UNSET":
                    continue

                # Convert enum name to display name
                display_name = value.name.replace("_", " ").title()

                # Special cases for better display names
                display_name_map = {
                    "Diy V1": "DIY V1",
                    "Heltec V1": "Heltec V1",
                    "Heltec V2 0": "Heltec V2.0",
                    "Heltec V2 1": "Heltec V2.1",
                    "Heltec V3": "Heltec V3",
                    "Heltec Wsl V3": "Heltec WSL V3",
                    "Heltec Wireless Paper": "Heltec Wireless Paper",
                    "Heltec Wireless Tracker": "Heltec Wireless Tracker",
                    "Heltec Mesh Node T114": "Heltec Mesh Node T114",
                    "Tlora V1": "T-LoRa V1",
                    "Tlora V2 1 1P6": "T-LoRa V2.1.1.6",
                    "Tlora T3 S3": "T-LoRa T3 S3",
                    "Tbeam": "T-Beam",
                    "T Deck": "T-Deck",
                    "T Echo": "T-Echo",
                    "Lilygo Tbeam S3 Core": "LilyGO T-Beam S3 Core",
                    "Rak4631": "RAK4631",
                    "Rak11200": "RAK11200",
                    "Rak2560": "RAK2560",
                    "M5Stack Core2": "M5Stack Core2",
                    "Nrf52 Promicro Diy": "nRF52 Pro Micro DIY",
                    "Rpi Pico": "Raspberry Pi Pico",
                    "Rpi Pico2": "Raspberry Pi Pico 2",
                    "Station G2": "Station G2",
                    "Seeed Xiao S3": "Seeed XIAO S3",
                    "Sensecap Indicator": "SenseCAP Indicator",
                    "Tracker T1000 E": "Tracker T1000-E",
                    "Xiao Nrf52 Kit": "XIAO nRF52 Kit",
                    "Wismesh Tap": "WisMesh TAP",
                    "Thinknode M1": "ThinkNode M1",
                    "Private Hw": "Private Hardware",
                }

                final_display_name = display_name_map.get(display_name, display_name)
                hardware_models.append((value.name, final_display_name))

            # Sort by display name
            hardware_models.sort(key=lambda x: x[1])

            cls._hardware_models_cache = hardware_models
            return hardware_models

        except ImportError as e:
            logger.error(f"Failed to import Meshtastic protobuf: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting hardware models: {e}")
            return []

    @classmethod
    def get_packet_types(cls) -> list[tuple[str, str]]:
        """Get all available packet types from Meshtastic protobuf definitions.

        Returns:
            List of tuples (value, display_name) for packet types
        """
        if cls._packet_types_cache is not None:
            return cls._packet_types_cache

        try:
            from meshtastic import portnums_pb2

            # Get all portnum enum values
            packet_types = []

            # Get the PortNum enum descriptor
            portnum_enum = portnums_pb2.PortNum.DESCRIPTOR

            for value in portnum_enum.values:
                # Convert enum name to display name
                display_name = value.name.replace("_APP", "").replace("_", " ").title()

                # Special cases for better display names
                display_name_map = {
                    "Text Message": "Text Messages",
                    "Nodeinfo": "Node Info",
                    "Neighborinfo": "Neighbor Info",
                    "Store Forward": "Store and Forward",
                    "Range Test": "Range Test",
                    "Atak Plugin": "ATAK Plugin",
                    "Atak Forwarder": "ATAK Forwarder",
                    "Paxcounter": "PAX Counter",
                    "Ip Tunnel": "IP Tunnel",
                    "Serial": "Serial App",
                    "Simulator": "Simulator App",
                    "Audio": "Audio App",
                    "Detection Sensor": "Detection Sensor",
                    "Reply": "Reply App",
                    "Zps": "ZPS App",
                    "Max": "Max App",
                    "Unknown": "Unknown",
                }

                final_display_name = display_name_map.get(display_name, display_name)
                packet_types.append((value.name, final_display_name))

            # Sort by display name
            packet_types.sort(key=lambda x: x[1])

            cls._packet_types_cache = packet_types
            return packet_types

        except ImportError as e:
            logger.error(f"Failed to import Meshtastic protobuf: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting packet types: {e}")
            return []

    @classmethod
    def get_node_roles(cls) -> list[tuple[str, str]]:
        """Get all available node roles from Meshtastic protobuf definitions.

        Returns:
            List of tuples (value, display_name) for node roles
        """
        try:
            from meshtastic import config_pb2

            # Get all role enum values
            roles = []

            # Get the Role enum descriptor from Config.DeviceConfig
            role_enum = config_pb2.Config.DeviceConfig.Role.DESCRIPTOR

            for value in role_enum.values:
                # Skip CLIENT_HIDDEN as it's deprecated
                if value.name in ["CLIENT_HIDDEN"]:
                    continue

                # Convert enum name to display name
                display_name = value.name.replace("_", " ").title()

                # Special cases for better display names
                display_name_map = {
                    "Client Mute": "Client Mute",
                    "Router Client": "Router Client",
                    "Router Late": "Router Late",
                    "Tak": "TAK",
                    "Tak Tracker": "TAK Tracker",
                }

                final_display_name = display_name_map.get(display_name, display_name)
                roles.append((value.name, final_display_name))

            # Sort by display name
            roles.sort(key=lambda x: x[1])

            return roles

        except ImportError as e:
            logger.error(f"Failed to import Meshtastic protobuf: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting node roles: {e}")
            return []

    @classmethod
    def clear_cache(cls):
        """Clear the cached values to force refresh."""
        cls._hardware_models_cache = None
        cls._packet_types_cache = None
