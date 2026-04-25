"""PCAP parser with dual backend: pyshark (preferred) or scapy (fallback).

Extracts V2X ITS messages (CAM, DENM, SREM, SSEM, MAPEM, SPATEM) and
NMEA sentences from PCAP files.
"""

from __future__ import annotations

import logging
import shutil
from math import cos, hypot, radians
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from collections import Counter

from scapy.layers.dot11 import Dot11
from scapy.layers.l2 import SNAP

from .data_model import (
    MessageSource,
    MessageType,
    SessionData,
    V2xMessage,
    infer_capture_role,
)
from .nmea_parser import parse_nmea_sentence
from .protocol_constants import ITS_PDU_MESSAGE_ID

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
from .protocol_constants import ITS_PDU_MESSAGE_ID

# Re-export for backward compatibility of direct pcap_parser imports


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
        "ASN.1-Dekodierung": "erfolgreich"
        if decoded_ok
        else "nicht verfuegbar - Rohdetails aktiv",
    }
    return details


def _extract_geonet_lpv(
    raw_data: bytes, btp_offset: int
) -> Optional[dict[str, float | str]]:
    """Extract position-vector fields from a GeoNetworking long position vector."""
    gn_src_offset = btp_offset - 24
    lat_offset = btp_offset - 16
    lon_offset = btp_offset - 12
    speed_offset = btp_offset - 8
    heading_offset = btp_offset - 6
    if gn_src_offset < 0 or heading_offset + 2 > len(raw_data):
        return None

    lat = (
        int.from_bytes(raw_data[lat_offset : lat_offset + 4], "big", signed=True) / 1e7
    )
    lon = (
        int.from_bytes(raw_data[lon_offset : lon_offset + 4], "big", signed=True) / 1e7
    )
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    speed_field = int.from_bytes(raw_data[speed_offset : speed_offset + 2], "big")
    heading_field = int.from_bytes(raw_data[heading_offset : heading_offset + 2], "big")
    return {
        "station_id": raw_data[gn_src_offset : gn_src_offset + 8].hex(":"),
        "latitude": lat,
        "longitude": lon,
        "speed": float(speed_field & 0x7FFF) / 100.0,
        "heading": float(heading_field) / 10.0,
    }


def _partial_cam_decode(payload: bytes) -> Optional[dict[str, int]]:
    """Extract stable CAM header fields even when full ASN.1 decoding fails."""
    if len(payload) < 8 or payload[0] != 0x02 or payload[1] != 0x02:
        return None
    return {
        "stationId": int.from_bytes(payload[2:6], "big"),
        "generationDeltaTime": int.from_bytes(payload[6:8], "big"),
    }


