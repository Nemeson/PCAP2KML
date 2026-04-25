"""Interactive Leaflet.js map widget embedded in QWebEngineView.

Displays V2X entity markers, trajectories, and supports synchronized
playback highlighting via JavaScript calls.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from math import cos, hypot, radians
from pathlib import Path
from typing import Optional

from PyQt6 import sip
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QResizeEvent, QShowEvent
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .data_model import MessageType, V2xMessage
from .scene_model import build_scene_snapshot

logger = logging.getLogger(__name__)
PLAYBACK_TRAIL_POINTS = 8
DISPLAY_CLUSTER_RADIUS_M = 5000.0
MAP_PERFORMANCE_NORMAL = "normal"
MAP_PERFORMANCE_SAVER = "saver"
MAP_PERFORMANCE_DIAGNOSTIC = "diagnostic"
MAP_PERFORMANCE_MODES = {
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
    MAP_PERFORMANCE_DIAGNOSTIC,
}
MAP_RENDER_BUDGETS = {
    MAP_PERFORMANCE_NORMAL: {
        "markers": 1500,
        "infrastructure": 2500,
        "trajectories": 1000,
        "trajectory_points": 8000,
    },
    MAP_PERFORMANCE_SAVER: {
        "markers": 600,
        "infrastructure": 1200,
        "trajectories": 300,
        "trajectory_points": 2500,
    },
    MAP_PERFORMANCE_DIAGNOSTIC: {
        "markers": 200,
        "infrastructure": 600,
        "trajectories": 50,
        "trajectory_points": 400,
    },
}
MAP_RENDER_STALL_SECONDS = 8.0
MAP_BOOTSTRAP_TIMEOUT_SECONDS = 6.0


def _qt_object_deleted(obj: object) -> bool:
    """Return whether Qt already destroyed the wrapped C++ object."""
    if not getattr(obj, "__dict__", {}).get("_qt_initialized", False):
        return False
    try:
        return bool(sip.isdeleted(obj))
    except (AttributeError, RuntimeError, TypeError):
        return False


# Color palette for station markers (hex strings for Leaflet)
STATION_PALETTE = [
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
    "#469990",
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


@dataclass(frozen=True)
class MapRenderTelemetry:
    """Compact diagnostics for one map payload."""

    timestamp: float
    performance_mode: str
    source_message_count: int
    visible_message_count: int
    marker_count: int
    infrastructure_count: int
    trajectory_count: int
    trajectory_point_count: int
    payload_bytes: int
    queued_payload_replaced: bool = False
    budget_dropped_markers: int = 0
    budget_dropped_infrastructure: int = 0
    budget_dropped_trajectories: int = 0
    budget_dropped_trajectory_points: int = 0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def _marker_id_for_message(msg: V2xMessage) -> str:
    """Return a stable marker id, preserving MAP/SPAT overlays separately."""
    if msg.msg_type in INFRASTRUCTURE_MESSAGE_COLORS:
        return f"infrastructure_{msg.msg_type.value}_{msg.station_id}"
    return f"station_{msg.station_id}"


def _marker_position_for_message(msg: V2xMessage) -> tuple[float, float]:
    """Slightly offset infrastructure markers so MAP/SPAT stay visible together."""
    lat_offset, lon_offset = INFRASTRUCTURE_MESSAGE_OFFSETS.get(
        msg.msg_type, (0.0, 0.0)
    )
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
        return [
            intersection
            for intersection in intersections
            if isinstance(intersection, dict)
        ]
    return [{}]


def _polyline_label_point(
    points: list[tuple[float, float]],
) -> Optional[tuple[float, float]]:
    """Place a label near the middle of a lane polyline."""
    if not points:
        return None
    return points[len(points) // 2]


def _point_distance_meters(
    point_a: tuple[float, float], point_b: tuple[float, float]
) -> float:
    """Approximate local distance in meters between two nearby points."""
    lat_scale = 111_320.0
    lon_scale = max(1e-6, 111_320.0 * cos(radians((point_a[0] + point_b[0]) / 2.0)))
    dx = (point_a[1] - point_b[1]) * lon_scale
    dy = (point_a[0] - point_b[0]) * lat_scale
    return hypot(dx, dy)


def _display_anchor_points(
    messages: list[V2xMessage],
    *,
    max_index: Optional[int] = None,
) -> list[tuple[float, float]]:
    """Return stable infrastructure points used to reject far-away display outliers."""
    anchors: list[tuple[float, float]] = []
    end_index = (
        len(messages) if max_index is None else min(max_index + 1, len(messages))
    )
    for index, msg in enumerate(messages):
        if index >= end_index:
            break
        if (
            msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS
            or not _has_display_position(msg)
        ):
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


def _valid_lat_lon(lat: object, lon: object) -> Optional[tuple[float, float]]:
    """Return a finite WGS84 coordinate pair suitable for Leaflet bounds."""
    try:
        lat_num = float(lat)
        lon_num = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat_num <= 90 and -180 <= lon_num <= 180):
        return None
    return (lat_num, lon_num)


def _payload_bounds(
    markers: list[dict[str, object]],
    infrastructure: list[dict[str, object]],
) -> Optional[list[list[float]]]:
    """Build stable Leaflet bounds from the explicit render payload."""
    points: list[tuple[float, float]] = []
    for marker in markers:
        point = _valid_lat_lon(marker.get("lat"), marker.get("lon"))
        if point is not None:
            points.append(point)
    for item in infrastructure:
        if item.get("kind") == "polyline":
            for coord in item.get("coords", []):
                if not isinstance(coord, list | tuple) or len(coord) < 2:
                    continue
                point = _valid_lat_lon(coord[0], coord[1])
                if point is not None:
                    points.append(point)
        else:
            point = _valid_lat_lon(item.get("lat"), item.get("lon"))
            if point is not None:
                points.append(point)
    if not points:
        return None
    min_lat = min(point[0] for point in points)
    max_lat = max(point[0] for point in points)
    min_lon = min(point[1] for point in points)
    max_lon = max(point[1] for point in points)
    if abs(max_lat - min_lat) < 1e-9:
        min_lat -= 0.0005
        max_lat += 0.0005
    if abs(max_lon - min_lon) < 1e-9:
        min_lon -= 0.0005
        max_lon += 0.0005
    return [[min_lat, min_lon], [max_lat, max_lon]]


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


def _offset_polyline(
    coords: list[tuple[float, float]], offset_m: float
) -> list[tuple[float, float]]:
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
    parts.append(f"{request_visual['request_id']}/{request_visual['sequence_number']}")
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
        events = signal_group.get(
            "stateTimeSpeed", signal_group.get("state-time-speed")
        )
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
    return SPAT_PHASE_COLORS.get(
        phase, INFRASTRUCTURE_MESSAGE_COLORS[MessageType.SPATEM]
    )


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
        events = signal_group.get(
            "stateTimeSpeed", signal_group.get("state-time-speed")
        )
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
        events = signal_group.get(
            "stateTimeSpeed", signal_group.get("state-time-speed")
        )
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


def _intersection_popup(
    msg: V2xMessage, intersection: Optional[dict], fallback_label: str
) -> str:
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

            popup = _intersection_popup(
                msg, intersection, f"{msg.msg_type.value} Intersection"
            )
            circle_color = (
                _spat_color_for_intersection(intersection)
                if msg.msg_type == MessageType.SPATEM
                else base_color
            )
            overlays.append(
                {
                    "kind": "circle",
                    "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_circle",
                    "lat": point[0],
                    "lon": point[1],
                    "radius": 20 if msg.msg_type == MessageType.MAPEM else 28,
                    "color": circle_color,
                    "popup": popup,
                    "layer": layer,
                }
            )
            overlays.append(
                {
                    "kind": "label",
                    "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_label",
                    "lat": point[0],
                    "lon": point[1],
                    "text": popup,
                    "color": circle_color,
                    "layer": layer,
                }
            )

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
                    overlays.append(
                        {
                            "kind": "polyline",
                            "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}",
                            "coords": [[lat, lon] for lat, lon in points],
                            "color": lane_color,
                            "popup": _lane_popup_text(lane, role),
                            "layer": lane_layer,
                        }
                    )
                    lane_id = _lane_identifier(lane)
                    label_point = _polyline_label_point(points)
                    if lane_id and label_point is not None:
                        overlays.append(
                            {
                                "kind": "label",
                                "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}_label",
                                "lat": label_point[0],
                                "lon": label_point[1],
                                "text": f"Lane {lane_id}",
                                "color": lane_color,
                                "layer": lane_layer,
                            }
                        )
                    stopline_points = _stopline_points(lane)
                    if stopline_points is not None:
                        overlays.append(
                            {
                                "kind": "polyline",
                                "id": f"{msg.msg_type.value}_{msg.station_id}_{index}_lane_{polyline_index}_stopline",
                                "coords": [[lat, lon] for lat, lon in stopline_points],
                                "color": STOPLINE_COLOR,
                                "popup": f"Stopline | Lane {lane_id}"
                                if lane_id
                                else "Stopline",
                                "layer": "map_stoplines",
                            }
                        )
    else:
        raw_popup = f"{msg.msg_type.value} raw infrastructure position"
        overlays.append(
            {
                "kind": "circle",
                "id": f"{msg.msg_type.value}_{msg.station_id}_raw",
                "lat": msg.latitude,
                "lon": msg.longitude,
                "radius": 18 if msg.msg_type == MessageType.MAPEM else 26,
                "color": base_color,
                "popup": raw_popup,
                "layer": layer,
            }
        )
        overlays.append(
            {
                "kind": "label",
                "id": f"{msg.msg_type.value}_{msg.station_id}_raw_label",
                "lat": msg.latitude,
                "lon": msg.longitude,
                "text": f"{msg.msg_type.value} raw",
                "color": base_color,
                "layer": layer,
            }
        )

    return overlays


def _infrastructure_overlays_for_messages(
    messages: list[V2xMessage],
    *,
    max_index: Optional[int] = None,
) -> list[dict[str, object]]:
    """Aggregate the latest MAP/SPAT context per intersection into render overlays."""
    if not messages:
        return []

    end_index = (
        len(messages) if max_index is None else min(max_index + 1, len(messages))
    )
    if end_index <= 0:
        return []
    timeline_position = messages[end_index - 1].timestamp
    latest_map: dict[str, tuple[V2xMessage, dict]] = {}
    latest_spat: dict[str, tuple[V2xMessage, dict]] = {}
    scene = build_scene_snapshot(messages, timeline_position)
    request_visuals = scene.request_visuals_by_intersection

    for index, msg in enumerate(messages):
        if index >= end_index:
            break
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
            map_popup = _intersection_popup(
                map_msg, map_intersection, "MAPEM Intersection"
            )
            intersection_numeric_id = _coerce_int(
                map_intersection.get("intersectionId", map_intersection.get("id"))
            )
            intersection_requests = (
                request_visuals.get(intersection_numeric_id, [])
                if intersection_numeric_id is not None
                else []
            )
            if SHOW_INFRASTRUCTURE_POINT_OVERLAYS:
                overlays.append(
                    {
                        "kind": "circle",
                        "id": f"{key}_map_circle",
                        "lat": map_point[0],
                        "lon": map_point[1],
                        "radius": 20,
                        "color": INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                        "popup": map_popup,
                        "layer": "map",
                    }
                )
                overlays.append(
                    {
                        "kind": "label",
                        "id": f"{key}_map_label",
                        "lat": map_point[0],
                        "lon": map_point[1],
                        "text": map_popup,
                        "color": INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                        "layer": "map",
                    }
                )

            lane_set = map_intersection.get("laneSet")
            if not isinstance(lane_set, list):
                lane_set = []
            spat_states = (
                _spat_states_by_group(spat_entry[1]) if spat_entry is not None else {}
            )
            spat_tooltips = (
                _spat_tooltips_by_group(spat_entry[1]) if spat_entry is not None else {}
            )
            lane_by_id = {
                _coerce_int(
                    lane.get("laneId", lane.get("laneID", lane.get("id")))
                ): lane
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
                lane_color = LANE_ROLE_COLORS.get(
                    role, INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM]
                )
                lane_layer = (
                    "map_inbound"
                    if role == "inbound"
                    else "map_outbound"
                    if role == "outbound"
                    else "map"
                )
                overlays.append(
                    {
                        "kind": "polyline",
                        "id": f"{key}_lane_{polyline_index}",
                        "coords": [[lat, lon] for lat, lon in points],
                        "color": lane_color,
                        "popup": _lane_popup_text(lane, role),
                        "layer": lane_layer,
                    }
                )
                label_point = _polyline_label_point(points)
                if label_point is not None:
                    label_parts = []
                    if lane_id:
                        label_parts.append(f"Lane {lane_id}")
                    if role:
                        label_parts.append(role)
                    if label_parts:
                        overlays.append(
                            {
                                "kind": "label",
                                "id": f"{key}_lane_{polyline_index}_label",
                                "lat": label_point[0],
                                "lon": label_point[1],
                                "text": " | ".join(label_parts),
                                "color": lane_color,
                                "layer": lane_layer,
                            }
                        )
                stopline_points = _stopline_points(lane)
                if stopline_points is not None:
                    overlays.append(
                        {
                            "kind": "polyline",
                            "id": f"{key}_lane_{polyline_index}_stopline",
                            "coords": [[lat, lon] for lat, lon in stopline_points],
                            "color": STOPLINE_COLOR,
                            "popup": f"Stopline | Lane {lane_id}"
                            if lane_id
                            else "Stopline",
                            "layer": "map_stoplines",
                        }
                    )

                connections = lane.get("connections", lane.get("connectsTo"))
                if not isinstance(connections, list):
                    continue
                for connection in connections:
                    if not isinstance(connection, dict):
                        continue
                    target_lane_id = _coerce_int(
                        connection.get("targetLaneId", connection.get("connectingLane"))
                    )
                    if target_lane_id is None:
                        continue
                    target_lane = lane_by_id.get(target_lane_id)
                    if not isinstance(target_lane, dict):
                        continue
                    connection_points = _connection_curve_points(
                        lane, target_lane, map_point
                    )
                    if connection_points is None:
                        continue
                    signal_group = _coerce_int(connection.get("signalGroup"))
                    matched_phase = (
                        spat_states.get(signal_group)
                        if signal_group is not None
                        else None
                    )
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
                    overlays.append(
                        {
                            "kind": "polyline",
                            "id": f"{key}_lane_{polyline_index}_connection_{target_lane_id}",
                            "coords": [[lat, lon] for lat, lon in connection_points],
                            "color": connection_color,
                            "popup": " | ".join(popup_parts),
                            "tooltip": " | ".join(tooltip_parts),
                            "layer": "map_connections",
                        }
                    )
                    matching_requests = [
                        visual
                        for visual in intersection_requests
                        if visual.in_lane
                        == _coerce_int(
                            lane.get("laneId", lane.get("laneID", lane.get("id")))
                        )
                        and visual.out_lane == target_lane_id
                    ]
                    for request_visual in matching_requests:
                        style = _request_overlay_style(
                            request_visual.status.value, request_visual.is_dominant
                        )
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
                        overlays.append(
                            {
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
                            }
                        )

                lane_requests = [
                    visual
                    for visual in intersection_requests
                    if visual.in_lane
                    == _coerce_int(
                        lane.get("laneId", lane.get("laneID", lane.get("id")))
                    )
                    or visual.out_lane
                    == _coerce_int(
                        lane.get("laneId", lane.get("laneID", lane.get("id")))
                    )
                ]
                for request_visual in lane_requests:
                    style = _request_overlay_style(
                        request_visual.status.value, request_visual.is_dominant
                    )
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
                        "Inbound-Lane"
                        if request_visual.in_lane
                        == _coerce_int(
                            lane.get("laneId", lane.get("laneID", lane.get("id")))
                        )
                        else "Outbound-Lane"
                    )
                    overlays.append(
                        {
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
                        }
                    )

        if spat_entry is not None:
            spat_msg, spat_intersection = spat_entry
            spat_point = _intersection_point(spat_intersection, spat_msg)
            spat_popup = _intersection_popup(
                spat_msg, spat_intersection, "SPATEM Intersection"
            )
            spat_color = _spat_color_for_intersection(spat_intersection)
            if SHOW_INFRASTRUCTURE_POINT_OVERLAYS:
                overlays.append(
                    {
                        "kind": "circle",
                        "id": f"{key}_spat_circle",
                        "lat": spat_point[0],
                        "lon": spat_point[1],
                        "radius": 28,
                        "color": spat_color,
                        "popup": spat_popup,
                        "layer": "spat",
                    }
                )
                overlays.append(
                    {
                        "kind": "label",
                        "id": f"{key}_spat_label",
                        "lat": spat_point[0],
                        "lon": spat_point[1],
                        "text": spat_popup,
                        "color": spat_color,
                        "layer": "spat",
                    }
                )

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
    <link rel="stylesheet" href="leaflet/leaflet.css"
          onerror="this.onerror=null;this.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';" />
    <script src="leaflet/leaflet.js"></script>
    <script>
        if (typeof L === 'undefined') {
            document.write('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"><\\/script>');
        }
    </script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        if (typeof L === 'undefined') {
            document.getElementById('map').innerHTML =
                '<div style="font:14px Segoe UI, sans-serif;color:#10233f;padding:18px;">' +
                '<b>Karte konnte nicht initialisiert werden.</b><br>' +
                'Leaflet wurde nicht geladen. Bitte Diagnose exportieren oder Karte neu laden.' +
                '</div>';
            console.error('Leaflet unavailable; map bootstrap aborted.');
        } else {
        var map = L.map('map', {preferCanvas: true}).setView([48.0, 11.0], 13);
        map.whenReady(function() {
            map.invalidateSize(false);
        });

        // Primary tile layer (OpenStreetMap with proper attribution)
        var osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        });

        // Fallback tile layer (CartoDB — works reliably from embedded browsers)
        var cartoLightLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            maxZoom: 20
        });

        var cartoDarkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            maxZoom: 20
        });

        var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community',
            maxZoom: 19
        });

        var baseLayers = {
            'Hell / Schwarz-Weiss': cartoLightLayer,
            'OSM Standard': osmLayer,
            'Dunkel': cartoDarkLayer,
            'Satellit': satelliteLayer
        };

        function readStoredBaseLayerName() {
            try {
                return localStorage.getItem('pcap2kml.baseLayer');
            } catch (error) {
                return null;
            }
        }

        function storeBaseLayerName(name) {
            try {
                localStorage.setItem('pcap2kml.baseLayer', name);
            } catch (error) {
                // Some QtWebEngine contexts block localStorage for about:blank pages.
            }
        }

        // Restore the last base layer locally; default to OSM for maximum compatibility.
        var preferredBaseLayerName = readStoredBaseLayerName() || 'OSM Standard';
        var activeLayer = baseLayers[preferredBaseLayerName] || osmLayer;
        activeLayer.addTo(map);
        var tileErrorCount = 0;

        function switchToFallbackLayer() {
            if (activeLayer !== cartoLightLayer) {
                map.removeLayer(activeLayer);
                cartoLightLayer.addTo(map);
                activeLayer = cartoLightLayer;
                storeBaseLayerName('Hell / Schwarz-Weiss');
            }
        }

        function registerTileFallback(layer) {
            layer.on('tileerror', function() {
                tileErrorCount++;
                if (tileErrorCount >= 3) {
                    switchToFallbackLayer();
                }
            });
        }

        for (var baseLayerName in baseLayers) {
            registerTileFallback(baseLayers[baseLayerName]);
        }

        map.on('baselayerchange', function(event) {
            activeLayer = event.layer;
            storeBaseLayerName(event.name);
            tileErrorCount = 0;
        });

        var markers = {};
        var trajectories = {};
        var infrastructureLayers = {};
        var mapPerformanceMode = 'normal';
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
        var overlayControl = L.control.layers(baseLayers, {
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

        function setMapPerformanceMode(mode) {
            mapPerformanceMode = mode || 'normal';
        }

        // Called from Python to add a marker
        function addMarker(id, stationId, lat, lon, popup, color, layerName) {
            var group = overlayGroups[layerName] || overlayGroups.markers;
            if (markers[id]) {
                markers[id].setLatLng([lat, lon]);
                setLayerPopup(markers[id], popup);
            } else {
                markers[id] = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'station-marker',
                        html: '<div style="background:' + color + ';width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 4px rgba(0,0,0,0.5)"></div>',
                        iconSize: [12, 12],
                        iconAnchor: [6, 6]
                    })
                }).addTo(group);
                setLayerPopup(markers[id], popup);
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

        function setLayerPopup(layer, popup) {
            if (!popup) {
                if (layer.unbindPopup) {
                    layer.unbindPopup();
                }
                return;
            }
            var existingPopup = layer.getPopup ? layer.getPopup() : null;
            if (existingPopup) {
                existingPopup.setContent(popup);
            } else {
                layer.bindPopup(popup);
            }
        }

        function disposeLayer(layer) {
            if (!layer) {
                return;
            }
            if (layer.off) {
                layer.off();
            }
            if (layer.unbindPopup) {
                layer.unbindPopup();
            }
            if (layer.unbindTooltip) {
                layer.unbindTooltip();
            }
        }

        function addInfrastructureCircle(id, lat, lon, radius, color, popup, layerName) {
            if (infrastructureLayers[id]) {
                infrastructureLayers[id].setLatLng([lat, lon]);
                infrastructureLayers[id].setRadius(radius);
                infrastructureLayers[id].setStyle({color: color});
                setLayerPopup(infrastructureLayers[id], popup);
            } else {
                infrastructureLayers[id] = L.circle([lat, lon], {
                    radius: radius,
                    color: color,
                    weight: 2,
                    fillColor: color,
                    fillOpacity: 0.12
                }).addTo(infrastructureGroup(layerName));
                setLayerPopup(infrastructureLayers[id], popup);
            }
        }

        function attachHoverTooltip(layer, tooltip, weight, opacity) {
            if (mapPerformanceMode !== 'normal') {
                if (layer.unbindTooltip) {
                    layer.unbindTooltip();
                }
                layer.off('mouseover');
                layer.off('mouseout');
                return;
            }
            if (!tooltip) {
                if (layer.unbindTooltip) {
                    layer.unbindTooltip();
                }
                layer.off('mouseover');
                layer.off('mouseout');
                return;
            }
            var existingTooltip = layer.getTooltip ? layer.getTooltip() : null;
            if (existingTooltip) {
                existingTooltip.setContent(tooltip);
            } else {
                layer.bindTooltip(tooltip, {sticky: true});
            }
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
                setLayerPopup(infrastructureLayers[id], popup);
                attachHoverTooltip(infrastructureLayers[id], tooltip, weight, opacity);
            } else {
                infrastructureLayers[id] = L.polyline(coords, {
                    color: color,
                    weight: weight || 3,
                    opacity: opacity || 0.85,
                    dashArray: dashArray || '8 6'
                }).addTo(infrastructureGroup(layerName));
                setLayerPopup(infrastructureLayers[id], popup);
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
            disposeLayer(infrastructureLayers[id]);
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

        function applyRenderPayload(payload) {
            setMapPerformanceMode(payload.performanceMode || 'normal');
            if (payload.clear) {
                clearAll();
            }
            setStationColors(payload.stationColors || {});

            var markersPayload = payload.markers || [];
            var activeMarkerIds = [];
            for (var markerIndex = 0; markerIndex < markersPayload.length; markerIndex++) {
                var marker = markersPayload[markerIndex];
                activeMarkerIds.push(marker.id);
                addMarker(
                    marker.id,
                    marker.stationId,
                    marker.lat,
                    marker.lon,
                    marker.popup,
                    marker.color,
                    marker.layerName || 'markers'
                );
            }

            var infrastructurePayload = payload.infrastructure || [];
            var activeInfrastructureIds = [];
            for (var infraIndex = 0; infraIndex < infrastructurePayload.length; infraIndex++) {
                var item = infrastructurePayload[infraIndex];
                activeInfrastructureIds.push(item.id);
                if (item.kind === 'circle') {
                    addInfrastructureCircle(
                        item.id, item.lat, item.lon, item.radius, item.color,
                        item.popup || '', item.layerName || 'map'
                    );
                } else if (item.kind === 'polyline') {
                    addInfrastructurePolyline(
                        item.id, item.coords || [], item.color, item.popup || '',
                        item.layerName || 'map', item.weight || 3, item.opacity || 0.85,
                        item.dashArray || '8 6', item.tooltip || ''
                    );
                } else if (item.kind === 'label') {
                    addInfrastructureLabel(
                        item.id, item.lat, item.lon, item.text || '', item.color,
                        item.layerName || 'map'
                    );
                }
            }

            var trajectoriesPayload = payload.trajectories || [];
            var activeTrajectoryIds = [];
            for (var trajectoryIndex = 0; trajectoryIndex < trajectoriesPayload.length; trajectoryIndex++) {
                var trajectory = trajectoriesPayload[trajectoryIndex];
                activeTrajectoryIds.push(trajectory.stationId);
                addTrajectory(trajectory.stationId, trajectory.coords || [], trajectory.color);
            }

            syncMarkers(activeMarkerIds);
            syncTrajectories(activeTrajectoryIds);
            syncInfrastructure(activeInfrastructureIds);

            if (payload.fitView) {
                fitToPayloadBounds(payload.bounds || null);
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

        function fitToPayloadBounds(bounds) {
            map.invalidateSize(false);
            if (!bounds || bounds.length !== 2) {
                fitToMarkers();
                return;
            }
            try {
                var southWest = bounds[0];
                var northEast = bounds[1];
                var leafletBounds = L.latLngBounds(southWest, northEast);
                if (leafletBounds.isValid()) {
                    map.fitBounds(leafletBounds, {padding: [30, 30], maxZoom: 16});
                    return;
                }
            } catch (error) {
                console.warn('fitToPayloadBounds skipped:', error);
            }
            fitToMarkers();
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
                disposeLayer(markers[key]);
            }
            for (var key in trajectories) {
                overlayGroups.trajectories.removeLayer(trajectories[key]);
                disposeLayer(trajectories[key]);
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
        }
    </script>
</body>
</html>"""


