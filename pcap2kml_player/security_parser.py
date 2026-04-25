"""ETSI TS 103 097 security header parser for ITS G5 messages.

Extracts PKI/signature data from the security envelope that wraps
signed V2X messages. Supports ETSI TS 103 097 V2.2.1 (IEEE 1609.2).

The security envelope structure:
  [Protocol Version][Content Type][Signer Info][Header Info][Payload][Signature]

Reference standards:
  - ETSI TS 103 097 V2.2.1 — Security header and certificate formats
  - IEEE 1609.2 — Security Services for V2X
  - ETSI TS 102 941 — ITS Trust Management
"""

from __future__ import annotations

import logging
import struct

from .data_model import SecurityInfo
from .protocol_constants import ITS_PDU_MESSAGE_ID

logger = logging.getLogger(__name__)

# ─── Security Profile Types (ETSI TS 103 097) ─────────────────────

SECURITY_PROFILE_UNSECURED = 0
SECURITY_PROFILE_SIGNED = 1
SECURITY_PROFILE_SIGNED_ENCRYPTED = 2
SECURITY_PROFILE_SIGNED_ENCRYPTED_AUTH = 3

SECURITY_PROFILE_NAMES = {
    SECURITY_PROFILE_UNSECURED: "unsecured",
    SECURITY_PROFILE_SIGNED: "signed",
    SECURITY_PROFILE_SIGNED_ENCRYPTED: "signed_encrypted",
    SECURITY_PROFILE_SIGNED_ENCRYPTED_AUTH: "signed_encrypted_auth",
}

# ─── Signer Info Types ─────────────────────────────────────────────

SIGNER_SELF = 0
SIGNER_DIGEST = 1
SIGNER_CERTIFICATE_CHAIN = 2

SIGNER_TYPE_NAMES = {
    SIGNER_SELF: "self",
    SIGNER_DIGEST: "digest",
    SIGNER_CERTIFICATE_CHAIN: "certificate_chain",
}

# ─── Subject Types (ETSI TS 103 097) ───────────────────────────────

SUBJECT_TYPE_NAMES = {
    0: "CA",
    1: "subscriber",
    2: "enrollment_CA",
}

# ─── Station Types (ETSI TS 102 894-2) ────────────────────────────

STATION_TYPE_NAMES = {
    0: "unknown",
    1: "pedestrian",
    2: "cyclist",
    3: "moped",
    4: "motorcycle",
    5: "passengerCar",
    6: "bus",
    7: "lightTruck",
    8: "heavyTruck",
    9: "trailer",
    10: "specialVehicles",
    11: "tram",
    15: "roadSideUnit",
}

# ─── Geographic Region Types ────────────────────────────────────────

REGION_TYPE_NAMES = {
    0: "none",
    1: "circular",
    2: "rectangular",
    3: "polygonal",
    4: "country",
}


# ─── ITS-AID permission constants (hex) ─────────────────────────────

ITS_AID_DENM = 0x00000024
ITS_AID_CAM = 0x00000024
ITS_AID_MAP_SPAT = 0x00000079


# ─── Low-level helpers ───────────────────────────────────────────


def _looks_like_plain_its_pdu(payload: bytes) -> bool:
    """Heuristic: distinguish plain ITS-PDU headers from TS 103 097 envelopes."""
    if len(payload) < 6 or payload[0] != 2:
        return False
    return payload[1] in ITS_PDU_MESSAGE_ID and payload[2] == 0 and payload[3] == 0


def _read_uint8(data: bytes, offset: int) -> tuple[int, int]:
    """Read a single byte, return (value, new_offset)."""
    if offset >= len(data):
        return 0, offset
    return data[offset], offset + 1


def _read_uint16(data: bytes, offset: int) -> tuple[int, int]:
    """Read a big-endian uint16, return (value, new_offset)."""
    if offset + 1 >= len(data):
        return 0, offset
    return struct.unpack_from("!H", data, offset)[0], offset + 2


