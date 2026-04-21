"""Interactive Leaflet.js map widget embedded in QWebEngineView.

Displays V2X entity markers, trajectories, and supports synchronized
playback highlighting via JavaScript calls.
"""

from __future__ import annotations

import json
import logging
from math import cos, hypot, radians
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .data_model import MessageType, V2xMessage
from .scene_model import build_scene_snapshot

logger = logging.getLogger(__name__)
PLAYBACK_TRAIL_POINTS = 8
DISPLAY_CLUSTER_RADIUS_M = 5000.0

# Color palette for station markers (hex strings for Leaflet)
STATION_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
]

INFRASTRUCTURE_MESSAGE_COLORS = {
    MessageType.MAPEM: "#1f9d55",
    MessageType.SPATEM: "#c026d3",
}
NON_STATION_MARKER_TYPES = {
    MessageType.MAPEM,
    MessageType.SPATEM,
    MessageType.SSEM,
}
SHOW_INFRASTRUCTURE_POINT_OVERLAYS = False
LANE_ROLE_COLORS = {
    "inbound": "#0f766e",
    "outbound": "#2563eb",
}
STOPLINE_COLOR = "#f97316"
REQUEST_STATUS_COLORS = {
    "pending": "#2563eb",
    "acknowledged": "#eab308",
    "granted": "#16a34a",
    "rejected": "#dc2626",
    "timeout": "#7f1d1d",
}
INFRASTRUCTURE_MESSAGE_OFFSETS = {
    MessageType.MAPEM: (0.0, 0.00003),
    MessageType.SPATEM: (0.0, -0.00003),
}
SPAT_PHASE_COLORS = {
    "protected-Movement-Allowed": "#16a34a",
    "permissive-Movement-Allowed": "#65a30d",
    "protected-clearance": "#f59e0b",
    "permissive-clearance": "#facc15",
    "stop-And-Remain": "#dc2626",
    "stop-Then-Proceed": "#ea580c",
    "pre-Movement": "#2563eb",
    "caution-Conflicting-Traffic": "#fb7185",
    "dark": "#475569",
    "unavailable": "#64748b",
}


def _marker_id_for_message(msg: V2xMessage) -> str:
    """Return a stable marker id, preserving MAP/SPAT overlays separately."""
    if msg.msg_type in INFRASTRUCTURE_MESSAGE_COLORS:
        return f"infrastructure_{msg.msg_type.value}_{msg.station_id}"
    return f"station_{msg.station_id}"


def _marker_position_for_message(msg: V2xMessage) -> tuple[float, float]:
    """Slightly offset infrastructure markers so MAP/SPAT stay visible together."""
    lat_offset, lon_offset = INFRASTRUCTURE_MESSAGE_OFFSETS.get(msg.msg_type, (0.0, 0.0))
    return (msg.latitude + lat_offset, msg.longitude + lon_offset)


def _has_display_position(msg: V2xMessage) -> bool:
    """Return whether a message has a useful map position."""
    if not (-90 <= msg.latitude <= 90 and -180 <= msg.longitude <= 180):
        return False
    if abs(msg.latitude) < 1e-9 and abs(msg.longitude) < 1e-9:
        return False
    return True


def _coerce_lat_lon(value: object) -> Optional[tuple[float, float]]:
    """Normalize mixed ASN.1 coordinate shapes to decimal degrees."""
    if not isinstance(value, dict):
        return None
    lat = value.get("lat", value.get("latitude"))
    lon = value.get("lon", value.get("longitude"))
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
    return (lat_num, lon_num)


