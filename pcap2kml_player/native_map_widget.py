"""Qt-native fallback map for systems where QtWebEngine cannot create GL contexts."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from math import cos, hypot, radians
from typing import Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView

from .data_model import MessageType, V2xMessage
from .map_backend import (
    MAP_PERFORMANCE_DIAGNOSTIC,
    MAP_PERFORMANCE_MODES,
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
)
from .scene_model import build_scene_snapshot

PLAYBACK_TRAIL_POINTS = 8
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
NON_STATION_MARKER_TYPES = {
    MessageType.MAPEM,
    MessageType.SPATEM,
    MessageType.SSEM,
}


@dataclass(frozen=True)
class NativeMapTelemetry:
    """Compact diagnostics with the same keys as the WebEngine map telemetry."""

    timestamp: float
    performance_mode: str
    source_message_count: int
    visible_message_count: int
    marker_count: int
    infrastructure_count: int
    trajectory_count: int
    trajectory_point_count: int
    payload_bytes: int = 0
    queued_payload_replaced: bool = False
    budget_dropped_markers: int = 0
    budget_dropped_infrastructure: int = 0
    budget_dropped_trajectories: int = 0
    budget_dropped_trajectory_points: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class NativeMapWidget(QGraphicsView):
    """A lightweight local map that avoids QtWebEngine and GPU compositing."""

    telemetry_updated = pyqtSignal(dict)
    map_issue_detected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#eef4fb"))
        self._station_color_map: dict[str, str] = {}
        self._station_index = 0
        self._performance_mode = MAP_PERFORMANCE_NORMAL
        self._latest_telemetry: Optional[NativeMapTelemetry] = None
        self._last_messages: list[V2xMessage] = []
        self._highlighted_request: Optional[tuple[int, int, int]] = None
        self._focused_intersection: Optional[int] = None
        self.setMinimumSize(200, 150)
        self._draw_ready_hint()

    def set_performance_mode(self, mode: str) -> None:
        if mode not in MAP_PERFORMANCE_MODES:
            mode = MAP_PERFORMANCE_NORMAL
        self._performance_mode = mode
        if self._last_messages:
            self.load_messages(self._last_messages)

    def latest_telemetry(self) -> Optional[dict[str, object]]:
        if self._latest_telemetry is None:
            return None
        return self._latest_telemetry.to_dict()

    def reload_map_page(self) -> None:
        self.load_messages(self._last_messages)

    def load_messages(self, messages: list[V2xMessage]) -> None:
        self._last_messages = list(messages)
        self._render_messages(messages, max_index=None, fit_view=True, short_trails=False)

    def render_playback_slice(
        self,
        messages: list[V2xMessage],
        current_index: int,
        *,
        window_seconds: Optional[float] = None,
    ) -> None:
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
        )

    def update_playback_position(self, msg: V2xMessage) -> None:
        if not self._last_messages:
            self.load_messages([msg])

    def highlight_request(self, intersection_id: int, request_id: int, sequence_number: int) -> None:
        self._highlighted_request = (intersection_id, request_id, sequence_number)
        if self._last_messages:
            self.load_messages(self._last_messages)

    def focus_intersection(self, intersection_id: int) -> None:
        self._focused_intersection = intersection_id

    def clear(self) -> None:
        self._scene.clear()
        self._station_color_map.clear()
        self._station_index = 0
        self._last_messages = []
        self._record_telemetry(
            NativeMapTelemetry(
                timestamp=time.time(),
                performance_mode=self._performance_mode,
                source_message_count=0,
                visible_message_count=0,
                marker_count=0,
                infrastructure_count=0,
                trajectory_count=0,
                trajectory_point_count=0,
            )
        )

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def _render_messages(
        self,
        messages: list[V2xMessage],
        *,
        max_index: Optional[int],
        window_start_timestamp: Optional[float] = None,
        fit_view: bool,
        short_trails: bool,
    ) -> None:
        self._scene.clear()
        end_index = len(messages) if max_index is None else min(max_index + 1, len(messages))
        visible = [
            msg
            for msg in messages[:end_index]
            if _has_display_position(msg)
            and (
                window_start_timestamp is None
                or msg.timestamp.timestamp() >= window_start_timestamp
                or msg.msg_type in INFRASTRUCTURE_MESSAGE_COLORS
            )
        ]
        infrastructure_overlays = _native_infrastructure_overlays(messages[:end_index])
        bounds = _bounds_for_positions(
            [(msg.latitude, msg.longitude) for msg in visible]
            + _overlay_points(infrastructure_overlays)
        )
        if bounds is None:
            self._draw_empty_hint()
            self._record_telemetry(
                NativeMapTelemetry(
                    timestamp=time.time(),
                    performance_mode=self._performance_mode,
                    source_message_count=end_index,
                    visible_message_count=0,
                    marker_count=0,
                    infrastructure_count=0,
                    trajectory_count=0,
                    trajectory_point_count=0,
                )
            )
            return

        for overlay in infrastructure_overlays:
            self._draw_overlay(overlay, bounds)

        projected = [_project_message(msg, bounds) for msg in visible]
        station_coords: dict[str, list[tuple[float, float]]] = {}
        latest_station_points: dict[str, tuple[V2xMessage, tuple[float, float]]] = {}
        infrastructure_count = len(infrastructure_overlays)
        for msg, point in projected:
            if msg.msg_type in INFRASTRUCTURE_MESSAGE_COLORS:
                if not infrastructure_overlays:
                    self._draw_infrastructure(msg, point)
                    infrastructure_count += 1
                continue
            if msg.msg_type in NON_STATION_MARKER_TYPES:
                continue
            station_coords.setdefault(msg.station_id, []).append(point)
            latest_station_points[msg.station_id] = (msg, point)

        trajectory_count = 0
        trajectory_point_count = 0
        if self._performance_mode != MAP_PERFORMANCE_DIAGNOSTIC:
            for station_id, coords in station_coords.items():
                if short_trails:
                    coords = coords[-PLAYBACK_TRAIL_POINTS:]
                if self._performance_mode == MAP_PERFORMANCE_SAVER and len(station_coords) > 25:
                    continue
                self._draw_trajectory(coords, self._station_color(station_id))
                trajectory_count += 1
                trajectory_point_count += len(coords)

        for station_id, (msg, point) in latest_station_points.items():
            self._draw_marker(msg, point, self._station_color(station_id))

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))
        if fit_view:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._record_telemetry(
            NativeMapTelemetry(
                timestamp=time.time(),
                performance_mode=self._performance_mode,
                source_message_count=end_index,
                visible_message_count=len(visible),
                marker_count=len(latest_station_points),
                infrastructure_count=infrastructure_count,
                trajectory_count=trajectory_count,
                trajectory_point_count=trajectory_point_count,
            )
        )

    def _draw_empty_hint(self) -> None:
        text = QGraphicsTextItem("Keine gueltigen Kartenpositionen verfuegbar")
        text.setDefaultTextColor(QColor("#42546b"))
        text.setPos(20, 20)
        self._scene.addItem(text)

    def _draw_ready_hint(self) -> None:
        bg = QGraphicsRectItem(QRectF(0, 0, 420, 80))
        bg.setBrush(QColor("#d0e8f7"))
        bg.setPen(QPen(QColor("#90bcd8"), 1.0))
        self._scene.addItem(bg)

        title = QGraphicsTextItem("Qt-Native Kartenansicht")
        title.setDefaultTextColor(QColor("#1e3a5f"))
        title.setPos(14, 8)
        self._scene.addItem(title)

        hint = QGraphicsTextItem("Leaflet/WebEngine nicht verfügbar — PCAP laden, um Nachrichten anzuzeigen")
        hint.setDefaultTextColor(QColor("#42546b"))
        hint.setPos(14, 36)
        self._scene.addItem(hint)

        self._scene.setSceneRect(QRectF(0, 0, 420, 160))

    def _draw_marker(self, msg: V2xMessage, point: tuple[float, float], color: str) -> None:
        radius = 7.0
        item = QGraphicsEllipseItem(point[0] - radius, point[1] - radius, radius * 2, radius * 2)
        item.setBrush(QColor(color))
        item.setPen(QPen(QColor("#10233f"), 1.5))
        item.setToolTip(
            f"{msg.msg_type.value}\nStation: {msg.station_id}\n"
            f"Zeit: {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}\n"
            f"Position: {msg.latitude:.6f}, {msg.longitude:.6f}"
        )
        self._scene.addItem(item)

    def _draw_infrastructure(self, msg: V2xMessage, point: tuple[float, float]) -> None:
        radius = 11.0
        color = INFRASTRUCTURE_MESSAGE_COLORS.get(msg.msg_type, "#475569")
        item = QGraphicsEllipseItem(point[0] - radius, point[1] - radius, radius * 2, radius * 2)
        item.setBrush(QColor(color))
        item.setPen(QPen(QColor("#ffffff"), 2.0))
        item.setToolTip(f"{msg.msg_type.value}\nStation: {msg.station_id}")
        self._scene.addItem(item)
        label = QGraphicsTextItem(msg.msg_type.value)
        label.setDefaultTextColor(QColor("#10233f"))
        label.setPos(point[0] + 12, point[1] - 12)
        self._scene.addItem(label)

    def _draw_trajectory(self, coords: list[tuple[float, float]], color: str) -> None:
        if len(coords) < 2:
            return
        path = QPainterPath()
        path.moveTo(*coords[0])
        for point in coords[1:]:
            path.lineTo(*point)
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor(color), 2.0, Qt.PenStyle.SolidLine))
        item.setOpacity(0.65)
        self._scene.addItem(item)

    def _draw_overlay(self, overlay: dict[str, object], bounds: tuple[float, float, float, float]) -> None:
        if overlay.get("kind") == "polyline":
            coords = [_project_point((float(lat), float(lon)), bounds) for lat, lon in overlay["coords"]]
            if len(coords) < 2:
                return
            self._draw_polyline(
                coords,
                str(overlay.get("color", "#475569")),
                float(overlay.get("weight", 3.0)),
                str(overlay.get("dash", "")),
                str(overlay.get("popup", "")),
            )
        elif overlay.get("kind") == "label" and self._performance_mode == MAP_PERFORMANCE_NORMAL:
            point = _project_point((float(overlay["lat"]), float(overlay["lon"])), bounds)
            label = QGraphicsTextItem(str(overlay.get("text", "")))
            label.setDefaultTextColor(QColor(str(overlay.get("color", "#10233f"))))
            label.setPos(point[0] + 4, point[1] + 4)
            self._scene.addItem(label)

    def _draw_polyline(
        self,
        coords: list[tuple[float, float]],
        color: str,
        weight: float,
        dash: str,
        tooltip: str,
    ) -> None:
        path = QPainterPath()
        path.moveTo(*coords[0])
        for point in coords[1:]:
            path.lineTo(*point)
        item = QGraphicsPathItem(path)
        pen = QPen(QColor(color), weight)
        if dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setOpacity(0.9)
        if tooltip:
            item.setToolTip(tooltip)
        self._scene.addItem(item)

    def _station_color(self, station_id: str) -> str:
        if station_id not in self._station_color_map:
            self._station_color_map[station_id] = STATION_PALETTE[
                self._station_index % len(STATION_PALETTE)
            ]
            self._station_index += 1
        return self._station_color_map[station_id]

    def _record_telemetry(self, telemetry: NativeMapTelemetry) -> None:
        self._latest_telemetry = telemetry
        self.telemetry_updated.emit(telemetry.to_dict())


def _has_display_position(msg: V2xMessage) -> bool:
    if not (-90 <= msg.latitude <= 90 and -180 <= msg.longitude <= 180):
        return False
    return not (abs(msg.latitude) < 1e-9 and abs(msg.longitude) < 1e-9)


def _bounds_for_messages(messages: list[V2xMessage]) -> Optional[tuple[float, float, float, float]]:
    return _bounds_for_positions([(msg.latitude, msg.longitude) for msg in messages])


def _bounds_for_positions(points: list[tuple[float, float]]) -> Optional[tuple[float, float, float, float]]:
    if not points:
        return None
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    if abs(max_lat - min_lat) < 1e-9:
        min_lat -= 0.0005
        max_lat += 0.0005
    if abs(max_lon - min_lon) < 1e-9:
        min_lon -= 0.0005
        max_lon += 0.0005
    return (min_lat, max_lat, min_lon, max_lon)


def _project_message(
    msg: V2xMessage,
    bounds: tuple[float, float, float, float],
) -> tuple[V2xMessage, tuple[float, float]]:
    return msg, _project_point((msg.latitude, msg.longitude), bounds)


def _project_point(
    point: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float]:
    min_lat, max_lat, min_lon, max_lon = bounds
    width = 1200.0
    height = 800.0
    mid_lat = (min_lat + max_lat) / 2.0
    lon_scale = max(0.2, cos(radians(mid_lat)))
    x = ((point[1] - min_lon) * lon_scale / max(1e-9, (max_lon - min_lon) * lon_scale)) * width
    y = (1.0 - ((point[0] - min_lat) / max(1e-9, max_lat - min_lat))) * height
    return (x, y)


def _overlay_points(overlays: list[dict[str, object]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for overlay in overlays:
        if overlay.get("kind") == "polyline":
            points.extend((float(lat), float(lon)) for lat, lon in overlay.get("coords", []))
        elif overlay.get("kind") == "label":
            points.append((float(overlay["lat"]), float(overlay["lon"])))
    return points


def _native_infrastructure_overlays(messages: list[V2xMessage]) -> list[dict[str, object]]:
    if not messages:
        return []
    timeline_position = messages[-1].timestamp
    scene = build_scene_snapshot(messages, timeline_position)
    latest_map: dict[str, tuple[V2xMessage, dict]] = {}
    for msg in messages:
        if msg.msg_type != MessageType.MAPEM:
            continue
        for intersection in _iter_message_intersections(msg):
            key = _intersection_key(intersection, msg)
            current = latest_map.get(key)
            if current is None or current[0].timestamp <= msg.timestamp:
                latest_map[key] = (msg, intersection)

    overlays: list[dict[str, object]] = []
    for key, (msg, intersection) in latest_map.items():
        map_point = _intersection_point(intersection, msg)
        intersection_id = _coerce_int(intersection.get("intersectionId", intersection.get("id")))
        request_visuals = scene.request_visuals_by_intersection.get(intersection_id, []) if intersection_id is not None else []
        lane_set = intersection.get("laneSet")
        if not isinstance(lane_set, list):
            continue
        lane_by_id = {
            _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id")))): lane
            for lane in lane_set
            if isinstance(lane, dict)
        }
        for lane_index, lane in enumerate(lane_set):
            if not isinstance(lane, dict):
                continue
            points = _lane_points(lane)
            if len(points) < 2:
                continue
            lane_id = _coerce_int(lane.get("laneId", lane.get("laneID", lane.get("id"))))
            role = _lane_role(lane)
            overlays.append({
                "kind": "polyline",
                "coords": points,
                "color": LANE_ROLE_COLORS.get(role, INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM]),
                "weight": 3.0,
                "popup": f"Lane {lane_id or '-'} | {role or 'unknown'}",
            })
            label_point = points[len(points) // 2]
            overlays.append({
                "kind": "label",
                "lat": label_point[0],
                "lon": label_point[1],
                "text": f"Lane {lane_id or '-'} {role or ''}".strip(),
                "color": LANE_ROLE_COLORS.get(role, "#10233f"),
            })
            stopline = _stopline_points(lane)
            if stopline is not None:
                overlays.append({
                    "kind": "polyline",
                    "coords": stopline,
                    "color": STOPLINE_COLOR,
                    "weight": 4.0,
                    "popup": f"Stopline | Lane {lane_id or '-'}",
                })
            connections = lane.get("connections", lane.get("connectsTo"))
            if isinstance(connections, list):
                for connection in connections:
                    if not isinstance(connection, dict):
                        continue
                    target_lane_id = _coerce_int(connection.get("targetLaneId", connection.get("connectingLane")))
                    target_lane = lane_by_id.get(target_lane_id)
                    if not isinstance(target_lane, dict):
                        continue
                    connection_points = _connection_curve_points(lane, target_lane, map_point)
                    if connection_points is None:
                        continue
                    overlays.append({
                        "kind": "polyline",
                        "coords": connection_points,
                        "color": INFRASTRUCTURE_MESSAGE_COLORS[MessageType.MAPEM],
                        "weight": 3.0,
                        "dash": "8 6",
                        "popup": f"Connection | Lane {lane_id or '-'} -> {target_lane_id}",
                    })
                    for request in request_visuals:
                        if request.in_lane == lane_id and request.out_lane == target_lane_id:
                            overlays.append({
                                "kind": "polyline",
                                "coords": _offset_polyline(connection_points, _request_overlay_offset_m(request.display_rank)),
                                "color": REQUEST_STATUS_COLORS.get(request.status.value, "#2563eb"),
                                "weight": 6.0 if request.is_dominant else 4.0,
                                "dash": "" if request.is_dominant else "6 6",
                                "popup": f"Request {request.request_id}/{request.sequence_number} | {request.status.value}",
                            })
            for request in request_visuals:
                if request.in_lane == lane_id or request.out_lane == lane_id:
                    overlays.append({
                        "kind": "polyline",
                        "coords": _offset_polyline(points, _request_overlay_offset_m(request.display_rank)),
                        "color": REQUEST_STATUS_COLORS.get(request.status.value, "#2563eb"),
                        "weight": 5.0 if request.is_dominant else 3.5,
                        "dash": "" if request.is_dominant else "6 6",
                        "popup": f"Request {request.request_id}/{request.sequence_number} | {request.status.value}",
                    })
    return overlays


def _iter_message_intersections(msg: V2xMessage) -> list[dict]:
    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list) and intersections:
        return [intersection for intersection in intersections if isinstance(intersection, dict)]
    return [{}]


def _coerce_lat_lon(value: object) -> Optional[tuple[float, float]]:
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


def _coerce_int(value: object) -> Optional[int]:
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
    if isinstance(value, tuple) and len(value) >= 2:
        return _coerce_int(value[1])
    if isinstance(value, dict):
        for key in ("id", "value", "lane", "signalGroup"):
            nested = _coerce_int(value.get(key))
            if nested is not None:
                return nested
    return None


def _intersection_point(intersection: dict, msg: V2xMessage) -> tuple[float, float]:
    for key in ("refPoint", "referencePoint", "refPos", "referencePosition"):
        point = _coerce_lat_lon(intersection.get(key))
        if point is not None:
            return point
    return (msg.latitude, msg.longitude)


def _intersection_key(intersection: dict, msg: V2xMessage) -> str:
    for key in ("intersectionId", "id"):
        numeric = _coerce_int(intersection.get(key))
        if numeric is not None:
            return f"id:{numeric}"
    point = _intersection_point(intersection, msg)
    return f"pos:{round(point[0], 4):.4f}:{round(point[1], 4):.4f}"


def _lane_points(lane: dict) -> list[tuple[float, float]]:
    node_list = lane.get("nodeList", lane.get("node-list"))
    nodes = node_list.get("nodes", node_list.get("nodeSetXY")) if isinstance(node_list, dict) else node_list
    if not isinstance(nodes, list):
        return []
    points: list[tuple[float, float]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        point = _coerce_lat_lon(node)
        if point is None:
            point = _coerce_lat_lon(node.get("delta"))
        if point is not None:
            points.append(point)
    return points


def _lane_role(lane: dict) -> Optional[str]:
    role = lane.get("laneRole")
    if isinstance(role, str):
        return role
    if lane.get("ingressApproach") is not None:
        return "inbound"
    if lane.get("egressApproach") is not None:
        return "outbound"
    return None


def _stopline_points(lane: dict) -> Optional[list[tuple[float, float]]]:
    stop_line = lane.get("stopLine")
    if not isinstance(stop_line, dict):
        return None
    points = stop_line.get("points")
    if not isinstance(points, list):
        return None
    normalized = [_coerce_lat_lon(point) for point in points if isinstance(point, dict)]
    normalized = [point for point in normalized if point is not None]
    return normalized if len(normalized) >= 2 else None


def _lane_anchor_points(
    lane: dict,
    intersection_point: tuple[float, float],
) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
    points = _lane_points(lane)
    if len(points) < 2:
        return None
    start_distance = _point_distance_meters(points[0], intersection_point)
    end_distance = _point_distance_meters(points[-1], intersection_point)
    return (points[0], points[-1]) if start_distance <= end_distance else (points[-1], points[0])


def _connection_curve_points(
    source_lane: dict,
    target_lane: dict,
    intersection_point: tuple[float, float],
) -> Optional[list[tuple[float, float]]]:
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


def _point_distance_meters(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    lat_scale = 111_320.0
    lon_scale = max(1e-6, 111_320.0 * cos(radians((point_a[0] + point_b[0]) / 2.0)))
    dx = (point_a[1] - point_b[1]) * lon_scale
    dy = (point_a[0] - point_b[0]) * lat_scale
    return hypot(dx, dy)


def _request_overlay_offset_m(display_rank: int) -> float:
    if display_rank <= 0:
        return 0.0
    step = ((display_rank + 1) // 2) * 2.5
    return step if display_rank % 2 == 1 else -step


def _offset_polyline(coords: list[tuple[float, float]], offset_m: float) -> list[tuple[float, float]]:
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
        shifted.append((point[0] + (((dx / length) * offset_m) / lat_scale), point[1] - (((dy / length) * offset_m) / lon_scale)))
    return shifted
