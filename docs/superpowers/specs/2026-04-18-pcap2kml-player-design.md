# PCAP2KML Player — Design Specification

**Date:** 2026-04-18
**Status:** Approved
**Author:** Kevin Seipel + Claude

---

## Overview

PCAP2KML Player is a Python desktop application for Windows that loads PCAP files containing V2X (ETSI ITS G5 / DSRC) messages, visualizes them on an interactive Leaflet map with synchronized playback, and exports GPS trajectories as KML files for Google Earth / QGIS.

## Architecture

**Approach:** Monolithic Pipeline with Qt-Signals at seams.

```
PCAP-Datei → pcap_parser.py → V2xMessage dataclass (SessionData)
                                    ↓
                            player_controller.py (Timeline/QTimer)
                           ↙              ↘
                 map_widget.py       main_window.py (Message List)
                           ↘              ↙
                          kml_exporter.py
```

Data flows linearly from parser through a shared `SessionData` container. Qt-Signals connect the playback controller to UI widgets (map highlight, list scroll).

## Data Model

### V2xMessage

```python
@dataclass
class V2xMessage:
    timestamp: datetime        # Reception timestamp
    station_id: str            # Entity ID (e.g., "STATION_001")
    msg_type: MessageType      # Enum: CAM, DENM, SREM, SSEM, MAPEM, SPATEM, NMEA
    latitude: float            # Degrees
    longitude: float           # Degrees
    altitude: float | None     # Meters (optional)
    speed: float | None        # m/s (optional)
    heading: float | None      # Degrees 0-359 (optional)
    raw_payload: bytes | None  # Original payload for debugging
```

### MessageType

```python
class MessageType(Enum):
    CAM = "CAM"
    DENM = "DENM"
    SREM = "SREM"
    SSEM = "SSEM"
    MAPEM = "MAPEM"
    SPATEM = "SPATEM"
    NMEA = "NMEA"
```

### SessionData

```python
@dataclass
class SessionData:
    messages: list[V2xMessage]                       # Sorted by timestamp
    station_ids: set[str]                             # All detected station IDs
    time_range: tuple[datetime, datetime]             # First/last timestamp
    msg_type_counts: dict[MessageType, int]           # Statistics
```

## PCAP Parser

### Dual-Backend Strategy

1. **Pyshark (Preferred):** Uses TShark dissectors for ITS-G5/DSRC. Automatically detects BTP/GeoNetworking layers and decodes V2X messages. Used when TShark is installed on the system.

2. **Scapy (Fallback):** When TShark is not available. Manual ASN.1 decoding with `asn1tools` and locally embedded ETSI schema files.

Backend selection is automatic: check for TShark availability at startup, fall back to Scapy gracefully with a user notification.

### ASN.1 Schema Management (Hybrid)

- `assets/asn1/` contains pre-bundled ETSI ITS ASN.1 schema files for CAM, DENM, MAPEM, SPATEM, SREM, SSEM
- Optional update from a Git repository (e.g., ETSI ITS) via button or CLI flag
- Schema files are compiled by `asn1tools` at startup and cached for the session

### NMEA Parsing

- Dedicated parser for NMEA sentences (GPGGA, GPRMC) found in PCAP streams
- Extracts lat/lon/speed/heading from `$GPGGA` and `$GPRMC` strings
- NMEA messages are mapped to `V2xMessage` with `msg_type=NMEA`

## Map Widget

**Component:** `map_widget.py` — `QWebEngineView` with Leaflet.js

**Implementation:**
- HTML with Leaflet.js loaded from CDN (online-only, no offline tile cache)
- Python → JavaScript: `page.runJavaScript()`
- JavaScript → Python: `QWebChannel`

**Marker Logic:**
- Each station ID gets a unique color from a palette (auto-assigned)
- Markers move synchronously with the playback timer
- Polyline shows the trajectory of each entity
- Click popup shows message details (timestamp, speed, heading)

**Tile Source:** OpenStreetMap (online, via CDN URL in Leaflet tile layer)

## Playback Controller

**Component:** `player_controller.py`

**Timer System:** `QTimer` with interval-based time simulation.

**Mechanics:**
- Calculates simulated PCAP time from `speed_multiplier` and elapsed real time
- Emits `tick(simulated_time)` signal
- Map and list react: highlight current message, update marker position

