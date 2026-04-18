"""Tests for scene aggregation and phase forecast logic."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.pcap_parser import parse_pcap
from pcap2kml_player.scene_model import (
    ActiveRequest,
    EtaVerification,
    ForecastConfidence,
    IntersectionState,
    MovementPhaseState,
    PhaseSegment,
    SceneSnapshot,
    SignalGroupState,
    SpatForecast,
    build_scene_snapshot,
    find_overdue_requests,
    get_clock_skew_warnings,
    get_eta_accuracy_seconds,
    is_flow_allowed,
)


@pytest.fixture
def now():
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


TESTFILES = Path(__file__).resolve().parent.parent / "testfiles"


# ---------- find_overdue_requests ----------

def test_pending_default_request_within_window_not_overdue(now):
    req = ActiveRequest(
        request_id=1, sequence_number=0, intersection_id=42, station_id="A",
        importance_level=5, requested_at=now - timedelta(milliseconds=800),
    )
    assert find_overdue_requests([req], now) == []


def test_pending_default_request_past_window_is_overdue(now):
    req = ActiveRequest(
        request_id=1, sequence_number=0, intersection_id=42, station_id="A",
        importance_level=5, requested_at=now - timedelta(milliseconds=1500),
    )
    assert find_overdue_requests([req], now) == [req]


def test_high_priority_request_has_stricter_500ms_window(now):
    req = ActiveRequest(
        request_id=2, sequence_number=0, intersection_id=42, station_id="B",
        importance_level=12, requested_at=now - timedelta(milliseconds=700),
    )
    assert find_overdue_requests([req], now) == [req]


def test_answered_request_ignored_even_if_old(now):
    req = ActiveRequest(
        request_id=3, sequence_number=0, intersection_id=42, station_id="C",
        importance_level=5, requested_at=now - timedelta(seconds=10),
        responded_at=now - timedelta(seconds=5),
    )
    assert find_overdue_requests([req], now) == []


# ---------- is_flow_allowed ----------

def _scene_with_phase(now, phase, forecast_segments=None):
    sg = SignalGroupState(
        signal_group_id=3, phase=phase,
        time_confidence=ForecastConfidence.HIGH,
    )
    isec = IntersectionState(intersection_id=42)
    isec.signal_groups[3] = sg
    forecasts = {}
    if forecast_segments is not None:
        forecasts[42] = SpatForecast(
            intersection_id=42, horizon_seconds=30.0,
            segments_by_group={3: forecast_segments},
        )
    return SceneSnapshot(
        timeline_position=now,
        intersections={42: isec},
        forecasts=forecasts,
    )


def test_flow_allowed_when_phase_is_protected_movement(now):
    scene = _scene_with_phase(now, MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED)
    allowed, eta, conf = is_flow_allowed(scene, 42, 1, 5, ingress_signal_group=3)
    assert allowed is True
    assert eta is None
    assert conf == ForecastConfidence.HIGH


def test_flow_allowed_when_phase_is_permissive(now):
    scene = _scene_with_phase(now, MovementPhaseState.PERMISSIVE_MOVEMENT_ALLOWED)
    allowed, _, _ = is_flow_allowed(scene, 42, 1, 5, ingress_signal_group=3)
    assert allowed is True


def test_flow_blocked_with_eta_from_forecast(now):
    release = now + timedelta(seconds=8)
    segs = [
        PhaseSegment(MovementPhaseState.STOP_AND_REMAIN, now, release, ForecastConfidence.MEDIUM),
        PhaseSegment(MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED, release,
                     release + timedelta(seconds=15), ForecastConfidence.MEDIUM),
    ]
    scene = _scene_with_phase(now, MovementPhaseState.STOP_AND_REMAIN, forecast_segments=segs)
    allowed, eta, conf = is_flow_allowed(scene, 42, 1, 5, ingress_signal_group=3)
    assert allowed is False
    assert eta == release
    assert conf == ForecastConfidence.MEDIUM


def test_flow_blocked_without_forecast_returns_no_eta(now):
    scene = _scene_with_phase(now, MovementPhaseState.STOP_AND_REMAIN)
    allowed, eta, conf = is_flow_allowed(scene, 42, 1, 5, ingress_signal_group=3)
    assert allowed is False
    assert eta is None


def test_unknown_intersection_returns_blocked(now):
    scene = _scene_with_phase(now, MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED)
    assert is_flow_allowed(scene, 999, 1, 5, ingress_signal_group=3) == (False, None, None)


def test_unknown_signal_group_returns_blocked(now):
    scene = _scene_with_phase(now, MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED)
    assert is_flow_allowed(scene, 42, 1, 5, ingress_signal_group=99) == (False, None, None)


# ---------- build_scene_snapshot ----------

def test_build_scene_snapshot_joins_latest_map_and_spat(now):
    map_msg = V2xMessage(
        timestamp=now - timedelta(seconds=5),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 3,
                }
            ]
        },
    )
    spat_msg = V2xMessage(
        timestamp=now - timedelta(seconds=1),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 3,
                    "states": [
                        {
                            "signalGroup": 7,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protected-Movement-Allowed",
                                    "timing": {"likelyTime": 30, "timeConfidence": 5},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    scene = build_scene_snapshot([map_msg, spat_msg], now)

    assert 42 in scene.intersections
    intersection = scene.intersections[42]
    assert intersection.map_revision == 3
    assert intersection.spat_revision == 3
    assert intersection.revision_mismatch is False
    assert intersection.signal_groups[7].phase == MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED
    assert intersection.signal_groups[7].likely_time == spat_msg.timestamp + timedelta(seconds=3)


def test_build_scene_snapshot_creates_forecast_segments(now):
    spat_msg = V2xMessage(
        timestamp=now,
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 4,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "stop-And-Remain",
                                    "timing": {"likelyTime": 50, "timeConfidence": 20},
                                },
                                {
                                    "eventState": "protected-Movement-Allowed",
                                    "timing": {"likelyTime": 120, "timeConfidence": 5},
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )

    scene = build_scene_snapshot([spat_msg], now)

    forecast = scene.forecasts[42]
    segments = forecast.segments_by_group[3]
    assert len(segments) == 2
    assert segments[0].phase == MovementPhaseState.STOP_AND_REMAIN
    assert segments[0].end == now + timedelta(seconds=5)
    assert segments[0].confidence == ForecastConfidence.MEDIUM
    assert segments[1].phase == MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED
    assert segments[1].start == now + timedelta(seconds=5)
    assert segments[1].confidence == ForecastConfidence.HIGH


def test_build_scene_snapshot_correlates_srem_and_ssem(now):
    srem_msg = V2xMessage(
        timestamp=now - timedelta(milliseconds=800),
        station_id="bus-7",
        msg_type=MessageType.SREM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersectionId": 42,
            "requestId": 11,
            "sequenceNumber": 2,
            "importanceLevel": 12,
            "requestorType": "publicTransport",
            "inLane": 4,
            "outLane": 9,
        },
    )
    ssem_msg = V2xMessage(
        timestamp=now - timedelta(milliseconds=200),
        station_id="rsu-1",
        msg_type=MessageType.SSEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersectionId": 42,
            "requestId": 11,
            "sequenceNumber": 2,
            "requestState": "granted",
        },
    )

    scene = build_scene_snapshot([srem_msg, ssem_msg], now)

    assert scene.active_requests == []


def test_build_scene_snapshot_keeps_unanswered_srem_active(now):
    srem_msg = V2xMessage(
        timestamp=now - timedelta(milliseconds=800),
        station_id="bus-7",
        msg_type=MessageType.SREM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersectionId": 42,
            "requestId": 11,
            "sequenceNumber": 2,
            "importanceLevel": 12,
            "requestorType": "publicTransport",
            "inLane": 4,
            "outLane": 9,
        },
    )

    scene = build_scene_snapshot([srem_msg], now)

    assert len(scene.active_requests) == 1
    active_request = scene.active_requests[0]
    assert active_request.request_id == 11
    assert active_request.sequence_number == 2
    assert active_request.intersection_id == 42
    assert active_request.station_id == "bus-7"
    assert active_request.importance_level == 12


def test_build_scene_snapshot_ignores_future_messages(now):
    current_msg = V2xMessage(
        timestamp=now - timedelta(seconds=1),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={"intersections": [{"id": {"id": 42}, "revision": 1}]},
    )
    future_msg = V2xMessage(
        timestamp=now + timedelta(seconds=5),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={"intersections": [{"id": {"id": 99}, "revision": 1}]},
    )

    scene = build_scene_snapshot([current_msg, future_msg], now)

    assert 42 in scene.intersections
    assert 99 not in scene.intersections


def test_build_scene_snapshot_creates_fallback_intersection_for_raw_map_and_spat(now):
    map_msg = V2xMessage(
        timestamp=now - timedelta(seconds=2),
        station_id="map-rsu",
        msg_type=MessageType.MAPEM,
        latitude=52.42797,
        longitude=13.52680,
        decoded_data={},
    )
    spat_msg = V2xMessage(
        timestamp=now - timedelta(seconds=1),
        station_id="spat-rsu",
        msg_type=MessageType.SPATEM,
        latitude=52.42798,
        longitude=13.52682,
        decoded_data={},
    )

    scene = build_scene_snapshot([map_msg, spat_msg], now)

    assert len(scene.intersections) == 1
    intersection = next(iter(scene.intersections.values()))
    assert intersection.last_map_time == map_msg.timestamp
    assert intersection.last_spat_time == spat_msg.timestamp
    assert intersection.map_reference_point is not None


def test_build_scene_snapshot_computes_clock_skew_from_spat_dsrc_time(now):
    start_of_year = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    packet_timestamp = start_of_year + timedelta(minutes=10, seconds=5)
    spat_msg = V2xMessage(
        timestamp=packet_timestamp,
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.1,
        longitude=13.1,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 1,
                    "moy": 10,
                    "timeStamp": 8000,
                    "states": [],
                }
            ]
        },
    )

    scene = build_scene_snapshot([spat_msg], packet_timestamp)

    assert scene.intersections[42].clock_skew_seconds == pytest.approx(3.0)
    assert get_clock_skew_warnings(scene, threshold_seconds=2.0) == [(42, pytest.approx(3.0))]


def test_build_scene_snapshot_verifies_eta_against_cam_arrival(now):
    map_msg = V2xMessage(
        timestamp=now - timedelta(seconds=5),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 1,
                    "refPoint": {"lat": 52.0000000, "lon": 13.0000000},
                }
            ]
        },
    )
    cam_before = V2xMessage(
        timestamp=now - timedelta(seconds=1),
        station_id="bus-7",
        msg_type=MessageType.CAM,
        latitude=52.0007,
        longitude=13.0007,
        decoded_data={},
    )
    srem_msg = V2xMessage(
        timestamp=now,
        station_id="bus-7",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 11,
            "sequenceNumber": 2,
            "importanceLevel": 12,
            "requestorType": "publicTransport",
            "eta": now + timedelta(seconds=8),
        },
    )
    cam_arrival = V2xMessage(
        timestamp=now + timedelta(seconds=9),
        station_id="bus-7",
        msg_type=MessageType.CAM,
        latitude=52.00005,
        longitude=13.00004,
        decoded_data={},
    )

    scene = build_scene_snapshot(
        [map_msg, cam_before, srem_msg, cam_arrival],
        now + timedelta(seconds=10),
    )

    assert len(scene.eta_verifications) == 1
    verification = scene.eta_verifications[0]
    assert isinstance(verification, EtaVerification)
    assert verification.intersection_id == 42
    assert verification.station_id == "bus-7"
    assert verification.delta_seconds == pytest.approx(1.0)
    assert verification.is_accurate is True
    assert get_eta_accuracy_seconds(scene) == pytest.approx(1.0)


def test_build_scene_snapshot_skips_eta_verification_without_map_reference(now):
    srem_msg = V2xMessage(
        timestamp=now,
        station_id="bus-7",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 11,
            "sequenceNumber": 2,
            "eta": now + timedelta(seconds=8),
        },
    )
    cam_arrival = V2xMessage(
        timestamp=now + timedelta(seconds=9),
        station_id="bus-7",
        msg_type=MessageType.CAM,
        latitude=52.00005,
        longitude=13.00004,
        decoded_data={},
    )

    scene = build_scene_snapshot([srem_msg, cam_arrival], now + timedelta(seconds=10))

    assert scene.eta_verifications == []
    assert get_eta_accuracy_seconds(scene) is None


def test_build_scene_snapshot_detects_raw_map_and_spat_in_real_test_pcap():
    session = parse_pcap(str(TESTFILES / "txa_22082025.pcap"))

    scene = build_scene_snapshot(session.messages, session.messages[200].timestamp)

    assert any(msg.msg_type == MessageType.MAPEM for msg in session.messages)
    assert any(msg.msg_type == MessageType.SPATEM for msg in session.messages)
    assert scene.intersections
    assert any(intersection.map_revision is not None for intersection in scene.intersections.values())
    assert any(intersection.spat_revision is not None for intersection in scene.intersections.values())
