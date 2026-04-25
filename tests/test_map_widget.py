"""Tests for JavaScript escaping helpers in the map widget."""

import json
from datetime import datetime, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.map_widget import (
    MAP_PERFORMANCE_DIAGNOSTIC,
    MAP_PERFORMANCE_NORMAL,
    MAP_RENDER_BUDGETS,
    MAP_PERFORMANCE_SAVER,
    MapWidget,
    _asset_base_path,
    _leaflet_runtime_html,
    _display_anchor_points,
    _has_display_position,
    _is_near_display_anchors,
    _infrastructure_overlays_for_message,
    _infrastructure_overlays_for_messages,
    _js_escape,
    _marker_id_for_message,
    _marker_position_for_message,
    _payload_bounds,
    _spat_color_for_intersection,
    LEAFLET_HTML,
)


def test_js_escape_handles_problematic_sequences():
    raw = "RSU` ${payload} </script> 'line'\nnext\rrow\x00"
    escaped = _js_escape(raw)

    assert "\\`" in escaped
    assert "\\${" in escaped
    assert "</script>" not in escaped.lower()
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert "\x00" not in escaped
    assert "\\'" in escaped
    assert "<\\/script>" in escaped


def test_marker_id_for_map_and_spat_stays_separate():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
    )
    cam_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 2, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )

    assert _marker_id_for_message(map_msg) != _marker_id_for_message(spat_msg)
    assert _marker_id_for_message(cam_msg) == "station_rsu-1"


def test_marker_position_offsets_map_and_spat_to_keep_both_visible():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
    )

    assert _marker_position_for_message(map_msg) != _marker_position_for_message(
        spat_msg
    )


def test_has_display_position_rejects_null_island_sentinel():
    msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="denm-rsu",
        msg_type=MessageType.DENM,
        latitude=0.0,
        longitude=0.0,
    )

    assert _has_display_position(msg) is False


def test_infrastructure_overlays_create_raw_circle_for_undecoded_map_message():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={},
    )

    overlays = _infrastructure_overlays_for_message(map_msg)

    assert any(overlay["kind"] == "circle" for overlay in overlays)
    assert any(overlay["kind"] == "label" for overlay in overlays)
    circle = next(overlay for overlay in overlays if overlay["kind"] == "circle")
    assert circle["lat"] == 52.0
    assert circle["lon"] == 13.0
    assert circle["layer"] == "map"


def test_infrastructure_overlays_create_lane_polylines_for_decoded_map_geometry():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                            "stopLine": {
                                "points": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0000, "lon": 13.0001},
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    )

    overlays = _infrastructure_overlays_for_message(map_msg)

    assert any(overlay["kind"] == "circle" for overlay in overlays)
    assert any(overlay["kind"] == "polyline" for overlay in overlays)
    assert any(
        overlay["kind"] == "polyline" and overlay["layer"] == "map_stoplines"
        for overlay in overlays
    )
    assert any(
        overlay["kind"] == "label" and overlay["text"] == "Lane 17"
        for overlay in overlays
    )


def test_spat_color_for_intersection_uses_decoded_phase_state():
    intersection = {
        "states": [
            {
                "signalGroup": 3,
                "stateTimeSpeed": [
                    {"eventState": "protected-Movement-Allowed"},
                ],
            }
        ]
    }

    assert _spat_color_for_intersection(intersection) == "#16a34a"


