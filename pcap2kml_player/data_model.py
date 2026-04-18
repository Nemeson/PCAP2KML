"""Data model for PCAP2KML Player.

Defines the core data structures shared across all modules:
V2xMessage, MessageType, SessionData.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MessageType(Enum):
    """Supported V2X and GNSS message types."""
    CAM = "CAM"
    DENM = "DENM"
    SREM = "SREM"
    SSEM = "SSEM"
    MAPEM = "MAPEM"
    SPATEM = "SPATEM"
    NMEA = "NMEA"


@dataclass
class V2xMessage:
    """A single decoded V2X or NMEA message with position data."""
    timestamp: datetime
    station_id: str
    msg_type: MessageType
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    raw_payload: Optional[bytes] = None

    def to_kml_description(self) -> str:
        """Generate an HTML description string for KML Placemark."""
        parts = [
            f"<b>Type:</b> {self.msg_type.value}",
            f"<b>Station:</b> {self.station_id}",
            f"<b>Time:</b> {self.timestamp.isoformat()}",
            f"<b>Lat/Lon:</b> {self.latitude:.6f}, {self.longitude:.6f}",
        ]
        if self.altitude is not None:
            parts.append(f"<b>Altitude:</b> {self.altitude:.1f} m")
        if self.speed is not None:
            parts.append(f"<b>Speed:</b> {self.speed:.1f} m/s")
        if self.heading is not None:
            parts.append(f"<b>Heading:</b> {self.heading:.1f}°")
        return "<br>".join(parts)


@dataclass
class SessionData:
    """Container for all messages parsed from one or more PCAP files."""
    messages: list[V2xMessage] = field(default_factory=list)
    station_ids: set[str] = field(default_factory=set)
    msg_type_counts: dict[MessageType, int] = field(default_factory=dict)

    @property
    def time_range(self) -> tuple[datetime, datetime]:
        """First and last timestamp in the session."""
        if not self.messages:
            raise ValueError("Session has no messages")
        return self.messages[0].timestamp, self.messages[-1].timestamp

    @property
    def duration_seconds(self) -> float:
        """Duration of the session in seconds."""
        if not self.messages:
            return 0.0
        start, end = self.time_range
        return (end - start).total_seconds()

    def add_message(self, msg: V2xMessage) -> None:
        """Add a message and update indices."""
        self.messages.append(msg)
        self.station_ids.add(msg.station_id)
        self.msg_type_counts[msg.msg_type] = self.msg_type_counts.get(msg.msg_type, 0) + 1

    def finalize(self) -> None:
        """Sort messages by timestamp after all parsing is complete."""
        self.messages.sort(key=lambda m: m.timestamp)

    def filter_messages(
        self,
        active_types: set[MessageType],
        active_stations: set[str],
    ) -> list[V2xMessage]:
        """Return messages matching the given type and station filters."""
        return [
            m for m in self.messages
            if m.msg_type in active_types and m.station_id in active_stations
        ]