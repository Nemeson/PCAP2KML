"""Interactive Leaflet.js map widget embedded in QWebEngineView.

Displays V2X entity markers, trajectories, and supports synchronized
playback highlighting via JavaScript calls.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .data_model import MessageType, V2xMessage

logger = logging.getLogger(__name__)

# Color palette for station markers (hex strings for Leaflet)
STATION_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
]

INFRASTRUCTURE_MESSAGE_COLORS = {
    MessageType.MAPEM: "#1f9d55",
    MessageType.SPATEM: "#c026d3",
}
INFRASTRUCTURE_MESSAGE_OFFSETS = {
    MessageType.MAPEM: (0.0, 0.00003),
    MessageType.SPATEM: (0.0, -0.00003),
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
    <style>
        html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([48.0, 11.0], 13);

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
        var stationColors = {};

        // Called from Python to set station colors
        function setStationColors(colors) {
            stationColors = colors;
        }

        // Called from Python to add a marker
        function addMarker(id, lat, lon, popup, color) {
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
                }).addTo(map).bindPopup(popup);
            }
        }

        // Called from Python to add/update a trajectory line
        function addTrajectory(stationId, coords, color) {
            if (trajectories[stationId]) {
                trajectories[stationId].setLatLngs(coords);
            } else {
                trajectories[stationId] = L.polyline(coords, {
                    color: color, weight: 2, opacity: 0.6
                }).addTo(map);
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

        // Called from Python to fit the map view to all markers
        function fitToMarkers() {
            var group = [];
            for (var key in markers) {
                var ll = markers[key].getLatLng();
                group.push([ll.lat, ll.lng]);
            }
            if (group.length > 0) {
                map.fitBounds(group, { padding: [30, 30], maxZoom: 16 });
            }
        }

        // Called from Python to clear all markers and trajectories
        function clearAll() {
            for (var key in markers) {
                map.removeLayer(markers[key]);
            }
            for (var key in trajectories) {
                map.removeLayer(trajectories[key]);
            }
            markers = {};
            trajectories = {};
        }

        // Bridge for Python communication
        new QWebChannel(qt.webChannelTransport, function(channel) {
            window.bridge = channel.objects.bridge;
        });
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
        """Load all messages onto the map: markers and trajectories."""
        self._run_js("clearAll()")

        # Assign colors and set them in JS
        colors_js = json.dumps(self._station_color_map)
        self._run_js(f"setStationColors({colors_js})")

        # Group by station for trajectories
        station_coords: dict[str, list] = {}
        station_last_msg: dict[str, V2xMessage] = {}

        for msg in messages:
            color = self._color_for_message(msg)
            marker_lat, marker_lon = _marker_position_for_message(msg)
            popup = (
                f"<b>{msg.msg_type.value}</b><br>"
                f"Station: {msg.station_id}<br>"
                f"Time: {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}<br>"
                f"Pos: {msg.latitude:.6f}, {msg.longitude:.6f}"
            )

            # Place marker at latest position
            marker_id = _js_escape(_marker_id_for_message(msg))
            popup_js = _js_escape(popup)
            color_js = _js_escape(color)
            self._run_js(
                f"addMarker('{marker_id}', {marker_lat}, {marker_lon}, "
                f"'{popup_js}', '{color_js}')"
            )
            station_last_msg[msg.station_id] = msg

            # Collect trajectory coordinates
            station_coords.setdefault(msg.station_id, []).append(
                [msg.latitude, msg.longitude]
            )

        # Draw trajectories
        for station_id, coords in station_coords.items():
            color = _js_escape(self._get_station_color(station_id))
            coords_js = json.dumps(coords)
            self._run_js(f"addTrajectory('{_js_escape(station_id)}', {coords_js}, '{color}')")

        # Fit map to all markers
        self._run_js("fitToMarkers()")

    def update_playback_position(self, msg: V2xMessage) -> None:
        """Move the marker for msg.station_id and highlight it."""
        self._color_for_message(msg)
        marker_id = _js_escape(_marker_id_for_message(msg))
        self._run_js(f"highlightMarker('{marker_id}')")

    def clear(self) -> None:
        """Remove all markers and trajectories from the map."""
        self._run_js("clearAll()")
        self._station_color_map.clear()
        self._station_index = 0

    def _run_js(self, script: str) -> None:
        """Execute JavaScript in the web page."""
        self.page().runJavaScript(script, 0)