def test_infrastructure_overlays_create_spat_label_and_phase_color():
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "states": [
                        {
                            "signalGroup": 5,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "stop-And-Remain",
                                    "timing": {
                                        "likelyTime": 42,
                                        "timeConfidence": "high",
                                    },
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )

    overlays = _infrastructure_overlays_for_message(spat_msg)

    circle = next(overlay for overlay in overlays if overlay["kind"] == "circle")
    label = next(overlay for overlay in overlays if overlay["kind"] == "label")
    assert circle["color"] == "#dc2626"
    assert circle["layer"] == "spat"
    assert "Intersection 42" in label["text"]
    assert "stop-And-Remain" in label["text"]


def test_infrastructure_overlays_for_messages_colors_connection_by_matching_spat_group():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "connections": [{"signalGroup": 5, "targetLaneId": 18}],
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                        },
                        {
                            "laneID": 18,
                            "laneRole": "outbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0002, "lon": 13.0003},
                                    {"lat": 52.0003, "lon": 13.0004},
                                ]
                            },
                        },
                    ],
                }
            ]
        },
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "states": [
                        {
                            "signalGroup": 5,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "stop-And-Remain",
                                    "timing": {
                                        "likelyTime": 42,
                                        "timeConfidence": "high",
                                    },
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )

    overlays = _infrastructure_overlays_for_messages([map_msg, spat_msg])

    inbound_lane_overlay = next(
        overlay
        for overlay in overlays
        if overlay["kind"] == "polyline" and overlay["layer"] == "map_inbound"
    )
    connection_overlay = next(
        overlay
        for overlay in overlays
        if overlay["kind"] == "polyline" and overlay["layer"] == "map_connections"
    )
    lane_label = next(
        overlay
        for overlay in overlays
        if overlay["kind"] == "label" and "Lane 17" in overlay["text"]
    )
    assert inbound_lane_overlay["color"] == "#0f766e"
    assert connection_overlay["color"] == "#dc2626"
    assert "SG 5" in connection_overlay["popup"]
    assert "stop-And-Remain" in connection_overlay["popup"]
    assert "MovementState: stop-And-Remain" in connection_overlay["tooltip"]
    assert "likelyTime: 42" in connection_overlay["tooltip"]
    assert "inbound" in lane_label["text"]


def test_infrastructure_overlays_for_messages_create_stopline_layer_for_inbound_lane():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                            "stopLine": {
                                "points": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0000, "lon": 13.0001},
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    )

    overlays = _infrastructure_overlays_for_messages([map_msg])

    stopline_overlay = next(
        overlay
        for overlay in overlays
        if overlay["kind"] == "polyline" and overlay["layer"] == "map_stoplines"
    )

    assert stopline_overlay["color"] == "#f97316"
    assert "Stopline" in stopline_overlay["popup"]


def test_infrastructure_overlays_for_messages_create_request_overlays_for_lane_and_connection():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneId": 17,
                            "laneRole": "inbound",
                            "connections": [{"signalGroup": 5, "targetLaneId": 18}],
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                        },
                        {
                            "laneID": 18,
                            "laneId": 18,
                            "laneRole": "outbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0002, "lon": 13.0003},
                                    {"lat": 52.0003, "lon": 13.0004},
                                ]
                            },
                        },
                    ],
                }
            ]
        },
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "states": [
                        {
                            "signalGroup": 5,
                            "stateTimeSpeed": [{"eventState": "stop-And-Remain"}],
                        }
                    ],
                }
            ]
        },
    )
    dominant_request = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 2, tzinfo=timezone.utc),
        station_id="bus-1",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 7,
            "sequenceNumber": 1,
            "importanceLevel": 12,
            "inLane": 17,
            "outLane": 18,
        },
    )
    secondary_request = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 2, 500000, tzinfo=timezone.utc),
        station_id="tram-2",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 8,
            "sequenceNumber": 1,
            "importanceLevel": 8,
            "inLane": 17,
            "outLane": 18,
        },
    )
    ssem_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 3, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SSEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 7,
            "sequenceNumber": 1,
            "requestState": "granted",
        },
    )

    overlays = _infrastructure_overlays_for_messages(
        [map_msg, spat_msg, dominant_request, secondary_request, ssem_msg]
    )

    request_overlays = [
        overlay
        for overlay in overlays
        if overlay["kind"] == "polyline" and overlay["layer"] == "map_requests"
    ]

    assert request_overlays
    assert any(
        overlay["weight"] == 6 and overlay["color"] == "#16a34a"
        for overlay in request_overlays
    )
    assert any(
        overlay["weight"] == 4 and overlay["dashArray"] == "6 6"
        for overlay in request_overlays
    )
    assert any(
        "Priorisierung" in overlay["popup"] and "granted" in overlay["popup"]
        for overlay in request_overlays
    )
    connection_request_overlays = [
        overlay for overlay in request_overlays if "connection" in overlay["id"]
    ]
    assert len(connection_request_overlays) >= 2
    assert (
        connection_request_overlays[0]["coords"]
        != connection_request_overlays[1]["coords"]
    )


