"""PCAP parser with dual backend: pyshark (preferred) or scapy (fallback).

Extracts V2X ITS messages (CAM, DENM, SREM, SSEM, MAPEM, SPATEM) and
NMEA sentences from PCAP files.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scapy.layers.dot11 import Dot11
from scapy.layers.l2 import SNAP

from .data_model import MessageType, SessionData, V2xMessage
from .nmea_parser import parse_nmea_sentence

logger = logging.getLogger(__name__)

# BTP port numbers for ITS message types (ETSI TS 103 248 V2.2.1)
BTP_PORTS = {
    2001: MessageType.CAM,
    2002: MessageType.DENM,
    2003: MessageType.MAPEM,
    2004: MessageType.SPATEM,
    2007: MessageType.SREM,
    2008: MessageType.SSEM,
}

GEONETWORKING_ETHERTYPE = 0x8947
GEONET_BTP_PORT_SCAN_START = 32
GEONET_BTP_PORT_SCAN_STOP = 96

# Pyshark display filter: keep ITS-specific layers; broad "or gps" kept for
# GNSS sources that present as neither udp.port 2947 nor a named nmea layer.
PYSHARK_DISPLAY_FILTER = (
    "btp or nmea or gnw or gn or its or "
    "eth.type == 0x8947 or udp.port == 2001 or udp.port == 2002 or "
    "udp.port == 2003 or udp.port == 2004 or udp.port == 2007 or udp.port == 2008"
)
PYSHARK_OPEN_TIMEOUT_S = 30.0

# ITS-PDU-Header itsPduHeader.messageId fallback mapping (ETSI TS 102 894-2).
# Used when BTP destination port is missing or masked.
ITS_PDU_MESSAGE_ID = {
    1: MessageType.DENM,
    2: MessageType.CAM,
    3: MessageType.SPATEM,
    4: MessageType.MAPEM,
    5: MessageType.SPATEM,
    9: MessageType.SREM,
    10: MessageType.SSEM,
}


def _infer_msg_type_from_pdu(payload: bytes) -> Optional[MessageType]:
    """Fallback: infer message type from ITS-PDU header messageId byte.

    ITS PDU header layout (ETSI TS 102 894-2):
      byte 0: protocolVersion (== 2 for current ITS)
      byte 1: messageID (1=DENM, 2=CAM, 3/5=SPATEM, 4=MAPEM, 9=SREM, 10=SSEM)
    """
    if len(payload) < 2 or payload[0] != 0x02:
        return None
    return ITS_PDU_MESSAGE_ID.get(payload[1])


class ParseCancelled(RuntimeError):
    """Raised when parsing is cancelled by the caller."""


def _default_details(
    msg_type: MessageType,
    payload: bytes,
    transport: str,
    source: str,
    dst_port: int,
    decoded_ok: bool,
) -> dict[str, str]:
    """Create a user-facing details summary for a parsed message."""
    semantic_label = {
        MessageType.MAPEM: "Kreuzungsgeometrie / Fahrstreifen-Referenz",
        MessageType.SPATEM: "Signalphasen und Timing",
        MessageType.SREM: "Signalanforderung",
        MessageType.SSEM: "Signalstatus",
        MessageType.CAM: "Fahrzeugzustand / Awareness",
        MessageType.DENM: "Ereignis- und Warnmeldung",
    }.get(msg_type, msg_type.value)
    details = {
        "Transport": transport,
        "Quelle": source,
        "BTP-Zielport": str(dst_port),
        "Payload-Laenge": str(len(payload)),
        "Bedeutung": semantic_label,
        "ASN.1-Dekodierung": "erfolgreich" if decoded_ok else "nicht verfuegbar - Rohdetails aktiv",
    }
    return details


def _decode_direct_geonet_payload(
    raw_data: bytes,
    timestamp: datetime,
    station_id: str,
    source: str,
) -> Optional[V2xMessage]:
    """Decode a GeoNetworking/BTP payload from direct ITS-G5 frames.

    The provided capture files contain GeoNetworking frames without UDP wrapping.
    We scan the GeoNet payload for a known BTP destination port and then derive
    the BTP payload plus the embedded long position vector fields.
    """
    scan_stop = min(len(raw_data) - 6, GEONET_BTP_PORT_SCAN_STOP)
    for offset in range(GEONET_BTP_PORT_SCAN_START, max(scan_stop, 0)):
        dst_port = int.from_bytes(raw_data[offset:offset + 2], "big")
        msg_type = BTP_PORTS.get(dst_port)
        if msg_type is None:
            # Fallback: BTP port unknown — look at the ITS PDU header messageId
            # one byte ahead of the BTP payload start (offset+4, then +1).
            btp_start = offset + 4
            if btp_start + 2 < len(raw_data):
                fallback_type = _infer_msg_type_from_pdu(raw_data[btp_start:btp_start + 2])
                if fallback_type is not None:
                    msg_type = fallback_type
                else:
                    continue
            else:
                continue

        btp_payload_offset = offset + 4
        if btp_payload_offset >= len(raw_data):
            continue

        # ITS PDU payloads in the supplied captures start with protocolVersion=2.
        if raw_data[btp_payload_offset] != 0x02:
            continue

        lat_offset = offset - 16
        lon_offset = offset - 12
        if lat_offset < 0 or lon_offset + 4 > len(raw_data):
            continue

        lat = int.from_bytes(raw_data[lat_offset:lat_offset + 4], "big", signed=True) / 1e7
        lon = int.from_bytes(raw_data[lon_offset:lon_offset + 4], "big", signed=True) / 1e7
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        payload = raw_data[btp_payload_offset:]
        # GeoNetworking source-address is the 8-byte GN_ADDR at offset-24
        # from the BTP port field (CommonHeader + 8-byte source address).
        gn_src_offset = offset - 24
        gn_source_addr = None
        if gn_src_offset >= 0 and gn_src_offset + 8 <= len(raw_data):
            gn_source_addr = raw_data[gn_src_offset:gn_src_offset + 8].hex(":")

        decoded = _decode_its_message(
            msg_type,
            payload,
            transport="GeoNetworking direkt",
            source=source,
            dst_port=dst_port,
        )
        if decoded:
            decoded.timestamp = timestamp
            if decoded.station_id == "unknown":
                decoded.station_id = station_id
            if gn_source_addr:
                decoded.details["GN-Quelladresse"] = gn_source_addr
            return decoded

        return V2xMessage(
            timestamp=timestamp,
            station_id=station_id,
            msg_type=msg_type,
            latitude=lat,
            longitude=lon,
            raw_payload=payload,
            details=_default_details(
                msg_type,
                payload,
                "GeoNetworking direkt",
                source,
                dst_port,
                False,
            ),
        )

    return None


def _tshark_available() -> bool:
    """Check if TShark is available on the system."""
    return shutil.which("tshark") is not None


def _extract_cam_position(decoded: dict) -> Optional[tuple]:
    """Extract lat/lon/alt/speed/heading from a decoded CAM message."""
    try:
        cam = decoded.get("cam", decoded)
        params = cam.get("camParameters", cam)

        # Basic container
        basic = params.get("basicContainer", {})
        ref_pos = basic.get("referencePosition", {})

        lat = int(ref_pos.get("latitude", 0)) / 1e7
        lon = int(ref_pos.get("longitude", 0)) / 1e7
        alt = int(ref_pos.get("altitude", {}).get("altitudeValue", 0)) / 100.0

        # High frequency container
        hf = params.get("highFrequencyContainer", {})
        speed = int(hf.get("speed", 0)) / 100.0  # cm/s -> m/s
        heading = int(hf.get("heading", 0)) / 10.0  # decidegrees -> degrees

        station_id = str(basic.get("stationID", "unknown"))

        return lat, lon, alt, speed, heading, station_id
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("CAM position extraction failed: %s", e)
        return None


def _extract_denm_position(decoded: dict) -> Optional[tuple]:
    """Extract lat/lon/alt/speed/heading from a decoded DENM message."""
    try:
        denm = decoded.get("denm", decoded)
        mgmt = denm.get("managementContainer", {})
        ref_pos = mgmt.get("eventPosition", {})

        lat = int(ref_pos.get("latitude", 0)) / 1e7
        lon = int(ref_pos.get("longitude", 0)) / 1e7
        alt = int(ref_pos.get("altitude", {}).get("altitudeValue", 0)) / 100.0

        station_id = str(denm.get("header", {}).get("stationID", "unknown"))
        speed = None
        heading = None

        return lat, lon, alt, speed, heading, station_id
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("DENM position extraction failed: %s", e)
        return None


def _extract_generic_position(decoded: dict, msg_type: MessageType) -> Optional[tuple]:
    """Extract position from other ITS message types (SREM, SSEM, MAPEM, SPATEM)."""
    try:
        # Most ITS messages have a reference position in their header
        header = decoded.get("header", decoded.get("protocolVersion", {}))
        station_id = str(header.get("stationID", "unknown"))

        # Try to find any position reference
        ref_pos = decoded.get("referencePosition", None)
        if ref_pos is None:
            # Search nested structures
            for key, val in decoded.items():
                if isinstance(val, dict) and "latitude" in val:
                    ref_pos = val
                    break

        if ref_pos is None:
            return None

        lat = int(ref_pos.get("latitude", 0)) / 1e7
        lon = int(ref_pos.get("longitude", 0)) / 1e7
        alt = int(ref_pos.get("altitude", {}).get("altitudeValue", 0)) / 100.0

        return lat, lon, alt, None, None, station_id
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("Generic position extraction failed for %s: %s", msg_type.value, e)
        return None


_EXTRACTORS = {
    MessageType.CAM: _extract_cam_position,
    MessageType.DENM: _extract_denm_position,
}


# ─── Phase 2.1: extended field extraction per ITS message type ───────────
# These helpers populate V2xMessage.decoded_data with human-useful fields.
# References: ETSI EN 302 637-2/3, ETSI TS 103 301, SAE J2735.


def _safe_get(obj, *keys, default=None):
    """Walk nested dicts/tuples without raising."""
    cur = obj
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key, default if key == keys[-1] else {})
        elif isinstance(cur, (list, tuple)) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return default
    return cur if cur != {} else default


def _extra_fields_cam(decoded: dict) -> dict:
    """CAM extension: vehicle dimensions, drive direction, lights."""
    cam = decoded.get("cam", decoded)
    params = cam.get("camParameters", cam) if isinstance(cam, dict) else {}
    basic = params.get("basicContainer", {}) if isinstance(params, dict) else {}
    hf = params.get("highFrequencyContainer", {}) if isinstance(params, dict) else {}
    # highFrequencyContainer is a CHOICE; asn1tools may wrap it as tuple
    if isinstance(hf, tuple) and len(hf) == 2:
        hf = hf[1]
    fields: dict = {}
    station_type = _safe_get(basic, "stationType")
    if station_type is not None:
        fields["stationType"] = station_type
    for key in ("driveDirection", "vehicleLength", "vehicleWidth",
                "longitudinalAcceleration", "curvature", "yawRate",
                "exteriorLights"):
        val = _safe_get(hf, key)
        if val is not None:
            fields[key] = val
    return fields


def _extra_fields_denm(decoded: dict) -> dict:
    """DENM extension: cause, severity, validity."""
    denm = decoded.get("denm", decoded)
    mgmt = denm.get("managementContainer", {}) if isinstance(denm, dict) else {}
    situation = denm.get("situationContainer", {}) if isinstance(denm, dict) else {}
    fields: dict = {}
    for key in ("detectionTime", "referenceTime", "validityDuration",
                "stationType", "relevanceDistance", "relevanceTrafficDirection"):
        val = _safe_get(mgmt, key)
        if val is not None:
            fields[key] = val
    event_type = _safe_get(situation, "eventType")
    if isinstance(event_type, dict):
        fields["causeCode"] = event_type.get("causeCode")
        fields["subCauseCode"] = event_type.get("subCauseCode")
    severity = _safe_get(situation, "informationQuality")
    if severity is not None:
        fields["informationQuality"] = severity
    return fields


def _extra_fields_mapem(decoded: dict) -> dict:
    """MAPEM extension: intersectionId, revision, lane count, speed limits."""
    body = decoded.get("map", decoded)
    if isinstance(body, dict):
        intersections = body.get("intersections", [])
    else:
        intersections = []
    fields: dict = {}
    if intersections:
        first = intersections[0]
        iid = _safe_get(first, "id", "id")
        if iid is not None:
            fields["intersectionId"] = iid
        rev = first.get("revision") if isinstance(first, dict) else None
        if rev is not None:
            fields["revision"] = rev
        lanes = first.get("laneSet", []) if isinstance(first, dict) else []
        fields["laneCount"] = len(lanes)
        fields["intersectionCount"] = len(intersections)
        speed_limits = first.get("speedLimits") if isinstance(first, dict) else None
        if speed_limits:
            fields["speedLimits"] = speed_limits
        fields["intersections"] = intersections
    return fields


def _extra_fields_spatem(decoded: dict) -> dict:
    """SPATEM extension: intersectionId, signal group count, timestamp, moy."""
    body = decoded.get("spat", decoded)
    fields: dict = {}
    intersections = body.get("intersections", []) if isinstance(body, dict) else []
    if intersections:
        first = intersections[0]
        iid = _safe_get(first, "id", "id")
        if iid is not None:
            fields["intersectionId"] = iid
        rev = first.get("revision") if isinstance(first, dict) else None
        if rev is not None:
            fields["revision"] = rev
        moy = first.get("moy") if isinstance(first, dict) else None
        if moy is not None:
            fields["moy"] = moy
        ts = first.get("timeStamp") if isinstance(first, dict) else None
        if ts is not None:
            fields["timeStamp"] = ts
        states = first.get("states", []) if isinstance(first, dict) else []
        fields["signalGroupCount"] = len(states)
        fields["intersections"] = intersections
    return fields


def _extra_fields_srem(decoded: dict) -> dict:
    """SREM extension: requestId, sequenceNumber, importanceLevel, lanes, ETA."""
    body = decoded.get("srm", decoded)
    fields: dict = {}
    if not isinstance(body, dict):
        return fields
    requests = body.get("requests", [])
    if requests and isinstance(requests[0], dict):
        req = requests[0].get("request", requests[0])
        fields["requestId"] = req.get("requestID") if isinstance(req, dict) else None
        fields["sequenceNumber"] = req.get("sequenceNumber") if isinstance(req, dict) else None
        in_bound = _safe_get(req, "inBoundLane", "lane")
        if in_bound:
            fields["inLane"] = in_bound
        out_bound = _safe_get(req, "outBoundLane", "lane")
        if out_bound:
            fields["outLane"] = out_bound
        eta = _safe_get(req, "expectedTimeOfArrival")
        if eta:
            fields["eta"] = eta
        intersection_id = _safe_get(req, "intersectionID", "id")
        if intersection_id is not None:
            fields["intersectionId"] = intersection_id
    requestor = body.get("requestor")
    if isinstance(requestor, dict):
        fields["requestorType"] = _safe_get(requestor, "type", "role")
        fields["importanceLevel"] = _safe_get(requestor, "type", "importanceLevel")
    return {k: v for k, v in fields.items() if v is not None}


def _extra_fields_ssem(decoded: dict) -> dict:
    """SSEM extension: intersectionId, status list, request correlation."""
    body = decoded.get("ssm", decoded)
    fields: dict = {}
    if not isinstance(body, dict):
        return fields
    status_list = body.get("status", [])
    fields["statusCount"] = len(status_list)
    if status_list and isinstance(status_list[0], dict):
        first = status_list[0]
        iid = _safe_get(first, "id", "id")
        if iid is not None:
            fields["intersectionId"] = iid
        sigs = first.get("sigStatus", []) if isinstance(first, dict) else []
        if sigs and isinstance(sigs[0], dict):
            req = sigs[0].get("sigStatusPackage", sigs[0])
            fields["requestId"] = _safe_get(req, "requester", "id")
            fields["sequenceNumber"] = _safe_get(req, "requester", "sequenceNumber")
            fields["requestState"] = req.get("status") if isinstance(req, dict) else None
    return {k: v for k, v in fields.items() if v is not None}


_EXTRA_FIELD_EXTRACTORS = {
    MessageType.CAM: _extra_fields_cam,
    MessageType.DENM: _extra_fields_denm,
    MessageType.MAPEM: _extra_fields_mapem,
    MessageType.SPATEM: _extra_fields_spatem,
    MessageType.SREM: _extra_fields_srem,
    MessageType.SSEM: _extra_fields_ssem,
}


def _safe_extract_extra(msg_type: MessageType, decoded: dict) -> dict:
    """Run the per-type extra-field extractor, swallowing any surprises."""
    extractor = _EXTRA_FIELD_EXTRACTORS.get(msg_type)
    if not extractor:
        return {}
    try:
        return extractor(decoded) or {}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        logger.debug("Extended-field extraction failed for %s: %s", msg_type.value, exc)
        return {}


def _decode_its_message(
    msg_type: MessageType,
    payload: bytes,
    *,
    transport: str,
    source: str,
    dst_port: int,
) -> Optional[V2xMessage]:
    """Attempt to decode an ITS message using ASN.1 schemas."""
    try:
        from .asn1_schemas import decode_its_message
        decoded = decode_its_message(msg_type.value, payload)
    except ImportError:
        logger.warning("asn1_schemas not available")
        return None

    if decoded is None:
        return None

    extractor = _EXTRACTORS.get(msg_type, _extract_generic_position)
    result = extractor(decoded, msg_type) if extractor == _extract_generic_position else extractor(decoded)

    if result is None:
        return None

    lat, lon, alt, speed, heading, station_id = result

    # ─── Extract security header info from raw payload ────
    from .security_parser import parse_security_header, extract_security_from_decoded
    security_info = parse_security_header(payload)
    # Also try to extract from the decoded message fields
    decoded_security = extract_security_from_decoded(decoded, msg_type.value)
    if security_info is None:
        security_info = decoded_security
    elif decoded_security is not None:
        # Merge: decoded fields fill in gaps left by raw parsing
        if security_info.station_type is None and decoded_security.station_type:
            security_info.station_type = decoded_security.station_type
        if security_info.its_aid_list is None and decoded_security.its_aid_list:
            security_info.its_aid_list = decoded_security.its_aid_list

    extra_fields = _safe_extract_extra(msg_type, decoded)
    details = _default_details(msg_type, payload, transport, source, dst_port, True)
    for key, value in extra_fields.items():
        if value is None:
            continue
        display = str(value)
        if len(display) > 80:
            display = display[:77] + "..."
        details[key] = display

    return V2xMessage(
        timestamp=datetime.now(tz=timezone.utc),
        station_id=station_id,
        msg_type=msg_type,
        latitude=lat,
        longitude=lon,
        altitude=alt,
        speed=speed,
        heading=heading,
        raw_payload=payload,
        details=details,
        security_info=security_info,
        decoded_data=extra_fields,
    )


# ─── Pyshark Backend ──────────────────────────────────────────────

def _parse_with_pyshark(
    pcap_path: str,
    session: SessionData,
    progress_callback=None,
    cancel_check=None,
) -> int:
    """Parse PCAP using pyshark (TShark backend).

    Returns the number of messages successfully parsed.
    """
    import pyshark

    count = 0
    try:
        cap = pyshark.FileCapture(
            pcap_path,
            display_filter=PYSHARK_DISPLAY_FILTER,
            use_json=True,
            include_raw=True,
        )
        # pyshark exposes tshark process timeout via internal settings only;
        # apply a conservative default to prevent hangs on truncated captures.
        try:
            cap._tshark_read_timeout = PYSHARK_OPEN_TIMEOUT_S  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception as e:
        logger.error("pyshark failed to open %s: %s", pcap_path, e)
        return 0

    packet_index = 0
    for pkt in cap:
        try:
            packet_index += 1
            if cancel_check and cancel_check():
                cap.close()
                raise ParseCancelled("Parsing was cancelled")
            if progress_callback and packet_index % 25 == 0:
                progress_callback(min(0.95, packet_index / max(packet_index + 1, 1)))

            # Try NMEA extraction from UDP/TCP payload
            if hasattr(pkt, "data") and hasattr(pkt.data, "data_data"):
                raw = bytes.fromhex(pkt.data.data_data.replace(":", ""))
                nmea_msg = parse_nmea_sentence(raw)
                if nmea_msg:
                    nmea_msg.timestamp = _pyshark_timestamp(pkt)
                    session.add_message(nmea_msg)
                    count += 1
                    continue

            # Try BTP/ITS extraction
            if hasattr(pkt, "btp"):
                btp_layer = pkt.btp
                dst_port = int(getattr(btp_layer, "dstport", 0))
                msg_type = BTP_PORTS.get(dst_port)
                if msg_type and hasattr(pkt, "data"):
                    payload_hex = getattr(pkt.data, "data_data", "")
                    if payload_hex:
                        payload = bytes.fromhex(payload_hex.replace(":", ""))
                        msg = _decode_its_message(
                            msg_type,
                            payload,
                            transport="Pyshark / BTP",
                            source=str(getattr(pkt, "eth", getattr(pkt, "wlan", "unknown"))),
                            dst_port=dst_port,
                        )
                        if msg:
                            msg.timestamp = _pyshark_timestamp(pkt)
                            session.add_message(msg)
                            count += 1
        except ParseCancelled:
            raise
        except Exception as e:
            logger.debug("Error processing pyshark packet: %s", e)
            continue

    cap.close()
    if progress_callback:
        progress_callback(1.0)
    return count


def _pyshark_timestamp(pkt) -> datetime:
    """Extract timestamp from a pyshark packet."""
    try:
        ts = float(pkt.sniff_timestamp)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


# ─── Scapy Backend ────────────────────────────────────────────────

def _parse_with_scapy(
    pcap_path: str,
    session: SessionData,
    progress_callback=None,
    cancel_check=None,
) -> int:
    """Parse PCAP using Scapy.

    Returns the number of messages successfully parsed.
    """
    from scapy.all import Ether, PcapReader, Raw, TCP, UDP

    count = 0
    try:
        reader = PcapReader(pcap_path)
    except Exception as e:
        logger.error("Scapy failed to read %s: %s", pcap_path, e)
        return 0

    total_size = Path(pcap_path).stat().st_size
    file_handle = getattr(reader, "f", None)

    for pkt in reader:
        try:
            if cancel_check and cancel_check():
                reader.close()
                raise ParseCancelled("Parsing was cancelled")
            ts = datetime.fromtimestamp(float(pkt.time), tz=timezone.utc)

            # Check for UDP packets (BTP runs over UDP in test setups)
            if UDP in pkt and Raw in pkt:
                raw_data = bytes(pkt[Raw].load)

                # Try NMEA first
                nmea_msg = parse_nmea_sentence(raw_data)
                if nmea_msg:
                    nmea_msg.timestamp = ts
                    session.add_message(nmea_msg)
                    count += 1
                    continue

                # Check BTP port mapping, fall back to PDU messageId.
                dst_port = pkt[UDP].dport
                msg_type = BTP_PORTS.get(dst_port) or _infer_msg_type_from_pdu(raw_data)
                if msg_type:
                    source = "unknown"
                    if Ether in pkt and getattr(pkt[Ether], "src", None):
                        source = str(pkt[Ether].src)
                    elif Dot11 in pkt and getattr(pkt[Dot11], "addr2", None):
                        source = str(pkt[Dot11].addr2)
                    msg = _decode_its_message(
                        msg_type,
                        raw_data,
                        transport="UDP / BTP",
                        source=source,
                        dst_port=dst_port,
                    )
                    if msg:
                        msg.timestamp = ts
                        session.add_message(msg)
                        count += 1

            elif Raw in pkt:
                is_direct_geonet = (
                    (SNAP in pkt and int(pkt[SNAP].code) == GEONETWORKING_ETHERTYPE)
                    or (Ether in pkt and int(pkt[Ether].type) == GEONETWORKING_ETHERTYPE)
                )
                if is_direct_geonet:
                    station_id = "unknown"
                    if Dot11 in pkt and getattr(pkt[Dot11], "addr2", None):
                        station_id = str(pkt[Dot11].addr2)
                    elif Ether in pkt and getattr(pkt[Ether], "src", None):
                        station_id = str(pkt[Ether].src)
                    source = station_id

                    direct_msg = _decode_direct_geonet_payload(
                        bytes(pkt[Raw].load),
                        ts,
                        station_id,
                        source,
                    )
                    if direct_msg:
                        session.add_message(direct_msg)
                        count += 1

            # Check for TCP-based NMEA
            elif TCP in pkt and Raw in pkt:
                raw_data = bytes(pkt[Raw].load)
                nmea_msg = parse_nmea_sentence(raw_data)
                if nmea_msg:
                    nmea_msg.timestamp = ts
                    session.add_message(nmea_msg)
                    count += 1

        except ParseCancelled:
            raise
        except Exception as e:
            logger.debug("Error processing scapy packet: %s", e)
            continue

        if progress_callback and file_handle and total_size > 0:
            try:
                progress_callback(min(1.0, file_handle.tell() / total_size))
            except Exception:
                pass

    reader.close()
    if progress_callback:
        progress_callback(1.0)

    return count


# ─── Public API ───────────────────────────────────────────────────

def parse_pcap(
    pcap_path: str,
    session: Optional[SessionData] = None,
    progress_callback=None,
    cancel_check=None,
) -> SessionData:
    """Parse a PCAP file and return session data.

    Automatically selects pyshark (if TShark available) or scapy backend.

    Args:
        pcap_path: Path to the PCAP file.
        session: Existing SessionData to append to, or None for a new session.

    Returns:
        SessionData with all parsed messages.
    """
    if session is None:
        session = SessionData()

    path = Path(pcap_path)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")
    if not path.suffix.lower() in (".pcap", ".pcapng", ".cap"):
        raise ValueError(f"Unsupported file format: {path.suffix}")

    if _tshark_available():
        logger.info("Using pyshark backend (TShark available)")
        count = _parse_with_pyshark(
            pcap_path,
            session,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    else:
        logger.info("Using scapy backend (TShark not available)")
        count = _parse_with_scapy(
            pcap_path,
            session,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    session.finalize()
    logger.info("Parsed %d messages from %s", count, path.name)
    return session
