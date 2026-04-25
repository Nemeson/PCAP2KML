"""Shared V2X protocol constants to avoid circular imports.

This module holds mappings that are needed by both pcap_parser and
security_parser (e.g. ITS_PDU_MESSAGE_ID).
"""

from __future__ import annotations

from .data_model import MessageType

ITS_PDU_MESSAGE_ID = {
    1: MessageType.DENM,
    2: MessageType.CAM,
    3: MessageType.SPATEM,
    4: MessageType.MAPEM,
    5: MessageType.SPATEM,
    9: MessageType.SREM,
    10: MessageType.SSEM,
}
