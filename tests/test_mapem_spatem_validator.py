from datetime import UTC, datetime

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.mapem_spatem_validator import validate_mapem_spatem, validation_summary


def _msg(msg_type: MessageType, decoded_data: dict) -> V2xMessage:
    return V2xMessage(
        timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        station_id="test",
        msg_type=msg_type,
        latitude=48.895,
        longitude=9.208,
        decoded_data=decoded_data,
    )


def test_validator_accepts_consistent_map_and_spat() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 2,
                            "egressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                        },
                    ],
                }
            ]
        },
    )
    spat_msg = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [{"signalGroup": 3, "eventState": "protectedMovementAllowed"}],
                }
            ]
        },
    )

    issues = validate_mapem_spatem([map_msg, spat_msg])

    assert validation_summary(issues) == {"error": 0, "warning": 0, "info": 0}


def test_validator_reports_duplicate_lane_and_revision_mismatch() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {"laneID": 1, "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}]}},
                        {"laneID": 1, "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}]}},
                    ],
                }
            ]
        },
    )
    spat_msg = _msg(MessageType.SPATEM, {"intersections": [{"intersectionId": 42, "revision": 8, "states": []}]})

    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_msg])}

    assert "MAP_LANE_ID_DUPLICATE" in codes
    assert "MAP_SPAT_REVISION_MISMATCH" in codes
    assert "SPAT_STATES_EMPTY" in codes


def test_lane_width_validation() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 2,
                            "egressApproach": 1,
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_LANEWIDTH_MISSING" in codes

    # Now try with unusual lane width
    map_msg2 = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 15000,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 2,
                            "egressApproach": 1,
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                        },
                    ],
                }
            ]
        },
    )
    codes2 = {issue.code for issue in validate_mapem_spatem([map_msg2])}
    assert "MAP_LANEWIDTH_UNUSUAL" in codes2


def test_lane_attributes_validation() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "invalid_direction",
                                "laneType": "unknown_type",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_LANE_ATTR_DIRECTIONALUSE_INVALID" in codes
    assert "MAP_LANE_ATTR_LANETYPE_UNUSUAL" in codes


def test_crosswalk_linking_validation() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 10,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "crosswalk",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 1}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 20}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 20,
                            "egressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    # Crosswalk connects to vehicle lane - should be fine
    assert "CROSSWALK_NO_CONNECTION" not in codes
    assert "CROSSWALK_CONNECTS_TO_CROSSWALK" not in codes


def test_crosswalk_connects_to_crosswalk() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 10,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "crosswalk",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 11}}]},
                        },
                        {
                            "laneID": 11,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "crosswalk",
                            },
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "CROSSWALK_CONNECTS_TO_CROSSWALK" in codes


def test_bicycle_lane_linking_validation() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 20,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "bikeLane",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 1}}]},
                        },
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "BIKE_NO_CONNECTION" not in codes
    assert "BIKE_NO_VEHICLE_CONNECTION" not in codes


def test_bicycle_lane_no_vehicle_connection() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 20,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "bikeLane",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 21}}]},
                        },
                        {
                            "laneID": 21,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "bikeLane",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "BIKE_NO_VEHICLE_CONNECTION" in codes


def test_roundabout_detection() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}}]},
                        },
                        {
                            "laneID": 2,
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 1}}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "ROUNDABOUT_CIRCULAR_TOPOLOGY" in codes


def test_spat_signalgroup_not_in_map() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    spat_msg = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {"signalGroup": 3, "eventState": "protectedMovementAllowed"},
                        {"signalGroup": 99, "eventState": "protectedMovementAllowed"},
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_msg])}
    assert "SPAT_SIGNALGROUP_NOT_IN_MAP" in codes


def test_maneuvers_validation() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_MANEUVERS_MISSING" in codes


def test_stopline_for_signalized_lanes() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_STOPLINE_RECOMMENDED" in codes


def test_egress_with_signal_group() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                        {
                            "laneID": 2,
                            "egressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.896, "lon": 9.209}, {"lat": 48.897, "lon": 9.21}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 1}, "signalGroup": 4}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_EGRESS_WITH_SIGNAL_GROUP" in codes


def test_approach_without_direction() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "approachID": 99,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_APPROACH_WITHOUT_DIRECTION" in codes


def test_lane_nodelist_extremely_long() -> None:
    nodes = [{"lat": 48.895 + i * 0.001, "lon": 9.208} for i in range(510)]
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": nodes},
                        },
                    ],
                }
            ]
        },
    )

    codes = {issue.code for issue in validate_mapem_spatem([map_msg])}
    assert "MAP_LANE_NODELIST_EXTREMELY_LONG" in codes