def test_leaflet_html_exposes_layer_toggles_and_label_renderer():
    assert "Hell / Schwarz-Weiss" in LEAFLET_HTML
    assert 'href="leaflet/leaflet.css"' in LEAFLET_HTML
    assert 'src="leaflet/leaflet.js"' in LEAFLET_HTML
    assert "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" in LEAFLET_HTML
    assert "OSM Standard" in LEAFLET_HTML
    assert "Dunkel" in LEAFLET_HTML
    assert "Satellit" in LEAFLET_HTML
    assert "World_Imagery" in LEAFLET_HTML
    assert "function readStoredBaseLayerName()" in LEAFLET_HTML
    assert "function storeBaseLayerName(name)" in LEAFLET_HTML
    assert "readStoredBaseLayerName() || 'OSM Standard'" in LEAFLET_HTML
    assert "var preferredBaseLayerName = localStorage.getItem" not in LEAFLET_HTML
    assert "localStorage.setItem('pcap2kml.baseLayer', event.name)" not in LEAFLET_HTML
    assert "});\n            }\n        });" not in LEAFLET_HTML
    assert "L.control.layers(baseLayers" in LEAFLET_HTML
    assert "MAP-Punkte" in LEAFLET_HTML
    assert "Inbound-Lanes" in LEAFLET_HTML
    assert "Outbound-Lanes" in LEAFLET_HTML
    assert "Connections" in LEAFLET_HTML
    assert "Requests" in LEAFLET_HTML
    assert "Stoplines" in LEAFLET_HTML
    assert "SPAT-Punkte" in LEAFLET_HTML
    assert "addInfrastructureLabel" in LEAFLET_HTML
    assert "bindTooltip" in LEAFLET_HTML
    assert "highlightRequest" in LEAFLET_HTML
    assert "focusIntersection" in LEAFLET_HTML
    assert "qrc:///qtwebchannel/qwebchannel.js" in LEAFLET_HTML
    assert "typeof QWebChannel !== 'undefined'" in LEAFLET_HTML
    assert "map.invalidateSize(false)" in LEAFLET_HTML
    assert "function setMapPerformanceMode(mode)" in LEAFLET_HTML
    assert "Leaflet unavailable; map bootstrap aborted." in LEAFLET_HTML
    assert "fitToPayloadBounds(payload.bounds || null)" in LEAFLET_HTML
    assert "function fitToPayloadBounds(bounds)" in LEAFLET_HTML
    assert "map: L.layerGroup()," in LEAFLET_HTML
    assert "spat: L.layerGroup()" in LEAFLET_HTML
    assert "map: L.layerGroup().addTo(map)" not in LEAFLET_HTML
    assert "spat: L.layerGroup().addTo(map)" not in LEAFLET_HTML


def test_payload_bounds_include_markers_and_infrastructure():
    bounds = _payload_bounds(
        markers=[
            {"lat": 48.895, "lon": 9.208},
            {"lat": "invalid", "lon": 9.0},
        ],
        infrastructure=[
            {"kind": "polyline", "coords": [[48.894, 9.207], [48.896, 9.21]]},
            {"kind": "label", "lat": 48.893, "lon": 9.206},
            {"kind": "label", "lat": 99.0, "lon": 9.0},
        ],
    )

    assert bounds == [[48.893, 9.206], [48.896, 9.21]]


def test_payload_bounds_expand_single_point():
    bounds = _payload_bounds(
        markers=[{"lat": 48.895, "lon": 9.208}],
        infrastructure=[],
    )

    assert bounds is not None
    assert round(bounds[0][0], 4) == 48.8945
    assert round(bounds[0][1], 4) == 9.2075
    assert round(bounds[1][0], 4) == 48.8955
    assert round(bounds[1][1], 4) == 9.2085


class _FakePage:
    def __init__(self):
        self.scripts: list[str] = []

    def runJavaScript(self, script: str, _world_id: int) -> None:
        self.scripts.append(script)


class _CallbackPage:
    def __init__(self):
        self.scripts: list[str] = []
        self.callbacks = []

    def runJavaScript(self, script: str, _world_id: int, callback=None) -> None:
        self.scripts.append(script)
        if callback is not None:
            self.callbacks.append(callback)