def _read_length_determinant(data: bytes, offset: int) -> tuple[int, int]:
    """Read an ASN.1 UPER length determinant."""
    if offset >= len(data):
        return 0, offset
    first = data[offset]
    if first < 128:
        return first, offset + 1
    if offset + 1 >= len(data):
        return 0, offset
    length = ((first & 0x7F) << 8) | data[offset + 1]
    return length, offset + 2


def _read_fixed_length(data: bytes, offset: int, length: int) -> tuple[bytes, int]:
    """Read a fixed-length byte sequence."""
    if offset + length > len(data):
        return b"", offset
    return data[offset : offset + length], offset + length


def _bytes_to_hex(data: bytes, max_len: int = 16) -> str:
    """Convert bytes to hex string, truncated to max_len bytes."""
    if not data:
        return "—"
    truncated = data[:max_len]
    hex_str = truncated.hex()
    if len(data) > max_len:
        hex_str += "..."
    return hex_str


# ─── Certificate field scanners ─────────────────────────────────


def _scan_assurance_level(data: bytes, start: int, end: int) -> int | None:
    """Heuristic: find SubjectAssurance byte (bits 5-7 = assuranceLevel 0-7)."""
    for offset in range(start, min(end, len(data))):
        byte_value = data[offset]
        level = (byte_value >> 5) & 0x07
        confidence = byte_value & 0x07
        if 0 <= level <= 7 and 0 <= confidence <= 7:
            # Additional sanity: byte should not be a regular ASCII char
            if byte_value > 0x0F:
                return level
    return None


def _scan_station_type(data: bytes, start: int, end: int) -> str | None:
    """Heuristic: find StationType byte (0-15) in certificate attributes."""
    for offset in range(start, min(end, len(data))):
        value = data[offset]
        if value in STATION_TYPE_NAMES:
            # Context check: next byte(s) should not look like length field
            if offset + 1 < end and data[offset + 1] < 128:
                return STATION_TYPE_NAMES[value]
    return None


def _scan_validity_period(data: bytes, start: int, end: int) -> tuple[str | None, str | None]:
    """Heuristic: find ValidityPeriod (StartTime + Duration/EndTime).

    ETSI TS 103 097 ValidityPeriod:
      start  : Time32 (32-bit Unix epoch seconds since 2004-01-01)
      duration : Duration (1 byte: units * value)
    """
    for offset in range(start, end - 4):
        # Look for plausible Time32 values (2004-2026 ≈ 0-700M seconds)
        time_val = struct.unpack_from("!I", data, offset)[0]
        if 0 < time_val < 0x30000000:  # Roughly until ~2030
            base_year = 2004
            try:
                from datetime import datetime, timedelta, timezone

                base = datetime(base_year, 1, 1, tzinfo=timezone.utc)
                validity_start = (base + timedelta(seconds=time_val)).isoformat()
            except (OverflowError, ValueError):
                continue

            # Duration byte follows
            dur_offset = offset + 4
            if dur_offset < end:
                dur_byte = data[dur_offset]
                # Duration: top 2 bits = unit (0=seconds,1=minutes,2=hours,3=64hours),
                #           bottom 6 bits = value (0 = 1 unit, ..., 63 = 64 units)
                unit_type = (dur_byte >> 6) & 0x03
                unit_value = (dur_byte & 0x3F) + 1
                unit_names = ["seconds", "minutes", "hours", "64hours"]
                unit_name = unit_names[unit_type]
                validity_end = f"+{unit_value} {unit_name}"
                return validity_start, validity_end
    return None, None


def _scan_its_aid(data: bytes, start: int, end: int) -> list[int] | None:
    """Heuristic: find ITS-AID (PSID) list in certificate permissions.

    ITS-AIDs in ETSI are typically 1-4 bytes.
    Known values: CAM/DENM=36 (0x24), MAP/SPAT/SREM/SSEM=121 (0x79).
    """
    found: set[int] = set()
    for offset in range(start, min(end - 1, len(data))):
        val = data[offset]
        if val == 0x24:
            found.add(ITS_AID_DENM)
        elif val == 0x79:
            found.add(ITS_AID_MAP_SPAT)
    return list(found) if found else None


