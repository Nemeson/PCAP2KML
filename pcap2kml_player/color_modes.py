"""Shared visual color palettes for maps and exports."""

from __future__ import annotations

from .data_model import MessageType

MAP_COLOR_MODE_NORMAL = "normal"
MAP_COLOR_MODE_COLORBLIND = "colorblind"
MAP_COLOR_MODES = {MAP_COLOR_MODE_NORMAL, MAP_COLOR_MODE_COLORBLIND}

NORMAL_MESSAGE_HEX = {
    MessageType.CAM: "#2563eb",
    MessageType.DENM: "#dc2626",
    MessageType.SREM: "#f97316",
    MessageType.SSEM: "#facc15",
    MessageType.MAPEM: "#16a34a",
    MessageType.SPATEM: "#c026d3",
    MessageType.NMEA: "#7f1d1d",
}

COLORBLIND_MESSAGE_HEX = {
    MessageType.CAM: "#0072b2",
    MessageType.DENM: "#d55e00",
    MessageType.SREM: "#e69f00",
    MessageType.SSEM: "#56b4e9",
    MessageType.MAPEM: "#009e73",
    MessageType.SPATEM: "#cc79a7",
    MessageType.NMEA: "#000000",
}

NORMAL_STATION_HEX = [
    "#dc2626",
    "#2563eb",
    "#16a34a",
    "#f97316",
    "#c026d3",
    "#06b6d4",
    "#db2777",
    "#facc15",
    "#7f1d1d",
    "#1e3a8a",
]

COLORBLIND_STATION_HEX = [
    "#0072b2",
    "#e69f00",
    "#009e73",
    "#d55e00",
    "#cc79a7",
    "#56b4e9",
    "#000000",
    "#f0e442",
    "#8b5a2b",
    "#6a3d9a",
]


def normalize_color_mode(color_mode: str | None) -> str:
    """Return a supported color mode string."""
    return color_mode if color_mode in MAP_COLOR_MODES else MAP_COLOR_MODE_NORMAL


def message_color_hex(msg_type: MessageType, color_mode: str | None = None) -> str:
    """Return a CSS hex color for a V2X message type."""
    palette = COLORBLIND_MESSAGE_HEX if normalize_color_mode(color_mode) == MAP_COLOR_MODE_COLORBLIND else NORMAL_MESSAGE_HEX
    return palette.get(msg_type, "#ffffff")


def station_color_hex(index: int, color_mode: str | None = None) -> str:
    """Return a CSS hex color for a station trajectory."""
    palette = COLORBLIND_STATION_HEX if normalize_color_mode(color_mode) == MAP_COLOR_MODE_COLORBLIND else NORMAL_STATION_HEX
    return palette[index % len(palette)]


def hex_to_kml_color(hex_color: str, alpha: str = "ff") -> str:
    """Convert #RRGGBB to KML AABBGGRR."""
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return "ffffffff"
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"{alpha}{blue}{green}{red}".lower()


def message_kml_color(msg_type: MessageType, color_mode: str | None = None) -> str:
    """Return a KML AABBGGRR color for a V2X message type."""
    return hex_to_kml_color(message_color_hex(msg_type, color_mode))


def station_kml_color(index: int, color_mode: str | None = None) -> str:
    """Return a KML AABBGGRR color for a station trajectory."""
    return hex_to_kml_color(station_color_hex(index, color_mode))