class _NoSliceMessages(list):
    def __getitem__(self, item):
        if isinstance(item, slice):
            raise AssertionError("playback rendering must not copy message slices")
        return super().__getitem__(item)


def _render_payload(captured_scripts: list[str]) -> dict:
    script = next(
        script
        for script in captured_scripts
        if script.startswith("applyRenderPayload(")
    )
    return json.loads(script.removeprefix("applyRenderPayload(").removesuffix(")"))


def test_run_js_queues_until_map_page_is_loaded():
    widget = MapWidget.__new__(MapWidget)
    fake_page = _FakePage()
    widget._page_ready = False
    widget._pending_scripts = []
    widget.page = lambda: fake_page

    widget._run_js("first()")

    assert widget._pending_scripts == ["first()"]
    assert fake_page.scripts == []

    widget._on_load_finished(True)

    assert widget._pending_scripts == []
    assert fake_page.scripts[-1] == "first()"
    assert "typeof L !== 'undefined'" in fake_page.scripts[0]


def test_bootstrap_probe_false_emits_map_issue():
    widget = MapWidget.__new__(MapWidget)
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._on_bootstrap_probe_finished(False)

    assert issues == ["Leaflet wurde geladen, aber die Karte wurde nicht initialisiert"]


def test_bootstrap_probe_none_emits_verification_issue():
    widget = MapWidget.__new__(MapWidget)
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._on_bootstrap_probe_finished(None)

    assert issues == ["Leaflet-Bootstrap konnte nicht verifiziert werden"]


def test_bootstrap_timeout_emits_map_issue():
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_generation = 3
    widget._page_ready = False
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._check_bootstrap_timeout(3)

    assert issues == ["Karten-WebView Initialisierungstimeout nach 6s"]


def test_bootstrap_timeout_ignores_stale_generation():
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_generation = 4
    widget._page_ready = False
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._check_bootstrap_timeout(3)

    assert issues == []


def test_load_finished_false_emits_map_load_issue():
    widget = MapWidget.__new__(MapWidget)
    widget._pending_scripts = []
    widget._render_payload_in_flight = True
    widget._queued_render_payload_script = "applyRenderPayload({})"
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._on_load_finished(False)

    assert widget._page_ready is False
    assert widget._render_payload_in_flight is False
    assert widget._queued_render_payload_script is None
    assert issues == ["Karten-WebView konnte nicht geladen werden"]


def test_run_js_coalesces_render_payloads_while_previous_payload_is_active():
    widget = MapWidget.__new__(MapWidget)
    fake_page = _CallbackPage()
    widget._page_ready = True
    widget._pending_scripts = []
    widget._render_payload_in_flight = False
    widget._queued_render_payload_script = None
    widget._stall_timer = None
    widget.page = lambda: fake_page

    widget._run_js('applyRenderPayload({"id": 1})')
    widget._run_js('applyRenderPayload({"id": 2})')
    widget._run_js('applyRenderPayload({"id": 3})')

    assert fake_page.scripts == ['applyRenderPayload({"id": 1})']
    assert widget._queued_render_payload_script == 'applyRenderPayload({"id": 3})'

    fake_page.callbacks.pop(0)(None)

    assert fake_page.scripts == [
        'applyRenderPayload({"id": 1})',
        'applyRenderPayload({"id": 3})',
    ]


def test_load_messages_handles_label_overlays_without_popup(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0, "lon": 13.0},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    )

    widget.load_messages([map_msg])

    payload = _render_payload(captured_scripts)
    assert any(item["kind"] == "label" for item in payload["infrastructure"])
    assert payload["markers"] == []
    assert payload["trajectories"] == []


def test_load_messages_does_not_render_markers_for_map_or_spat(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-map",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={},
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-spat",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={},
    )

    widget.load_messages([map_msg, spat_msg])

    payload = _render_payload(captured_scripts)
    assert payload["markers"] == []
    assert payload["infrastructure"] == []


def test_load_messages_does_not_render_station_marker_for_ssem(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    ssem_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-ssem",
        msg_type=MessageType.SSEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={},
    )

    widget.load_messages([ssem_msg])

    payload = _render_payload(captured_scripts)
    assert payload["markers"] == []
    assert payload["trajectories"] == []


