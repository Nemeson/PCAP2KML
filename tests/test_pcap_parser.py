from __future__ import annotations

from pathlib import Path

from pcap2kml_player.data_model import CaptureRole, MessageType
from pcap2kml_player.pcap_parser import parse_pcap


TESTFILES = Path(__file__).resolve().parent.parent / "testfiles"


def test_parse_srem_with_ocit_pcap() -> None:
    session = parse_pcap(str(TESTFILES / "SREM with OCIT.pcap"))

    assert session.messages
    assert session.msg_type_counts[MessageType.SREM] > 0
    assert any(53.0 < msg.latitude < 54.0 for msg in session.messages)
    assert any(10.0 < msg.longitude < 11.0 for msg in session.messages)


def test_parse_rxa_22082025_pcap() -> None:
    session = parse_pcap(str(TESTFILES / "rxa_22082025.pcap"))

    assert session.messages
    assert MessageType.MAPEM in session.msg_type_counts
    assert len(session.station_ids) >= 1


def test_parse_txa_22082025_pcap() -> None:
    session = parse_pcap(str(TESTFILES / "txa_22082025.pcap"))

    assert session.messages
    assert session.msg_type_counts[MessageType.SPATEM] > 0
    assert any(52.0 < msg.latitude < 53.0 for msg in session.messages)
    assert session.sources[0].role == CaptureRole.TXA
    assert all(msg.source is not None for msg in session.messages)
    assert {msg.source.role for msg in session.messages if msg.source} == {CaptureRole.TXA}


def test_parse_txa_22082025_pcap_decodes_mapem_and_spatem_payloads() -> None:
    session = parse_pcap(str(TESTFILES / "txa_22082025.pcap"))

    map_messages = [msg for msg in session.messages if msg.msg_type == MessageType.MAPEM]
    spat_messages = [msg for msg in session.messages if msg.msg_type == MessageType.SPATEM]

    assert map_messages
    assert spat_messages
    assert any(msg.decoded_data for msg in map_messages)
    assert any(msg.decoded_data for msg in spat_messages)

    decoded_map = next(msg for msg in map_messages if msg.decoded_data)
    decoded_spat = next(msg for msg in spat_messages if msg.decoded_data)

    map_intersection = decoded_map.decoded_data["intersections"][0]
    map_lane = map_intersection["laneSet"][0]
    map_nodes = map_lane["nodeList"]["nodes"]
    spat_state = decoded_spat.decoded_data["intersections"][0]["states"][0]

    assert map_intersection["refPoint"]["lat"] > 52.0
    assert map_intersection["refPoint"]["lon"] > 13.0
    assert len(map_nodes) >= 2
    assert "lat" in map_nodes[0]
    assert "lon" in map_nodes[0]
    assert "stateTimeSpeed" in spat_state


def test_parse_rsu_rxa_preserves_denm_null_island_when_lpv_is_not_trusted() -> None:
    session = parse_pcap(
        str(TESTFILES / "2024-04-24_LB72_RSU_PCAP" / "10.28_srem_oev" / "rsu_rxa.pcap")
    )

    denm_messages = [msg for msg in session.messages if msg.msg_type == MessageType.DENM]

    assert denm_messages
    assert any(
        abs(msg.latitude) < 1e-9 and abs(msg.longitude) < 1e-9
        for msg in denm_messages
    )
    assert not any("Positions-Fallback" in msg.details for msg in denm_messages)


def test_parse_txa_22082025_pcap_normalizes_map_lane_roles_connections_and_stoplines() -> None:
    session = parse_pcap(str(TESTFILES / "txa_22082025.pcap"))

    map_messages = [msg for msg in session.messages if msg.msg_type == MessageType.MAPEM and msg.decoded_data]

    assert map_messages
    map_intersection = map_messages[0].decoded_data["intersections"][0]
    lanes = map_intersection["laneSet"]
    inbound_lanes = [lane for lane in lanes if lane.get("laneRole") == "inbound"]
    outbound_lanes = [lane for lane in lanes if lane.get("laneRole") == "outbound"]

    assert inbound_lanes
    assert outbound_lanes
    assert any(lane.get("connections") for lane in inbound_lanes)
    assert any("stopLine" in lane for lane in inbound_lanes)
    assert all("stopLine" not in lane for lane in outbound_lanes)

    first_connected_lane = next(lane for lane in inbound_lanes if lane.get("connections"))
    first_connection = first_connected_lane["connections"][0]

    assert "laneId" in first_connected_lane
    assert "targetLaneId" in first_connection
    assert "signalGroup" in first_connection


def test_parse_rxa_22082025_cam_extracts_partial_header_without_fake_security() -> None:
    session = parse_pcap(str(TESTFILES / "rxa_22082025.pcap"))

    cam_messages = [msg for msg in session.messages if msg.msg_type == MessageType.CAM]

    assert cam_messages
    partial_cam = next(msg for msg in cam_messages if msg.decoded_data)
    assert partial_cam.security_info is None
    assert partial_cam.details["ASN.1-Dekodierung"] == (
        "CAM-Header teilweise extrahiert - optionale Container unvollstaendig"
    )
    assert partial_cam.decoded_data["stationId"] == 7153
    assert "generationDeltaTime" in partial_cam.decoded_data
    assert "speed" in partial_cam.decoded_data
    assert "heading" in partial_cam.decoded_data
    assert partial_cam.speed is not None
    assert partial_cam.heading is not None
    assert partial_cam.details["Fallback-Quelle"] == "GeoNetworking Long Position Vector"


def test_parse_rxa_22082025_marks_cam_station_id_outlier_without_rewriting_it() -> None:
    session = parse_pcap(str(TESTFILES / "rxa_22082025.pcap"))

    cam_messages = [msg for msg in session.messages if msg.msg_type == MessageType.CAM]
    flagged = [msg for msg in cam_messages if "Identitaets-Hinweis" in msg.details]

    assert flagged
    assert {msg.station_id for msg in cam_messages} == {"7153", "3858003421"}
    assert len(flagged) == 1
    assert flagged[0].station_id == "3858003421"
    assert flagged[0].decoded_data["stationId"] == 3858003421
    assert "dominanter Session-ID 7153" in flagged[0].details["Identitaets-Hinweis"]
