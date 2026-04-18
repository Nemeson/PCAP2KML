"""Playback controller for synchronized message replay.

Uses QTimer to simulate PCAP time with adjustable speed. Emits tick
signals that the map widget and message list use to highlight the
current message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from data_model import SessionData, V2xMessage

logger = logging.getLogger(__name__)

# Timer interval in milliseconds
TICK_INTERVAL_MS = 50

# Available playback speeds
SPEED_OPTIONS = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]


class PlayerController(QObject):
    """Controls playback of V2X messages with time simulation."""

    # Signals
    tick = pyqtSignal(object)          # Emits current V2xMessage or None
    time_updated = pyqtSignal(float)   # Current playback time (epoch seconds)
    duration_changed = pyqtSignal(float)  # Total duration in seconds
    state_changed = pyqtSignal(str)   # "playing", "paused", "stopped"
    position_changed = pyqtSignal(int)  # Current message index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: Optional[SessionData] = None
        self._messages: list[V2xMessage] = []
        self._current_index: int = 0
        self._speed: float = 1.0
        self._state: str = "stopped"

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        # Real-time tracking
        self._last_real_time: float = 0.0
        self._playback_start_time: datetime = datetime.min.replace(tzinfo=timezone.utc)

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
        self._messages = list(session.messages)  # Work with a snapshot
        self._current_index = 0

        if self._messages:
            self.duration_changed.emit(session.duration_seconds)

    def set_filtered_messages(self, messages: list[V2xMessage]) -> None:
        """Update the message list when filters change (without restarting)."""
        was_playing = self._state == "playing"
        self.stop()
        self._messages = messages
        self._current_index = 0

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

        self._state = "playing"
        self._playback_start_time = self._messages[self._current_index].timestamp
        self._last_real_time = 0.0
        self._timer.start()
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
        self._state = "stopped"
        self.state_changed.emit("stopped")
        if self._messages:
            self.tick.emit(self._messages[0])
        else:
            self.tick.emit(None)

    def set_speed(self, speed: float) -> None:
        """Set playback speed multiplier."""
        self._speed = speed

    def seek_to_index(self, index: int) -> None:
        """Jump to a specific message index."""
        if 0 <= index < len(self._messages):
            self._current_index = index
            msg = self._messages[index]
            self.tick.emit(msg)
            self.position_changed.emit(index)
            if self._state == "playing":
                self._playback_start_time = msg.timestamp
                self._last_real_time = 0.0

    def seek_to_position(self, percent: float) -> None:
        """Jump to a position as percentage (0.0 - 1.0)."""
        if not self._messages:
            return
        index = int(percent * (len(self._messages) - 1))
        self.seek_to_index(max(0, min(index, len(self._messages) - 1)))

    def _on_tick(self) -> None:
        """Timer tick handler — advance playback position."""
        if self._current_index >= len(self._messages):
            self.pause()
            return

        current_msg = self._messages[self._current_index]

        # Find next message whose timestamp is ahead of the simulated time
        # Use elapsed real time * speed factor to simulate PCAP time
        elapsed_real = TICK_INTERVAL_MS / 1000.0
        elapsed_pcap = elapsed_real * self._speed

        # Advance to the next message if enough simulated time has passed
        next_index = self._current_index + 1
        if next_index < len(self._messages):
            next_msg = self._messages[next_index]
            gap = (next_msg.timestamp - current_msg.timestamp).total_seconds()

            if elapsed_pcap >= gap:
                self._current_index = next_index
                self.tick.emit(next_msg)
                self.position_changed.emit(next_index)
            else:
                # Still within the current time gap — emit current message
                self.tick.emit(current_msg)
        else:
            # Last message reached
            self._current_index = next_index
            self.tick.emit(current_msg)
            self.pause()

    def format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS.s."""
        minutes = int(seconds) // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:04.1f}"

    def get_current_playback_time(self) -> float:
        """Get the current playback time as seconds from start."""
        if not self._messages or self._current_index >= len(self._messages):
            return 0.0
        current_msg = self._messages[self._current_index]
        start_time = self._messages[0].timestamp
        return (current_msg.timestamp - start_time).total_seconds()