def test_render_playback_slice_uses_only_messages_up_to_current_index(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    cam1 = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="car-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )
    cam2 = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="car-1",
        msg_type=MessageType.CAM,
        latitude=52.1,
        longitude=13.1,
    )

    widget.render_playback_slice([cam1, cam2], 0)

    payload = _render_payload(captured_scripts)

    assert payload["markers"]
    assert payload["markers"][-1]["lat"] == 52.0
    assert payload["markers"][-1]["lon"] == 13.0
    assert payload["trajectories"]
    assert [52.1, 13.1] not in payload["trajectories"][-1]["coords"]
    assert payload["clear"] is False


def test_render_playback_slice_limits_trail_to_recent_points(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._follow_station_id = None

    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, index, tzinfo=timezone.utc),
            station_id="car-1",
            msg_type=MessageType.CAM,
            latitude=52.0 + (index / 1000.0),
            longitude=13.0 + (index / 1000.0),
        )
        for index in range(10)
    ]

    widget.render_playback_slice(messages, 9)

    payload = _render_payload(captured_scripts)
    coords = payload["trajectories"][-1]["coords"]
    assert [52.0, 13.0] not in coords
    assert [52.009, 13.009] in coords


def test_render_playback_slice_does_not_copy_growing_message_prefix(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._follow_station_id = None
    messages = _NoSliceMessages(
        [
            V2xMessage(
                timestamp=datetime(2026, 4, 18, 12, 0, index, tzinfo=timezone.utc),
                station_id="car-1",
                msg_type=MessageType.CAM,
                latitude=52.0 + (index / 1000.0),
                longitude=13.0 + (index / 1000.0),
            )
            for index in range(3)
        ]
    )

    widget.render_playback_slice(messages, 1)

    payload = _render_payload(captured_scripts)
    assert payload["markers"][-1]["lat"] == 52.001
    assert [52.002, 13.002] not in payload["trajectories"][-1]["coords"]


def test_render_playback_slice_applies_time_window(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._performance_mode = MAP_PERFORMANCE_SAVER
    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, index, tzinfo=timezone.utc),
            station_id="car-1",
            msg_type=MessageType.CAM,
            latitude=52.0 + (index / 1000.0),
            longitude=13.0 + (index / 1000.0),
        )
        for index in range(5)
    ]

    widget.render_playback_slice(messages, 4, window_seconds=2.0)

    payload = _render_payload(captured_scripts)
    coords = payload["trajectories"][-1]["coords"]
    assert [52.0, 13.0] not in coords
    assert [52.002, 13.002] in coords
    assert payload["performanceMode"] == MAP_PERFORMANCE_SAVER


def test_diagnostic_mode_keeps_short_trajectories(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._performance_mode = MAP_PERFORMANCE_DIAGNOSTIC
    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, index, tzinfo=timezone.utc),
            station_id="car-1",
            msg_type=MessageType.CAM,
            latitude=52.0 + (index / 1000.0),
            longitude=13.0 + (index / 1000.0),
        )
        for index in range(2)
    ]

    widget.load_messages(messages)

    payload = _render_payload(captured_scripts)
    assert payload["markers"]
    assert payload["trajectories"]
    assert payload["performanceMode"] == MAP_PERFORMANCE_DIAGNOSTIC


def test_diagnostic_mode_keeps_essential_infrastructure_layers(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._performance_mode = MAP_PERFORMANCE_DIAGNOSTIC
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                            "stopLine": {
                                "points": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0000, "lon": 13.0001},
                                ]
                            },
                        },
                        {
                            "laneID": 18,
                            "laneRole": "outbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0002, "lon": 13.0003},
                                    {"lat": 52.0003, "lon": 13.0004},
                                ]
                            },
                        },
                    ],
                }
            ]
        },
    )

    widget.load_messages([map_msg])

    payload = _render_payload(captured_scripts)
    layers = {item["layerName"] for item in payload["infrastructure"]}
    assert "map_inbound" in layers
    assert "map_outbound" in layers
    assert "map_stoplines" in layers
    assert "map" not in layers


