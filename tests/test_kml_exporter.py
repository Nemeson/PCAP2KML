"""Tests for KML export (simplekml-based)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.kml_exporter import MSG_TYPE_COLORS, export_kml

NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _mk_msg(station: str, msg_type: MessageType, lat: float, lon: float, offset_s: float):
    return V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_s),
        station_id=station,
        msg_type=msg_type,
        latitude=lat,
        longitude=lon,
        altitude=100.0,
        speed=10.0,
        heading=45.0,
    )


@pytest.fixture
def session():
    s = SessionData()
    for i in range(3):
        s.add_message(_mk_msg("A", MessageType.CAM, 48.0 + i * 0.001, 11.0 + i * 0.001, i))
    for i in range(2):
        s.add_message(_mk_msg("B", MessageType.DENM, 49.0 + i * 0.001, 12.0 + i * 0.001, i))
    s.finalize()
    return s


def test_export_kml_creates_one_file_per_station(session, tmp_path: Path):
    created = export_kml(session, tmp_path)
    assert len(created) == 2
    names = {p.name for p in created}
    assert names == {"station_A.kml", "station_B.kml"}


def test_export_kml_files_are_valid_xml(session, tmp_path: Path):
    created = export_kml(session, tmp_path)
    for path in created:
        root = ET.parse(path).getroot()
        assert root.tag.endswith("}kml")


def test_export_kml_contains_placemarks_per_message(session, tmp_path: Path):
    created = export_kml(session, tmp_path)
    station_a = next(p for p in created if p.name == "station_A.kml")
    root = ET.parse(station_a).getroot()
    placemarks = root.findall(".//kml:Placemark", NS)
    # 3 points + 1 trajectory LineString
    assert len(placemarks) == 4


def test_export_kml_includes_trajectory_linestring(session, tmp_path: Path):
    created = export_kml(session, tmp_path)
    station_a = next(p for p in created if p.name == "station_A.kml")
    root = ET.parse(station_a).getroot()
    lines = root.findall(".//kml:LineString", NS)
    assert len(lines) == 1


def test_export_kml_skips_trajectory_when_disabled(session, tmp_path: Path):
    created = export_kml(session, tmp_path, include_trajectory=False)
    station_a = next(p for p in created if p.name == "station_A.kml")
    root = ET.parse(station_a).getroot()
    assert root.findall(".//kml:LineString", NS) == []


def test_export_kml_respects_type_filter(session, tmp_path: Path):
    # Only CAM -> station B (DENM only) should be skipped entirely
    created = export_kml(session, tmp_path, active_types={MessageType.CAM})
    assert len(created) == 1
    assert created[0].name == "station_A.kml"


def test_export_kml_respects_station_filter(session, tmp_path: Path):
    created = export_kml(session, tmp_path, active_stations={"B"})
    assert len(created) == 1
    assert created[0].name == "station_B.kml"


def test_export_kml_sanitizes_station_id_in_filename(tmp_path: Path):
    s = SessionData()
    s.add_message(_mk_msg("weird / id \\ with spaces", MessageType.NMEA, 48.0, 11.0, 0))
    s.finalize()
    created = export_kml(s, tmp_path)
    assert len(created) == 1
    assert "/" not in created[0].name
    assert "\\" not in created[0].name
    assert " " not in created[0].name


def test_export_kml_sanitizes_windows_invalid_filename_chars(tmp_path: Path):
    s = SessionData()
    s.add_message(_mk_msg("02:11:22:33:44:55", MessageType.CAM, 48.0, 11.0, 0))
    s.finalize()

    created = export_kml(s, tmp_path)

    assert len(created) == 1
    assert ":" not in created[0].name
    assert created[0].exists()


def test_export_kml_avoids_filename_collisions_after_sanitizing(tmp_path: Path):
    s = SessionData()
    s.add_message(_mk_msg("A/B", MessageType.CAM, 48.0, 11.0, 0))
    s.add_message(_mk_msg("A:B", MessageType.DENM, 49.0, 12.0, 1))
    s.finalize()

    created = export_kml(s, tmp_path)

    assert len(created) == 2
    assert len({path.name.lower() for path in created}) == 2


def test_kml_message_type_colors_are_unique():
    assert len(set(MSG_TYPE_COLORS.values())) == len(MSG_TYPE_COLORS)