def test_spat_timing_consistency() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    # Valid timing
    spat_valid = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protectedMovementAllowed",
                                    "timing": {
                                        "startTime": 10,
                                        "minEndTime": 20,
                                        "maxEndTime": 30,
                                        "confidence": 5,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_valid])}
    # Should not have timing errors
    assert "SPAT_MINENDTIME_AFTER_MAX" not in codes
    assert "SPAT_MAXEND_WITHOUT_MINEND" not in codes
    assert "SPAT_CONFIDENCE_INVALID" not in codes


def test_spat_timing_invalid() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    # Invalid timing
    spat_invalid = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protectedMovementAllowed",
                                    "timing": {
                                        "startTime": -5,
                                        "minEndTime": 50,
                                        "maxEndTime": 30,
                                        "confidence": 10,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_invalid])}
    assert "SPAT_STARTTIME_UNUSUAL" in codes
    assert "SPAT_MINENDTIME_AFTER_MAX" in codes
    assert "SPAT_CONFIDENCE_INVALID" in codes


def test_spat_timing_missing_minend() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    spat_no_min = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protectedMovementAllowed",
                                    "timing": {
                                        "maxEndTime": 30,
                                        "confidence": 2,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_no_min])}
    assert "SPAT_MAXEND_WITHOUT_MINEND" in codes
    assert "SPAT_CONFIDENCE_LOW" in codes


def test_spat_timing_likely_before_minend() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    spat_likely_early = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protectedMovementAllowed",
                                    "timing": {
                                        "minEndTime": 50,
                                        "maxEndTime": 60,
                                        "likelyTime": 40,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_likely_early])}
    assert "SPAT_LIKELYTIME_BEFORE_MINEND" in codes


def test_spat_timing_nexttime_before_maxend() -> None:
    map_msg = _msg(
        MessageType.MAPEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "laneWidth": 320,
                    "refPoint": {"lat": 48.895, "lon": 9.208},
                    "laneSet": [
                        {
                            "laneID": 1,
                            "ingressApproach": 1,
                            "laneAttributes": {
                                "directionalUse": "forward",
                                "laneType": "vehicle",
                            },
                            "maneuvers": {"maneuverStraightAllowed": True},
                            "stopLine": {"lat": 48.895, "lon": 9.208},
                            "nodeList": {"nodes": [{"lat": 48.895, "lon": 9.208}, {"lat": 48.896, "lon": 9.209}]},
                            "connectsTo": {"connections": [{"connectingLane": {"lane": 2}, "signalGroup": 3}]},
                        },
                    ],
                }
            ]
        },
    )
    spat_next_early = _msg(
        MessageType.SPATEM,
        {
            "intersections": [
                {
                    "intersectionId": 42,
                    "revision": 7,
                    "states": [
                        {
                            "signalGroup": 3,
                            "stateTimeSpeed": [
                                {
                                    "eventState": "protectedMovementAllowed",
                                    "timing": {
                                        "minEndTime": 50,
                                        "maxEndTime": 60,
                                        "nextTime": 55,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    codes = {issue.code for issue in validate_mapem_spatem([map_msg, spat_next_early])}
    assert "SPAT_NEXTTIME_BEFORE_MAXEND" in codes


def test_validate_real_xml_landau() -> None:
    """Validate the Landau real-world MAP XML file."""
    from pcap2kml_player.xml_map_parser import parse_map_xml

    session = SessionData()
    parsed = parse_map_xml("testfiles/Landau_2009886_V06_R1.xml", session)
    assert parsed >= 1
    assert len(session.messages) >= 1
    msg = session.messages[0]
    assert msg.msg_type == MessageType.MAPEM

    issues = validate_mapem_spatem(session.messages)
    summary = validation_summary(issues)
    # Real files should be mostly valid; check structure is parsed correctly
    assert summary["error"] <= 30  # Some lane parsing issues expected from raw XML
    assert summary["warning"] <= 50

    # Check specific structure
    assert msg.latitude > 48.0 and msg.latitude < 50.0
    assert msg.longitude > 7.0 and msg.longitude < 10.0


def test_validate_real_xml_woerth() -> None:
    """Validate the Wörth am Rhein real-world MAP XML file."""
    from pcap2kml_player.xml_map_parser import parse_map_xml

    session = SessionData()
    parsed = parse_map_xml("testfiles/Woerth_am_Rhein_2033087_V02_R2.xml", session)
    assert parsed >= 1
    assert len(session.messages) >= 1
    msg = session.messages[0]
    assert msg.msg_type == MessageType.MAPEM

    issues = validate_mapem_spatem(session.messages)
    summary = validation_summary(issues)
    assert summary["error"] <= 10  # Smaller file, fewer issues
    assert summary["warning"] <= 20

    assert msg.latitude > 48.0 and msg.latitude < 50.0
    assert msg.longitude > 7.0 and msg.longitude < 10.0
