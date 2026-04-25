"""Tests for lane connectivity and flow resolution."""

from datetime import UTC, datetime, timedelta

import pytest

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.scene_model import (
    ForecastConfidence,
    IntersectionState,
    LaneConnection,
    MovementPhaseState,
    PhaseSegment,
    SceneSnapshot,
    SignalGroupState,
    SpatForecast,
    _extract_lane_connections,
    build_scene_snapshot,
    resolve_flow_status,
)


def _make_map_msg(**kwargs):
    """Create a MAPEM message with minimal default decoded data."""
    defaults = {
        "timestamp": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        "station_id": "rsu-1",
        "msg_type": MessageType.MAPEM,
        "latitude": 52.1,
        "longitude": 13.1,
        "decoded_data": {
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 1,
                    "refPoint": {"lat": 521000000, "long": 131000000},
                    "laneSet": [
                        {
                            "laneId": 1,
                            "nodeList": {
                                "nodes": [
                                    {"delta": {"lat": 0, "lon": 0}},
                                    {"delta": {"lat": 10, "lon": 0}},
                                ]
                            },
                            "connectsTo": {
                                "connections": [
                                    {
                                        "connectionId": 101,
                                        "signalGroup": 7,
                                        "connectingLane": {"lane": 2},
                                    }
                                ]
                            },
                        },
                        {
                            "laneId": 2,
                            "nodeList": {
                                "nodes": [
                                    {"delta": {"lat": 10, "lon": 0}},
                                    {"delta": {"lat": 20, "lon": 0}},
                                ]
                            },
                        },
                    ],
                }
            ]
        },
    }
    defaults.update(kwargs)
    return V2xMessage(**defaults)


def _make_spat_msg(**kwargs):
    """Create a SPATEM message with minimal default decoded data."""
    defaults = {
        "timestamp": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        "station_id": "rsu-1",
        "msg_type": MessageType.SPATEM,
        "latitude": 52.1,
        "longitude": 13.1,
        "decoded_data": {
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 1,
                    "states": [
                        {
                            "signalGroup": 7,
                            "state-time-speed": [
                                {
                                    "eventState": "protected-Movement-Allowed",
                                    "timing": {
                                        "minEndTime": 100,
                                        "maxEndTime": 200,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    defaults.update(kwargs)
    return V2xMessage(**defaults)


class TestExtractLaneConnections:
    """Unit tests for _extract_lane_connections."""

    def test_extracts_connection_with_all_fields(self):
        intersection = {
            "laneSet": [
                {
                    "laneId": 1,
                    "connectsTo": {
                        "connections": [
                            {
                                "connectionId": 101,
                                "signalGroup": 7,
                                "connectingLane": {"lane": 2},
                            }
                        ]
                    },
                }
            ]
        }
        result = _extract_lane_connections(intersection)
        assert result == {
            1: [LaneConnection(connection_id=101, ingress_lane_id=1, egress_lane_id=2, signal_group_id=7)]
        }

    def test_skips_missing_target_lane(self):
        intersection = {
            "laneSet": [
                {
                    "laneId": 1,
                    "connectsTo": {
                        "connections": [
                            {"signalGroup": 7}  # no connectingLane
                        ]
                    },
                }
            ]
        }
        result = _extract_lane_connections(intersection)
        assert result == {}

    def test_handles_multiple_connections_per_lane(self):
        intersection = {
            "laneSet": [
                {
                    "laneId": 1,
                    "connectsTo": {
                        "connections": [
                            {"connectionId": 101, "signalGroup": 7, "connectingLane": {"lane": 2}},
                            {"connectionId": 102, "signalGroup": 8, "connectingLane": {"lane": 3}},
                        ]
                    },
                }
            ]
        }
        result = _extract_lane_connections(intersection)
        assert len(result[1]) == 2
        assert result[1][0].egress_lane_id == 2
        assert result[1][1].egress_lane_id == 3

    def test_empty_lane_set(self):
        assert _extract_lane_connections({}) == {}
        assert _extract_lane_connections({"laneSet": []}) == {}


class TestResolveFlowStatus:
    """Integration tests for resolve_flow_status using build_scene_snapshot."""

    def test_flow_allowed_when_signal_group_is_green(self):
        map_msg = _make_map_msg()
        spat_msg = _make_spat_msg()
        scene = build_scene_snapshot([map_msg, spat_msg], map_msg.timestamp)

        is_allowed, release_time, confidence = resolve_flow_status(scene, 42, 1, 2)
        assert is_allowed is True
        assert release_time is None
        assert confidence is not None

    def test_flow_blocked_when_signal_group_is_red(self):
        map_msg = _make_map_msg()
        spat_msg = _make_spat_msg(
            decoded_data={
                "intersections": [
                    {
                        "id": {"id": 42},
                        "revision": 1,
                        "states": [
                            {
                                "signalGroup": 7,
                                "state-time-speed": [
                                    {
                                        "eventState": "stop-And-Remain",
                                        "timing": {
                                            "minEndTime": 100,
                                            "maxEndTime": 200,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
        scene = build_scene_snapshot([map_msg, spat_msg], map_msg.timestamp)

        is_allowed, release_time, confidence = resolve_flow_status(scene, 42, 1, 2)
        assert is_allowed is False

    def test_flow_blocked_with_forecast_release(self):
        map_msg = _make_map_msg()
        now = map_msg.timestamp
        spat_msg = _make_spat_msg(
            decoded_data={
                "intersections": [
                    {
                        "id": {"id": 42},
                        "revision": 1,
                        "states": [
                            {
                                "signalGroup": 7,
                                "state-time-speed": [
                                    {
                                        "eventState": "stop-And-Remain",
                                        "timing": {
                                            "minEndTime": 100,
                                            "maxEndTime": 200,
                                        },
                                    },
                                    {
                                        "eventState": "protected-Movement-Allowed",
                                        "timing": {
                                            "startTime": 200,
                                            "minEndTime": 500,
                                            "maxEndTime": 600,
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        )
        scene = build_scene_snapshot([map_msg, spat_msg], now)

        is_allowed, release_time, confidence = resolve_flow_status(scene, 42, 1, 2)
        assert is_allowed is False
        assert release_time is not None
        assert confidence is not None

    def test_unknown_connection_returns_false(self):
        map_msg = _make_map_msg()
        scene = build_scene_snapshot([map_msg], map_msg.timestamp)

        is_allowed, release_time, confidence = resolve_flow_status(scene, 42, 1, 99)
        assert is_allowed is False
        assert release_time is None
        assert confidence is None

    def test_unknown_intersection_returns_false(self):
        scene = SceneSnapshot(timeline_position=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
        is_allowed, release_time, confidence = resolve_flow_status(scene, 999, 1, 2)
        assert is_allowed is False
        assert release_time is None
        assert confidence is None
