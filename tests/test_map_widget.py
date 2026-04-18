"""Tests for JavaScript escaping helpers in the map widget."""

from datetime import datetime, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.map_widget import (
    MapWidget,
    _infrastructure_overlays_for_message,
    _infrastructure_overlays_for_messages,
    _js_escape,
    _marker_id_for_message,
    _marker_position_for_message,
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

    assert _marker_position_for_message(map_msg) != _marker_position_for_message(spat_msg)


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
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            }
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
                                {"eventState": "stop-And-Remain"},
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


def test_infrastructure_overlays_for_messages_colors_map_lane_by_matching_spat_group():
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
                            "connectsTo": [{"signalGroup": 5}],
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                        }
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
                                {"eventState": "stop-And-Remain"},
                            ],
                        }
                    ],
                }
            ]
        },
    )

    overlays = _infrastructure_overlays_for_messages([map_msg, spat_msg])

    lane_overlay = next(overlay for overlay in overlays if overlay["kind"] == "polyline")
    lane_label = next(
        overlay
        for overlay in overlays
        if overlay["kind"] == "label" and "Lane 17" in overlay["text"]
    )
    assert lane_overlay["color"] == "#dc2626"
    assert "SG 5" in lane_overlay["popup"]
    assert "stop-And-Remain" in lane_label["text"]


def test_leaflet_html_exposes_layer_toggles_and_label_renderer():
    assert "MAP-Infrastruktur" in LEAFLET_HTML
    assert "SPAT-Status" in LEAFLET_HTML
    assert "addInfrastructureLabel" in LEAFLET_HTML


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
        decoded_data={},
    )

    widget.load_messages([map_msg])

    assert any("addInfrastructureLabel(" in script for script in captured_scripts)
    assert any("'map')" in script and "addMarker(" in script for script in captured_scripts)
    assert not any("addTrajectory(" in script for script in captured_scripts)
