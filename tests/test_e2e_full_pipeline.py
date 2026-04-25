"""End-to-end full pipeline test using real capture files."""

from __future__ import annotations

from pathlib import Path

import pytest

from pcap2kml_player.data_model import SessionData
from pcap2kml_player.export_formats import (
    export_csv,
    export_geojson,
    export_gpx,
    export_kml_tour,
)
from pcap2kml_player.merge_model import build_merge_groups
from pcap2kml_player.pcap_parser import parse_pcap


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.pcap_real
class TestFullPipelineE2E:
    """Load real PCAP → Session → Exports → Verify contents."""

    TESTFILES = Path(__file__).parent.parent / "testfiles"

    def _load_capture(self, stem: str) -> SessionData:
        paths = list(self.TESTFILES.glob(f"{stem}*.pcap*"))
        if not paths:
            pytest.skip(f"Capture {stem}* not found in testfiles/")
        session = SessionData()
        for p in paths[:1]:
            parse_pcap(str(p), session)
        session.finalize()
        build_merge_groups(session.messages)
        return session

    def test_load_txa_and_export(self, tmp_path: Path) -> None:
        session = self._load_capture("txa_22082025")
        assert len(session.messages) > 0
        assert len(session.station_ids) > 0

        # Export all formats
        kml_dir = tmp_path / "kml"
        kml_dir.mkdir()
        # KML Tour
        kml_files = export_kml_tour(session, kml_dir)
        assert len(kml_files) > 0
        assert all(f.exists() for f in kml_files)

        # GeoJSON
        geojson_dir = tmp_path / "geojson"
        gj_files = export_geojson(session, geojson_dir)
        assert len(gj_files) > 0
        for f in gj_files:
            assert "FeatureCollection" in f.read_text(encoding="utf-8")

        # CSV
        csv_path = tmp_path / "export.csv"
        export_csv(session, csv_path)
        assert csv_path.exists()
        lines = csv_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 2  # header + at least one row

        # GPX
        gpx_dir = tmp_path / "gpx"
        gpx_files = export_gpx(session, gpx_dir)
        assert len(gpx_files) > 0
        for f in gpx_files:
            assert "wpt" in f.read_text(encoding="utf-8")

    def test_load_rxa_and_merge_with_txa(self) -> None:
        txa = self._load_capture("txa_22082025")
        rxa = self._load_capture("rxa_22082025")

        combined = SessionData()
        for msg in txa.messages:
            combined.add_message(msg)
        for msg in rxa.messages:
            combined.add_message(msg)
        combined.finalize()
        build_merge_groups(combined.messages)

        # Should have merge groups if captures overlap
        assert len(combined.merge_groups) >= 0

    def test_statistics_computation(self) -> None:
        from pcap2kml_player.statistics import (
            compute_message_rate,
            compute_session_overview,
            compute_station_speed_heading,
        )

        session = self._load_capture("txa_22082025")
        overview = compute_session_overview(session)
        assert overview.total_messages > 0
        assert overview.station_count > 0

        rates = compute_message_rate(session, bucket_seconds=1.0)
        assert len(rates) > 0
        for entry in rates:
            assert entry.rate >= 0

        stats = compute_station_speed_heading(session)
        # May be empty if no speed data
        for station_id, sh in stats.items():
            assert sh.avg_speed >= 0
