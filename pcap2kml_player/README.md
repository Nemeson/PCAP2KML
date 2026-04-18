# PCAP2KML Player

Desktop-Anwendung zur Visualisierung von V2X-Nachrichten (ETSI ITS G5 / DSRC) aus PCAP-Dateien auf einer interaktiven Karte mit synchronisierter Wiedergabe und KML-Export.

## Funktionen

- **PCAP-Verarbeitung:** Lädt eine oder mehrere PCAP-Dateien und dekodiert V2X-Nachrichten (CAM, DENM, SREM, SSEM, MAPEM, SPATEM) sowie NMEA-GPS-Sätze
- **Interaktive Karte:** Leaflet.js-Karte (OpenStreetMap) mit farbigen Markern pro Station und Trajektorien-Pfaden
- **Synchronisierte Wiedergabe:** Play/Pause/Stop mit Geschwindigkeitsregler (0.1x–10x) und Scrubbing
- **Nachrichtenliste:** Tabellarische Ansicht mit Timestamp, Station ID, Nachrichtentyp, Koordinaten und Geschwindigkeit/Heading
- **Filter:** Echtzeit-Filter nach Nachrichtentyp und Station ID — wirkt auf Karte und Liste
- **KML-Export:** Generiert KML-Dateien pro Entität, kompatibel mit Google Earth und QGIS

## Voraussetzungen

- Windows 10/11 (64-bit)
- Python 3.11+
- **Optional:** Wireshark/TShark (für verbesserte V2X-Dekodierung via pyshark)

## Installation

```bash
cd pcap2kml_player
pip install -r requirements.txt
```

## Start

```bash
python main.py
```

## Projektstruktur

```
pcap2kml_player/
├── main.py              # Einstiegspunkt
├── data_model.py        # V2xMessage, MessageType, SessionData
├── pcap_parser.py       # PCAP-Parsing (pyshark + scapy Fallback)
├── nmea_parser.py       # NMEA-Satz-Parser (GPGGA, GPRMC)
├── asn1_schemas.py      # ASN.1 Schema-Verwaltung (Hybrid)
├── kml_exporter.py      # KML-Erzeugung via simplekml
├── map_widget.py        # QWebEngineView + Leaflet.js
├── player_controller.py # Playback-Logik & QTimer
├── ui/
│   ├── __init__.py
│   └── main_window.py   # PyQt6 Hauptfenster
├── assets/
│   ├── asn1/            # ETSI ITS ASN.1 Schemadateien
│   └── leaflet/         # (reserviert für lokale Leaflet-Einbettung)
├── requirements.txt
└── README.md
```

