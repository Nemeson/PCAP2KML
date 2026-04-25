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
from typing import Optional

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
    """Read an ASN.1 UPER length determinant.

    For small lengths (<128): single byte.
    For larger lengths: first byte = 0x80 | (high bits), second byte = low bits.
    """
    if offset >= len(data):
        return 0, offset
    first = data[offset]
    if first < 128:
        return first, offset + 1
    else:
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


def _parse_certificate(cert_data: bytes) -> dict:
    """Parse an ETSI TS 103 097 certificate (simplified field extraction).

    Certificate structure per ETSI TS 103 097:
      Version | SignerInfo | SubjectInfo | SubjectAssurance |
      ValidityPeriod | Region | SubjectAttributes

    Returns a dict with extracted fields. Fields that cannot be parsed
    are set to None.
    """
    result: dict = {}
    offset = 0

    if len(cert_data) < 2:
        return result

    # Version (1 byte)
    version, offset = _read_uint8(cert_data, offset)
    result["version"] = version

    # Signer Info — determines who issued this certificate
    if offset >= len(cert_data):
        return result

    signer_info_type = cert_data[offset] & 0xC0  # Top 2 bits
    # The signer info is UPER encoded; exact parsing depends on type
    # For now, we skip detailed parsing of the signer info field
    result["signer_info_raw"] = _bytes_to_hex(cert_data[offset : offset + 8])

    # Skip to find subject info — this is a simplified parser
    # In practice, we'd need full ASN.1 UPER decoding
    # We'll extract what we can with heuristic byte scanning

    return result


def parse_security_header(payload: bytes) -> Optional[SecurityInfo]:
    """Parse the ETSI TS 103 097 security envelope from a V2X payload.

    Tries to extract security information from signed messages.
    If the message is unsigned or the format is not recognized,
    returns None.

    The security envelope starts with:
      - Protocol Version (1 byte): value 2 for current ETSI TS 103 097
      - Content Type / Security Profile (1 byte): 0=unsecured, 1=signed, etc.

    Args:
        payload: Raw payload bytes (may include security header).

    Returns:
        SecurityInfo with extracted fields, or None if not a signed message.
    """
    if len(payload) < 2:
        return None

    if _looks_like_plain_its_pdu(payload):
        return None

    offset = 0

    # ─── Protocol Version ────────────────────────────────────
    protocol_version, offset = _read_uint8(payload, offset)

    # Only version 2 is defined in ETSI TS 103 097 V2.2.1
    if protocol_version != 2:
        # Not a security envelope or unsupported version
        return None

    # ─── Security Profile (Content Type) ─────────────────────
    security_profile, offset = _read_uint8(payload, offset)

    profile_name = SECURITY_PROFILE_NAMES.get(
        security_profile, f"unknown({security_profile})"
    )

    # Unsecured messages have no further security data
    if security_profile == SECURITY_PROFILE_UNSECURED:
        return SecurityInfo(
            protocol_version=protocol_version,
            security_profile=profile_name,
        )

    # ─── For signed messages, extract signer info ────────────
    # The remaining structure depends on the security profile.
    # We do our best to extract key fields.

    info = SecurityInfo(
        protocol_version=protocol_version,
        security_profile=profile_name,
    )

    if offset >= len(payload):
        return info

    # ─── Signer Info (UPER encoded) ─────────────────────────
    # SignerInfo ::= CHOICE {
    #   self                  [0] HashedId8,
    #   digest                [1] HashedId8,
    #   certificateChain      [2] SequenceOfCertificate,
    # }
    # In UPER, choice index is 2 bits: 0=digest(8), 1=digest(8), 2=chain

    # Read the signer info type byte
    # UPER encodes choice index in first 2 bits
    signer_byte = payload[offset]
    # Top 2 bits indicate signer type (0=self with signature, 1=digest, 2=chain, 3=digest+unknown)
    signer_type_bits = (signer_byte >> 6) & 0x03

    info.signer_type = SIGNER_TYPE_NAMES.get(
        signer_type_bits, f"unknown({signer_type_bits})"
    )

    # ─── Extract certificate digest or chain ─────────────────
    if signer_type_bits in (0, 1):
        # HashedId8 (8 bytes) follows the choice byte
        # The digest is embedded in the remaining bits of the first byte + next 7 bytes
        # UPER alignment: after choice (2 bits), HashedId8 is 64 bits = 8 bytes
        # We need to read 8 bytes starting from offset, but the first byte has 2 bits used
        # For simplicity, extract the next 8 bytes as the digest
        digest_start = offset + 1  # Skip the signer info byte
        if digest_start + 8 <= len(payload):
            digest_bytes = payload[digest_start : digest_start + 8]
            info.signer_digest = digest_bytes.hex()
            offset = digest_start + 8
        else:
            # Not enough data for digest
            return info

    elif signer_type_bits == 2:
        # Certificate chain — length determinant followed by certificates
        offset += 1  # Skip signer info byte
        chain_len, offset = _read_length_determinant(payload, offset)

        if chain_len > 0 and offset + 10 < len(payload):
            # Try to extract the first certificate's data
            # Certificate starts with version byte + length
            cert_start = offset
            # The certificate chain contains one or more certificates
            # Each certificate has a length determinant
            cert_len, cert_start = _read_length_determinant(payload, offset)

            if cert_len > 0 and cert_start + cert_len <= len(payload):
                cert_data = payload[cert_start : cert_start + cert_len]
                # Try to extract basic fields from the certificate
                cert_info = _parse_certificate(cert_data)
                if cert_info.get("signer_info_raw"):
                    info.certificate_issuer = cert_info["signer_info_raw"]

    # ─── Header Info ─────────────────────────────────────────
    # After signer info: HeaderInfo contains:
    #   - PSID (ITS-AID)
    #   - Generation time
    #   - Generation location (optional)
    #   - ... other optional fields

    # We attempt to find the signature at the end of the message
    # ETSI TS 103 097 signatures are always the last field

    # ECDSA signature: 2 * field_size bytes (R + S)
    # NIST P-256: 2 * 32 = 64 bytes
    # BrainpoolP256r1: 2 * 32 = 64 bytes

    # Try to extract signature from the end of the payload
    remaining_len = len(payload) - offset
    if remaining_len >= 65:
        # Most likely signature is at the end (64 bytes for P-256)
        # The signature format: [algorithm byte][R (32 bytes)][S (32 bytes)]
        # or for EcdsaP256: [R length][R (32 bytes)][S length][S (32 bytes)]
        sig_end = len(payload)
        sig_start = max(offset, sig_end - 66)  # 1 byte algo + 32 R + 1 byte len + 32 S

        # Check for signature algorithm indicator
        # UPER: 0 = NIST P-256, 1 = BrainpoolP256r1
        algo_offset = sig_start
        if algo_offset < len(payload):
            algo_byte = payload[algo_offset]
            if algo_byte == 0:
                info.signature_algorithm = "ECDSA NIST P-256"
            elif algo_byte == 1:
                info.signature_algorithm = "ECDSA BrainpoolP256r1"
            else:
                info.signature_algorithm = f"unknown({algo_byte})"

        # Extract R and S values (last 64 bytes for P-256 signatures)
        if len(payload) >= 65:
            r_start = len(payload) - 64
            s_start = len(payload) - 32
            info.signature_r = _bytes_to_hex(payload[r_start : r_start + 16], 16)
            info.signature_s = _bytes_to_hex(payload[s_start : s_start + 16], 16)

    return info


