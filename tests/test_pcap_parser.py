from __future__ import annotations

from pathlib import Path

from pcap2kml_player.data_model import MessageType
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
