"""Global test fixtures for PCAP2KML Player.

Scope hierarchy:
  session  → qapp, tmp_pcap_dir
  module   → fake fixtures per module
  function → synthetic_session, sample messages
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage

logger = logging.getLogger(__name__)


# ─── Logging suppress noisy third-party ──────────────────────────

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
logging.getLogger("pyshark").setLevel(logging.ERROR)


# ─── Session-scope fixtures ─────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Qt Application instance for headless GUI tests."""
    # QtWebEngineWidgets must be imported before QApplication is instantiated,
    # otherwise the embedded Chromium process cannot initialize its GPU/GL
    # shared context. Importing the module triggers the necessary global setup.
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="session")
def tmp_pcap_dir(tmp_path_factory) -> Path:
    """Temporary directory for synthetic PCAP files."""
    return tmp_path_factory.mktemp("pcaps")


# ─── Function-scope helpers ──────────────────────────────────────

@pytest.fixture
def frozen_time():
    """Freeze time to 2026-01-01 12:00:00 UTC for deterministic tests."""
    from freezegun import freeze_time

    with freeze_time("2026-01-01 12:00:00", tz_offset=0):
        yield datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def synthetic_session() -> SessionData:
    """Empty SessionData with finalized state."""
    session = SessionData()
    session.finalize(build_merge_groups=False)
    return session


@pytest.fixture
def sample_cam_msg() -> V2xMessage:
    """Single CAM message with typical fields."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        station_id="veh-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
        altitude=10.0,
        heading=90.0,
        speed=50.0,
        details={"vehicleWidth": "2.1", "vehicleLength": "4.5"},
    )


@pytest.fixture
def sample_denm_msg() -> V2xMessage:
    """Single DENM message with typical fields."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        station_id="rsu-1",
        msg_type=MessageType.DENM,
        latitude=52.001,
        longitude=13.001,
        altitude=5.0,
        details={"causeCode": "2", "subCauseCode": "0", "severity": "1"},
    )


@pytest.fixture
def sample_map_msg() -> V2xMessage:
    """Single MAPEM message with intersection and lanes."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        details={"intersectionId": "42", "revision": "1"},
        decoded_data={
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
    )


@pytest.fixture
def sample_spat_msg() -> V2xMessage:
    """Single SPATEM message with signal groups."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 3, tzinfo=UTC),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
        details={"intersectionId": "42", "moy": "1", "timeStamp": "100"},
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
    )


@pytest.fixture
def sample_srem_msg() -> V2xMessage:
    """Single SREM message with requestor data."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 4, tzinfo=UTC),
        station_id="veh-1",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        details={"requestId": "1", "sequenceNumber": "0"},
        decoded_data={
            "requests": [
                {
                    "id": {"id": 1},
                    "requestor": {"type": {"role": "unknown"}},
                    "request": {
                        "inBoundLane": {"lane": 1},
                        "outBoundLane": {"lane": 2},
                    },
                }
            ]
        },
    )


@pytest.fixture
def sample_ssem_msg() -> V2xMessage:
    """Single SSEM message with grant status."""
    return V2xMessage(
        timestamp=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        station_id="rsu-1",
        msg_type=MessageType.SSEM,
        latitude=52.0,
        longitude=13.0,
        details={"requestId": "1", "sequenceNumber": "0", "status": "granted"},
        decoded_data={
            "status": "granted",
            "requestId": 1,
        },
    )


# ─── Headless marker ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ensure_headless(monkeypatch):
    """Force offscreen platform for all Qt tests if not already set."""
    import os

    if "QT_QPA_PLATFORM" not in os.environ:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    if "QT_OPENGL" not in os.environ:
        monkeypatch.setenv("QT_OPENGL", "software")