def test_render_payload_budget_caps_markers_and_records_telemetry(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._performance_mode = MAP_PERFORMANCE_NORMAL
    marker_budget = MAP_RENDER_BUDGETS[MAP_PERFORMANCE_NORMAL]["markers"]
    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, index % 60, tzinfo=timezone.utc),
            station_id=f"car-{index}",
            msg_type=MessageType.CAM,
            latitude=52.0 + (index / 100000.0),
            longitude=13.0 + (index / 100000.0),
        )
        for index in range(marker_budget + 5)
    ]

    widget.load_messages(messages)

    payload = _render_payload(captured_scripts)
    telemetry = widget.latest_telemetry()
    assert len(payload["markers"]) == marker_budget
    assert telemetry is not None
    assert telemetry["marker_count"] == marker_budget
    assert telemetry["budget_dropped_markers"] == 5
    assert telemetry["payload_bytes"] > 0


def test_leaflet_assets_are_bundled_locally():
    base_path = _asset_base_path()
    assert (base_path / "leaflet" / "leaflet.js").exists()
    assert (base_path / "leaflet" / "leaflet.css").exists()


def test_runtime_leaflet_html_embeds_local_assets_for_webengine_file_robustness():
    html = _leaflet_runtime_html()
    assert "Local Leaflet assets embedded" in html
    assert "Leaflet" in html
    assert 'href="leaflet/leaflet.css"' in html
    assert 'src="leaflet/leaflet.js"' in html
    assert "url(leaflet/images/" in html


def test_update_playback_position_follows_selected_station(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0
    widget._follow_station_id = "car-1"

    msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="car-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )

    widget.update_playback_position(msg)

    assert any(
        "highlightMarker('station_car-1')" in script for script in captured_scripts
    )
    assert any("followMarker('station_car-1')" in script for script in captured_scripts)


def test_load_messages_clears_before_full_reload(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    cam_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="car-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )

    widget.load_messages([cam_msg])

    assert _render_payload(captured_scripts)["clear"] is True


def test_load_messages_skips_null_island_markers(monkeypatch):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    null_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="bad-denm",
        msg_type=MessageType.DENM,
        latitude=0.0,
        longitude=0.0,
    )
    good_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="good-cam",
        msg_type=MessageType.CAM,
        latitude=48.894068,
        longitude=9.208135,
    )

    widget.load_messages([null_msg, good_msg])

    payload = _render_payload(captured_scripts)
    station_ids = {marker["stationId"] for marker in payload["markers"]}
    assert "bad-denm" not in station_ids
    assert "good-cam" in station_ids


def test_load_messages_skips_far_outliers_when_infrastructure_anchor_exists(
    monkeypatch,
):
    captured_scripts = []

    def fake_run_js(self, script):
        captured_scripts.append(script)

    monkeypatch.setattr(MapWidget, "_run_js", fake_run_js)
    monkeypatch.setattr(MapWidget, "__init__", lambda self, parent=None: None)

    widget = MapWidget()
    widget._station_color_map = {}
    widget._station_index = 0

    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-map",
        msg_type=MessageType.MAPEM,
        latitude=48.894068,
        longitude=9.208135,
        decoded_data={
            "intersections": [{"refPoint": {"lat": 48.894068, "lon": 9.208135}}]
        },
    )
    outlier_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="bad-denm",
        msg_type=MessageType.DENM,
        latitude=10.745933,
        longitude=-53.4697692,
    )
    local_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 2, tzinfo=timezone.utc),
        station_id="local-cam",
        msg_type=MessageType.CAM,
        latitude=48.8941,
        longitude=9.2082,
    )

    anchors = _display_anchor_points([map_msg, outlier_msg, local_msg])
    assert _is_near_display_anchors(outlier_msg, anchors) is False
    assert _is_near_display_anchors(local_msg, anchors) is True

    widget.load_messages([map_msg, outlier_msg, local_msg])

    payload = _render_payload(captured_scripts)
    station_ids = {marker["stationId"] for marker in payload["markers"]}
    assert "bad-denm" not in station_ids
    assert "local-cam" in station_ids


