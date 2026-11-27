"""
Decryption utilities for Meshtastic packets.

This module provides functions to decrypt encrypted Meshtastic packets using
channel-specific key derivation, for both AES256-CTR and the AES-CCM
(``use_aead``) channels that firmware 2.8.1 and later can select.
"""

import base64
import hashlib
import logging
import os
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from meshtastic import mesh_pb2, portnums_pb2

logger = logging.getLogger(__name__)

# Default Meshtastic channel key
DEFAULT_CHANNEL_KEY = os.getenv("MESHTASTIC_KEY", "1PG7OiApB1nwvP+rz05pAQ==")

# Firmware 2.8.1+ channels with ``use_aead`` encapsulate AES-CCM: a 12-byte tag
# is appended to the ciphertext and the two node ids are authenticated as
# associated data. The tag makes a wrong key fail loudly, so CCM can be tried
# before CTR (whose output has no integrity check) on every packet.
AEAD_TAG_SIZE = 12


def derive_key_from_channel_name(channel_name: str, key_base64: str) -> bytes:
    """
    Derive encryption key from channel name and base key.
    This follows Meshtastic's key derivation algorithm.

    Args:
        channel_name: Channel name for key derivation (empty for primary channel)
        key_base64: Base64-encoded encryption key

    Returns:
        32-byte encryption key
    """
    try:
        # Decode the base key from base64
        key_bytes = base64.b64decode(key_base64)

        # If channel name is provided, derive key using SHA256
        if channel_name and channel_name != "":
            # Convert channel name to bytes
            channel_bytes = channel_name.encode("utf-8")
            # Create SHA256 hash of base key + channel name
            hasher = hashlib.sha256()
            hasher.update(key_bytes)
            hasher.update(channel_bytes)
            derived_key = hasher.digest()
            return derived_key
        else:
            # For primary channel, use the key as-is (should already be 32 bytes for AES256)
            return key_bytes
    except Exception as e:
        logger.warning(f"Error deriving key: {e}")
        return b"\x00" * 32  # Return null key on error


def decrypt_packet_payload(
    encrypted_payload: bytes, packet_id: int, sender_id: int, key: bytes
) -> bytes:
    """
    Decrypt a Meshtastic packet using AES256-CTR.

    Args:
        encrypted_payload: The encrypted payload bytes
        packet_id: The packet ID for nonce construction
        sender_id: The sender node ID for nonce construction
        key: The encryption key (32 bytes for AES256)

    Returns:
        Decrypted payload bytes or empty bytes if decryption fails
    """
    try:
        if len(encrypted_payload) == 0:
            logger.debug("Empty encrypted payload, nothing to decrypt")
            return b""

        # Construct nonce: packet_id (8 bytes) + sender_id (8 bytes) = 16 bytes
        packet_id_bytes = packet_id.to_bytes(8, byteorder="little")
        sender_id_bytes = sender_id.to_bytes(8, byteorder="little")
        nonce = packet_id_bytes + sender_id_bytes

        if len(nonce) != 16:
            logger.warning(f"Invalid nonce length: {len(nonce)}, expected 16 bytes")
            return b""

        # Create AES-CTR cipher
        cipher = Cipher(
            algorithms.AES(key), modes.CTR(nonce), backend=default_backend()
        )
        decryptor = cipher.decryptor()

        # Decrypt the payload
        decrypted = decryptor.update(encrypted_payload) + decryptor.finalize()

        logger.debug(
            f"Successfully decrypted {len(encrypted_payload)} bytes to {len(decrypted)} bytes"
        )
        return decrypted

    except Exception as e:
        logger.warning(f"Decryption failed: {e}")
        return b""