def _raw_decode_hint(msg_type: MessageType, payload: bytes) -> Optional[str]:
    """Return a more specific fallback hint for known undecoded payload shapes."""
    if msg_type != MessageType.CAM or len(payload) < 2:
        return None

    if payload[0] == 0x02 and payload[1] == 0x02:
        return "CAM-PDU erkannt - Nutzlast unvollstaendig oder abweichend codiert"
    return None


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
        dst_port = int.from_bytes(raw_data[offset : offset + 2], "big")
        msg_type = BTP_PORTS.get(dst_port)
        if msg_type is None:
            # Fallback: BTP port unknown — look at the ITS PDU header messageId
            # one byte ahead of the BTP payload start (offset+4, then +1).
            btp_start = offset + 4
            if btp_start + 2 < len(raw_data):
                fallback_type = _infer_msg_type_from_pdu(
                    raw_data[btp_start : btp_start + 2]
                )
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

        lpv = _extract_geonet_lpv(raw_data, offset)
        if lpv is None:
            continue
        lat = float(lpv["latitude"])
        lon = float(lpv["longitude"])

        payload = raw_data[btp_payload_offset:]
        gn_source_addr = str(lpv["station_id"])

        decoded = _decode_its_message(
            msg_type,
            payload,
            transport="GeoNetworking direkt",
            source=source,
            dst_port=dst_port,
            fallback_position=(lat, lon),
            fallback_station_id=station_id,
            fallback_speed=float(lpv["speed"]),
            fallback_heading=float(lpv["heading"]),
        )
        if decoded:
            decoded.timestamp = timestamp
            if decoded.station_id == "unknown":
                decoded.station_id = station_id
            if gn_source_addr:
                decoded.details["GN-Quelladresse"] = gn_source_addr
            return decoded

        from .security_parser import parse_security_header

        security_info = parse_security_header(payload)
        details = _default_details(
            msg_type,
            payload,
            "GeoNetworking direkt",
            source,
            dst_port,
            False,
        )
        decode_hint = _raw_decode_hint(msg_type, payload)
        if decode_hint is not None:
            details["ASN.1-Dekodierung"] = decode_hint
        if security_info is not None and security_info.security_profile is not None:
            details["Sicherheitsprofil"] = security_info.security_profile

        return V2xMessage(
            timestamp=timestamp,
            station_id=station_id,
            msg_type=msg_type,
            latitude=lat,
            longitude=lon,
            speed=float(lpv["speed"]),
            heading=float(lpv["heading"]),
            raw_payload=payload,
            details=details,
            security_info=security_info,
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
        station_id = str(header.get("stationID", header.get("stationId", "unknown")))

        # Try to find any position reference
        ref_pos = decoded.get("referencePosition", None)
        if ref_pos is None:
            # Search nested structures
            for key, val in decoded.items():
                if isinstance(val, dict) and any(
                    field in val for field in ("latitude", "lat", "longitude", "long")
                ):
                    ref_pos = val
                    break
        if ref_pos is None and msg_type == MessageType.MAPEM:
            intersections = _safe_get(decoded, "map", "intersections", default=[])
            if isinstance(intersections, list) and intersections:
                ref_pos = intersections[0].get("refPoint")

        if ref_pos is None:
            return None

        lat_raw = ref_pos.get("latitude", ref_pos.get("lat", 0))
        lon_raw = ref_pos.get("longitude", ref_pos.get("lon", ref_pos.get("long", 0)))
        lat = int(lat_raw) / 1e7
        lon = int(lon_raw) / 1e7
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
        elif (
            isinstance(cur, (list, tuple))
            and isinstance(key, int)
            and 0 <= key < len(cur)
        ):
            cur = cur[key]
        else:
            return default
    return cur if cur != {} else default


def _coerce_int(value: object) -> Optional[int]:
    """Best-effort integer normalization for nested decoded fields."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("id", "lane", "value", "timeStamp"):
            coerced = _coerce_int(value.get(key))
            if coerced is not None:
                return coerced
    if isinstance(value, tuple) and len(value) == 2:
        return _coerce_int(value[1])
    return None


def _coerce_lane_id(value: object) -> Optional[int]:
    """Normalize lane/approach choice structures to their numeric id."""
    return _coerce_int(value)


def _normalize_geo_point(point: object) -> Optional[dict[str, float]]:
    """Normalize ASN.1 coordinate dicts to {'lat', 'lon'} in decimal degrees."""
    if not isinstance(point, dict):
        return None
    lat = point.get("lat", point.get("latitude"))
    lon = point.get("lon", point.get("longitude", point.get("long")))
    if lat is None or lon is None:
        return None
    try:
        lat_num = float(lat)
        lon_num = float(lon)
    except (TypeError, ValueError):
        return None
    if abs(lat_num) > 90 or abs(lon_num) > 180:
        lat_num /= 1e7
        lon_num /= 1e7
    return {"lat": lat_num, "lon": lon_num}


def _delta_to_geo(
    lat: float,
    lon: float,
    delta_x_cm: int,
    delta_y_cm: int,
) -> tuple[float, float]:
    """Approximate ISO 19091 local XY deltas as absolute WGS84 points."""
    meters_east = delta_x_cm / 100.0
    meters_north = delta_y_cm / 100.0
    lat += meters_north / 111_320.0
    lon += meters_east / max(1e-6, 111_320.0 * cos(radians(lat)))
    return (lat, lon)


def _normalize_node_list(
    node_list: object, ref_point: Optional[dict[str, float]]
) -> Optional[dict]:
    """Convert ASN.1 MAP nodeList variants to a normalized {'nodes': [...]} shape."""
    if ref_point is None:
        return None

    nodes = None
    if isinstance(node_list, tuple) and len(node_list) == 2:
        _, nodes = node_list
    elif isinstance(node_list, dict):
        nodes = node_list.get("nodes", node_list.get("nodeSetXY"))
    elif isinstance(node_list, list):
        nodes = node_list
    if not isinstance(nodes, list):
        return None

    current_lat = ref_point["lat"]
    current_lon = ref_point["lon"]
    normalized_nodes: list[dict[str, float]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        point = _normalize_geo_point(node)
        if point is not None:
            current_lat = point["lat"]
            current_lon = point["lon"]
            normalized_nodes.append(point)
            continue

        delta = node.get("delta")
        if isinstance(delta, tuple) and len(delta) == 2 and isinstance(delta[1], dict):
            delta = delta[1]
        if not isinstance(delta, dict):
            continue
        try:
            delta_x = int(delta.get("x", 0))
            delta_y = int(delta.get("y", 0))
        except (TypeError, ValueError):
            continue
        current_lat, current_lon = _delta_to_geo(
            current_lat, current_lon, delta_x, delta_y
        )
        normalized_nodes.append({"lat": current_lat, "lon": current_lon})

    return {"nodes": normalized_nodes} if normalized_nodes else None


def _lane_role(lane: dict) -> Optional[str]:
    """Classify a normalized MAP lane into a simple directional role."""
    if lane.get("ingressApproach") is not None:
        return "inbound"
    if lane.get("egressApproach") is not None:
        return "outbound"
    return None


def _normalize_map_connection(connection: object) -> Optional[dict]:
    """Normalize one MAP connectsTo entry to a compact app-friendly shape."""
    if not isinstance(connection, dict):
        return None
    normalized = dict(connection)
    connection_id = _coerce_int(
        connection.get("connectionID", connection.get("connectionId"))
    )
    if connection_id is not None:
        normalized["connectionId"] = connection_id

    target_lane = _coerce_int(_safe_get(connection, "connectingLane", "lane"))
    if target_lane is not None:
        normalized["targetLaneId"] = target_lane

    signal_group = _coerce_int(connection.get("signalGroup"))
    if signal_group is not None:
        normalized["signalGroup"] = signal_group
    return normalized


def _perpendicular_stopline(
    anchor: tuple[float, float],
    neighbor: tuple[float, float],
    width_m: float,
) -> Optional[list[dict[str, float]]]:
    """Build a short stopline perpendicular to a lane centerline."""
    lat_scale = 111_320.0
    lon_scale = max(1e-6, 111_320.0 * cos(radians(anchor[0])))
    dx = (neighbor[1] - anchor[1]) * lon_scale
    dy = (neighbor[0] - anchor[0]) * lat_scale
    length = hypot(dx, dy)
    if length < 0.1:
        return None

    half_width = max(2.0, width_m / 2.0)
    perp_x = -dy / length
    perp_y = dx / length

    point_a = {
        "lat": anchor[0] + ((perp_y * half_width) / lat_scale),
        "lon": anchor[1] + ((perp_x * half_width) / lon_scale),
    }
    point_b = {
        "lat": anchor[0] - ((perp_y * half_width) / lat_scale),
        "lon": anchor[1] - ((perp_x * half_width) / lon_scale),
    }
    return [point_a, point_b]


def _derive_stopline(
    lane: dict,
    ref_point: Optional[dict[str, float]],
    default_lane_width_cm: Optional[int],
) -> Optional[dict]:
    """Derive a simple stopline near the intersection-facing end of an inbound lane."""
    if _lane_role(lane) != "inbound":
        return None
    node_list = lane.get("nodeList")
    if not isinstance(node_list, dict):
        return None
    nodes = node_list.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        return None

    points = [
        _normalize_geo_point(node) if isinstance(node, dict) else None for node in nodes
    ]
    points = [point for point in points if point is not None]
    if len(points) < 2:
        return None

    intersection_anchor = points[0]
    direction_neighbor = points[1]
    if ref_point is not None:
        start_distance = hypot(
            (points[0]["lat"] - ref_point["lat"]) * 111_320.0,
            (points[0]["lon"] - ref_point["lon"])
            * max(1e-6, 111_320.0 * cos(radians(ref_point["lat"]))),
        )
        end_distance = hypot(
            (points[-1]["lat"] - ref_point["lat"]) * 111_320.0,
            (points[-1]["lon"] - ref_point["lon"])
            * max(1e-6, 111_320.0 * cos(radians(ref_point["lat"]))),
        )
        if end_distance < start_distance:
            intersection_anchor = points[-1]
            direction_neighbor = points[-2]

    width_cm = _coerce_int(lane.get("laneWidth"))
    if width_cm is None:
        width_cm = default_lane_width_cm
    width_m = (width_cm / 100.0) if width_cm is not None else 3.0
    stopline_points = _perpendicular_stopline(
        (intersection_anchor["lat"], intersection_anchor["lon"]),
        (direction_neighbor["lat"], direction_neighbor["lon"]),
        width_m=width_m,
    )
    if stopline_points is None:
        return None

    return {
        "source": "derived",
        "points": stopline_points,
    }


def _normalize_map_intersection(intersection: dict) -> dict:
    """Normalize decoded MAP intersection fields to the app's expected shape."""
    normalized = dict(intersection)
    normalized["intersectionId"] = _safe_get(intersection, "id", "id")
    ref_point = _normalize_geo_point(intersection.get("refPoint"))
    if ref_point is not None:
        normalized["refPoint"] = ref_point

    lane_set = intersection.get("laneSet")
    if isinstance(lane_set, list):
        normalized_lanes = []
        default_lane_width_cm = _coerce_int(intersection.get("laneWidth"))
        for lane in lane_set:
            if not isinstance(lane, dict):
                continue
            normalized_lane = dict(lane)
            normalized_node_list = _normalize_node_list(lane.get("nodeList"), ref_point)
            if normalized_node_list is not None:
                normalized_lane["nodeList"] = normalized_node_list
            lane_id = _coerce_int(
                lane.get("laneID", lane.get("laneId", lane.get("id")))
            )
            if lane_id is not None:
                normalized_lane["laneId"] = lane_id
            role = _lane_role(lane)
            if role is not None:
                normalized_lane["laneRole"] = role
            connects_to = lane.get("connectsTo", lane.get("connectsto"))
            if isinstance(connects_to, dict):
                connects_to = connects_to.get(
                    "connections", connects_to.get("connectsTo")
                )
            if isinstance(connects_to, list):
                normalized_connections = [
                    normalized_connection
                    for normalized_connection in (
                        _normalize_map_connection(connection)
                        for connection in connects_to
                    )
                    if normalized_connection is not None
                ]
                if normalized_connections:
                    normalized_lane["connections"] = normalized_connections
                    normalized_lane["connectsTo"] = normalized_connections
            stopline = _derive_stopline(
                normalized_lane, ref_point, default_lane_width_cm
            )
            if stopline is not None:
                normalized_lane["stopLine"] = stopline
            normalized_lanes.append(normalized_lane)
        normalized["laneSet"] = normalized_lanes
    return normalized


def _normalize_spat_intersection(intersection: dict) -> dict:
    """Normalize decoded SPAT intersection fields to the app's expected shape."""
    normalized = dict(intersection)
    normalized["intersectionId"] = _safe_get(intersection, "id", "id")
    states = intersection.get("states")
    if isinstance(states, list):
        normalized_states = []
        for state in states:
            if not isinstance(state, dict):
                continue
            normalized_state = dict(state)
            if (
                "stateTimeSpeed" not in normalized_state
                and "state-time-speed" in normalized_state
            ):
                normalized_state["stateTimeSpeed"] = normalized_state[
                    "state-time-speed"
                ]
            normalized_states.append(normalized_state)
        normalized["states"] = normalized_states
    return normalized


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
    for key in (
        "driveDirection",
        "vehicleLength",
        "vehicleWidth",
        "longitudinalAcceleration",
        "curvature",
        "yawRate",
        "exteriorLights",
    ):
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
    for key in (
        "detectionTime",
        "referenceTime",
        "validityDuration",
        "stationType",
        "relevanceDistance",
        "relevanceTrafficDirection",
    ):
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
        normalized_intersections = [
            _normalize_map_intersection(intersection)
            for intersection in intersections
            if isinstance(intersection, dict)
        ]
        first = normalized_intersections[0]
        iid = _safe_get(first, "id", "id")
        if iid is not None:
            fields["intersectionId"] = iid
        rev = first.get("revision") if isinstance(first, dict) else None
        if rev is not None:
            fields["revision"] = rev
        lanes = first.get("laneSet", []) if isinstance(first, dict) else []
        fields["laneCount"] = len(lanes)
        fields["intersectionCount"] = len(normalized_intersections)
        speed_limits = first.get("speedLimits") if isinstance(first, dict) else None
        if speed_limits:
            fields["speedLimits"] = speed_limits
        fields["intersections"] = normalized_intersections
    return fields


def _extra_fields_spatem(decoded: dict) -> dict:
    """SPATEM extension: intersectionId, signal group count, timestamp, moy."""
    body = decoded.get("spat", decoded)
    fields: dict = {}
    intersections = body.get("intersections", []) if isinstance(body, dict) else []
    if intersections:
        normalized_intersections = [
            _normalize_spat_intersection(intersection)
            for intersection in intersections
            if isinstance(intersection, dict)
        ]
        first = normalized_intersections[0]
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
        fields["intersections"] = normalized_intersections
    return fields


def _extra_fields_srem(decoded: dict) -> dict:
    """SREM extension: requestId, sequenceNumber, importanceLevel, lanes, ETA."""
    body = decoded.get("srm", decoded)
    fields: dict = {}
    if not isinstance(body, dict):
        return fields
    sequence_number = _coerce_int(body.get("sequenceNumber"))
    if sequence_number is not None:
        fields["sequenceNumber"] = sequence_number
    timestamp = _coerce_int(body.get("timeStamp"))
    if timestamp is not None:
        fields["timeStamp"] = timestamp
    second = _coerce_int(body.get("second"))
    if second is not None:
        fields["second"] = second
    requests = body.get("requests", [])
    if requests and isinstance(requests[0], dict):
        req = requests[0].get("request", requests[0])
        if isinstance(req, dict):
            fields["requestId"] = _coerce_int(req.get("requestID"))
            if fields.get("sequenceNumber") is None:
                request_sequence_number = _coerce_int(req.get("sequenceNumber"))
                if request_sequence_number is not None:
                    fields["sequenceNumber"] = request_sequence_number
        in_bound = req.get("inBoundLane") if isinstance(req, dict) else None
        in_lane = _coerce_lane_id(in_bound)
        if in_lane is not None:
            fields["inLane"] = in_lane
            fields["inLaneRef"] = str(in_bound)
        out_bound = req.get("outBoundLane") if isinstance(req, dict) else None
        out_lane = _coerce_lane_id(out_bound)
        if out_lane is not None:
            fields["outLane"] = out_lane
            fields["outLaneRef"] = str(out_bound)
        eta = _safe_get(req, "expectedTimeOfArrival")
        if eta:
            fields["eta"] = eta
        intersection_id = (
            _coerce_int(req.get("intersectionID")) if isinstance(req, dict) else None
        )
        if intersection_id is None and isinstance(req, dict):
            intersection_id = _coerce_int(req.get("id"))
        if intersection_id is not None:
            fields["intersectionId"] = intersection_id
    requestor = body.get("requestor")
    if isinstance(requestor, dict):
        fields["requestorType"] = _safe_get(requestor, "type", "role")
        fields["importanceLevel"] = _safe_get(requestor, "type", "importanceLevel")
        requestor_id = _coerce_int(requestor.get("id"))
        if requestor_id is not None:
            fields["requestorStationId"] = requestor_id
        schedule = _coerce_int(requestor.get("transitSchedule"))
        if schedule is not None:
            fields["transitSchedule"] = schedule
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
            fields["requestId"] = _coerce_int(_safe_get(req, "requester", "request"))
            requestor_station_id = _coerce_int(_safe_get(req, "requester", "id"))
            if fields["requestId"] is None:
                fields["requestId"] = requestor_station_id
            else:
                fields["requestorStationId"] = requestor_station_id
            fields["sequenceNumber"] = _coerce_int(
                _safe_get(req, "requester", "sequenceNumber")
            )
            inbound_on = req.get("inboundOn") if isinstance(req, dict) else None
            inbound_lane = _coerce_lane_id(inbound_on)
            if inbound_lane is not None:
                fields["inLane"] = inbound_lane
                fields["inLaneRef"] = str(inbound_on)
            fields["requestState"] = (
                req.get("status") if isinstance(req, dict) else None
            )
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
    fallback_position: Optional[tuple[float, float]] = None,
    fallback_station_id: Optional[str] = None,
    fallback_speed: Optional[float] = None,
    fallback_heading: Optional[float] = None,
) -> Optional[V2xMessage]:
    """Attempt to decode an ITS message using ASN.1 schemas."""
    try:
        from .asn1_schemas import decode_its_message

        decoded = decode_its_message(msg_type.value, payload)
    except ImportError:
        logger.warning("asn1_schemas not available")
        return None

    if decoded is None:
        if msg_type == MessageType.CAM:
            partial_cam = _partial_cam_decode(payload)
            if partial_cam is not None and fallback_position is not None:
                if fallback_speed is not None:
                    partial_cam["speed"] = fallback_speed
                if fallback_heading is not None:
                    partial_cam["heading"] = fallback_heading
                details = _default_details(
                    msg_type, payload, transport, source, dst_port, False
                )
                details["ASN.1-Dekodierung"] = (
                    "CAM-Header teilweise extrahiert - optionale Container unvollstaendig"
                )
                details["stationId"] = str(partial_cam["stationId"])
                details["generationDeltaTime"] = str(partial_cam["generationDeltaTime"])
                if fallback_speed is not None:
                    details["LPV-Geschwindigkeit"] = f"{fallback_speed:.2f} m/s"
                if fallback_heading is not None:
                    details["LPV-Heading"] = f"{fallback_heading:.1f} deg"
                details["Fallback-Quelle"] = "GeoNetworking Long Position Vector"
                return V2xMessage(
                    timestamp=datetime.now(tz=timezone.utc),
                    station_id=str(partial_cam["stationId"]),
                    msg_type=msg_type,
                    latitude=fallback_position[0],
                    longitude=fallback_position[1],
                    speed=fallback_speed,
                    heading=fallback_heading,
                    raw_payload=payload,
                    details=details,
                    decoded_data=partial_cam,
                )
        return None

    extractor = _EXTRACTORS.get(msg_type, _extract_generic_position)
    result = (
        extractor(decoded, msg_type)
        if extractor == _extract_generic_position
        else extractor(decoded)
    )

    if result is None:
        if fallback_position is None:
            return None
        lat, lon = fallback_position
        alt = None
        speed = None
        heading = None
        station_id = fallback_station_id or "unknown"
    else:
        lat, lon, alt, speed, heading, station_id = result
        if (
            _is_null_island_position(lat, lon)
            and fallback_position is not None
            and msg_type != MessageType.DENM
        ):
            lat, lon = fallback_position
            details_position_source = "GeoNetworking Long Position Vector (0/0 ersetzt)"
        else:
            details_position_source = None
        if station_id == "unknown" and fallback_station_id is not None:
            station_id = fallback_station_id
        if speed is None:
            speed = fallback_speed
        if heading is None:
            heading = fallback_heading

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
    if "details_position_source" in locals() and details_position_source is not None:
        details["Positions-Fallback"] = details_position_source

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


