"""Additional export formats: GeoJSON, CSV, GPX, and animated KML Tour."""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from .data_model import MessageType, SessionData, V2xMessage

logger = logging.getLogger(__name__)

_INVALID_FILENAME_CHARS = re.compile(r"[<>:\"/\\|?*\s]+")


def _sanitize_station_id(station_id: str) -> str:
    """Convert a station id into a Windows-safe filename fragment."""
    sanitized = _INVALID_FILENAME_CHARS.sub("_", station_id).strip("._")
    return sanitized or "unknown_station"


def _make_output_path(output_dir: Path, station_id: str, suffix: str, used_names: set[str]) -> Path:
    """Create a unique output path even when sanitized station ids collide."""
    safe_id = _sanitize_station_id(station_id)
    candidate = f"station_{safe_id}{suffix}"
    num = 2
    while candidate.lower() in used_names:
        candidate = f"station_{safe_id}_{num}{suffix}"
        num += 1
    used_names.add(candidate.lower())
    return output_dir / candidate


def _get_filtered_messages(
    session: SessionData,
    active_types: set[MessageType] | None,
    active_stations: set[str] | None,
    canonical: bool,
) -> list[V2xMessage]:
    """Return the message stream respecting canonical view and filters."""
    messages = session.canonical_messages() if canonical else session.messages
    types_filter = active_types or set(MessageType)
    stations_filter = active_stations or session.station_ids
    return [msg for msg in messages if msg.msg_type in types_filter and msg.station_id in stations_filter]


# ─────────────────────────────────────────────
# GeoJSON Export
# ─────────────────────────────────────────────


def export_geojson(
    session: SessionData,
    output_dir: Path,
    active_types: set[MessageType] | None = None,
    active_stations: set[str] | None = None,
    include_trajectory: bool = True,
    canonical: bool = False,
) -> list[Path]:
    """Export session data as GeoJSON files (one per station ID)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    used_names: set[str] = set()

    messages = _get_filtered_messages(session, active_types, active_stations, canonical)
    stations: dict[str, list[V2xMessage]] = {}
    for msg in messages:
        stations.setdefault(msg.station_id, []).append(msg)

    for station_id, msgs in stations.items():
        features: list[dict] = []
        for msg in msgs:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            msg.longitude,
                            msg.latitude,
                            msg.altitude or 0,
                        ],
                    },
                    "properties": {
                        "timestamp": msg.timestamp.isoformat(),
                        "msg_type": msg.msg_type.value,
                        "station_id": msg.station_id,
                        "heading": msg.heading,
                        "speed": msg.speed,
                        "details": msg.details,
                    },
                }
            )
        if include_trajectory and len(msgs) > 1:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[msg.longitude, msg.latitude, msg.altitude or 0] for msg in msgs],
                    },
                    "properties": {
                        "type": "trajectory",
                        "station_id": station_id,
                        "point_count": len(msgs),
                    },
                }
            )

        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "properties": {
                "station_id": station_id,
                "message_count": len(msgs),
                "export_format": "geojson",
            },
        }

        out_path = _make_output_path(output_dir, station_id, ".geojson", used_names)
        out_path.write_text(json.dumps(geojson, indent=2, ensure_ascii=False), encoding="utf-8")
        created.append(out_path)
        logger.info("Exported GeoJSON for station %s -> %s", station_id, out_path)

    return created


# ─────────────────────────────────────────────
# CSV Export
# ─────────────────────────────────────────────


def export_csv(
    session: SessionData,
    output_path: Path,
    active_types: set[MessageType] | None = None,
    active_stations: set[str] | None = None,
    canonical: bool = False,
) -> Path:
    """Export session data as a single CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    messages = _get_filtered_messages(session, active_types, active_stations, canonical)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "station_id",
                "msg_type",
                "latitude",
                "longitude",
                "altitude",
                "heading",
                "speed",
                "details_json",
            ]
        )
        for msg in messages:
            writer.writerow(
                [
                    msg.timestamp.isoformat(),
                    msg.station_id,
                    msg.msg_type.value,
                    msg.latitude,
                    msg.longitude,
                    msg.altitude,
                    msg.heading,
                    msg.speed,
                    json.dumps(msg.details, ensure_ascii=False),
                ]
            )

    logger.info("Exported CSV -> %s (%d rows)", output_path, len(messages))
    return output_path


# ─────────────────────────────────────────────
# GPX Export
# ─────────────────────────────────────────────