def decrypt_packet_payload_ccm(
    encrypted_payload: bytes,
    packet_id: int,
    sender_id: int,
    dest_id: int,
    key: bytes,
) -> bytes:
    """Decrypt an AES-CCM (``use_aead``) payload.

    Layout matches firmware ``CryptoEngine.cpp``: 13-byte nonce
    ``[packet id (8, LE)][from node (4, LE)][0]``, sender/destination ids as
    associated data, 12-byte tag appended to the ciphertext. Returns empty
    bytes when the tag does not verify (wrong key or not an AEAD payload).
    """
    if len(encrypted_payload) <= AEAD_TAG_SIZE or len(key) not in (16, 32):
        return b""
    try:
        nonce = (
            (packet_id & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
            + (sender_id & 0xFFFFFFFF).to_bytes(4, "little")
            + b"\x00"
        )
        aad = (sender_id & 0xFFFFFFFF).to_bytes(4, "little") + (
            dest_id & 0xFFFFFFFF
        ).to_bytes(4, "little")
        return AESCCM(key, tag_length=AEAD_TAG_SIZE).decrypt(
            nonce, bytes(encrypted_payload), aad
        )
    except Exception:  # noqa: BLE001 - InvalidTag or bad lengths: not our key
        return b""


def _parse_decrypted_data(decrypted_payload: bytes) -> mesh_pb2.Data | None:
    """Parse plaintext as ``Data``; None unless it carries a real portnum."""
    if not decrypted_payload:
        return None
    try:
        decoded_data = mesh_pb2.Data()
        decoded_data.ParseFromString(decrypted_payload)
    except Exception:  # noqa: BLE001
        return None
    if decoded_data.portnum == portnums_pb2.PortNum.UNKNOWN_APP:
        return None
    return decoded_data


def try_decrypt_mesh_packet(
    mesh_packet,
    channel_name: str = "",
    key_base64: str = DEFAULT_CHANNEL_KEY,
    keys_base64: list[str] | None = None,
    info: dict[str, Any] | None = None,
) -> bool:
    """
    Try to decrypt an encrypted MeshPacket and update it with decoded content.

    Attempts AES-CCM (firmware 2.8.1+ ``use_aead`` channels) first, then
    AES-CTR, with each configured key until one yields a valid ``Data``.

    Args:
        mesh_packet: The MeshPacket protobuf object
        channel_name: Channel name for key derivation (empty for primary channel)
        key_base64: Single base64-encoded key, used when ``keys_base64`` is None
        keys_base64: Optional list of base64-encoded keys to try in order
        info: Optional dict that receives ``method`` ("ccm" or "ctr") on success

    Returns:
        bool: True if decryption was successful and packet was updated
    """
    try:
        # Check if packet already has decoded data
        if (
            hasattr(mesh_packet, "decoded")
            and mesh_packet.decoded.portnum != portnums_pb2.PortNum.UNKNOWN_APP
        ):
            logger.debug("Packet already decoded successfully")
            return False

        # Check if packet has encrypted data
        if not hasattr(mesh_packet, "encrypted") or not mesh_packet.encrypted:
            logger.debug("No encrypted payload found in packet")
            return False

        encrypted_payload = mesh_packet.encrypted
        packet_id = mesh_packet.id
        sender_id = getattr(mesh_packet, "from")  # 'from' is a Python keyword
        dest_id = getattr(mesh_packet, "to", 0)
        keys_to_try = keys_base64 if keys_base64 is not None else [key_base64]

        if not keys_to_try:
            logger.debug("No decryption keys configured")
            return False

        logger.debug(
            f"Attempting to decrypt packet {packet_id} from {sender_id}, encrypted payload: {len(encrypted_payload)} bytes"
        )

        for key_index, candidate in enumerate(keys_to_try):
            key = derive_key_from_channel_name(channel_name, candidate)

            # CCM authenticates, so a successful tag means the key is right.
            # CTR has no integrity check and can silently yield garbage, so it
            # is only attempted after CCM fails and its output must parse.
            decoded_data = _parse_decrypted_data(
                decrypt_packet_payload_ccm(
                    encrypted_payload, packet_id, sender_id, dest_id, key
                )
            )
            method = "ccm"
            if decoded_data is None:
                decoded_data = _parse_decrypted_data(
                    decrypt_packet_payload(encrypted_payload, packet_id, sender_id, key)
                )
                method = "ctr"
            if decoded_data is None:
                logger.debug(
                    f"Key {key_index + 1}/{len(keys_to_try)} did not yield a valid Data payload"
                )
                continue

            mesh_packet.decoded.CopyFrom(decoded_data)
            if info is not None:
                info["method"] = method

            portnum_name = portnums_pb2.PortNum.Name(decoded_data.portnum)
            logger.info(
                f"✅ Successfully decrypted packet {packet_id} from {sender_id} with key {key_index + 1}/{len(keys_to_try)}"
                f"{' (AEAD)' if method == 'ccm' else ''}: {portnum_name}"
            )
            return True

        logger.debug(
            f"Failed to decrypt packet with any of the {len(keys_to_try)} provided keys"
        )
        return False

    except Exception as e:
        logger.warning(f"Error in try_decrypt_mesh_packet: {e}")
        return False


def try_decrypt_database_packet(
    packet_data: dict, channel_name: str = "", key_base64: str = DEFAULT_CHANNEL_KEY
) -> tuple[bytes, str] | None:
    """
    Try to decrypt a packet stored in the database with encrypted payload.

    This function is for packets that were stored in the database as UNKNOWN_APP
    but may contain encrypted data that can be decrypted.

    Args:
        packet_data: Dictionary containing packet data from database
        channel_name: Channel name for key derivation
        key_base64: Base64-encoded encryption key

    Returns:
        Tuple of (decrypted_payload, portnum_name) if successful, None if failed
    """
    try:
        # For database packets, we'd need access to the original encrypted payload
        # which isn't currently stored. This is a limitation of the current design.
        # We can only decrypt packets that still have the encrypted field.

        logger.debug(
            "Database packet decryption not currently supported - encrypted data not stored"
        )
        return None

    except Exception as e:
        logger.warning(f"Error in try_decrypt_database_packet: {e}")
        return None


def extract_channel_name_from_topic(topic: str) -> str:
    """
    Extract channel name from MQTT topic for key derivation.

    Args:
        topic: MQTT topic (e.g., "msh/EU_868/2/e/LongFast/!7aa6fbec")

    Returns:
        Channel name or empty string for primary channel
    """
    try:
        topic_parts = topic.split("/")
        if len(topic_parts) >= 5:
            # The 4th part (index 4) might be channel name like "LongFast"
            potential_channel = topic_parts[4]
            if potential_channel not in ["e", "c"] and not potential_channel.startswith(
                "!"
            ):
                return potential_channel
    except Exception:
        pass
    return ""