**Controls:**
- Play / Pause / Stop buttons
- Scrubbing via QSlider (0% = first message, 100% = last message)
- Speed: 0.1x, 0.5x, 1x, 2x, 5x, 10x (QComboBox)

**Display:**
- Current playback time (formatted as MM:SS.s)
- Total duration (formatted as MM:SS.s)

## GUI Layout

```
┌────────────────────────────────────────────────────────────────┐
│  Toolbar: [PCAP laden] [KML export] | Filter-Buttons          │
├───────────────────────────────────┬────────────────────────────┤
│                                   │ Nachrichtenliste           │
│   Interaktive Leaflet-Karte       │ (QTableWidget)            │
│   (QWebEngineView, ~70%)         │ Spalten:                  │
│                                   │  Timestamp                │
│   - Farbige Marker pro Station   │  Station ID               │
│   - Trajektorien-Pfade           │  Msg Type                 │
│   - Popup bei Klick              │  Lat/Lon                  │
│                                   │  Speed / Heading          │
├───────────────────────────────────┤                           │
│ Playback: ◄◄ ▶ ■ ►► │ Slider │ │ Aktuelle Zeile farbig     │
│ 1x ▼ │ 00:12.3 / 05:00.0        │ markiert, Auto-Scroll      │
└───────────────────────────────────┴────────────────────────────┘
```

**Splitter:** `QSplitter` with 70/30 initial ratio, user-resizable.

**Filter Panel:**
- In the toolbar or as a collapsible section above the message list
- Checkboxes per MessageType (CAM, DENM, SREM, SSEM, MAPEM, SPATEM)
- Multi-select dropdown for Station IDs (highlight or hide individual entities)
- Filters apply in real-time to both map and list

**Message List:**
- `QTableWidget` with columns: Timestamp, Station ID, Msg Type, Lat/Lon, Speed/Heading
- Currently playing message row is color-highlighted
- Auto-scroll follows playback position
- Clicking a row jumps the map to that position and time

## KML Export

**Component:** `kml_exporter.py`

**Library:** `simplekml`

**Output:**
- One KML file per Station ID
- `<Placemark>` per message with timestamp, coordinates, message type
- Optional `<LineString>` for the trajectory (connects all points in time order)
- Compatible with Google Earth and QGIS

**Export Flow:**
1. User clicks "KML exportieren"
2. Directory dialog opens for save location
3. KML files generated for all (or filtered) entities
4. Success/failure notification

## Project Structure

```
pcap2kml_player/
├── main.py              # Entry point
├── pcap_parser.py       # PCAP parsing & V2X decoding (pyshark + scapy fallback)
├── kml_exporter.py      # KML generation via simplekml
├── map_widget.py        # QWebEngineView + Leaflet.js integration
├── player_controller.py # Playback logic & QTimer
├── data_model.py        # V2xMessage, MessageType, SessionData
├── nmea_parser.py       # NMEA sentence parsing (GPGGA, GPRMC)
├── asn1_schemas.py     # ASN.1 schema loading & caching
├── ui/
│   └── main_window.py   # PyQt6 main window & layout
├── assets/
│   ├── asn1/            # ETSI ITS ASN.1 schema files
│   └── leaflet/         # Leaflet.js HTML template
├── requirements.txt
└── README.md
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid/corrupt PCAP file | Dialog with clear error message, no crash |
| TShark not installed | Automatic fallback to Scapy backend, info dialog |
| ASN.1 decoding failure | Warning in statusbar, message skipped, parsing continues |
| No position data found | Statusbar hint, empty map with informational overlay |
| No PCAP loaded | Controls disabled, map shows default location |
| KML export failure | Error dialog with path and reason |

## Technical Requirements

- **OS:** Windows 10/11 (64-bit)
- **Python:** 3.11+
- **Dependencies:** PyQt6, PyQt6-WebEngine, scapy, pyshark (optional), asn1tools, simplekml
- **Leaflet.js:** Via CDN (online-only)
- **Distribution:** Python project with `requirements.txt`, optional PyInstaller bundle (.exe)

## Out of Scope

- Offline tile caching
- Real-time V2X stream reception (only PCAP file playback)
- Editing or modifying PCAP files
- Network simulation or message injection