def export_gpx(
    session: SessionData,
    output_dir: Path,
    active_types: set[MessageType] | None = None,
    active_stations: set[str] | None = None,
    canonical: bool = False,
) -> list[Path]:
    """Export session data as GPX 1.1 files (one per station ID)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    used_names: set[str] = set()

    messages = _get_filtered_messages(session, active_types, active_stations, canonical)
    stations: dict[str, list[V2xMessage]] = {}
    for msg in messages:
        stations.setdefault(msg.station_id, []).append(msg)

    ns = "http://www.topografix.com/GPX/1/1"
    ET.register_namespace("", ns)

    for station_id, msgs in stations.items():
        root = ET.Element(
            "{%s}gpx" % ns,
            {
                "version": "1.1",
                "creator": "PCAP2KML-Player",
            },
        )
        root.set("xmlns", ns)

        # Waypoints for each message
        for msg in msgs:
            wpt = ET.SubElement(root, "{%s}wpt" % ns)
            wpt.set("lat", str(msg.latitude))
            wpt.set("lon", str(msg.longitude))
            if msg.altitude is not None:
                ele = ET.SubElement(wpt, "{%s}ele" % ns)
                ele.text = str(msg.altitude)
            name = ET.SubElement(wpt, "{%s}name" % ns)
            name.text = f"{msg.msg_type.value} @ {msg.timestamp.strftime('%H:%M:%S')}"
            time = ET.SubElement(wpt, "{%s}time" % ns)
            time.text = msg.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Track for trajectory
        if len(msgs) > 1:
            trk = ET.SubElement(root, "{%s}trk" % ns)
            trk_name = ET.SubElement(trk, "{%s}name" % ns)
            trk_name.text = f"Trajectory - {station_id}"
            trkseg = ET.SubElement(trk, "{%s}trkseg" % ns)
            for msg in msgs:
                trkpt = ET.SubElement(trkseg, "{%s}trkpt" % ns)
                trkpt.set("lat", str(msg.latitude))
                trkpt.set("lon", str(msg.longitude))
                if msg.altitude is not None:
                    ele = ET.SubElement(trkpt, "{%s}ele" % ns)
                    ele.text = str(msg.altitude)

        tree = ET.ElementTree(root)
        out_path = _make_output_path(output_dir, station_id, ".gpx", used_names)
        tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
        created.append(out_path)
        logger.info("Exported GPX for station %s -> %s", station_id, out_path)

    return created


# ─────────────────────────────────────────────
# Animated KML Tour Export
# ─────────────────────────────────────────────


def export_kml_tour(
    session: SessionData,
    output_dir: Path,
    active_types: set[MessageType] | None = None,
    active_stations: set[str] | None = None,
    canonical: bool = False,
) -> list[Path]:
    """Export session data as an animated KML Tour (one per station ID).

    Uses <gx:Tour> with <gx:Playlist> for a flyover animation,
    and <TimeSpan> on Placemarks for timeline display.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    used_names: set[str] = set()

    messages = _get_filtered_messages(session, active_types, active_stations, canonical)
    stations: dict[str, list[V2xMessage]] = {}
    for msg in messages:
        stations.setdefault(msg.station_id, []).append(msg)

    for station_id, msgs in stations.items():
        kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        kml.set("xmlns:gx", "http://www.google.com/kml/ext/2.2")
        document = ET.SubElement(kml, "Document")
        doc_name = ET.SubElement(document, "name")
        doc_name.text = f"PCAP2KML Tour - Station {station_id}"

        # Style for point
        style = ET.SubElement(document, "Style", id="pointStyle")
        icon_style = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(icon_style, "Icon")
        href = ET.SubElement(icon, "href")
        href.text = "http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png"

        # Create folder for placemarks
        folder = ET.SubElement(document, "Folder")
        folder_name = ET.SubElement(folder, "name")
        folder_name.text = "Messages"

        for msg in msgs:
            pm = ET.SubElement(folder, "Placemark")
            pm_name = ET.SubElement(pm, "name")
            pm_name.text = f"{msg.msg_type.value}"
            pm_desc = ET.SubElement(pm, "description")
            pm_desc.text = msg.to_kml_description()

            # TimeSpan for temporal display
            timespan = ET.SubElement(pm, "TimeSpan")
            begin = ET.SubElement(timespan, "begin")
            begin.text = msg.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            end = ET.SubElement(timespan, "end")
            end.text = (msg.timestamp + __import__("datetime").timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Point geometry
            point = ET.SubElement(pm, "Point")
            coords = ET.SubElement(point, "coordinates")
            coords.text = f"{msg.longitude},{msg.latitude},{msg.altitude or 0}"

        # Create Tour
        if len(msgs) > 1:
            tour = ET.SubElement(document, "gx:Tour")
            tour_name = ET.SubElement(tour, "name")
            tour_name.text = f"Flyover - {station_id}"
            playlist = ET.SubElement(tour, "gx:Playlist")

            for msg in msgs:
                flyto = ET.SubElement(playlist, "gx:FlyTo")
                duration = ET.SubElement(flyto, "gx:duration")
                duration.text = "2.0"

                camera = ET.SubElement(flyto, "Camera")
                long = ET.SubElement(camera, "longitude")
                long.text = str(msg.longitude)
                lat = ET.SubElement(camera, "latitude")
                lat.text = str(msg.latitude)
                alt = ET.SubElement(camera, "altitude")
                alt.text = str((msg.altitude or 0) + 100)
                alt_mode = ET.SubElement(camera, "altitudeMode")
                alt_mode.text = "relativeToGround"
                heading_el = ET.SubElement(camera, "heading")
                heading_el.text = str(msg.heading or 0)
                tilt = ET.SubElement(camera, "tilt")
                tilt.text = "60"

        tree = ET.ElementTree(kml)
        out_path = _make_output_path(output_dir, station_id, ".kml", used_names)
        tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
        created.append(out_path)
        logger.info("Exported KML Tour for station %s -> %s", station_id, out_path)

    return created
