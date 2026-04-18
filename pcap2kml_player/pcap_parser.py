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


def _decode_its_message(msg_type: MessageType, payload: bytes) -> Optional[V2xMessage]:
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
    )


# ─── Pyshark Backend ──────────────────────────────────────────────

def _parse_with_pyshark(pcap_path: str, session: SessionData) -> int:
    """Parse PCAP using pyshark (TShark backend).

    Returns the number of messages successfully parsed.
    """
    import pyshark

    count = 0
    try:
        cap = pyshark.FileCapture(
            pcap_path,
            display_filter="btp or nmea or gps",
            use_json=True,
            include_raw=True,
        )
    except Exception as e:
        logger.error("pyshark failed to open %s: %s", pcap_path, e)
        return 0

    for pkt in cap:
        try:
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
                        msg = _decode_its_message(msg_type, payload)
                        if msg:
                            msg.timestamp = _pyshark_timestamp(pkt)
                            session.add_message(msg)
                            count += 1
        except Exception as e:
            logger.debug("Error processing pyshark packet: %s", e)
            continue

    cap.close()
    return count


def _pyshark_timestamp(pkt) -> datetime:
    """Extract timestamp from a pyshark packet."""
    try:
        ts = float(pkt.sniff_timestamp)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


# ─── Scapy Backend ────────────────────────────────────────────────

def _parse_with_scapy(pcap_path: str, session: SessionData) -> int:
    """Parse PCAP using Scapy.

    Returns the number of messages successfully parsed.
    """
    from scapy.all import rdpcap, UDP, TCP, Raw

    count = 0
    try:
        pkts = rdpcap(pcap_path)
    except Exception as e:
        logger.error("Scapy failed to read %s: %s", pcap_path, e)
        return 0

    for pkt in pkts:
        try:
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

                # Check BTP port mapping
                dst_port = pkt[UDP].dport
                msg_type = BTP_PORTS.get(dst_port)
                if msg_type:
                    msg = _decode_its_message(msg_type, raw_data)
                    if msg:
                        msg.timestamp = ts
                        session.add_message(msg)
                        count += 1

            # Check for TCP-based NMEA
            elif TCP in pkt and Raw in pkt:
                raw_data = bytes(pkt[Raw].load)
                nmea_msg = parse_nmea_sentence(raw_data)
                if nmea_msg:
                    nmea_msg.timestamp = ts
                    session.add_message(nmea_msg)
                    count += 1

        except Exception as e:
            logger.debug("Error processing scapy packet: %s", e)
            continue

    return count


# ─── Public API ───────────────────────────────────────────────────

def parse_pcap(pcap_path: str, session: Optional[SessionData] = None) -> SessionData:
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
        count = _parse_with_pyshark(pcap_path, session)
    else:
        logger.info("Using scapy backend (TShark not available)")
        count = _parse_with_scapy(pcap_path, session)

    session.finalize()
    logger.info("Parsed %d messages from %s", count, path.name)
    return session