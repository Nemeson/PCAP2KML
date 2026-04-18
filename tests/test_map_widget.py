"""Tests for JavaScript escaping helpers in the map widget."""

from datetime import datetime, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.map_widget import (
    _js_escape,
    _marker_id_for_message,
    _marker_position_for_message,
)


def test_js_escape_handles_problematic_sequences():
    raw = "RSU` ${payload} </script> 'line'\nnext\rrow\x00"
    escaped = _js_escape(raw)

    assert "\\`" in escaped
    assert "\\${" in escaped
    assert "</script>" not in escaped.lower()
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert "\x00" not in escaped
    assert "\\'" in escaped
    assert "<\\/script>" in escaped


def test_marker_id_for_map_and_spat_stays_separate():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
    )
    cam_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 2, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )

    assert _marker_id_for_message(map_msg) != _marker_id_for_message(spat_msg)
    assert _marker_id_for_message(cam_msg) == "station_rsu-1"


def test_marker_position_offsets_map_and_spat_to_keep_both_visible():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
    )
    spat_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.SPATEM,
        latitude=52.0,
        longitude=13.0,
    )

    assert _marker_position_for_message(map_msg) != _marker_position_for_message(spat_msg)
