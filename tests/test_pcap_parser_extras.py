"""Tests for the per-message-type extra-field extractors in pcap_parser."""

from pcap2kml_player.data_model import MessageType
from pcap2kml_player.pcap_parser import (
    _extra_fields_cam,
    _extra_fields_denm,
    _extra_fields_mapem,
    _extra_fields_spatem,
    _extra_fields_srem,
    _extra_fields_ssem,
    _infer_msg_type_from_pdu,
    _safe_extract_extra,
    _safe_get,
)


# ---------- _safe_get ----------

def test_safe_get_walks_nested_dict():
    obj = {"a": {"b": {"c": 42}}}
    assert _safe_get(obj, "a", "b", "c") == 42


def test_safe_get_returns_default_on_missing_key():
    assert _safe_get({"a": {}}, "a", "missing", default="X") == "X"


def test_safe_get_handles_non_dict_gracefully():
    assert _safe_get({"a": "string"}, "a", "b", default=None) is None


def test_safe_get_empty_dict_returns_default():
    assert _safe_get({}, "a", default="fallback") == "fallback"


# ---------- CAM ----------

def test_extra_fields_cam_extracts_station_and_hf_fields():
    decoded = {
        "cam": {
            "camParameters": {
                "basicContainer": {"stationType": 5},
                "highFrequencyContainer": (
                    "basicVehicleContainerHighFrequency",
                    {
                        "driveDirection": "forward",
                        "vehicleLength": {"vehicleLengthValue": 40},
                        "vehicleWidth": 20,
                        "yawRate": 0,
                        "exteriorLights": "00000000",
                    },
                ),
            }
        }
    }
    fields = _extra_fields_cam(decoded)
    assert fields["stationType"] == 5
    assert fields["driveDirection"] == "forward"
    assert fields["vehicleWidth"] == 20
    assert "exteriorLights" in fields


def test_extra_fields_cam_empty_returns_empty_dict():
    assert _extra_fields_cam({}) == {}


# ---------- DENM ----------

def test_extra_fields_denm_extracts_cause_and_mgmt():
    decoded = {
        "denm": {
            "managementContainer": {
                "validityDuration": 600,
                "stationType": 5,
                "relevanceDistance": "lessThan200m",
            },
            "situationContainer": {
                "eventType": {"causeCode": 95, "subCauseCode": 2},
                "informationQuality": 7,
            },
        }
    }
    fields = _extra_fields_denm(decoded)
    assert fields["causeCode"] == 95
    assert fields["subCauseCode"] == 2
    assert fields["informationQuality"] == 7
    assert fields["validityDuration"] == 600


def test_extra_fields_denm_no_situation_container():
    decoded = {"denm": {"managementContainer": {"stationType": 5}}}
    fields = _extra_fields_denm(decoded)
    assert fields["stationType"] == 5
    assert "causeCode" not in fields


# ---------- MAPEM ----------

def test_extra_fields_mapem_extracts_intersection():
    decoded = {
        "map": {
            "intersections": [
                {
                    "id": {"id": 1234},
                    "revision": 5,
                    "refPoint": {"lat": 52.4280, "lon": 13.5268},
                    "laneWidth": 320,
                    "laneSet": [
                        {
                            "laneID": 7,
                            "ingressApproach": 1,
                            "nodeList": [
                                {"lat": 52.4280000, "lon": 13.5268000},
                                {"delta": {"x": 0, "y": 1800}},
                            ],
                            "connectsTo": [
                                {
                                    "connectionID": 11,
                                    "signalGroup": 3,
                                    "connectingLane": {"lane": 2},
                                }
                            ],
                        },
                        {},
                        {},
                    ],
                    "speedLimits": [{"type": "maxSpeedInSchoolZone"}],
                }
            ]
        }
    }
    fields = _extra_fields_mapem(decoded)
    assert fields["intersectionId"] == 1234
    assert fields["revision"] == 5
    assert fields["laneCount"] == 3
    assert fields["intersectionCount"] == 1
    assert "speedLimits" in fields
    assert fields["intersections"][0]["revision"] == 5
    lane = fields["intersections"][0]["laneSet"][0]
    assert lane["laneId"] == 7
    assert lane["laneRole"] == "inbound"
    assert lane["connections"][0]["connectionId"] == 11
    assert lane["connections"][0]["targetLaneId"] == 2
    assert lane["connections"][0]["signalGroup"] == 3
    assert len(lane["nodeList"]["nodes"]) == 2
    assert len(lane["stopLine"]["points"]) == 2


def test_extra_fields_mapem_marks_outbound_lane_without_stopline():
    decoded = {
        "map": {
            "intersections": [
                {
                    "id": {"id": 5},
                    "refPoint": {"lat": 52.4280, "lon": 13.5268},
                    "laneSet": [
                        {
                            "laneID": 2,
                            "egressApproach": 3,
                            "nodeList": [
                                {"lat": 52.4280000, "lon": 13.5268000},
                                {"delta": {"x": 1000, "y": 0}},
                            ],
                        }
                    ],
                }
            ]
        }
    }

    fields = _extra_fields_mapem(decoded)
    lane = fields["intersections"][0]["laneSet"][0]

    assert lane["laneRole"] == "outbound"
    assert "stopLine" not in lane


