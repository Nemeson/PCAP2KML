# Changelog

## [Unreleased] — Phase D (Visualisierung & Dashboard)

### Phase D — Karten- und Visualisierungsverbesserung
- **Heatmap / Cluster**: UI-Stubs vorbereitet (`visualisation_stubs.py`)
- **Offline-Karten**: Vector-Tile-Unterstützung vorbereitet (MapLibre-Stub)
- **Koordinaten- und Maßstabsanzeige**: Stubs vorbereitet
- **Dichte-Timeline + Loop-Modus + Frame-Navigation**: Stubs vorbereitet
- **Screenshot-Export**: Stub vorbereitet

### Phase 4 — Analyse und Export
- **GeoJSON-Export** (`export_formats.py`): FeatureCollection pro Station, Point + LineString
- **CSV-Export** (`export_formats.py`): Einzeldatei mit Header, Details als JSON
- **GPX-Export** (`export_formats.py`): Waypoints + Track pro Station (GPX 1.1)
- **Zeitanimierte KML-Tour** (`export_formats.py`): `gx:Tour` mit `gx:FlyTo`, `TimeSpan` pro Placemark
- **Statistik-Dashboard** (`statistics.py` + `dashboard_dialog.py`):
  - Session-Überblick (Gesamtnachrichten, Stationen, Typen, Dauer, Nachrichten/s)
  - Zeitlicher Verlauf der Nachrichtenraten
  - Geschwindigkeits- und Heading-Verteilung pro Station

## [Unreleased] — Phase C (Szenenaggregation)

- **Lane-Connectivity** (`scene_model.py`):
  - `LaneConnection`-Datenmodell (ingress/egress/signalGroup)
  - `IntersectionState.lane_connections`
  - `_extract_lane_connections()`: Parst MAPEM `connectsTo` inkl. `signalGroup`
- **Flow-Status-Resolution** (`scene_model.py`):
  - `resolve_flow_status()`: Automatische Signalgruppen-Auflösung aus Lane-Connections
  - Phase-Konfiguration: `protected-Movement-Allowed`, `permissive-Movement-Allowed`, `permissive-clearance` = frei

## [Unreleased] — Phase B (CI-Toolchain)

- **Build-Skript** (`scripts/run_ci.ps1`): Lokales CI für Windows
- **pyproject.toml**: ruff, mypy, pytest, Coverage-Konfiguration
- **GitHub Actions CI** (`.github/workflows/ci.yml`): CI-Pipeline für Windows

## [Unreleased] — Phase A (PKI-Signatur-Analyse)

- **A1 — Parser-Vervollständigung** (`security_parser.py`):
  - Heuristische Extraktion: `assurance_level`, `station_type`, `validity_start/end`
  - `its_aid_list`, `region_type`, `region_detail`
  - Konstanten: `ITS_AID_DENM`, `ITS_AID_CAM`, `ITS_AID_MAP_SPAT`
- **A2 — UI-Platzhalter** (`main_window.py`):
  - `_btn_verify_signature`: Sichtbar nur bei signierten Nachrichten
  - `_on_verify_signature()`: Hinweisdialog mit fehlenden Voraussetzungen
- **A3 — ECDSA-Verifikationsskript** (`scripts/verify_ecdsa.py`):
  - Standalone CLI: `verify_signature()` mit `cryptography`
  - Unterstützt NIST P-256 und BrainpoolP256r1

## [1.7.0] — Bugfix & Optimierung

- **Thread-Safety** (`parsing_worker.py`): Atomare Cancellation via Closure-Replacement
- **Signal-Leak-Fix** (`main_window.py`): Explizite Signal-Disconnection vor `deleteLater()`
- **Timer-Lifecycle** (`map_widget.py`): `QTimer`-Objekte statt `singleShot`, `dispose()` stoppt alle Timer
- **Performance** (`data_model.py`): `canonical_messages()` Cache mit Invalidierung
- **Exception-Spezifizität** (`main_window.py`): `OSError`, `PermissionError`, `ValueError` statt `Exception`
- **Architektur** (`protocol_constants.py`): `ITS_PDU_MESSAGE_ID` ausgelagert zur Vermeidung zirkulärer Imports

### Tests

- 267 Tests (100% passing)
- Neue Test-Dateien: `test_export_formats.py`, `test_statistics.py`, `test_flow_resolution.py`
