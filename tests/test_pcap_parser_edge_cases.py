"""Edge-case and branch coverage tests for pcap_parser heuristics."""

from __future__ import annotations

import pytest

from pcap2kml_player.data_model import MessageType
from pcap2kml_player.pcap_parser import ParseCancelled, _infer_msg_type_from_pdu


class TestInferMsgType:
    """Unit tests for _infer_msg_type_from_pdu."""

    def test_denm(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x01])) == MessageType.DENM

    def test_cam(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x02])) == MessageType.CAM

    def test_spatem(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x03])) == MessageType.SPATEM

    def test_mapem(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x04])) == MessageType.MAPEM

    def test_srem(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x09])) == MessageType.SREM

    def test_ssem(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0x0A])) == MessageType.SSEM

    def test_too_short(self):
        assert _infer_msg_type_from_pdu(b"\x02") is None

    def test_wrong_version(self):
        assert _infer_msg_type_from_pdu(bytes([0x01, 0x02])) is None

    def test_unknown_id(self):
        assert _infer_msg_type_from_pdu(bytes([0x02, 0xFF])) is None


class TestParseCancelled:
    def test_exception_is_caught(self):
        with pytest.raises(ParseCancelled):
            raise ParseCancelled

    def test_exception_message(self):
        with pytest.raises(ParseCancelled, match="cancelled"):
            raise ParseCancelled("cancelled by user")