## PyInstaller-Build (.exe)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PCAP2KML Player" main.py
```

## Abhängigkeiten

| Paket | Zweck |
|-------|-------|
| PyQt6 | GUI-Framework |
| PyQt6-WebEngine | Eingebettete Karte (QWebEngineView) |
| scapy | PCAP-Parsing (Fallback-Backend) |
| pyshark | PCAP-Parsing (Preferred, benötigt TShark) |
| asn1tools | ASN.1-Dekodierung der V2X-Nachrichten |
| simplekml | KML-Datei-Generierung |

---

## Roadmap — Geplante Verbesserungen

### v1.1 — Stabilität & Usability

- [ ] **ASN.1-Schemadateien beilegen** — ETSI ITS ASN.1-Dateien für CAM/DENM/MAPEM/SPATEM/SREM/SSEM direkt im `assets/asn1/`-Verzeichnis mitliefern
- [ ] **Fehlertoleranz beim Parsing** — Fehlerhafte Nachrichten überspringen statt abzubrechen, mit Zähler in der Statusbar
- [ ] **Drag & Drop** — PCAP-Dateien per Drag & Drop auf das Fenster laden
- [ ] **Letzte Sitzung merken** — Zuletzt geöffnete Dateien und Fenstergröße in QSettings speichern
- [ ] **TShark-Pfad konfigurierbar** — Benutzerdefinierter TShark-Pfad in den Einstellungen

### v1.2 — Erweiterte Visualisierung

- [ ] **Heatmap-Overlay** — Dichte-basierte Heatmap der Nachrichtenpositionen auf der Karte
- [ ] **Marker-Clustering** — Leaflet MarkerCluster für große Datenmengen (>10.000 Punkte)
- [ ] **Farbliche Differenzierung nach Nachrichtentyp** — Verschiedene Marker-Formen/-Farben pro MsgType (CAM = Kreis, DENM = Dreieck, etc.)
- [ ] **Dark Mode** — Dunkles Farbschema für die GUI und dunkler Karten-Tile (z.B. CartoDB Dark Matter)
- [ ] **Vollbild-Kartenmodus** — Karte auf Vollbild umschaltbar, Nachrichtenliste als Overlay

### v1.3 — Analyse-Funktionen

- [ ] **Statistik-Dashboard** — Übersicht mit Nachrichtenzahlen pro Typ, Zeitverteilung, Station-Timeline
- [ ] **Geschwindigkeits-/Heading-Diagramm** — Matplotlib oder pyqtgraph eingebettet für zeitliche Verläufe
- [ ] **Zeitbereich-Auswahl** — Bereich im Slider markieren, um nur einen Zeitabschnitt zu analysieren
- [ ] **Abstandsmessung** — Distanz zwischen zwei Stationen über die Zeit berechnen und darstellen
- [ ] **Nachrichtendetail-Panel** — Klick auf Nachricht zeigt dekodierten ASN.1-Baum im Detail-Panel

### v1.4 — Erweiterte PCAP-Unterstützung

- [ ] **IEEE 802.11p / ITS-G5 Direct Decoding** — Native Dekodierung von GeoNetworking/BTP-Schichten ohne TShark-Abhängigkeit
- [ ] **IPv6/UDP über GeoNet** — Erkennung von GN6-gekapselten V2X-Nachrichten
- [ ] **Live-PCAP-Streaming** — Lesen aus Named Pipes oder Netzwerk-Streams für Echtzeit-Visualisierung
- [ ] **PCAPNG-Metadaten** — Interface-Beschreibungen und Kommentar-Blöcke aus PCAPNG auslesen

### v1.5 — Export & Integration

- [ ] **GPX-Export** — Zusätzliches Export-Format für GPS-Geräte und Fitness-Apps
- [ ] **CSV-Export** — Tabellarischer Export der gefilterten Nachrichten als CSV
- [ ] **GeoJSON-Export** — Export als GeoJSON für Web-Karten (Mapbox, Leaflet-Web)
- [ ] **Video-Export** — Bildschirmaufnahme der Wiedergabe als MP4/WebM
- [ ] **Report-Generator** — PDF-Report mit Kartenansicht, Statistiken und Zeitstrahl

### v1.6 — Performance & Architektur

- [ ] **Streaming-Parser** — PCAPs >1 GB ohne vollständiges Laden ins Memory verarbeiten
- [ ] **SQLite-Cache** — Parsed messages in SQLite zwischenspeichern für schnelles Wiederladen
- [ ] **Multi-Threading** — PCAP-Parsing im Hintergrund-Thread mit Fortschrittsanzeige
- [ ] **Pluggable Backend** — Plugin-System für zusätzliche PCAP-Backends (z.B. dpkt, pcapfile)
- [ ] **Kommandozeilen-Modus** — Headless-Verarbeitung: `pcap2kml_player --input file.pcap --output-dir /tmp/kml`

### Langfristig

- [ ] **Plugin-System** — Eigene Nachrichtentypen über Python-Plugins registrierbar
- [ ] **Kooperative Analyse** — Mehrere PCAP2KML-Instanzen synchronisieren Sessions über Netzwerk
- [ ] **Cloud-Tile-Cache** — Map-Tiles in S3/MinIO cachen für Offline-Nutzung
- [ ] **Cross-Platform** — Linux- und macOS-Unterstützung (Qt ist plattformunabhängig)