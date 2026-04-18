"""KML export for V2X message trajectories.

Generates KML files compatible with Google Earth and QGIS using simplekml.
One KML file per entity/station ID, with Placemarks per message and
optional LineString trajectories.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import simplekml

from .data_model import MessageType, SessionData, V2xMessage

logger = logging.getLogger(__name__)

# Distinct colors for message types in KML
MSG_TYPE_COLORS = {
    MessageType.CAM: "ff0000ff",      # Blue
    MessageType.DENM: "ffff0000",     # Red
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

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\s]+')


def _get_station_color(index: int) -> str:
    """Get a color for a station based on its index."""
    return STATION_COLORS[index % len(STATION_COLORS)]


def _sanitize_station_id(station_id: str) -> str:
    """Convert a station id into a Windows-safe filename fragment."""
    sanitized = _INVALID_FILENAME_CHARS.sub("_", station_id).strip("._")
    return sanitized or "unknown_station"


def _make_output_path(output_dir: Path, station_id: str, used_names: set[str]) -> Path:
    """Create a unique output path even when sanitized station ids collide."""
    safe_id = _sanitize_station_id(station_id)
    candidate = f"station_{safe_id}.kml"
    suffix = 2
    while candidate.lower() in used_names:
        candidate = f"station_{safe_id}_{suffix}.kml"
        suffix += 1
    used_names.add(candidate.lower())
    return output_dir / candidate


def _format_schema_provenance() -> str:
    """Build a short human-readable string of ASN.1 schema versions in use."""
    try:
        from .asn1_schemas import get_schema_versions
    except ImportError:
        return ""
    versions = get_schema_versions()
    if not versions:
        return ""
    parts = [f"{name}: {ver}" for name, ver in sorted(versions.items())]
    return "ASN.1 Schema-Versionen: " + "; ".join(parts)


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
    used_names: set[str] = set()

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

    # Phase 2.2: record the ASN.1 schema versions used for this export so
    # downstream viewers can trace the decoding lineage.
    schema_provenance = _format_schema_provenance()

    for station_idx, (station_id, messages) in enumerate(stations.items()):
        kml = simplekml.Kml()
        kml.document.name = f"PCAP2KML - Station {station_id}"
        if schema_provenance:
            kml.document.description = schema_provenance

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
        out_path = _make_output_path(output_dir, station_id, used_names)
        kml.save(str(out_path))
        created_files.append(out_path)
        logger.info("Exported %d points for station %s -> %s", len(messages), station_id, out_path)

    return created_files
