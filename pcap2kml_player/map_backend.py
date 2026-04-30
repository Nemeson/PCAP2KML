"""Map performance constants and shared configuration helpers."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

MAP_PERFORMANCE_NORMAL = "normal"
MAP_PERFORMANCE_SAVER = "saver"
MAP_PERFORMANCE_DIAGNOSTIC = "diagnostic"
MAP_PERFORMANCE_MODES = {
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
    MAP_PERFORMANCE_DIAGNOSTIC,
}

METERS_PER_DEGREE_LATITUDE = 111_320.0


def create_settings() -> QSettings:
    """Return the application-wide QSettings instance."""
    return QSettings("PCAP2KML", "Player")
