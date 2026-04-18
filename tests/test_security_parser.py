"""Tests for the ETSI TS 103 097 security header parser."""

import struct

from pcap2kml_player.pcap_parser import ITS_PDU_MESSAGE_ID
from pcap2kml_player.security_parser import (
    _bytes_to_hex,
    _read_length_determinant,
    _read_uint16,
    _read_uint8,
    extract_security_from_decoded,
    parse_security_header,
)


# ---------- primitive readers ----------

def test_read_uint8_reads_single_byte():
    assert _read_uint8(b"\x42\x99", 0) == (0x42, 1)


def test_read_uint8_out_of_bounds_returns_zero():
    assert _read_uint8(b"", 0) == (0, 0)


def test_read_uint16_big_endian():
    assert _read_uint16(b"\x01\x02\x03", 0) == (0x0102, 2)


def test_read_uint16_out_of_bounds_returns_zero():
    assert _read_uint16(b"\x01", 0) == (0, 0)


def test_read_length_determinant_short_form():
    assert _read_length_determinant(b"\x05abc", 0) == (5, 1)


def test_read_length_determinant_long_form():
    # first byte 0x81 -> high bit set, low 7 bits = 1; next byte 0x00 -> 256
    assert _read_length_determinant(b"\x81\x00", 0) == (256, 2)


def test_read_length_determinant_empty_returns_zero():
    assert _read_length_determinant(b"", 0) == (0, 0)


# ---------- hex helper ----------

def test_bytes_to_hex_empty_returns_dash():
    assert _bytes_to_hex(b"") == "—"


def test_bytes_to_hex_truncates_with_ellipsis():
    data = b"\x01" * 20
    result = _bytes_to_hex(data, max_len=4)
    assert result == "01010101..."


def test_bytes_to_hex_no_truncation_when_short():
    assert _bytes_to_hex(b"\xab\xcd") == "abcd"


# ---------- parse_security_header ----------

def test_parse_security_header_empty_returns_none():
    assert parse_security_header(b"") is None


def test_parse_security_header_too_short_returns_none():
    assert parse_security_header(b"\x02") is None


def test_parse_security_header_wrong_version_returns_none():
    # Protocol version 3 is not defined in ETSI TS 103 097 V2.2.1
    assert parse_security_header(b"\x03\x00") is None


def test_parse_security_header_ignores_plain_its_pdu_header():
    # protocolVersion=2, messageId=2 (CAM), followed by a 4-byte stationID.
    assert parse_security_header(b"\x02\x02\x00\x00\x1b\xf1") is None


def test_parse_security_header_unsecured_message():
    # Version 2, profile 0 = unsecured
    info = parse_security_header(b"\x02\x00")
    assert info is not None
    assert info.protocol_version == 2
    assert info.security_profile == "unsecured"
    assert info.signer_type is None


def test_parse_security_header_signed_with_digest_signer():
    # Version 2, profile 1 = signed; signer byte 0x40 -> top-2-bits = 1 (digest)
    # Then 8 bytes digest, then ~65 bytes for signature
    payload = bytes([2, 1, 0x40]) + b"\xAA" * 8 + b"\x00" + b"\xBB" * 64
    info = parse_security_header(payload)
    assert info is not None
    assert info.security_profile == "signed"
    assert info.signer_type == "digest"
    assert info.signer_digest == "aa" * 8
    assert info.signature_algorithm == "ECDSA NIST P-256"


def test_parse_security_header_unknown_profile_name():
    info = parse_security_header(b"\x02\x09")
    # unsecured path only triggers on 0; anything else drops into signer handling
    # but with no further bytes, signer type is not set
    assert info is not None
    assert info.security_profile.startswith("unknown")


def test_parse_security_header_brainpool_algo():
    payload = bytes([2, 1, 0x40]) + b"\xAA" * 8 + b"\x01" + b"\xCC" * 64
    info = parse_security_header(payload)
    assert info is not None
    assert info.signature_algorithm == "ECDSA BrainpoolP256r1"


# ---------- extract_security_from_decoded ----------

def test_extract_security_from_decoded_cam_with_station_type():
    decoded = {
        "header": {"protocolVersion": 2, "messageID": 2, "stationID": 12345},
        "cam": {
            "camParameters": {
                "basicContainer": {"stationType": 5},  # passengerCar
            }
        },
    }
    info = extract_security_from_decoded(decoded, "CAM")
    assert info is not None
    assert info.protocol_version == 2
    assert info.station_type == "passengerCar"
    # CAM message ID 2 -> ITS-AID 0x24
    assert info.its_aid_list == [0x24]


def test_extract_security_from_decoded_denm_station_type():
    decoded = {
        "header": {"protocolVersion": 2, "messageID": 1, "stationID": 99},
        "denm": {"managementContainer": {"stationType": 15}},  # RSU
    }
    info = extract_security_from_decoded(decoded, "DENM")
    assert info is not None
    assert info.station_type == "roadSideUnit"


def test_extract_security_from_decoded_unknown_station_type():
    decoded = {
        "header": {"messageID": 2, "stationID": 1},
        "cam": {"camParameters": {"basicContainer": {"stationType": 77}}},
    }
    info = extract_security_from_decoded(decoded, "CAM")
    assert info is not None
    assert info.station_type == "type_77"


def test_extract_security_from_decoded_empty_returns_none():
    assert extract_security_from_decoded({}, "CAM") is None


def test_extract_security_from_decoded_mapem_uses_aid_121():
    decoded = {"header": {"messageId": 4, "stationId": 1}}
    info = extract_security_from_decoded(decoded, "MAPEM")
    assert info is not None
    assert info.its_aid_list == [0x79]
    assert info.station_type == "Station-ID: 1"


def test_extract_security_from_decoded_spatem_message_id_3_uses_aid_121():
    decoded = {"header": {"messageID": 3, "stationID": 1}}
    info = extract_security_from_decoded(decoded, "SPATEM")
    assert info is not None
    assert info.its_aid_list == [0x79]


def test_security_message_id_aid_mapping_stays_consistent_with_parser_mapping():
    expected_aids = {
        "DENM": 0x24,
        "CAM": 0x24,
        "MAPEM": 0x79,
        "SPATEM": 0x79,
        "SREM": 0x79,
        "SSEM": 0x79,
    }

    for message_id, msg_type in ITS_PDU_MESSAGE_ID.items():
        decoded = {"header": {"messageID": message_id, "stationID": 1}}
        info = extract_security_from_decoded(decoded, msg_type.value)
        assert info is not None
        assert info.its_aid_list == [expected_aids[msg_type.value]]