def _scan_region(data: bytes, start: int, end: int) -> tuple[str | None, str | None]:
    """Heuristic: find GeographicRegion in certificate.

    RegionType is 1 byte (0=none,1=circular,2=rectangular,3=polygonal,4=country).
    For country: 2-byte country code (e.g. 'DE') follows.
    """
    for offset in range(start, min(end, len(data))):
        region_type = data[offset]
        if region_type in REGION_TYPE_NAMES:
            if region_type == 4 and offset + 2 < end:
                country = data[offset + 1 : offset + 3].decode("ascii", errors="replace").upper()
                return "country", country
            if region_type == 0:
                return "none", None
            if region_type in (1, 2, 3):
                return REGION_TYPE_NAMES[region_type], None
    return None, None


def _parse_certificate(cert_data: bytes) -> dict:
    """Parse an ETSI TS 103 097 certificate with heuristic field extraction.

    Returns parsed fields.  Many fields rely on byte-pattern heuristics rather
    than full ASN.1/UPER decoding, so false negatives are expected.
    """
    result: dict = {
        "version": None,
        "signer_info_raw": None,
        "assurance_level": None,
        "station_type": None,
        "validity_start": None,
        "validity_end": None,
        "its_aid_list": None,
        "region_type": None,
        "region_detail": None,
    }

    if len(cert_data) < 4:
        return result

    offset = 0
    version, offset = _read_uint8(cert_data, offset)
    result["version"] = version

    # Signer Info — first byte after version
    if offset < len(cert_data):
        signer_info_type = cert_data[offset] & 0xC0  # Top 2 bits
        result["signer_info_raw"] = _bytes_to_hex(cert_data[offset : offset + 8])
        offset += 1

    # Try to extract certificate body via length determinant
    if offset < len(cert_data):
        body_len, body_start = _read_length_determinant(cert_data, offset)
        if body_len > 0 and body_start + body_len <= len(cert_data):
            body_end = body_start + body_len
        else:
            body_end = len(cert_data)
    else:
        body_end = len(cert_data)

    scan_start = offset
    scan_end = min(body_end, len(cert_data))

    result["assurance_level"] = _scan_assurance_level(cert_data, scan_start, scan_end)
    result["station_type"] = _scan_station_type(cert_data, scan_start, scan_end)
    result["validity_start"], result["validity_end"] = _scan_validity_period(cert_data, scan_start, scan_end)
    result["its_aid_list"] = _scan_its_aid(cert_data, scan_start, scan_end)
    result["region_type"], result["region_detail"] = _scan_region(cert_data, scan_start, scan_end)

    return result


# ─── Main parsing entrypoint ────────────────────────────────────────


