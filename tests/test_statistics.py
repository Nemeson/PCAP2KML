"""Tests for statistics dashboard computations."""

from datetime import UTC, datetime, timedelta

import pytest

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.statistics import (
    compute_message_rate,
    compute_station_speed_heading,
    compute_session_overview,
)


def _make_session():
    session = SessionData()
    for i in range(10):
        session.add_message(
            V2xMessage(
                timestamp=datetime(2026, 1, 1, 12, 0, i, tzinfo=UTC),
                station_id="veh-1",
                msg_type=MessageType.CAM,
                latitude=52.0,
                longitude=13.0,
                altitude=None,
                speed=float(i * 10),
                heading=float(i * 36),
            )
        )
    session.finalize(build_merge_groups=False)
    return session


class TestSessionOverview:
    def test_overview(self):
        session = _make_session()
        overview = compute_session_overview(session)
        assert overview.total_messages == 10
        assert overview.station_count == 1
        assert overview.unique_types == 1
        assert overview.duration_seconds == 9.0


class TestMessageRate:
    def test_rate_per_second(self):
        session = _make_session()
        rates = compute_message_rate(session, bucket_seconds=1.0)
        assert len(rates) == 10
        for entry in rates:
            assert entry.rate == 1.0

    def test_rate_bucketed(self):
        session = _make_session()
        rates = compute_message_rate(session, bucket_seconds=5.0)
        assert len(rates) == 2
        assert rates[0].rate == 5.0 / 5.0
        assert rates[1].rate == 5.0 / 5.0


class TestSpeedHeading:
    def test_per_station(self):
        session = _make_session()
        stats = compute_station_speed_heading(session)
        assert "veh-1" in stats
        sh = stats["veh-1"]
        assert len(sh.speeds) == 10
        assert sh.avg_speed == pytest.approx(45.0)
        assert sh.avg_heading == pytest.approx(162.0)

    def test_empty(self):
        session = SessionData()
        session.finalize(build_merge_groups=False)
        assert compute_station_speed_heading(session) == {}