def _asset_base_path() -> Path:
    """Return the directory used as base URL for local web assets."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    candidates = []
    if bundle_root:
        root = Path(bundle_root)
        candidates.extend(
            [
                root / "pcap2kml_player" / "assets",
                root / "assets",
            ]
        )
    candidates.append(Path(__file__).resolve().parent / "assets")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _leaflet_runtime_html() -> str:
    """Return map HTML with local Leaflet embedded when bundled assets are present."""
    leaflet_dir = _asset_base_path() / "leaflet"
    css_path = leaflet_dir / "leaflet.css"
    js_path = leaflet_dir / "leaflet.js"
    if not css_path.exists() or not js_path.exists():
        return LEAFLET_HTML
    try:
        css = css_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
    except OSError:
        return LEAFLET_HTML

    css = css.replace("url(images/", "url(leaflet/images/")
    js = js.replace("</script>", "<\\/script>")
    external_block = """    <link rel="stylesheet" href="leaflet/leaflet.css"
          onerror="this.onerror=null;this.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';" />
    <script src="leaflet/leaflet.js"></script>
    <script>
        if (typeof L === 'undefined') {
            document.write('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"><\\/script>');
        }
    </script>"""
    inline_block = (
        "    <!-- Local Leaflet assets embedded for QtWebEngine file-load robustness. -->\n"
        '    <!-- href="leaflet/leaflet.css" src="leaflet/leaflet.js" '
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js -->\n"
        f"    <style>\n{css}\n    </style>\n"
        f"    <script>\n{js}\n    </script>"
    )
    return LEAFLET_HTML.replace(external_block, inline_block)


class MapBridge(QObject):
    """Bridge object exposed to JavaScript via QWebChannel."""

    message_clicked = pyqtSignal(str)  # station_id

    @pyqtSlot(str)
    def onMarkerClicked(self, station_id: str) -> None:
        self.message_clicked.emit(station_id)


class DiagnosticWebEnginePage(QWebEnginePage):
    """QWebEnginePage that forwards JavaScript errors to Python diagnostics."""

    java_script_issue = pyqtSignal(str)

    def javaScriptConsoleMessage(
        self, level, message: str, line_number: int, source_id: str
    ) -> None:
        """Capture JS console issues that otherwise only appear in the terminal."""
        super().javaScriptConsoleMessage(level, message, line_number, source_id)
        level_name = getattr(level, "name", str(level))
        if (
            "Error" in level_name
            or "ReferenceError" in message
            or "TypeError" in message
        ):
            self.java_script_issue.emit(
                f"{level_name}: {message} ({source_id}:{line_number})"
            )


class MapWidget(QWebEngineView):
    """Interactive Leaflet map displaying V2X entity positions and trajectories."""

    telemetry_updated = pyqtSignal(dict)
    map_issue_detected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qt_initialized = True

        # Set a proper User-Agent so OSM tile servers don't reject requests with 403
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent(
            "PCAP2KML-Player/1.0 (Windows; V2X-Viewer) OSM-Tiles/1.0"
        )
        self._diagnostic_page = DiagnosticWebEnginePage(profile, self)
        self.setPage(self._diagnostic_page)
        self._diagnostic_page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._diagnostic_page.java_script_issue.connect(self._on_java_script_issue)

        self._bridge = MapBridge()
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)

        self._station_color_map: dict[str, str] = {}
        self._station_index = 0
        self._follow_station_id: Optional[str] = None
        self._performance_mode = MAP_PERFORMANCE_NORMAL
        self._page_ready = False
        self._pending_scripts: list[str] = []
        self._render_payload_in_flight = False
        self._queued_render_payload_script: Optional[str] = None
        self._render_payload_started_at: Optional[float] = None
        self._render_payload_stall_generation = 0
        self._bootstrap_generation = 0
        self._bootstrap_probe_succeeded = False
        self._ever_bootstrapped = False
        self._disposed = False
        self._latest_telemetry: Optional[MapRenderTelemetry] = None
        self._last_payload_was_replaced = False

        self._bridge.message_clicked.connect(self._on_marker_clicked)
        self.loadFinished.connect(self._on_load_finished)
        self._diagnostic_page.renderProcessTerminated.connect(
            self._on_render_process_terminated
        )

        # Owned timers for clean disposal
        self._bootstrap_timer: Optional[QTimer] = None
        self._stall_timer: Optional[QTimer] = None

        logger.info("Map backend created: webengine")
        self.setHtml(
            _leaflet_runtime_html(), QUrl.fromLocalFile(str(_asset_base_path()) + "/")
        )
        self._schedule_bootstrap_timeout()

    def dispose(self) -> None:
        """Cancel pending async WebEngine work and owned timers before replacement."""
        self.__dict__["_disposed"] = True
        self.__dict__["_page_ready"] = False
        self.__dict__["_pending_scripts"] = []
        self.__dict__["_render_payload_in_flight"] = False
        self.__dict__["_queued_render_payload_script"] = None
        self.__dict__["_render_payload_started_at"] = None
        self.__dict__["_render_payload_stall_generation"] = -1
        self.__dict__["_bootstrap_generation"] = -1
        self.__dict__["_bootstrap_probe_succeeded"] = True

        bootstrap_timer = self.__dict__.get("_bootstrap_timer")
        if bootstrap_timer is not None:
            bootstrap_timer.stop()
            bootstrap_timer.deleteLater()
        self.__dict__["_bootstrap_timer"] = None
        stall_timer = self.__dict__.get("_stall_timer")
        if stall_timer is not None:
            stall_timer.stop()
            stall_timer.deleteLater()
        self.__dict__["_stall_timer"] = None

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
        return INFRASTRUCTURE_MESSAGE_COLORS.get(
            msg.msg_type, self._get_station_color(msg.station_id)
        )

    def set_performance_mode(self, mode: str) -> None:
        """Set the map rendering detail level used for future payloads."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if mode not in MAP_PERFORMANCE_MODES:
            mode = MAP_PERFORMANCE_NORMAL
        self._performance_mode = mode
        self._run_js(f"setMapPerformanceMode('{mode}')")

    def latest_telemetry(self) -> Optional[dict[str, object]]:
        """Return the latest render telemetry, if available."""
        if self._latest_telemetry is None:
            return None
        return self._latest_telemetry.to_dict()

    def reload_map_page(self) -> None:
        """Reload the embedded Leaflet page and drop pending JavaScript work."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        self._page_ready = False
        self._bootstrap_probe_succeeded = False
        self._pending_scripts = []
        self._render_payload_in_flight = False
        self._queued_render_payload_script = None
        self._render_payload_started_at = None
        self.setHtml(
            _leaflet_runtime_html(), QUrl.fromLocalFile(str(_asset_base_path()) + "/")
        )
        self._schedule_bootstrap_timeout()

    def load_messages(self, messages: list[V2xMessage]) -> None:
        """Load all messages onto the map: markers, trajectories, and overlays."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        self._follow_station_id = None
        self._render_messages(
            messages,
            max_index=None,
            fit_view=True,
            short_trails=False,
            clear_first=True,
        )

    def render_playback_slice(
        self,
        messages: list[V2xMessage],
        current_index: int,
        *,
        window_seconds: Optional[float] = None,
    ) -> None:
        """Render only the state visible up to the current playback index."""
        if not messages:
            self.clear()
            return
        safe_index = max(0, min(current_index, len(messages) - 1))
        window_start = None
        if window_seconds is not None and window_seconds > 0:
            window_start = messages[safe_index].timestamp.timestamp() - window_seconds
        self._render_messages(
            messages,
            max_index=safe_index,
            window_start_timestamp=window_start,
            fit_view=False,
            short_trails=True,
            clear_first=False,
        )

    def _render_messages(
        self,
        messages: list[V2xMessage],
        *,
        max_index: Optional[int],
        window_start_timestamp: Optional[float] = None,
        fit_view: bool,
        short_trails: bool,
        clear_first: bool,
    ) -> None:
        """Internal renderer for a full load or a playback time slice."""
        # Assign colors and set them in JS
        # Group by station for trajectories
        station_coords: dict[str, list] = {}
        markers_by_id: dict[str, dict[str, object]] = {}
        performance_mode = self.__dict__.get(
            "_performance_mode", MAP_PERFORMANCE_NORMAL
        )
        budget = MAP_RENDER_BUDGETS.get(
            performance_mode,
            MAP_RENDER_BUDGETS[MAP_PERFORMANCE_NORMAL],
        )
        end_index = (
            len(messages) if max_index is None else min(max_index + 1, len(messages))
        )
        display_anchors = _display_anchor_points(messages, max_index=max_index)
        visible_message_count = 0

        for index, msg in enumerate(messages):
            if index >= end_index:
                break
            msg_timestamp = msg.timestamp.timestamp()
            if not _has_display_position(msg) or not _is_near_display_anchors(
                msg, display_anchors
            ):
                continue
            if (
                window_start_timestamp is not None
                and msg_timestamp < window_start_timestamp
                and msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS
            ):
                continue
            visible_message_count += 1
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
                markers_by_id[marker_id_raw] = {
                    "id": marker_id_raw,
                    "stationId": msg.station_id,
                    "lat": marker_lat,
                    "lon": marker_lon,
                    "popup": popup,
                    "color": color,
                    "layerName": "markers",
                }

            # Collect trajectory coordinates
            if msg.msg_type not in NON_STATION_MARKER_TYPES:
                station_coords.setdefault(msg.station_id, []).append(
                    [msg.latitude, msg.longitude]
                )

        infrastructure_payload: list[dict[str, object]] = []
        for overlay in _infrastructure_overlays_for_messages(
            messages, max_index=max_index
        ):
            if (
                performance_mode != MAP_PERFORMANCE_NORMAL
                and overlay["kind"] == "label"
            ):
                continue
            if performance_mode == MAP_PERFORMANCE_DIAGNOSTIC and overlay.get(
                "layer"
            ) not in {
                "map_inbound",
                "map_outbound",
                "map_connections",
                "map_stoplines",
                "map_requests",
                "spat",
            }:
                continue
            overlay_id = str(overlay["id"])
            layer_name = str(overlay["layer"])
            overlay_color = str(overlay["color"])
            if overlay["kind"] == "circle":
                infrastructure_payload.append(
                    {
                        "kind": "circle",
                        "id": overlay_id,
                        "lat": overlay["lat"],
                        "lon": overlay["lon"],
                        "radius": overlay["radius"],
                        "color": overlay_color,
                        "popup": str(overlay.get("popup", "")),
                        "layerName": layer_name,
                    }
                )
            elif overlay["kind"] == "polyline":
                infrastructure_payload.append(
                    {
                        "kind": "polyline",
                        "id": overlay_id,
                        "coords": overlay["coords"],
                        "color": overlay_color,
                        "popup": str(overlay.get("popup", "")),
                        "layerName": layer_name,
                        "weight": overlay.get("weight", 3),
                        "opacity": overlay.get("opacity", 0.85),
                        "dashArray": str(overlay.get("dashArray", "8 6")),
                        "tooltip": str(overlay.get("tooltip", "")),
                    }
                )
            elif overlay["kind"] == "label":
                infrastructure_payload.append(
                    {
                        "kind": "label",
                        "id": overlay_id,
                        "lat": overlay["lat"],
                        "lon": overlay["lon"],
                        "text": str(overlay["text"]),
                        "color": overlay_color,
                        "layerName": layer_name,
                    }
                )

        # Draw trajectories
        trajectories_payload: list[dict[str, object]] = []
        render_trajectories = performance_mode == MAP_PERFORMANCE_NORMAL
        if performance_mode == MAP_PERFORMANCE_SAVER and len(station_coords) <= 25:
            render_trajectories = True
        if performance_mode == MAP_PERFORMANCE_DIAGNOSTIC and len(station_coords) <= 10:
            render_trajectories = True
        for station_id, coords in station_coords.items():
            if not render_trajectories:
                continue
            if short_trails:
                coords = coords[-PLAYBACK_TRAIL_POINTS:]
            trajectories_payload.append(
                {
                    "stationId": station_id,
                    "coords": coords,
                    "color": self._get_station_color(station_id),
                }
            )

        marker_payload = list(markers_by_id.values())
        dropped_markers = max(0, len(marker_payload) - int(budget["markers"]))
        if dropped_markers:
            marker_payload = marker_payload[-int(budget["markers"]) :]

        dropped_infrastructure = max(
            0,
            len(infrastructure_payload) - int(budget["infrastructure"]),
        )
        if dropped_infrastructure:
            infrastructure_payload = infrastructure_payload[
                : int(budget["infrastructure"])
            ]

        dropped_trajectories = max(
            0, len(trajectories_payload) - int(budget["trajectories"])
        )
        if dropped_trajectories:
            trajectories_payload = trajectories_payload[-int(budget["trajectories"]) :]

        dropped_trajectory_points = self._trim_trajectory_payload(
            trajectories_payload,
            int(budget["trajectory_points"]),
        )

        payload = {
            "clear": clear_first,
            "fitView": fit_view,
            "bounds": _payload_bounds(marker_payload, infrastructure_payload),
            "performanceMode": performance_mode,
            "stationColors": self._station_color_map,
            "markers": marker_payload,
            "infrastructure": infrastructure_payload,
            "trajectories": trajectories_payload,
        }
        payload_json = json.dumps(payload)
        self._record_render_telemetry(
            MapRenderTelemetry(
                timestamp=time.time(),
                performance_mode=performance_mode,
                source_message_count=end_index,
                visible_message_count=visible_message_count,
                marker_count=len(marker_payload),
                infrastructure_count=len(infrastructure_payload),
                trajectory_count=len(trajectories_payload),
                trajectory_point_count=sum(
                    len(trajectory["coords"]) for trajectory in trajectories_payload
                ),
                payload_bytes=len(payload_json.encode("utf-8")),
                budget_dropped_markers=dropped_markers,
                budget_dropped_infrastructure=dropped_infrastructure,
                budget_dropped_trajectories=dropped_trajectories,
                budget_dropped_trajectory_points=dropped_trajectory_points,
            )
        )
        self._run_js(f"applyRenderPayload({payload_json})")

    def _trim_trajectory_payload(
        self,
        trajectories_payload: list[dict[str, object]],
        max_points: int,
    ) -> int:
        """Trim old trajectory points to keep the payload inside the mode budget."""
        if max_points <= 0:
            dropped = sum(
                len(trajectory["coords"]) for trajectory in trajectories_payload
            )
            trajectories_payload.clear()
            return dropped
        current_points = sum(
            len(trajectory["coords"]) for trajectory in trajectories_payload
        )
        if current_points <= max_points:
            return 0

        dropped_points = current_points - max_points
        remaining = max_points
        for index, trajectory in enumerate(trajectories_payload):
            coords = trajectory["coords"]
            trajectories_left = len(trajectories_payload) - index
            keep = max(1, remaining // trajectories_left)
            if len(coords) > keep:
                trajectory["coords"] = coords[-keep:]
            remaining -= len(trajectory["coords"])
        return dropped_points

    def _record_render_telemetry(self, telemetry: MapRenderTelemetry) -> None:
        """Store and publish the newest render telemetry."""
        self._latest_telemetry = telemetry
        try:
            self.telemetry_updated.emit(telemetry.to_dict())
        except RuntimeError:
            # Unit tests construct MapWidget without the Qt base initializer.
            pass

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

    def highlight_request(
        self, intersection_id: int, request_id: int, sequence_number: int
    ) -> None:
        """Highlight a rendered prioritization request route."""
        self._run_js(
            f"highlightRequest({intersection_id}, {request_id}, {sequence_number})"
        )

    def focus_intersection(self, intersection_id: int) -> None:
        """Focus the map around one rendered intersection."""
        self._run_js(f"focusIntersection({intersection_id})")

    def showEvent(self, event: QShowEvent) -> None:
        """Refresh Leaflet sizing after Qt exposes the WebEngine view."""
        super().showEvent(event)
        self._schedule_map_resize()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Refresh Leaflet sizing after DPI/window-size changes."""
        super().resizeEvent(event)
        self._schedule_map_resize()

    def clear(self) -> None:
        """Remove all markers and trajectories from the map."""
        self._run_js("clearAll()")
        self._station_color_map.clear()
        self._station_index = 0
        self._follow_station_id = None

    def _schedule_map_resize(self) -> None:
        """Defer Leaflet invalidateSize until Qt has delivered expose/resize."""
        QTimer.singleShot(0, lambda: self._run_js("map.invalidateSize(false)"))

    def _on_marker_clicked(self, station_id: str) -> None:
        """Remember which dynamic object should be followed during playback."""
        self._follow_station_id = station_id

    def _on_load_finished(self, ok: bool) -> None:
        """Flush queued JavaScript once the embedded map page is ready."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        self._page_ready = ok
        self._bootstrap_probe_succeeded = False
        self._render_payload_in_flight = False
        self._queued_render_payload_script = None
        self._render_payload_started_at = None
        if not ok:
            logger.warning("Leaflet map page did not finish loading")
            self._emit_map_issue("Karten-WebView konnte nicht geladen werden")
            return
        logger.info(
            "WebEngine loadFinished(ok=True) — starting Leaflet bootstrap probe"
        )
        self._execute_js(
            "typeof L !== 'undefined' && typeof map !== 'undefined'",
            self._on_bootstrap_probe_finished,
        )
        pending = self._pending_scripts
        self._pending_scripts = []
        for script in pending:
            self._run_js(script)

    def _on_bootstrap_probe_finished(self, result=None) -> None:
        """Report a visible issue if the page loaded but Leaflet did not bootstrap."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if result is True:
            self._bootstrap_probe_succeeded = True
            self._ever_bootstrapped = True
            logger.info("Leaflet bootstrap probe succeeded — map is ready")
        elif result is False:
            logger.warning(
                "Leaflet bootstrap probe returned False — map not initialised"
            )
            self._emit_map_issue(
                "Leaflet wurde geladen, aber die Karte wurde nicht initialisiert"
            )
        else:
            logger.warning(
                "Leaflet bootstrap probe returned %r — treating as failure", result
            )
            self._emit_map_issue("Leaflet-Bootstrap konnte nicht verifiziert werden")

    def _schedule_bootstrap_timeout(self) -> None:
        """Detect WebEngine pages that never finish because Chromium lost its GL context."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        generation = int(self.__dict__.get("_bootstrap_generation", 0)) + 1
        self._bootstrap_generation = generation

        # Use parentless QTimer to survive unit tests that instantiate
        # MapWidget without calling its __init__.
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._check_bootstrap_timeout(generation))
        timer.start(int(MAP_BOOTSTRAP_TIMEOUT_SECONDS * 1000))
        self._bootstrap_timer = timer

    def _check_bootstrap_timeout(self, generation: int) -> None:
        """Report a startup issue when Leaflet never becomes ready."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if generation != self.__dict__.get("_bootstrap_generation", 0):
            logger.debug("Bootstrap timeout ignored: stale generation %d", generation)
            return
        if self.__dict__.get("_bootstrap_probe_succeeded", False):
            logger.debug("Bootstrap timeout suppressed: probe already succeeded")
            return
        if self.__dict__.get("_ever_bootstrapped", False):
            logger.warning(
                "Bootstrap timeout ignored after earlier successful Leaflet bootstrap "
                "(page_ready=%s)",
                self.__dict__.get("_page_ready", False),
            )
            return
        logger.warning(
            "Bootstrap timeout fired after %.0fs — Leaflet probe never succeeded (page_ready=%s)",
            MAP_BOOTSTRAP_TIMEOUT_SECONDS,
            self.__dict__.get("_page_ready", False),
        )
        self._emit_map_issue(
            f"Karten-WebView Initialisierungstimeout nach {MAP_BOOTSTRAP_TIMEOUT_SECONDS:.0f}s"
        )

    def _on_render_process_terminated(self, termination_status, exit_code: int) -> None:
        """Handle Chromium render process crash or abnormal exit."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        logger.error(
            "WebEngine render process terminated: status=%s exit_code=%d",
            termination_status,
            exit_code,
        )
        self._bootstrap_probe_succeeded = False
        self._page_ready = False
        self._emit_map_issue(
            f"WebEngine Render-Prozess beendet (Status={termination_status}, Code={exit_code})"
        )

    def _run_js(self, script: str) -> None:
        """Execute JavaScript in the web page."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if not self._page_ready:
            self._pending_scripts.append(script)
            return
        if script.startswith("applyRenderPayload("):
            if self._render_payload_in_flight:
                self._queued_render_payload_script = script
                self._last_payload_was_replaced = True
                self._mark_latest_telemetry_replaced()
                return
            self._render_payload_in_flight = True
            self._render_payload_started_at = time.monotonic()
            self._schedule_render_stall_check()
            self._execute_js(script, self._on_render_payload_finished)
            return
        self._execute_js(script)

    def _execute_js(self, script: str, callback=None) -> None:
        """Run JavaScript, using a completion callback when Qt supports it."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        try:
            page = self.page()
            if callback is None:
                page.runJavaScript(script, 0)
                return
            try:
                page.runJavaScript(script, 0, callback)
            except TypeError:
                page.runJavaScript(script, 0)
                callback(None)
        except RuntimeError as exc:
            self._disposed = True
            self._render_payload_in_flight = False
            self._queued_render_payload_script = None
            self._render_payload_started_at = None
            logger.debug("Ignored JavaScript call on deleted map widget: %s", exc)

    def _on_render_payload_finished(self, _result=None) -> None:
        """Flush only the newest queued map payload after the previous one completed."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        next_script = self._queued_render_payload_script
        self._queued_render_payload_script = None
        if next_script is None:
            self._render_payload_in_flight = False
            self._render_payload_started_at = None
            return
        self._render_payload_started_at = time.monotonic()
        self._schedule_render_stall_check()
        self._execute_js(next_script, self._on_render_payload_finished)

    def _schedule_render_stall_check(self) -> None:
        """Detect a payload that appears to hang inside QtWebEngine."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        generation = int(self.__dict__.get("_render_payload_stall_generation", 0)) + 1
        self._render_payload_stall_generation = generation

        # Use parentless QTimer to survive unit tests that instantiate
        # MapWidget without calling its __init__.
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._check_render_payload_stall(generation))
        timer.start(int(MAP_RENDER_STALL_SECONDS * 1000))
        self._stall_timer = timer

    def _check_render_payload_stall(self, generation: int) -> None:
        """Emit a map issue if the same render payload is still in flight."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if generation != self._render_payload_stall_generation:
            return
        started_at = self.__dict__.get("_render_payload_started_at")
        if (
            not self.__dict__.get("_render_payload_in_flight", False)
            or started_at is None
        ):
            return
        if time.monotonic() - started_at >= MAP_RENDER_STALL_SECONDS:
            self._emit_map_issue(
                f"Karten-Renderpayload laeuft seit mehr als {MAP_RENDER_STALL_SECONDS:.0f}s"
            )

    def _on_java_script_issue(self, message: str) -> None:
        """Forward JavaScript errors from the map page to the main window."""
        logger.warning("Map JavaScript issue: %s", message)
        self._emit_map_issue(message)

    def _emit_map_issue(self, message: str) -> None:
        """Emit a map issue, tolerating tests that bypass Qt base initialization."""
        try:
            self.map_issue_detected.emit(message)
        except RuntimeError:
            pass

    def _mark_latest_telemetry_replaced(self) -> None:
        """Mark the newest telemetry entry as coalesced by the render queue."""
        telemetry = self.__dict__.get("_latest_telemetry")
        if telemetry is None:
            return
        replaced = MapRenderTelemetry(
            **{
                **telemetry.to_dict(),
                "queued_payload_replaced": True,
            }
        )
        self._record_render_telemetry(replaced)