def _extract_map_polyline_points(intersection: dict) -> list[list[tuple[float, float]]]:
    """Best-effort extraction of lane centerline points from MAPEM laneSet data."""
    polylines: list[list[tuple[float, float]]] = []
    lane_set = intersection.get("laneSet")
    if not isinstance(lane_set, list):
        return polylines

    for lane in lane_set:
        if not isinstance(lane, dict):
            continue
        node_list = lane.get("nodeList", lane.get("node-list"))
        if isinstance(node_list, dict):
            nodes = node_list.get("nodes", node_list.get("nodeSetXY"))
        else:
            nodes = node_list
        if not isinstance(nodes, list):
            continue

        points: list[tuple[float, float]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            point = _coerce_lat_lon(node)
            if point is None:
                delta = node.get("delta")
                point = _coerce_lat_lon(delta)
            if point is not None:
                points.append(point)
        if len(points) >= 2:
            polylines.append(points)
    return polylines


def _lane_points(lane: dict) -> list[tuple[float, float]]:
    """Return normalized centerline points for a single MAP lane."""
    node_list = lane.get("nodeList", lane.get("node-list"))
    if isinstance(node_list, dict):
        nodes = node_list.get("nodes", node_list.get("nodeSetXY"))
    else:
        nodes = node_list
    if not isinstance(nodes, list):
        return []

    points: list[tuple[float, float]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        point = _coerce_lat_lon(node)
        if point is None:
            delta = node.get("delta")
            point = _coerce_lat_lon(delta)
        if point is not None:
            points.append(point)
    return points


def _lane_identifier(lane: dict) -> Optional[str]:
    """Return a human-readable lane identifier if one exists."""
    for key in ("laneID", "laneId", "id"):
        value = lane.get(key)
        if value is None:
            continue
        return str(value)
    return None


def _lane_role(lane: dict) -> Optional[str]:
    """Return a normalized lane role label."""
    role = lane.get("laneRole")
    if isinstance(role, str):
        return role
    if lane.get("ingressApproach") is not None:
        return "inbound"
    if lane.get("egressApproach") is not None:
        return "outbound"
    return None


def _coerce_int(value: object) -> Optional[int]:
    """Best-effort integer coercion for decoded MAP/SPAT helper fields."""
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
        for key in ("id", "value", "lane", "signalGroup"):
            nested = _coerce_int(value.get(key))
            if nested is not None:
                return nested
    return None


def _intersection_point(intersection: dict, msg: V2xMessage) -> tuple[float, float]:
    """Return the best available map point for one infrastructure intersection."""
    for key in ("refPoint", "referencePoint", "refPos", "referencePosition"):
        point = _coerce_lat_lon(intersection.get(key))
        if point is not None:
            return point
    return (msg.latitude, msg.longitude)


def _intersection_key(intersection: dict, msg: V2xMessage) -> str:
    """Build a stable cross-message key for MAP/SPAT joins."""
    for key in ("intersectionId", "id"):
        value = intersection.get(key)
        numeric = _coerce_int(value)
        if numeric is not None:
            return f"id:{numeric}"
    point = _intersection_point(intersection, msg)
    return f"pos:{round(point[0], 4):.4f}:{round(point[1], 4):.4f}"


def _iter_message_intersections(msg: V2xMessage) -> list[dict]:
    """Return decoded intersections or a raw fallback for infrastructure messages."""
    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list) and intersections:
        return [intersection for intersection in intersections if isinstance(intersection, dict)]
    return [{}]


def _polyline_label_point(points: list[tuple[float, float]]) -> Optional[tuple[float, float]]:
    """Place a label near the middle of a lane polyline."""
    if not points:
        return None
    return points[len(points) // 2]


def _point_distance_meters(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Approximate local distance in meters between two nearby points."""
    lat_scale = 111_320.0
    lon_scale = max(1e-6, 111_320.0 * cos(radians((point_a[0] + point_b[0]) / 2.0)))
    dx = (point_a[1] - point_b[1]) * lon_scale
    dy = (point_a[0] - point_b[0]) * lat_scale
    return hypot(dx, dy)


def _display_anchor_points(messages: list[V2xMessage]) -> list[tuple[float, float]]:
    """Return stable infrastructure points used to reject far-away display outliers."""
    anchors: list[tuple[float, float]] = []
    for msg in messages:
        if msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS or not _has_display_position(msg):
            continue
        for intersection in _iter_message_intersections(msg):
            anchors.append(_intersection_point(intersection, msg))
    return anchors


def _is_near_display_anchors(
    msg: V2xMessage,
    anchors: list[tuple[float, float]],
    radius_m: float = DISPLAY_CLUSTER_RADIUS_M,
) -> bool:
    """Keep local V2X points near the loaded infrastructure cluster."""
    if not anchors or msg.msg_type in INFRASTRUCTURE_MESSAGE_COLORS:
        return True
    point = (msg.latitude, msg.longitude)
    return any(_point_distance_meters(point, anchor) <= radius_m for anchor in anchors)


def _lane_anchor_points(
    lane: dict,
    intersection_point: tuple[float, float],
) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
    """Return (intersection-facing point, outer point) for one lane."""
    points = _lane_points(lane)
    if len(points) < 2:
        return None

    start_distance = _point_distance_meters(points[0], intersection_point)
    end_distance = _point_distance_meters(points[-1], intersection_point)
    if start_distance <= end_distance:
        return (points[0], points[-1])
    return (points[-1], points[0])


def _connection_curve_points(
    source_lane: dict,
    target_lane: dict,
    intersection_point: tuple[float, float],
) -> Optional[list[tuple[float, float]]]:
    """Build a simple schematic curve between inbound and outbound lanes."""
    source_anchors = _lane_anchor_points(source_lane, intersection_point)
    target_anchors = _lane_anchor_points(target_lane, intersection_point)
    if source_anchors is None or target_anchors is None:
        return None

    source_inner, _ = source_anchors
    target_inner, _ = target_anchors
    control_point = (
        (source_inner[0] + target_inner[0] + intersection_point[0]) / 3.0,
        (source_inner[1] + target_inner[1] + intersection_point[1]) / 3.0,
    )
    return [source_inner, control_point, target_inner]


def _lane_popup_text(lane: dict, role: Optional[str]) -> str:
    """Build a compact popup for a MAP lane."""
    parts = ["MAPEM Lane"]
    lane_id = _lane_identifier(lane)
    if lane_id:
        parts.append(f"Lane {lane_id}")
    if role:
        parts.append(role)
    return " | ".join(parts)


def _stopline_points(lane: dict) -> Optional[list[tuple[float, float]]]:
    """Extract normalized stopline points from a normalized lane."""
    stop_line = lane.get("stopLine")
    if not isinstance(stop_line, dict):
        return None
    points = stop_line.get("points")
    if not isinstance(points, list):
        return None
    normalized_points: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        lat_lon = _coerce_lat_lon(point)
        if lat_lon is not None:
            normalized_points.append(lat_lon)
    return normalized_points if len(normalized_points) >= 2 else None


def _request_overlay_style(status: str, is_dominant: bool) -> dict[str, object]:
    """Return line style parameters for one request overlay."""
    return {
        "color": REQUEST_STATUS_COLORS.get(status, "#2563eb"),
        "weight": 6 if is_dominant else 4,
        "opacity": 0.95 if is_dominant else 0.65,
        "dashArray": "" if is_dominant else "6 6",
    }


def _request_overlay_offset_m(display_rank: int) -> float:
    """Spread overlapping request overlays sideways by display rank."""
    if display_rank <= 0:
        return 0.0
    step = ((display_rank + 1) // 2) * 2.5
    return step if display_rank % 2 == 1 else -step


def _offset_polyline(coords: list[tuple[float, float]], offset_m: float) -> list[tuple[float, float]]:
    """Shift a short polyline sideways to avoid complete overlap."""
    if abs(offset_m) < 0.01 or len(coords) < 2:
        return coords

    shifted: list[tuple[float, float]] = []
    for index, point in enumerate(coords):
        prev_point = coords[index - 1] if index > 0 else coords[index]
        next_point = coords[index + 1] if index < len(coords) - 1 else coords[index]
        lat_scale = 111_320.0
        lon_scale = max(1e-6, 111_320.0 * cos(radians(point[0])))
        dx = (next_point[1] - prev_point[1]) * lon_scale
        dy = (next_point[0] - prev_point[0]) * lat_scale
        length = hypot(dx, dy)
        if length < 0.1:
            shifted.append(point)
            continue
        perp_x = -dy / length
        perp_y = dx / length
        shifted.append(
            (
                point[0] + ((perp_y * offset_m) / lat_scale),
                point[1] + ((perp_x * offset_m) / lon_scale),
            )
        )
    return shifted


def _request_popup_parts(request_visual: dict[str, object]) -> list[str]:
    """Build popup parts for a request overlay."""
    parts = ["Priorisierung"]
    parts.append(
        f"{request_visual['request_id']}/{request_visual['sequence_number']}"
    )
    parts.append(str(request_visual["status"]))
    if request_visual.get("station_id"):
        parts.append(f"Station {request_visual['station_id']}")
    if request_visual.get("importance_level") is not None:
        parts.append(f"Prio {request_visual['importance_level']}")
    if request_visual.get("ssem_status"):
        parts.append(f"SSM {request_visual['ssem_status']}")
    return parts


def _spat_intersection_phase(intersection: dict) -> Optional[str]:
    """Extract the currently active SPAT phase from the first signal group."""
    states = intersection.get("states")
    if not isinstance(states, list):
        return None
    for signal_group in states:
        if not isinstance(signal_group, dict):
            continue
        events = signal_group.get("stateTimeSpeed", signal_group.get("state-time-speed"))
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_state = event.get("eventState")
            if isinstance(event_state, str) and event_state:
                return event_state
    return None


def _spat_color_for_intersection(intersection: dict) -> str:
    """Choose a SPAT color that reflects the dominant decoded phase when available."""
    phase = _spat_intersection_phase(intersection)
    if phase is None:
        return INFRASTRUCTURE_MESSAGE_COLORS[MessageType.SPATEM]
    return SPAT_PHASE_COLORS.get(phase, INFRASTRUCTURE_MESSAGE_COLORS[MessageType.SPATEM])


def _spat_states_by_group(intersection: dict) -> dict[int, str]:
    """Extract the current phase per signal group from a SPAT intersection."""
    states_by_group: dict[int, str] = {}
    states = intersection.get("states")
    if not isinstance(states, list):
        return states_by_group
    for signal_group in states:
        if not isinstance(signal_group, dict):
            continue
        signal_group_id = _coerce_int(signal_group.get("signalGroup"))
        if signal_group_id is None:
            continue
        events = signal_group.get("stateTimeSpeed", signal_group.get("state-time-speed"))
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_state = event.get("eventState")
            if isinstance(event_state, str) and event_state:
                states_by_group[signal_group_id] = event_state
                break
    return states_by_group


def _spat_tooltips_by_group(intersection: dict) -> dict[int, str]:
    """Build hover tooltip text with active movement state and timing fields."""
    tooltips: dict[int, str] = {}
    states = intersection.get("states")
    if not isinstance(states, list):
        return tooltips
    for signal_group in states:
        if not isinstance(signal_group, dict):
            continue
        signal_group_id = _coerce_int(signal_group.get("signalGroup"))
        if signal_group_id is None:
            continue
        events = signal_group.get("stateTimeSpeed", signal_group.get("state-time-speed"))
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_state = event.get("eventState")
            if not isinstance(event_state, str) or not event_state:
                continue
            parts = [f"MovementState: {event_state}"]
            timing = event.get("timing")
            if isinstance(timing, dict):
                for key in ("minEndTime", "maxEndTime", "likelyTime", "timeConfidence"):
                    value = timing.get(key)
                    if value is not None:
                        parts.append(f"{key}: {value}")
            tooltips[signal_group_id] = " | ".join(parts)
            break
    return tooltips


def _lane_signal_group_ids(lane: dict) -> list[int]:
    """Extract related SPAT signal groups for one MAP lane."""
    signal_groups: list[int] = []
    direct_group = _coerce_int(lane.get("signalGroup"))
    if direct_group is not None:
        signal_groups.append(direct_group)

    connects_to = lane.get("connectsTo", lane.get("connectsto"))
    if isinstance(connects_to, dict):
        connects_to = connects_to.get("connections", connects_to.get("connectsTo"))
    if isinstance(connects_to, list):
        for connection in connects_to:
            if not isinstance(connection, dict):
                continue
            candidate = _coerce_int(connection.get("signalGroup"))
            if candidate is None:
                candidate = _coerce_int(connection.get("connectingLane"))
            if candidate is not None and candidate not in signal_groups:
                signal_groups.append(candidate)
    return signal_groups


def _intersection_popup(msg: V2xMessage, intersection: Optional[dict], fallback_label: str) -> str:
    """Build a concise popup text for infrastructure overlays."""
    if not isinstance(intersection, dict):
        return fallback_label

    pieces = [msg.msg_type.value]
    for key in ("intersectionId", "id"):
        value = intersection.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if value is not None:
            pieces.append(f"Intersection {value}")
            break

    if msg.msg_type == MessageType.MAPEM:
        lane_set = intersection.get("laneSet")
        if isinstance(lane_set, list):
            pieces.append(f"{len(lane_set)} lanes")
    elif msg.msg_type == MessageType.SPATEM:
        phase = _spat_intersection_phase(intersection)
        if phase:
            pieces.append(phase)
    return " | ".join(pieces)


def _infrastructure_overlays_for_message(msg: V2xMessage) -> list[dict[str, object]]:
    """Create renderable infrastructure overlays for MAPEM and SPATEM messages."""
    overlays: list[dict[str, object]] = []
    base_color = INFRASTRUCTURE_MESSAGE_COLORS.get(msg.msg_type)
    layer = "map" if msg.msg_type == MessageType.MAPEM else "spat"
    if base_color is None:
        return overlays

    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list) and intersections:
        for index, intersection in enumerate(intersections):
            if not isinstance(intersection, dict):
                continue
            point = None
            for key in ("refPoint", "referencePoint", "refPos", "referencePosition"):
                point = _coerce_lat_lon(intersection.get(key))
                if point is not None:
                    break
            if point is None:
                point = (msg.latitude, msg.longitude)

            popup = _intersection_popup(msg, intersection, f"{msg.msg_type.value} Intersection")
            circle_color = (
                _spat_color_for_intersection(intersection)
                if msg.msg_type == MessageType.SPATEM
                else base_color
            )
            overlays.append({
                "kind": "circle",
                "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_circle",
                "lat": point[0],
                "lon": point[1],
                "radius": 20 if msg.msg_type == MessageType.MAPEM else 28,
                "color": circle_color,
                "popup": popup,
                "layer": layer,
            })
            overlays.append({
                "kind": "label",
                "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_label",
                "lat": point[0],
                "lon": point[1],
                "text": popup,
                "color": circle_color,
                "layer": layer,
            })

            if msg.msg_type == MessageType.MAPEM:
                lane_set = intersection.get("laneSet")
                if not isinstance(lane_set, list):
                    lane_set = []
                for polyline_index, lane in enumerate(lane_set):
                    if not isinstance(lane, dict):
                        continue
                    points = _lane_points(lane)
                    if len(points) < 2:
                        continue
                    role = _lane_role(lane)
                    lane_color = LANE_ROLE_COLORS.get(role, base_color)
                    lane_layer = (
                        "map_inbound"
                        if role == "inbound"
                        else "map_outbound"
                        if role == "outbound"
                        else layer
                    )
                    overlays.append({
                        "kind": "polyline",
                        "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}",
                        "coords": [[lat, lon] for lat, lon in points],
                        "color": lane_color,
                        "popup": _lane_popup_text(lane, role),
                        "layer": lane_layer,
                    })
                    lane_id = _lane_identifier(lane)
                    label_point = _polyline_label_point(points)
                    if lane_id and label_point is not None:
                        overlays.append({
                            "kind": "label",
                            "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}_label",
                            "lat": label_point[0],
                            "lon": label_point[1],
                            "text": f"Lane {lane_id}",
                            "color": lane_color,
                            "layer": lane_layer,
                        })
                    stopline_points = _stopline_points(lane)
                    if stopline_points is not None:
                        overlays.append({
                            "kind": "polyline",
                            "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}_stopline",
                            "coords": [[lat, lon] for lat, lon in stopline_points],
                            "color": STOPLINE_COLOR,
                            "popup": f"Stopline | Lane {lane_id}" if lane_id else "Stopline",
                            "layer": "map_stoplines",
                        })
    else:
        raw_popup = f"{msg.msg_type.value} raw infrastructure position"
        overlays.append({
            "kind": "circle",
            "id": f"{msg.msg_type.value}_{msg.station_id}_raw",
            "lat": msg.latitude,
            "lon": msg.longitude,
            "radius": 18 if msg.msg_type == MessageType.MAPEM else 26,
            "color": base_color,
            "popup": raw_popup,
            "layer": layer,
        })
        overlays.append({
            "kind": "label",
            "id": f"{msg.msg_type.value}_{msg.station_id}_raw_label",
            "lat": msg.latitude,
            "lon": msg.longitude,
            "text": f"{msg.msg_type.value} raw",
            "color": base_color,
            "layer": layer,
        })

    return overlays


def _infrastructure_overlays_for_messages(messages: list[V2xMessage]) -> list[dict[str, object]]:
    """Aggregate the latest MAP/SPAT context per intersection into render overlays."""
    if not messages:
        return []

    latest_map: dict[str, tuple[V2xMessage, dict]] = {}
    latest_spat: dict[str, tuple[V2xMessage, dict]] = {}
    scene = build_scene_snapshot(messages, messages[-1].timestamp)
    request_visuals = scene.request_visuals_by_intersection

    for msg in messages:
        if msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS:
            continue
        for intersection in _iter_message_intersections(msg):
            key = _intersection_key(intersection, msg)
            target = latest_map if msg.msg_type == MessageType.MAPEM else latest_spat
            current = target.get(key)
            if current is None or current[0].timestamp <= msg.timestamp:
                target[key] = (msg, intersection)

    overlays: list[dict[str, object]] = []
    for key in sorted(set(latest_map) | set(latest_spat)):
        map_entry = latest_map.get(key)
        spat_entry = latest_spat.get(key)

        if map_entry is not None:
            map_msg, map_intersection = map_entry
            map_point = _intersection_point(map_intersection, map_msg)
            map_popup = _intersection_popup(map_msg, map_intersection, "MAPEM Intersection")
            intersection_numeric_id = _coerce_int(
                map_intersection.get("intersectionId", map_intersection.get("id"))
            )
            intersection_requests = (
                request_visuals.get(intersection_numeric_id, [])
                if intersection_numeric_id is not None
                else []
            )
            if SHOW_INFRASTRUCTURE_POINT_OVERLAYS:
                overlays.append({
                    "kind": "circle",
                    "id": f"{key}_map_circle",
                    "lat": map_point[0],
                    "lon": map_point[1],
                    "radius": 20,
                    "color": INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                    "popup": map_popup,
                    "layer": "map",
                })
                overlays.append({
                    "kind": "label",
                    "id": f"{key}_map_label",
                    "lat": map_point[0],
                    "lon": map_point[1],
                    "text": map_popup,
                    "color": INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                    "layer": "map",
                })

            lane_set = map_intersection.get("laneSet")
            if not isinstance(lane_set, list):
                lane_set = []
            spat_states = _spat_states_by_group(spat_entry[1]) if spat_entry is not None else {}
            spat_tooltips = _spat_tooltips_by_group(spat_entry[1]) if spat_entry is not None else {}
            lane_by_id = {
                _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id")))): lane
                for lane in lane_set
                if isinstance(lane, dict)
            }
            for polyline_index, lane in enumerate(lane_set):
                if not isinstance(lane, dict):
                    continue
                points = _lane_points(lane)
                if len(points) < 2:
                    continue
                lane_id = _lane_identifier(lane)
                role = _lane_role(lane)
                lane_color = LANE_ROLE_COLORS.get(role, INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM])
                lane_layer = (
                    "map_inbound"
                    if role == "inbound"
                    else "map_outbound"
                    if role == "outbound"
                    else "map"
                )
                overlays.append({
                    "kind": "polyline",
                    "id": f"{key}_lane_{polyline_index}",
                    "coords": [[lat, lon] for lat, lon in points],
                    "color": lane_color,
                    "popup": _lane_popup_text(lane, role),
                    "layer": lane_layer,
                })
                label_point = _polyline_label_point(points)
                if label_point is not None:
                    label_parts = []
                    if lane_id:
                        label_parts.append(f"Lane {lane_id}")
                    if role:
                        label_parts.append(role)
                    if label_parts:
                        overlays.append({
                            "kind": "label",
                            "id": f"{key}_lane_{polyline_index}_label",
                            "lat": label_point[0],
                            "lon": label_point[1],
                            "text": " | ".join(label_parts),
                            "color": lane_color,
                            "layer": lane_layer,
                        })
                stopline_points = _stopline_points(lane)
                if stopline_points is not None:
                    overlays.append({
                        "kind": "polyline",
                        "id": f"{key}_lane_{polyline_index}_stopline",
                        "coords": [[lat, lon] for lat, lon in stopline_points],
                        "color": STOPLINE_COLOR,
                        "popup": f"Stopline | Lane {lane_id}" if lane_id else "Stopline",
                        "layer": "map_stoplines",
                    })

                connections = lane.get("connections", lane.get("connectsTo"))
                if not isinstance(connections, list):
                    continue
                for connection in connections:
                    if not isinstance(connection, dict):
                        continue
                    target_lane_id = _coerce_int(connection.get("targetLaneId", connection.get("connectingLane")))
                    if target_lane_id is None:
                        continue
                    target_lane = lane_by_id.get(target_lane_id)
                    if not isinstance(target_lane, dict):
                        continue
                    connection_points = _connection_curve_points(lane, target_lane, map_point)
                    if connection_points is None:
                        continue
                    signal_group = _coerce_int(connection.get("signalGroup"))
                    matched_phase = spat_states.get(signal_group) if signal_group is not None else None
                    connection_color = (
                        SPAT_PHASE_COLORS.get(
                            matched_phase,
                            INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                        )
                        if matched_phase is not None
                        else INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM]
                    )
                    popup_parts = ["MAPEM Connection"]
                    if lane_id:
                        popup_parts.append(f"Lane {lane_id}")
                    popup_parts.append(f"to Lane {target_lane_id}")
                    if signal_group is not None:
                        popup_parts.append(f"SG {signal_group}")
                    if matched_phase:
                        popup_parts.append(matched_phase)
                    tooltip_parts = [
                        "Connection",
                        f"Lane {lane_id or '-'} -> Lane {target_lane_id}",
                    ]
                    if signal_group is not None:
                        tooltip_parts.append(f"Signal Group: {signal_group}")
                    if signal_group is not None and signal_group in spat_tooltips:
                        tooltip_parts.append(spat_tooltips[signal_group])
                    else:
                        tooltip_parts.append("MovementState: nicht verfuegbar")
                    overlays.append({
                        "kind": "polyline",
                        "id": f"{key}_lane_{polyline_index}_connection_{target_lane_id}",
                        "coords": [[lat, lon] for lat, lon in connection_points],
                        "color": connection_color,
                        "popup": " | ".join(popup_parts),
                        "tooltip": " | ".join(tooltip_parts),
                        "layer": "map_connections",
                    })
                    matching_requests = [
                        visual
                        for visual in intersection_requests
                        if visual.in_lane == _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id"))))
                        and visual.out_lane == target_lane_id
                    ]
                    for request_visual in matching_requests:
                        style = _request_overlay_style(request_visual.status.value, request_visual.is_dominant)
                        request_coords = _offset_polyline(
                            connection_points,
                            _request_overlay_offset_m(request_visual.display_rank),
                        )
                        popup_parts = _request_popup_parts(
                            {
                                "request_id": request_visual.request_id,
                                "sequence_number": request_visual.sequence_number,
                                "status": request_visual.status.value,
                                "station_id": request_visual.station_id,
                                "importance_level": request_visual.importance_level,
                                "ssem_status": request_visual.ssem_status,
                            }
                        )
                        overlays.append({
                            "kind": "polyline",
                            "id": (
                                f"{key}_lane_{polyline_index}_connection_{target_lane_id}"
                                f"_request_{request_visual.request_id}_{request_visual.sequence_number}"
                            ),
                            "coords": [[lat, lon] for lat, lon in request_coords],
                            "color": style["color"],
                            "weight": style["weight"],
                            "opacity": style["opacity"],
                            "dashArray": style["dashArray"],
                            "popup": " | ".join(popup_parts),
                            "layer": "map_requests",
                        })

                lane_requests = [
                    visual
                    for visual in intersection_requests
                    if visual.in_lane == _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id"))))
                    or visual.out_lane == _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id"))))
                ]
                for request_visual in lane_requests:
                    style = _request_overlay_style(request_visual.status.value, request_visual.is_dominant)
                    request_coords = _offset_polyline(
                        points,
                        _request_overlay_offset_m(request_visual.display_rank),
                    )
                    lane_popup_parts = _request_popup_parts(
                        {
                            "request_id": request_visual.request_id,
                            "sequence_number": request_visual.sequence_number,
                            "status": request_visual.status.value,
                            "station_id": request_visual.station_id,
                            "importance_level": request_visual.importance_level,
                            "ssem_status": request_visual.ssem_status,
                        }
                    )
                    lane_popup_parts.append(
                        "Inbound-Lane" if request_visual.in_lane == _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id"))))
                        else "Outbound-Lane"
                    )
                    overlays.append({
                        "kind": "polyline",
                        "id": (
                            f"{key}_lane_{polyline_index}_request_"
                            f"{request_visual.request_id}_{request_visual.sequence_number}_"
                            f"{request_visual.status.value}"
                        ),
                        "coords": [[lat, lon] for lat, lon in request_coords],
                        "color": style["color"],
                        "weight": style["weight"],
                        "opacity": style["opacity"],
                        "dashArray": style["dashArray"],
                        "popup": " | ".join(lane_popup_parts),
                        "layer": "map_requests",
                    })

        if spat_entry is not None:
            spat_msg, spat_intersection = spat_entry
            spat_point = _intersection_point(spat_intersection, spat_msg)
            spat_popup = _intersection_popup(spat_msg, spat_intersection, "SPATEM Intersection")
            spat_color = _spat_color_for_intersection(spat_intersection)
            if SHOW_INFRASTRUCTURE_POINT_OVERLAYS:
                overlays.append({
                    "kind": "circle",
                    "id": f"{key}_spat_circle",
                    "lat": spat_point[0],
                    "lon": spat_point[1],
                    "radius": 28,
                    "color": spat_color,
                    "popup": spat_popup,
                    "layer": "spat",
                })
                overlays.append({
                    "kind": "label",
                    "id": f"{key}_spat_label",
                    "lat": spat_point[0],
                    "lon": spat_point[1],
                    "text": spat_popup,
                    "color": spat_color,
                    "layer": "spat",
                })

    return overlays


def _js_escape(value: str) -> str:
    """Escape a Python string for safe embedding in single-quoted JS literals."""
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("`", "\\`")
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace("${", "\\${")
    escaped = escaped.replace("</script>", "<\\/script>")
    escaped = escaped.replace("\r", " ").replace("\n", " ")
    escaped = escaped.replace("\x00", "")
    return escaped

LEAFLET_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PCAP2KML Map</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([48.0, 11.0], 13);
        map.whenReady(function() {
            map.invalidateSize(false);
        });

        // Primary tile layer (OpenStreetMap with proper attribution)
        var osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        });

        // Fallback tile layer (CartoDB — works reliably from embedded browsers)
        var cartoLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            maxZoom: 20
        });

        // Try OSM first; if tiles fail to load, switch to CartoDB
        var activeLayer = osmLayer.addTo(map);
        var tileErrorCount = 0;

        osmLayer.on('tileerror', function() {
            tileErrorCount++;
            if (tileErrorCount >= 3 && activeLayer === osmLayer) {
                map.removeLayer(osmLayer);
                cartoLayer.addTo(map);
                activeLayer = cartoLayer;
            }
        });

        var markers = {};
        var trajectories = {};
        var infrastructureLayers = {};
        var overlayGroups = {
            markers: L.layerGroup().addTo(map),
            trajectories: L.layerGroup().addTo(map),
            map: L.layerGroup(),
            map_inbound: L.layerGroup().addTo(map),
            map_outbound: L.layerGroup().addTo(map),
            map_connections: L.layerGroup().addTo(map),
            map_stoplines: L.layerGroup().addTo(map),
            map_requests: L.layerGroup().addTo(map),
            spat: L.layerGroup()
        };
        var overlayControl = L.control.layers(null, {
            'Stationen': overlayGroups.markers,
            'Trajektorien': overlayGroups.trajectories,
            'MAP-Punkte': overlayGroups.map,
            'Inbound-Lanes': overlayGroups.map_inbound,
            'Outbound-Lanes': overlayGroups.map_outbound,
            'Connections': overlayGroups.map_connections,
            'Stoplines': overlayGroups.map_stoplines,
            'Requests': overlayGroups.map_requests,
            'SPAT-Punkte': overlayGroups.spat
        }, {collapsed: false}).addTo(map);
        var stationColors = {};

        // Called from Python to set station colors
        function setStationColors(colors) {
            stationColors = colors;
        }

        // Called from Python to add a marker
        function addMarker(id, stationId, lat, lon, popup, color, layerName) {
            var group = overlayGroups[layerName] || overlayGroups.markers;
            if (markers[id]) {
                markers[id].setLatLng([lat, lon]);
                markers[id].setPopupContent(popup);
            } else {
                markers[id] = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'station-marker',
                        html: '<div style="background:' + color + ';width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 4px rgba(0,0,0,0.5)"></div>',
                        iconSize: [12, 12],
                        iconAnchor: [6, 6]
                    })
                }).addTo(group).bindPopup(popup);
                markers[id].on('click', function() {
                    if (window.bridge && layerName === 'markers') {
                        window.bridge.onMarkerClicked(stationId);
                    }
                });
            }
        }

        // Called from Python to add/update a trajectory line
        function addTrajectory(stationId, coords, color) {
            if (trajectories[stationId]) {
                trajectories[stationId].setLatLngs(coords);
            } else {
                trajectories[stationId] = L.polyline(coords, {
                    color: color, weight: 2, opacity: 0.6
                }).addTo(overlayGroups.trajectories);
            }
        }

        function infrastructureGroup(layerName) {
            return overlayGroups[layerName] || overlayGroups.map;
        }

        function addInfrastructureCircle(id, lat, lon, radius, color, popup, layerName) {
            if (infrastructureLayers[id]) {
                infrastructureLayers[id].setLatLng([lat, lon]);
                infrastructureLayers[id].setRadius(radius);
                infrastructureLayers[id].setStyle({color: color});
                infrastructureLayers[id].bindPopup(popup);
            } else {
                infrastructureLayers[id] = L.circle([lat, lon], {
                    radius: radius,
                    color: color,
                    weight: 2,
                    fillColor: color,
                    fillOpacity: 0.12
                }).addTo(infrastructureGroup(layerName)).bindPopup(popup);
            }
        }

        function attachHoverTooltip(layer, tooltip, weight, opacity) {
            if (!tooltip) {
                return;
            }
            layer.bindTooltip(tooltip, {sticky: true});
            layer.off('mouseover');
            layer.off('mouseout');
            layer.on('mouseover', function() {
                layer.setStyle({weight: Math.max((weight || 3) + 2, 5), opacity: 1.0});
                layer.openTooltip();
            });
            layer.on('mouseout', function() {
                layer.setStyle({weight: weight || 3, opacity: opacity || 0.85});
                layer.closeTooltip();
            });
        }

        function addInfrastructurePolyline(id, coords, color, popup, layerName, weight, opacity, dashArray, tooltip) {
            if (infrastructureLayers[id]) {
                infrastructureLayers[id].setLatLngs(coords);
                infrastructureLayers[id].setStyle({
                    color: color,
                    weight: weight || 3,
                    opacity: opacity || 0.85,
                    dashArray: dashArray || '8 6'
                });
                infrastructureLayers[id].bindPopup(popup);
                attachHoverTooltip(infrastructureLayers[id], tooltip, weight, opacity);
            } else {
                infrastructureLayers[id] = L.polyline(coords, {
                    color: color,
                    weight: weight || 3,
                    opacity: opacity || 0.85,
                    dashArray: dashArray || '8 6'
                }).addTo(infrastructureGroup(layerName)).bindPopup(popup);
                attachHoverTooltip(infrastructureLayers[id], tooltip, weight, opacity);
            }
        }

        function addInfrastructureLabel(id, lat, lon, text, color, layerName) {
            if (infrastructureLayers[id]) {
                infrastructureLayers[id].setLatLng([lat, lon]);
                infrastructureLayers[id].setIcon(L.divIcon({
                    className: 'infrastructure-label',
                    html: '<div style="color:' + color + ';font:600 11px Segoe UI, sans-serif;text-shadow:0 0 4px white, 0 0 4px white;">' + text + '</div>',
                    iconSize: [160, 18],
                    iconAnchor: [8, -6]
                }));
            } else {
                infrastructureLayers[id] = L.marker([lat, lon], {
                    interactive: false,
                    icon: L.divIcon({
                        className: 'infrastructure-label',
                        html: '<div style="color:' + color + ';font:600 11px Segoe UI, sans-serif;text-shadow:0 0 4px white, 0 0 4px white;">' + text + '</div>',
                        iconSize: [160, 18],
                        iconAnchor: [8, -6]
                    })
                }).addTo(infrastructureGroup(layerName));
            }
        }

        function removeInfrastructureLayer(id) {
            if (!infrastructureLayers[id]) {
                return;
            }
            overlayGroups.map.removeLayer(infrastructureLayers[id]);
            overlayGroups.map_inbound.removeLayer(infrastructureLayers[id]);
            overlayGroups.map_outbound.removeLayer(infrastructureLayers[id]);
            overlayGroups.map_connections.removeLayer(infrastructureLayers[id]);
            overlayGroups.map_stoplines.removeLayer(infrastructureLayers[id]);
            overlayGroups.map_requests.removeLayer(infrastructureLayers[id]);
            overlayGroups.spat.removeLayer(infrastructureLayers[id]);
            delete infrastructureLayers[id];
        }

        function syncMarkers(activeIds) {
            var active = {};
            for (var index = 0; index < activeIds.length; index++) {
                active[activeIds[index]] = true;
            }
            for (var key in markers) {
                if (!active[key]) {
                    overlayGroups.markers.removeLayer(markers[key]);
                    delete markers[key];
                }
            }
        }

        function syncTrajectories(activeIds) {
            var active = {};
            for (var index = 0; index < activeIds.length; index++) {
                active[activeIds[index]] = true;
            }
            for (var key in trajectories) {
                if (!active[key]) {
                    overlayGroups.trajectories.removeLayer(trajectories[key]);
                    delete trajectories[key];
                }
            }
        }

        function syncInfrastructure(activeIds) {
            var active = {};
            for (var index = 0; index < activeIds.length; index++) {
                active[activeIds[index]] = true;
            }
            for (var key in infrastructureLayers) {
                if (!active[key]) {
                    removeInfrastructureLayer(key);
                }
            }
        }

        // Called from Python to highlight the current playback marker
        function highlightMarker(id) {
            for (var key in markers) {
                var el = markers[key].getElement();
                if (el) {
                    var dot = el.querySelector('.station-marker div');
                    if (dot) dot.style.transform = (key === id) ? 'scale(1.8)' : 'scale(1)';
                }
            }
        }

        function followMarker(id) {
            if (!markers[id]) {
                return;
            }
            var latLng = markers[id].getLatLng();
            map.panTo(latLng, {animate: false});
        }

        // Called from Python to fit the map view to all markers
        function fitToMarkers() {
            map.invalidateSize(false);
            var bounds = [];
            for (var key in markers) {
                var markerLatLng = markers[key].getLatLng();
                bounds.push([markerLatLng.lat, markerLatLng.lng]);
            }
            for (var infraKey in infrastructureLayers) {
                var layer = infrastructureLayers[infraKey];
                if (layer.getBounds) {
                    var layerBounds = layer.getBounds();
                    if (layerBounds.isValid()) {
                        bounds.push([layerBounds.getSouth(), layerBounds.getWest()]);
                        bounds.push([layerBounds.getNorth(), layerBounds.getEast()]);
                    }
                } else if (layer.getLatLng) {
                    var infraLatLng = layer.getLatLng();
                    bounds.push([infraLatLng.lat, infraLatLng.lng]);
                }
            }
            if (bounds.length > 0) {
                try {
                    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
                } catch (error) {
                    console.warn('fitToMarkers skipped:', error);
                }
            }
        }

        function highlightRequest(intersectionId, requestId, sequenceNumber) {
            var token = 'request_' + requestId + '_' + sequenceNumber;
            for (var key in infrastructureLayers) {
                var isMatch = key.indexOf('id:' + intersectionId + '_') === 0 && key.indexOf(token) !== -1;
                var layer = infrastructureLayers[key];
                if (!layer.setStyle) {
                    continue;
                }
                if (isMatch) {
                    layer.setStyle({weight: 8, opacity: 1.0});
                    if (layer.openPopup) layer.openPopup();
                }
            }
        }

        function focusIntersection(intersectionId) {
            var bounds = [];
            for (var key in infrastructureLayers) {
                if (key.indexOf('id:' + intersectionId + '_') !== 0) {
                    continue;
                }
                var layer = infrastructureLayers[key];
                if (layer.getBounds) {
                    var layerBounds = layer.getBounds();
                    if (layerBounds.isValid()) {
                        bounds.push([layerBounds.getSouth(), layerBounds.getWest()]);
                        bounds.push([layerBounds.getNorth(), layerBounds.getEast()]);
                    }
                } else if (layer.getLatLng) {
                    var latLng = layer.getLatLng();
                    bounds.push([latLng.lat, latLng.lng]);
                }
            }
            if (bounds.length > 0) {
                map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
            }
        }

        // Called from Python to clear all markers and trajectories
        function clearAll() {
            for (var key in markers) {
                overlayGroups.markers.removeLayer(markers[key]);
            }
            for (var key in trajectories) {
                overlayGroups.trajectories.removeLayer(trajectories[key]);
            }
            for (var key in infrastructureLayers) {
                removeInfrastructureLayer(key);
            }
            markers = {};
            trajectories = {};
            infrastructureLayers = {};
        }

        // Bridge for Python communication. The qrc script is available only
        // inside Qt WebEngine; keep the map usable even if the bridge is absent.
        if (typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined') {
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.bridge = channel.objects.bridge;
            });
        } else {
            console.warn('Qt WebChannel unavailable; marker click follow mode disabled.');
        }
    </script>
</body>
</html>"""


class MapBridge(QObject):
    """Bridge object exposed to JavaScript via QWebChannel."""
    message_clicked = pyqtSignal(str)  # station_id

    @pyqtSlot(str)
    def onMarkerClicked(self, station_id: str) -> None:
        self.message_clicked.emit(station_id)


class MapWidget(QWebEngineView):
    """Interactive Leaflet map displaying V2X entity positions and trajectories."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set a proper User-Agent so OSM tile servers don't reject requests with 403
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent(
            "PCAP2KML-Player/1.0 (Windows; V2X-Viewer) OSM-Tiles/1.0"
        )

        self._bridge = MapBridge()
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)

        self._station_color_map: dict[str, str] = {}
        self._station_index = 0
        self._follow_station_id: Optional[str] = None
        self._page_ready = False
        self._pending_scripts: list[str] = []

        self._bridge.message_clicked.connect(self._on_marker_clicked)
        self.loadFinished.connect(self._on_load_finished)

        self.setHtml(LEAFLET_HTML, QUrl("about:blank"))

    def _get_station_color(self, station_id: str) -> str:
        """Assign a color to a station ID, creating a new one if needed."""
        if station_id not in self._station_color_map:
            self._station_color_map[station_id] = STATION_PALETTE[
                self._station_index % len(STATION_PALETTE)
            ]
            self._station_index += 1
        return self._station_color_map[station_id]

    def _color_for_message(self, msg: V2xMessage) -> str:
        """Pick a marker color, with dedicated infrastructure colors for MAP/SPAT."""
        return INFRASTRUCTURE_MESSAGE_COLORS.get(msg.msg_type, self._get_station_color(msg.station_id))

    def load_messages(self, messages: list[V2xMessage]) -> None:
        """Load all messages onto the map: markers, trajectories, and overlays."""
        self._follow_station_id = None
        self._render_messages(messages, fit_view=True, short_trails=False, clear_first=True)

    def render_playback_slice(self, messages: list[V2xMessage], current_index: int) -> None:
        """Render only the state visible up to the current playback index."""
        if not messages:
            self.clear()
            return
        safe_index = max(0, min(current_index, len(messages) - 1))
        self._render_messages(
            messages[: safe_index + 1],
            fit_view=False,
            short_trails=True,
            clear_first=False,
        )

    def _render_messages(
        self,
        messages: list[V2xMessage],
        *,
        fit_view: bool,
        short_trails: bool,
        clear_first: bool,
    ) -> None:
        """Internal renderer for a full load or a playback time slice."""
        if clear_first:
            self._run_js("clearAll()")

        # Assign colors and set them in JS
        # Group by station for trajectories
        station_coords: dict[str, list] = {}
        active_marker_ids: list[str] = []
        active_trajectory_ids: list[str] = []
        display_anchors = _display_anchor_points(messages)

        for msg in messages:
            if not _has_display_position(msg) or not _is_near_display_anchors(msg, display_anchors):
                continue
            color = self._color_for_message(msg)
            marker_lat, marker_lon = _marker_position_for_message(msg)
            popup = (
                f"<b>{msg.msg_type.value}</b><br>"
                f"Station: {msg.station_id}<br>"
                f"Time: {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}<br>"
                f"Pos: {msg.latitude:.6f}, {msg.longitude:.6f}"
            )

            if msg.msg_type not in NON_STATION_MARKER_TYPES:
                # Place/update the current dynamic marker at the latest visible position.
                marker_id_raw = _marker_id_for_message(msg)
                marker_id = _js_escape(marker_id_raw)
                station_id_js = _js_escape(msg.station_id)
                popup_js = _js_escape(popup)
                color_js = _js_escape(color)
                active_marker_ids.append(marker_id_raw)
                self._run_js(
                    f"addMarker('{marker_id}', '{station_id_js}', {marker_lat}, {marker_lon}, "
                    f"'{popup_js}', '{color_js}', 'markers')"
                )

            # Collect trajectory coordinates
            if msg.msg_type not in NON_STATION_MARKER_TYPES:
                station_coords.setdefault(msg.station_id, []).append(
                    [msg.latitude, msg.longitude]
                )

        colors_js = json.dumps(self._station_color_map)
        self._run_js(f"setStationColors({colors_js})")

        active_infrastructure_ids: list[str] = []
        for overlay in _infrastructure_overlays_for_messages(messages):
            active_infrastructure_ids.append(str(overlay["id"]))
            overlay_id = _js_escape(str(overlay["id"]))
            overlay_color = _js_escape(str(overlay["color"]))
            if overlay["kind"] == "circle":
                overlay_popup = _js_escape(str(overlay.get("popup", "")))
                self._run_js(
                    "addInfrastructureCircle("
                    f"'{overlay_id}', {overlay['lat']}, {overlay['lon']}, {overlay['radius']}, "
                    f"'{overlay_color}', '{overlay_popup}', '{_js_escape(str(overlay['layer']))}')"
                )
            elif overlay["kind"] == "polyline":
                overlay_popup = _js_escape(str(overlay.get("popup", "")))
                coords_js = json.dumps(overlay["coords"])
                overlay_weight = overlay.get("weight", 3)
                overlay_opacity = overlay.get("opacity", 0.85)
                overlay_dash = _js_escape(str(overlay.get("dashArray", "8 6")))
                overlay_tooltip = _js_escape(str(overlay.get("tooltip", "")))
                self._run_js(
                    "addInfrastructurePolyline("
                    f"'{overlay_id}', {coords_js}, '{overlay_color}', '{overlay_popup}', "
                    f"'{_js_escape(str(overlay['layer']))}', {overlay_weight}, {overlay_opacity}, "
                    f"'{overlay_dash}', '{overlay_tooltip}')"
                )
            elif overlay["kind"] == "label":
                self._run_js(
                    "addInfrastructureLabel("
                    f"'{overlay_id}', {overlay['lat']}, {overlay['lon']}, "
                    f"'{_js_escape(str(overlay['text']))}', '{overlay_color}', "
                    f"'{_js_escape(str(overlay['layer']))}')"
                )

        # Draw trajectories
        for station_id, coords in station_coords.items():
            if short_trails:
                coords = coords[-PLAYBACK_TRAIL_POINTS:]
            color = _js_escape(self._get_station_color(station_id))
            coords_js = json.dumps(coords)
            active_trajectory_ids.append(station_id)
            self._run_js(f"addTrajectory('{_js_escape(station_id)}', {coords_js}, '{color}')")

        markers_js = json.dumps(active_marker_ids)
        trajectories_js = json.dumps(active_trajectory_ids)
        infrastructure_js = json.dumps(active_infrastructure_ids)
        self._run_js(f"syncMarkers({markers_js})")
        self._run_js(f"syncTrajectories({trajectories_js})")
        self._run_js(f"syncInfrastructure({infrastructure_js})")

        # Fit map to all markers
        if fit_view:
            self._run_js("fitToMarkers()")

    def update_playback_position(self, msg: V2xMessage) -> None:
        """Move the marker for msg.station_id and highlight it."""
        color = self._color_for_message(msg)
        marker_id_raw = _marker_id_for_message(msg)
        marker_id = _js_escape(marker_id_raw)
        if msg.msg_type not in NON_STATION_MARKER_TYPES and _has_display_position(msg):
            marker_lat, marker_lon = _marker_position_for_message(msg)
            popup = (
                f"<b>{msg.msg_type.value}</b><br>"
                f"Station: {msg.station_id}<br>"
                f"Time: {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}<br>"
                f"Pos: {msg.latitude:.6f}, {msg.longitude:.6f}"
            )
            self._run_js(
                f"addMarker('{marker_id}', '{_js_escape(msg.station_id)}', "
                f"{marker_lat}, {marker_lon}, '{_js_escape(popup)}', "
                f"'{_js_escape(color)}', 'markers')"
            )
        self._run_js(f"highlightMarker('{marker_id}')")
        if self._follow_station_id and msg.station_id == self._follow_station_id:
            self._run_js(f"followMarker('{_js_escape(marker_id)}')")

    def highlight_request(self, intersection_id: int, request_id: int, sequence_number: int) -> None:
        """Highlight a rendered prioritization request route."""
        self._run_js(f"highlightRequest({intersection_id}, {request_id}, {sequence_number})")

    def focus_intersection(self, intersection_id: int) -> None:
        """Focus the map around one rendered intersection."""
        self._run_js(f"focusIntersection({intersection_id})")

    def clear(self) -> None:
        """Remove all markers and trajectories from the map."""
        self._run_js("clearAll()")
        self._station_color_map.clear()
        self._station_index = 0
        self._follow_station_id = None

    def _on_marker_clicked(self, station_id: str) -> None:
        """Remember which dynamic object should be followed during playback."""
        self._follow_station_id = station_id

    def _on_load_finished(self, ok: bool) -> None:
        """Flush queued JavaScript once the embedded map page is ready."""
        self._page_ready = ok
        if not ok:
            logger.warning("Leaflet map page did not finish loading")
            return
        pending = self._pending_scripts
        self._pending_scripts = []
        for script in pending:
            self.page().runJavaScript(script, 0)

    def _run_js(self, script: str) -> None:
        """Execute JavaScript in the web page."""
        if not self._page_ready:
            self._pending_scripts.append(script)
            return
        self.page().runJavaScript(script, 0)