def test_extra_fields_mapem_no_intersections():
    assert _extra_fields_mapem({"map": {"intersections": []}}) == {}


# ---------- SPATEM ----------

def test_extra_fields_spatem_extracts_timing():
    decoded = {
        "spat": {
            "intersections": [
                {
                    "id": {"id": 42},
                    "revision": 3,
                    "moy": 123456,
                    "timeStamp": 999,
                    "states": [{}, {}],
                }
            ]
        }
    }
    fields = _extra_fields_spatem(decoded)
    assert fields["intersectionId"] == 42
    assert fields["revision"] == 3
    assert fields["moy"] == 123456
    assert fields["timeStamp"] == 999
    assert fields["signalGroupCount"] == 2
    assert fields["intersections"][0]["revision"] == 3


# ---------- SREM ----------

def test_extra_fields_srem_extracts_request_and_requestor():
    decoded = {
        "srm": {
            "requests": [
                {
                    "request": {
                        "requestID": 7,
                        "sequenceNumber": 1,
                        "inBoundLane": {"lane": 2},
                        "outBoundLane": {"lane": 5},
                        "expectedTimeOfArrival": {"timeStamp": 12345},
                    }
                }
            ],
            "requestor": {
                "type": {"role": "publicTransport", "importanceLevel": 12},
            },
        }
    }
    fields = _extra_fields_srem(decoded)
    assert fields["requestId"] == 7
    assert fields["sequenceNumber"] == 1
    assert fields["inLane"] == 2
    assert fields["outLane"] == 5
    assert fields["requestorType"] == "publicTransport"
    assert fields["importanceLevel"] == 12


def test_extra_fields_srem_empty_body():
    assert _extra_fields_srem({"srm": {}}) == {}


# ---------- SSEM ----------

def test_extra_fields_ssem_extracts_status():
    decoded = {
        "ssm": {
            "status": [
                {
                    "id": {"id": 77},
                    "sigStatus": [
                        {
                            "sigStatusPackage": {
                                "requester": {"id": 7, "sequenceNumber": 1},
                                "status": "processing",
                            }
                        }
                    ],
                }
            ]
        }
    }
    fields = _extra_fields_ssem(decoded)
    assert fields["statusCount"] == 1
    assert fields["intersectionId"] == 77
    assert fields["requestId"] == 7
    assert fields["sequenceNumber"] == 1
    assert fields["requestState"] == "processing"


def test_extra_fields_ssem_empty_status():
    fields = _extra_fields_ssem({"ssm": {"status": []}})
    assert fields["statusCount"] == 0


# ---------- _safe_extract_extra ----------

def test_safe_extract_extra_swallows_extractor_errors():
    # Passing a type where the extractor would raise: extractor works only on dicts
    # Use NMEA which is not in the extractor map
    assert _safe_extract_extra(MessageType.NMEA, {}) == {}


def test_safe_extract_extra_returns_empty_on_exception():
    # Force an AttributeError by passing a non-dict where dict ops are expected
    class Weird:
        def get(self, *_args, **_kwargs):
            raise TypeError("boom")
    assert _safe_extract_extra(MessageType.CAM, Weird()) == {}


def test_safe_extract_extra_delegates_to_cam():
    decoded = {"cam": {"camParameters": {"basicContainer": {"stationType": 5}}}}
    fields = _safe_extract_extra(MessageType.CAM, decoded)
    assert fields["stationType"] == 5


# ---------- _infer_msg_type_from_pdu ----------

def test_infer_msg_type_from_pdu_cam():
    # Protocol version 2, messageID 2 = CAM
    assert _infer_msg_type_from_pdu(b"\x02\x02rest") == MessageType.CAM


def test_infer_msg_type_from_pdu_denm():
    assert _infer_msg_type_from_pdu(b"\x02\x01rest") == MessageType.DENM


def test_infer_msg_type_from_pdu_mapem():
    assert _infer_msg_type_from_pdu(b"\x02\x04rest") == MessageType.MAPEM


def test_infer_msg_type_from_pdu_spatem():
    assert _infer_msg_type_from_pdu(b"\x02\x05rest") == MessageType.SPATEM


def test_infer_msg_type_from_pdu_srem():
    assert _infer_msg_type_from_pdu(b"\x02\x09rest") == MessageType.SREM


def test_infer_msg_type_from_pdu_ssem():
    assert _infer_msg_type_from_pdu(b"\x02\x0arest") == MessageType.SSEM


def test_infer_msg_type_from_pdu_unknown_id():
    assert _infer_msg_type_from_pdu(b"\x02\x99rest") is None


def test_infer_msg_type_from_pdu_wrong_protocol_version():
    assert _infer_msg_type_from_pdu(b"\x03\x02rest") is None


def test_infer_msg_type_from_pdu_too_short():
    assert _infer_msg_type_from_pdu(b"\x02") is None
    assert _infer_msg_type_from_pdu(b"") is None
