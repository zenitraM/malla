from types import SimpleNamespace
from unittest.mock import patch

from meshtastic import config_pb2, mesh_pb2, mqtt_pb2, portnums_pb2

from src.malla import mqtt_capture


def build_nodeinfo_message(hw_model: int) -> SimpleNamespace:
    """Create a minimal MQTT message containing a NODEINFO packet."""
    user = mesh_pb2.User()
    user.id = "!7f6e5d4c"
    user.long_name = "Gabriela"
    user.short_name = "GAB"
    user.hw_model = hw_model
    user.role = config_pb2.Config.DeviceConfig.Role.CLIENT

    mesh_packet = mesh_pb2.MeshPacket()
    setattr(mesh_packet, "from", 0x7F6E5D4C)
    mesh_packet.to = 0
    mesh_packet.decoded.portnum = portnums_pb2.PortNum.NODEINFO_APP
    mesh_packet.decoded.payload = user.SerializeToString()

    service_envelope = mqtt_pb2.ServiceEnvelope()
    service_envelope.channel_id = "Bulgaria"
    service_envelope.packet.CopyFrom(mesh_packet)

    return SimpleNamespace(
        topic="msh/Bulgaria/2/e/Bulgaria/!a2e96b40",
        payload=service_envelope.SerializeToString(),
    )


class TestOnMessageNodeInfo:
    @patch("src.malla.mqtt_capture.log_packet_to_database")
    @patch("src.malla.mqtt_capture.get_node_display_name", return_value="Gabriela")
    @patch("src.malla.mqtt_capture.update_node_cache")
    def test_on_message_updates_node_cache_for_thinknode_m3(
        self,
        mock_update_node_cache,
        _mock_get_node_display_name,
        mock_log_packet_to_database,
    ):
        msg = build_nodeinfo_message(mesh_pb2.HardwareModel.THINKNODE_M3)

        mqtt_capture.on_message(None, None, msg)

        mock_update_node_cache.assert_called_once_with(
            node_id=0x7F6E5D4C,
            hex_id="!7f6e5d4c",
            long_name="Gabriela",
            short_name="GAB",
            hw_model="THINKNODE_M3",
            role="CLIENT",
            is_licensed=False,
            mac_address=None,
            primary_channel="Bulgaria",
        )
        assert mock_log_packet_to_database.call_args.args[3] is True
        assert mock_log_packet_to_database.call_args.args[5] is None

    @patch("src.malla.mqtt_capture.log_packet_to_database")
    @patch("src.malla.mqtt_capture.get_node_display_name", return_value="Gabriela")
    @patch("src.malla.mqtt_capture.update_node_cache")
    def test_on_message_keeps_updating_node_cache_for_unknown_hw_models(
        self,
        mock_update_node_cache,
        _mock_get_node_display_name,
        mock_log_packet_to_database,
    ):
        msg = build_nodeinfo_message(999)

        mqtt_capture.on_message(None, None, msg)

        mock_update_node_cache.assert_called_once()
        assert mock_update_node_cache.call_args.kwargs["hw_model"] == "UNKNOWN_999"
        assert mock_log_packet_to_database.call_args.args[3] is True
        assert mock_log_packet_to_database.call_args.args[5] is None
