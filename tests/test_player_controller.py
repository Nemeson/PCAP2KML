from __future__ import annotations

from datetime import datetime, timedelta

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.player_controller import PlayerController


def _message(ts: datetime, station: str = "station") -> V2xMessage:
    return V2xMessage(
        timestamp=ts,
        station_id=station,
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )


def test_player_advances_across_gaps_larger_than_single_tick() -> None:
    base = datetime(2025, 8, 22, 12, 0, 0)
    session = SessionData(
        messages=[
            _message(base),
            _message(base + timedelta(milliseconds=150)),
            _message(base + timedelta(milliseconds=320)),
        ]
    )

    controller = PlayerController()
    controller.set_session(session)
    controller.play()

    for _ in range(4):
        controller._on_tick()

    assert controller.current_index >= 1
    assert controller.get_current_playback_time() >= 0.15


def test_seek_updates_playback_time() -> None:
    base = datetime(2025, 8, 22, 12, 0, 0)
    session = SessionData(
        messages=[
            _message(base),
            _message(base + timedelta(seconds=2)),
            _message(base + timedelta(seconds=5)),
        ]
    )

    controller = PlayerController()
    controller.set_session(session)
    controller.seek_to_index(2)

    assert controller.current_index == 2
    assert controller.get_current_playback_time() == 5.0


def test_tick_emits_only_when_message_index_changes() -> None:
    base = datetime(2025, 8, 22, 12, 0, 0)
    session = SessionData(
        messages=[
            _message(base),
            _message(base + timedelta(seconds=1)),
        ]
    )

    controller = PlayerController()
    ticked_indices: list[int] = []
    time_updates: list[float] = []

    controller.tick.connect(lambda _msg: ticked_indices.append(controller.current_index))
    controller.time_updated.connect(time_updates.append)

    controller.set_session(session)
    controller.play()
    ticked_indices.clear()
    time_updates.clear()

    controller._on_tick()

    assert ticked_indices == []
    assert time_updates
    assert controller.current_index == 0


def test_play_emits_position_and_time_for_initial_state() -> None:
    base = datetime(2025, 8, 22, 12, 0, 0)
    session = SessionData(messages=[_message(base)])

    controller = PlayerController()
    positions: list[int] = []
    times: list[float] = []

    controller.position_changed.connect(positions.append)
    controller.time_updated.connect(times.append)

    controller.set_session(session)
    controller.play()

    assert positions[-1] == 0
    assert times[-1] == 0.0
