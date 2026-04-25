"""Tests for GeoJSON, CSV, GPX, and KML Tour exports."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.export_formats import (
    export_csv,
    export_geojson,
    export_gpx,
    export_kml_tour,
)


def _sample_session():
    session = SessionData()
    session.add_message(
        V2xMessage(
            timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            station_id="veh-1",
            msg_type=MessageType.CAM,
            latitude=52.0,
            longitude=13.0,
            altitude=10.0,
            heading=90.0,
            speed=50.0,
            details={"test": "data"},
        )
    )
    session.add_message(
        V2xMessage(
            timestamp=datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC),
            station_id="veh-1",
            msg_type=MessageType.CAM,
            latitude=52.001,
            longitude=13.001,
            altitude=11.0,
            heading=91.0,
            speed=51.0,
            details={"test": "data2"},
        )
    )
    session.finalize(build_merge_groups=False)
    return session


class TestGeoJSONExport:
    def test_export_geojson_creates_file(self, tmp_path: Path):
        session = _sample_session()
        result = export_geojson(session, tmp_path)
        assert len(result) == 1
        assert result[0].suffix == ".geojson"
        assert "FeatureCollection" in result[0].read_text(encoding="utf-8")

    def test_geojson_has_point_and_linestring(self, tmp_path: Path):
        session = _sample_session()
        export_geojson(session, tmp_path)
        geojson_path = next(tmp_path.glob("*.geojson"))
        import json

        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        assert len(data["features"]) == 3  # 2 points + 1 linestring
        assert data["features"][0]["geometry"]["type"] == "Point"
        assert data["features"][-1]["geometry"]["type"] == "LineString"


class TestCSVExport:
    def test_export_csv_creates_file(self, tmp_path: Path):
        session = _sample_session()
        out = tmp_path / "export.csv"
        result = export_csv(session, out)
        assert result == out
        content = out.read_text(encoding="utf-8")
        assert "timestamp" in content
        assert "veh-1" in content

    def test_csv_rows_count(self, tmp_path: Path):
        session = _sample_session()
        out = tmp_path / "export.csv"
        export_csv(session, out)
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3  # header + 2 data rows


class TestGPXExport:
    def test_export_gpx_creates_file(self, tmp_path: Path):
        session = _sample_session()
        result = export_gpx(session, tmp_path)
        assert len(result) == 1
        assert result[0].suffix == ".gpx"
        content = result[0].read_text(encoding="utf-8")
        assert "wpt" in content
        assert "trk" in content


class TestKMLTourExport:
    def test_export_kml_tour_creates_file(self, tmp_path: Path):
        session = _sample_session()
        result = export_kml_tour(session, tmp_path)
        assert len(result) == 1
        assert result[0].suffix == ".kml"
        content = result[0].read_text(encoding="utf-8")
        assert "gx:Tour" in content
        assert "TimeSpan" in content

    def test_tour_has_flyto_entries(self, tmp_path: Path):
        session = _sample_session()
        export_kml_tour(session, tmp_path)
        kml_path = next(tmp_path.glob("*.kml"))
        content = kml_path.read_text(encoding="utf-8")
        assert "gx:FlyTo" in content
        assert content.count("gx:FlyTo") == 4  # open + close for 2 entries

    def test_empty_messages(self, tmp_path: Path):
        session = SessionData()
        session.finalize(build_merge_groups=False)
        result = export_geojson(session, tmp_path)
        assert result == []
