"""KML export for V2X message trajectories.

Generates KML files compatible with Google Earth and QGIS using simplekml.
One KML file per entity/station ID, with Placemarks per message and
optional LineString trajectories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import simplekml

from data_model import MessageType, SessionData, V2xMessage

logger = logging.getLogger(__name__)

# Distinct colors for message types in KML
MSG_TYPE_COLORS = {
    MessageType.CAM: "ff0000ff",      # Blue
    MessageType.DENM: "ff0000ff",    # Red
    MessageType.SREM: "ffff6600",    # Orange
    MessageType.SSEM: "ff00ffff",    # Yellow
    MessageType.MAPEM: "ff00ff00",   # Green
    MessageType.SPATEM: "ffff00ff",  # Magenta
    MessageType.NMEA: "ff800000",    # Dark red / Maroon
}

# Distinct colors per station for trajectory lines
STATION_COLORS = [
    simplekml.Color.red,
    simplekml.Color.blue,
    simplekml.Color.green,
    simplekml.Color.orange,
    simplekml.Color.purple,
    simplekml.Color.cyan,
    simplekml.Color.magenta,
    simplekml.Color.yellow,
    simplekml.Color.darkred,
    simplekml.Color.darkblue,
]


def _get_station_color(index: int) -> str:
    """Get a color for a station based on its index."""
    return STATION_COLORS[index % len(STATION_COLORS)]


def export_kml(
    session: SessionData,
    output_dir: Path,
    active_types: Optional[set[MessageType]] = None,
    active_stations: Optional[set[str]] = None,
    include_trajectory: bool = True,
) -> list[Path]:
    """Export session data as KML files (one per station ID).

    Args:
        session: SessionData with parsed messages.
        output_dir: Directory to write KML files into.
        active_types: Optional filter — only these message types.
        active_stations: Optional filter — only these station IDs.
        include_trajectory: Whether to include LineString trajectories.

    Returns:
        List of paths to created KML files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    created_files: list[Path] = []

    # Apply filters
    types_filter = active_types or set(MsgType for MsgType in MessageType)
    stations_filter = active_stations or session.station_ids

    # Group messages by station ID
    stations: dict[str, list[V2xMessage]] = {}
    for msg in session.messages:
        if msg.msg_type not in types_filter:
            continue
        if msg.station_id not in stations_filter:
            continue
        stations.setdefault(msg.station_id, []).append(msg)

    for station_idx, (station_id, messages) in enumerate(stations.items()):
        kml = simplekml.Kml()
        kml.document.name = f"PCAP2KML - Station {station_id}"

        # Add placemarks for each message
        for msg in messages:
            pnt = kml.newpoint(
                name=f"{msg.msg_type.value} @ {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}",
                description=msg.to_kml_description(),
                coords=[(msg.longitude, msg.latitude, msg.altitude or 0)],
            )
            pnt.timestamp.when = msg.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            pnt.style.iconstyle.color = MSG_TYPE_COLORS.get(msg.msg_type, "ffffffff")

        # Add trajectory LineString
        if include_trajectory and len(messages) > 1:
            coords = [
                (msg.longitude, msg.latitude, msg.altitude or 0)
                for msg in messages
            ]
            line = kml.newlinestring(
                name=f"Trajectory - {station_id}",
                description=f"Path of station {station_id} ({len(messages)} points)",
                coords=coords,
            )
            line.style.linestyle.color = _get_station_color(station_idx)
            line.style.linestyle.width = 3
            line.extrude = 1
            line.altitudemode = simplekml.AltitudeMode.clamptoground

        # Write KML file
        safe_id = station_id.replace("/", "_").replace("\\", "_").replace(" ", "_")
        out_path = output_dir / f"station_{safe_id}.kml"
        kml.save(str(out_path))
        created_files.append(out_path)
        logger.info("Exported %d points for station %s -> %s", len(messages), station_id, out_path)

    return created_files