def extract_security_from_decoded(
    decoded: dict, msg_type: str
) -> Optional[SecurityInfo]:
    """Extract security information from a decoded ITS message.

    Decoded messages from asn1tools may contain security-related fields
    in their header. This extracts them into a SecurityInfo structure.

    Args:
        decoded: Decoded message dict from asn1tools.
        msg_type: Message type string (CAM, DENM, etc.)

    Returns:
        SecurityInfo with available fields, or None if no security data found.
    """
    info = SecurityInfo()

    # Try to extract from the ITS PDU header
    header = decoded.get("header", decoded.get("itsPduHeader", {}))

    # Protocol version from ITS PDU header
    if "protocolVersion" in header:
        info.protocol_version = header["protocolVersion"]

    # Message ID maps to ITS-AID
    msg_id = header.get("messageID", header.get("messageId"))
    if msg_id is not None:
        # ITS-AID values per ETSI TS 102 965
        its_aid_map = {
            1: 0x00000024,  # DENM = 36
            2: 0x00000024,  # CAM = 36 (same ITS-AID)
            3: 0x00000079,  # SPATEM = 121
            4: 0x00000079,  # MAPEM = 121
            5: 0x00000079,  # SPATEM = 121
            9: 0x00000079,  # SREM = 121
            10: 0x00000079,  # SSEM = 121
        }
        info.its_aid_list = [its_aid_map.get(msg_id, msg_id)]

    # Station ID from header
    station_id = header.get("stationID", header.get("stationId"))
    if station_id is not None:
        info.station_type = f"Station-ID: {station_id}"

    # Try to extract from CAM/DENM specific fields
    if msg_type == "CAM":
        cam = decoded.get("cam", decoded)
        params = cam.get("camParameters", cam)
        basic = params.get("basicContainer", {})
        # CAM basicContainer has stationType
        station_type_int = basic.get("stationType")
        if station_type_int is not None:
            info.station_type = STATION_TYPE_NAMES.get(
                station_type_int, f"type_{station_type_int}"
            )

    elif msg_type == "DENM":
        denm = decoded.get("denm", decoded)
        mgmt = denm.get("managementContainer", {})
        station_type_int = mgmt.get("stationType")
        if station_type_int is not None:
            info.station_type = STATION_TYPE_NAMES.get(
                station_type_int, f"type_{station_type_int}"
            )

    return (
        info
        if any(
            v is not None
            for v in [info.protocol_version, info.its_aid_list, info.station_type]
        )
        else None
    )