def _is_null_island_position(lat: float, lon: float) -> bool:
    """Return whether a decoded position is the common unavailable 0/0 sentinel."""
    return abs(lat) < 1e-9 and abs(lon) < 1e-9


def _annotate_cam_identity_outliers(session: SessionData) -> None:
    """Mark one-off CAM station-id outliers without silently rewriting them."""
    station_counts = Counter(
        msg.station_id
        for msg in session.messages
        if msg.msg_type == MessageType.CAM and msg.station_id != "unknown"
    )
    if len(station_counts) < 2:
        return

    dominant_station_id, dominant_count = station_counts.most_common(1)[0]
    total = sum(station_counts.values())
    if dominant_count < 3 or (dominant_count / total) < 0.8:
        return

    for msg in session.messages:
        if msg.msg_type != MessageType.CAM or msg.station_id == dominant_station_id:
            continue
        observed_count = station_counts.get(msg.station_id, 0)
        if observed_count != 1:
            continue
        msg.details["Identitaets-Hinweis"] = (
            f"Einzelne CAM-Station-ID {msg.station_id} weicht von dominanter "
            f"Session-ID {dominant_station_id} ab; keine automatische Korrektur"
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
                            source=str(
                                getattr(pkt, "eth", getattr(pkt, "wlan", "unknown"))
                            ),
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
                    SNAP in pkt and int(pkt[SNAP].code) == GEONETWORKING_ETHERTYPE
                ) or (Ether in pkt and int(pkt[Ether].type) == GEONETWORKING_ETHERTYPE)
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
    start_index = len(session.messages)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")
    if not path.suffix.lower() in (".pcap", ".pcapng", ".cap"):
        raise ValueError(f"Unsupported file format: {path.suffix}")

    if _tshark_available():
        logger.info("Using pyshark backend (TShark available)")
        parser_backend = "pyshark"
        count = _parse_with_pyshark(
            pcap_path,
            session,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    else:
        logger.info("Using scapy backend (TShark not available)")
        parser_backend = "scapy"
        count = _parse_with_scapy(
            pcap_path,
            session,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    role = infer_capture_role(str(path))
    source = session.register_source(
        str(path), role, len(session.messages) - start_index
    )
    for packet_index, msg in enumerate(session.messages[start_index:], start=1):
        msg.source = MessageSource(
            path=source.path,
            filename=source.filename,
            source_index=source.source_index,
            role=source.role,
            parser_backend=parser_backend,
            packet_index=packet_index,
        )
        msg.details.setdefault("Capture-Datei", source.filename)
        msg.details.setdefault("Capture-Rolle", source.role.value.upper())

    _annotate_cam_identity_outliers(session)
    session.finalize()
    logger.info("Parsed %d messages from %s", count, path.name)
    return session