def parse_security_header(payload: bytes) -> SecurityInfo | None:
    """Parse the ETSI TS 103 097 security envelope from a V2X payload."""
    if len(payload) < 2:
        return None

    if _looks_like_plain_its_pdu(payload):
        return None

    offset = 0

    # ─── Protocol Version ────────────────────────────────────
    protocol_version, offset = _read_uint8(payload, offset)
    if protocol_version != 2:
        return None

    # ─── Security Profile (Content Type) ─────────────────────
    security_profile, offset = _read_uint8(payload, offset)
    profile_name = SECURITY_PROFILE_NAMES.get(security_profile, f"unknown({security_profile})")

    if security_profile == SECURITY_PROFILE_UNSECURED:
        return SecurityInfo(
            protocol_version=protocol_version,
            security_profile=profile_name,
        )

    info = SecurityInfo(
        protocol_version=protocol_version,
        security_profile=profile_name,
    )

    if offset >= len(payload):
        return info

    # ─── Signer Info (UPER encoded) ─────────────────────────
    signer_byte = payload[offset]
    signer_type_bits = (signer_byte >> 6) & 0x03
    info.signer_type = SIGNER_TYPE_NAMES.get(signer_type_bits, f"unknown({signer_type_bits})")

    if signer_type_bits in (0, 1):
        digest_start = offset + 1
        if digest_start + 8 <= len(payload):
            info.signer_digest = payload[digest_start : digest_start + 8].hex()
            offset = digest_start + 8
        else:
            return info

    elif signer_type_bits == 2:
        offset += 1
        chain_len, offset = _read_length_determinant(payload, offset)
        if chain_len > 0 and offset + 10 < len(payload):
            cert_len, cert_start = _read_length_determinant(payload, offset)
            if cert_len > 0 and cert_start + cert_len <= len(payload):
                cert_data = payload[cert_start : cert_start + cert_len]
                cert_info = _parse_certificate(cert_data)
                if cert_info.get("signer_info_raw"):
                    info.certificate_issuer = cert_info["signer_info_raw"]
                if cert_info.get("assurance_level") is not None:
                    info.assurance_level = cert_info["assurance_level"]
                if cert_info.get("station_type") is not None:
                    info.station_type = cert_info["station_type"]
                if cert_info.get("validity_start") is not None:
                    info.validity_start = cert_info["validity_start"]
                if cert_info.get("validity_end") is not None:
                    info.validity_end = cert_info["validity_end"]
                if cert_info.get("its_aid_list") is not None:
                    info.its_aid_list = cert_info["its_aid_list"]
                if cert_info.get("region_type") is not None:
                    info.region_type = cert_info["region_type"]
                if cert_info.get("region_detail") is not None:
                    info.region_detail = cert_info["region_detail"]

    # ─── Signature extraction ──────────────────────────────────
    remaining_len = len(payload) - offset
    if remaining_len >= 65:
        sig_end = len(payload)
        sig_start = max(offset, sig_end - 66)

        algo_offset = sig_start
        if algo_offset < len(payload):
            algo_byte = payload[algo_offset]
            if algo_byte == 0:
                info.signature_algorithm = "ECDSA NIST P-256"
            elif algo_byte == 1:
                info.signature_algorithm = "ECDSA BrainpoolP256r1"
            else:
                info.signature_algorithm = f"unknown({algo_byte})"

        if len(payload) >= 65:
            r_start = len(payload) - 64
            s_start = len(payload) - 32
            info.signature_r = _bytes_to_hex(payload[r_start : r_start + 16], 16)
            info.signature_s = _bytes_to_hex(payload[s_start : s_start + 16], 16)

    return info


# ─── Decoded-message extractor (no raw payload) ──────────────────


def extract_security_from_decoded(decoded: dict, msg_type: str) -> SecurityInfo | None:
    """Extract security information from a decoded ITS message."""
    info = SecurityInfo()

    header = decoded.get("header", decoded.get("itsPduHeader", {}))

    if "protocolVersion" in header:
        info.protocol_version = header["protocolVersion"]

    msg_id = header.get("messageID", header.get("messageId"))
    if msg_id is not None:
        its_aid_map = {
            1: ITS_AID_DENM,
            2: ITS_AID_CAM,
            3: ITS_AID_MAP_SPAT,
            4: ITS_AID_MAP_SPAT,
            5: ITS_AID_MAP_SPAT,
            9: ITS_AID_MAP_SPAT,
            10: ITS_AID_MAP_SPAT,
        }
        info.its_aid_list = [its_aid_map.get(msg_id, msg_id)]

    station_id = header.get("stationID", header.get("stationId"))
    if station_id is not None:
        info.station_type = f"Station-ID: {station_id}"

    if msg_type == "CAM":
        cam = decoded.get("cam", decoded)
        params = cam.get("camParameters", cam)
        basic = params.get("basicContainer", {})
        station_type_int = basic.get("stationType")
        if station_type_int is not None:
            info.station_type = STATION_TYPE_NAMES.get(station_type_int, f"type_{station_type_int}")

    elif msg_type == "DENM":
        denm = decoded.get("denm", decoded)
        mgmt = denm.get("managementContainer", {})
        station_type_int = mgmt.get("stationType")
        if station_type_int is not None:
            info.station_type = STATION_TYPE_NAMES.get(station_type_int, f"type_{station_type_int}")

    return info if any(v is not None for v in [info.protocol_version, info.its_aid_list, info.station_type]) else None
