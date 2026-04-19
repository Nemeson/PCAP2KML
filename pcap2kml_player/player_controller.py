"""Playback controller for synchronized message replay."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .data_model import SessionData, V2xMessage

logger = logging.getLogger(__name__)

TICK_INTERVAL_MS = 50
SPEED_OPTIONS = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]


class PlayerController(QObject):
    """Controls playback of V2X messages with accumulated time simulation."""

    tick = pyqtSignal(object)
    time_updated = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    state_changed = pyqtSignal(str)
    position_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: Optional[SessionData] = None
        self._messages: list[V2xMessage] = []
        self._current_index = 0
        self._speed = 1.0
        self._state = "stopped"
        self._playback_time_seconds = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def total_messages(self) -> int:
        return len(self._messages)

    def set_session(self, session: SessionData) -> None:
        """Set the session data for playback."""
        self.stop()
        self._session = session
        self._messages = list(session.messages)
        self._current_index = 0
        self._playback_time_seconds = 0.0
        if self._messages:
            self.duration_changed.emit(session.duration_seconds)

    def set_filtered_messages(self, messages: list[V2xMessage]) -> None:
        """Update the message list when filters change."""
        was_playing = self._state == "playing"
        self.stop()
        self._messages = messages
        self._current_index = 0
        self._playback_time_seconds = 0.0
        if self._messages:
            duration = (
                self._messages[-1].timestamp - self._messages[0].timestamp
            ).total_seconds()
            self.duration_changed.emit(duration)
        if was_playing and self._messages:
            self.play()

    def play(self) -> None:
        """Start or resume playback."""
        if not self._messages:
            return
        if self._current_index >= len(self._messages):
            self._current_index = 0
            self._playback_time_seconds = 0.0
        self._state = "playing"
        self._timer.start()
        self.tick.emit(self._messages[self._current_index])
        self.position_changed.emit(self._current_index)
        self.time_updated.emit(self._playback_time_seconds)
        self.state_changed.emit("playing")

    def pause(self) -> None:
        """Pause playback."""
        self._timer.stop()
        self._state = "paused"
        self.state_changed.emit("paused")

    def stop(self) -> None:
        """Stop playback and reset to beginning."""
        self._timer.stop()
        self._current_index = 0
        self._playback_time_seconds = 0.0
        self._state = "stopped"
        self.state_changed.emit("stopped")
        if self._messages:
            self.tick.emit(self._messages[0])
            self.position_changed.emit(0)
        else:
            self.tick.emit(None)
        self.time_updated.emit(self._playback_time_seconds)

    def set_speed(self, speed: float) -> None:
        """Set playback speed multiplier."""
        self._speed = speed

    def seek_to_index(self, index: int) -> None:
        """Jump to a specific message index."""
        if 0 <= index < len(self._messages):
            self._current_index = index
            msg = self._messages[index]
            self._playback_time_seconds = (
                msg.timestamp - self._messages[0].timestamp
            ).total_seconds()
            self.tick.emit(msg)
            self.position_changed.emit(index)
            self.time_updated.emit(self._playback_time_seconds)

    def seek_to_position(self, percent: float) -> None:
        """Jump to a position as percentage (0.0 - 1.0)."""
        if not self._messages:
            return
        index = int(percent * (len(self._messages) - 1))
        self.seek_to_index(max(0, min(index, len(self._messages) - 1)))

    def _on_tick(self) -> None:
        """Advance playback according to accumulated simulated time."""
        if not self._messages:
            self.pause()
            return

        previous_index = self._current_index
        self._playback_time_seconds += (TICK_INTERVAL_MS / 1000.0) * self._speed

        while self._current_index + 1 < len(self._messages):
            next_msg = self._messages[self._current_index + 1]
            next_offset = (
                next_msg.timestamp - self._messages[0].timestamp
            ).total_seconds()
            if next_offset > self._playback_time_seconds:
                break
            self._current_index += 1

        if self._current_index != previous_index:
            current_msg = self._messages[self._current_index]
            self.tick.emit(current_msg)
            self.position_changed.emit(self._current_index)
        self.time_updated.emit(self._playback_time_seconds)

        if self._current_index >= len(self._messages) - 1:
            self.pause()

    def format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS.s."""
        minutes = int(seconds) // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:04.1f}"

    def get_current_playback_time(self) -> float:
        """Get the current playback time in seconds from the start."""
        return self._playback_time_seconds