def test_leaflet_html_exposes_incremental_sync_helpers():
    assert "L.map('map', {preferCanvas: true})" in LEAFLET_HTML
    assert "applyRenderPayload(payload)" in LEAFLET_HTML
    assert "function setLayerPopup(layer, popup)" in LEAFLET_HTML
    assert "function disposeLayer(layer)" in LEAFLET_HTML
    assert "existingTooltip.setContent(tooltip)" in LEAFLET_HTML
    assert "syncMarkers(activeIds)" in LEAFLET_HTML
    assert "syncTrajectories(activeIds)" in LEAFLET_HTML
    assert "syncInfrastructure(activeIds)" in LEAFLET_HTML


# ---------------------------------------------------------------------------
# Bootstrap probe / timeout regression tests
# ---------------------------------------------------------------------------


def test_bootstrap_timeout_fires_even_when_page_loaded():
    """Regression: loadFinished(ok=True) must NOT silence the timeout when the
    Leaflet probe never confirmed success (_bootstrap_probe_succeeded=False)."""
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_generation = 1
    widget._page_ready = True  # simulates loadFinished(ok=True) having fired
    widget._bootstrap_probe_succeeded = False  # probe never returned True
    widget._ever_bootstrapped = False
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._check_bootstrap_timeout(1)

    assert issues == ["Karten-WebView Initialisierungstimeout nach 6s"]


def test_bootstrap_timeout_silent_after_probe_succeeded():
    """Timeout must not fire when the bootstrap probe already confirmed success."""
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_generation = 1
    widget._bootstrap_probe_succeeded = True
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._check_bootstrap_timeout(1)

    assert issues == []


def test_bootstrap_timeout_silent_after_any_previous_success():
    """A later reload/timeout must not replace an already working geographic map."""
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_generation = 1
    widget._bootstrap_probe_succeeded = False
    widget._ever_bootstrapped = True
    widget._page_ready = False
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._check_bootstrap_timeout(1)

    assert issues == []


def test_bootstrap_probe_true_sets_succeeded_flag():
    """A True probe result must set _bootstrap_probe_succeeded so the timeout is suppressed."""
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_probe_succeeded = False
    widget._ever_bootstrapped = False
    widget.map_issue_detected = type("Signal", (), {"emit": lambda self, msg: None})()

    widget._on_bootstrap_probe_finished(True)

    assert widget._bootstrap_probe_succeeded is True
    assert widget._ever_bootstrapped is True


def test_dispose_cancels_pending_render_callbacks():
    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._page_ready = True
    widget._pending_scripts = ["highlightMarker('x')"]
    widget._render_payload_in_flight = True
    widget._queued_render_payload_script = "applyRenderPayload({})"
    widget._render_payload_started_at = 1.0
    widget._render_payload_stall_generation = 3
    widget._bootstrap_generation = 4
    widget._bootstrap_probe_succeeded = False

    widget.dispose()
    widget._on_render_payload_finished(None)
    widget._check_render_payload_stall(-1)
    widget._check_bootstrap_timeout(-1)

    assert widget._disposed is True
    assert widget._pending_scripts == []
    assert widget._render_payload_in_flight is False
    assert widget._queued_render_payload_script is None
    assert widget._render_payload_started_at is None
    assert widget._bootstrap_probe_succeeded is True


def test_execute_js_marks_widget_disposed_when_qt_object_was_deleted():
    class DeletedPage:
        def runJavaScript(self, *_args):
            raise RuntimeError(
                "wrapped C/C++ object of type MapWidget has been deleted"
            )

    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._render_payload_in_flight = True
    widget._queued_render_payload_script = "applyRenderPayload({})"
    widget._render_payload_started_at = 1.0
    widget.page = lambda: DeletedPage()

    widget._execute_js("clearAll()")

    assert widget._disposed is True
    assert widget._render_payload_in_flight is False
    assert widget._queued_render_payload_script is None
    assert widget._render_payload_started_at is None


def test_render_process_terminated_emits_map_issue():
    """Chromium render-process termination must emit a map_issue with 'Render-Prozess'."""
    widget = MapWidget.__new__(MapWidget)
    widget._bootstrap_probe_succeeded = True
    widget._page_ready = True
    issues: list[str] = []
    widget.map_issue_detected = type(
        "Signal", (), {"emit": lambda self, msg: issues.append(msg)}
    )()

    widget._on_render_process_terminated("NormalTerminationStatus", 0)

    assert widget._bootstrap_probe_succeeded is False
    assert widget._page_ready is False
    assert issues and "Render-Prozess" in issues[0]
