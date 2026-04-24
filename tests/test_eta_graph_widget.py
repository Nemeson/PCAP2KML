"""Tests for request-centric ETA analysis helpers."""

from datetime import datetime, timedelta, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.ui.eta_graph_widget import (
    DiagnosticItem,
    EtaPoint,
    EtaSelection,
    EtaGraphWidget,
    RequestEvent,
    StatusBand,
    _build_status_bands,
    _detect_diagnostics,
    _smooth_speed_points,
    build_eta_selection_options,
)
from pcap2kml_player.scene_model import build_scene_snapshot


def _ts(seconds: float):
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_build_eta_selection_options_prefers_request_merge_keys():
    msg = V2xMessage(
        timestamp=_ts(0),
        station_id="bus-1",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={"intersectionId": 72, "requestId": 6, "sequenceNumber": 86},
        merge_group_id="merge-1",
    )

    options = build_eta_selection_options([msg])

    assert len(options) == 1
    assert options[0].key == "REQ:72:6:86:bus-1:merge-1"
    assert "I72 R6/S86" in options[0].label
    assert "Merge merge-1" in options[0].label


def test_smooth_speed_points_uses_moving_average():
    messages = [
        V2xMessage(_ts(0), "bus-1", MessageType.CAM, 52.0, 13.0, speed=3.0),
        V2xMessage(_ts(1), "bus-1", MessageType.CAM, 52.0, 13.0, speed=6.0),
        V2xMessage(_ts(2), "bus-1", MessageType.CAM, 52.0, 13.0, speed=12.0),
        V2xMessage(_ts(3), "bus-1", MessageType.CAM, 52.0, 13.0, speed=15.0),
    ]

    points = _smooth_speed_points(messages, _ts(0), window=3)

    assert [point.speed_mps for point in points] == [3.0, 4.5, 7.0, 11.0]


def test_status_bands_turn_ssem_updates_into_intervals():
    messages = [
        V2xMessage(_ts(1), "rsu", MessageType.SSEM, 52.0, 13.0, decoded_data={"requestState": "processing"}),
        V2xMessage(_ts(3), "rsu", MessageType.SSEM, 52.0, 13.0, decoded_data={"requestState": "granted"}),
    ]

    bands = _build_status_bands(messages, _ts(0), _ts(5))

    assert [(band.start_relative_seconds, band.end_relative_seconds, band.status) for band in bands] == [
        (1.0, 3.0, "processing"),
        (3.0, 5.0, "granted"),
    ]


def test_detect_diagnostics_marks_eta_jump_missing_ssem_and_missing_granted():
    srem = V2xMessage(
        _ts(0),
        "bus-1",
        MessageType.SREM,
        52.0,
        13.0,
        decoded_data={"intersectionId": 72, "requestId": 6, "sequenceNumber": 86},
    )
    selection = EtaSelection("REQ:72:6:86:bus-1:raw", "I72 R6/S86 | bus-1", "bus-1", 72, 6, 86)
    eta_points = [
        EtaPoint(_ts(0), 0.0, 5.0, None, "SREM 6/86"),
        EtaPoint(_ts(1), 1.0, 12.0, None, "SREM 6/86"),
    ]
    scene = build_scene_snapshot([srem], _ts(2))

    diagnostics = _detect_diagnostics(
        eta_points=eta_points,
        srem_messages=[srem],
        ssem_events=[],
        status_bands=[],
        scene=scene,
        selection=selection,
        start_time=_ts(0),
    )

    labels = [item.label for item in diagnostics]
    assert any("ETA-Sprung" in label for label in labels)
    assert "ETA steigt trotz Annaherung" in labels
    assert "SREM ohne SSEM-Antwort" in labels
    assert "kein granted fuer Request" in labels


def test_eta_dashboard_data_contains_metrics_and_events():
    widget = EtaGraphWidget.__new__(EtaGraphWidget)
    widget._selection = EtaSelection("REQ:72:6:86:bus-1:raw", "I72 R6/S86 | bus-1", "bus-1", 72, 6, 86)
    widget._eta_points = [EtaPoint(_ts(0), 0.0, 5.0, 1.5, "SREM 6/86")]
    widget._speed_points = [type("Speed", (), {"speed_mps": 4.0})()]
    widget._events = [RequestEvent(_ts(0), 0.0, "SREM", "SREM 6/86 | ETA 5.0s", None)]
    widget._status_bands = [StatusBand(_ts(2), _ts(4), 2.0, 4.0, "granted", "SSEM granted", None)]
    widget._diagnostics = [DiagnosticItem(_ts(3), 3.0, "ETA-Fehler +3.0s", None)]

    data = widget.dashboard_data()
    metrics = dict(data.metrics)
    event_types = [event.kind for event in data.events]
    assert metrics["Station"] == "bus-1"
    assert metrics["SREM-Samples"] == "1"
    assert metrics["SSEM-Updates"] == "1"
    assert metrics["letzter SSEM-Status"] == "granted"
    assert "SREM" in event_types
    assert "SSEM" in event_types


def test_eta_dashboard_without_selection_returns_operator_fallback():
    widget = EtaGraphWidget.__new__(EtaGraphWidget)
    widget._selection = None

    data = widget.dashboard_data()

    assert data.metrics == [("Status", "Keine ETA-Auswahl vorhanden")]
    assert data.events == []
