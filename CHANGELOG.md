# Changelog

Dieses Changelog dokumentiert den aktuell rekonstruierten Entwicklungsstand der App auf Basis des vorhandenen Repos.

Das Format orientiert sich an Keep a Changelog.  
Eine lueckenlose Historie vor dem dokumentierten Stand wurde nicht rueckwirkend aus Commits rekonstruiert.

## [1.8.0] - 2026-05-05

### Added

- **C-Roads MAPEM/SPATEM Validator** nach Handbook 3.2.0 mit Regel-IDs
  - MAP: intersectionId, revision, refPoint, laneSet, laneID, connectsTo, signalGroup, laneWidth, directionalUse, maneuvers, stopLine
  - SPAT: signalGroup States, minEndTime/maxEndTime, likelyTime, nextTime, confidence
  - Linking: Crosswalk-Verbindungen, BikeLane-Verbindungen, Roundabout-Erkennung
  - Maschinenlesbarer JSON-Export mit vollstaendigem Rule-ID-Mapping
- **XML MAP Parser** fuer Kreuzungsgeometrie-Dateien
  - Parst XML-MAP-Dateien mit normalisierten Koordinaten
  - Erzeugt synthetische MAPEM-Messages pro Intersection
  - Multi-Intersection-Dateien als getrennte Stationen
- **Rot/Gruen-Farbmodus** (Deuteranopie/Protanopie)
  - Umschaltbar fuer Karte, ETA-Graph und alle Exportformate
  - Palette nach ColorBrewer mit eindeutigen Hue-Differenzen
- **Performance-Optimierungen**
  - Bisect-Cut + Reorder + Index-Cache (rxa p95 -82%, txa p95 -69%)
  - `_display_anchor_points` Cache nach (id(messages), max_index)
  - Deferred Filter-Side-Effects via QTimer.singleShot(0)
  - JS-Bridge-Latenz-Messung (_last_js_latency_ms)
- **MAP Validation Dialog** als UI-Aktion
  - Severity-codierte Baumansicht (Error/Warning/Info)
  - HTML-Report mit Rule-ID-Spalte
  - JSON-Report mit Handbook-Version und vollstaendigem Issue-Array
- **Automatisierte UI-Doku-Erzeugung** (scripts/generate_ui_docs.py)
  - Startet App mit Fixture-PCAP, durchklickt Workspaces, erzeugt Screenshots
  - HTML-Referenzpruefung gegen existierende Screenshots
- **Hilfe-Button** oeffnet bundled Benutzerhandbuch (docs/benutzerhandbuch.html)
- **Tastatur-Navigation** in Nachrichtentabelle (Pfeiltasten aktualisieren Detail-Inspektor)
- **Station-ID-Filter-Entprellung** mit schonender Kartenaktualisierung

### Changed

- `_display_anchor_points` Cache verhindert O(N)-Rescan pro Render-Tick
- `_refresh_problem_replay_indices` und `_update_scene_for_message` laufen deferred
- `station_ids` ist jetzt `@property` (dynamisch aus messages)
- `Letzte Sitzung`-Button deaktiviert wenn bereits PCAP geladen
- `Abbrechen`-Button entfernt (ParsingWorker hatte keinen effektiven Cancel)
- PyInstaller-Skript bundlet Benutzerhandbuch (`--add-data docs\benutzerhandbuch.html;docs`)

### Fixed

- KML Export: 0 Dateien wegen leerem `station_ids`-Set (jetzt Property)
- PlayButton springt nach Erreichen des Endes nicht zurueck (Bedingung `>= len()-1`)
- Pfeilnavigation in Rohdaten aktualisiert nicht die Datentabelle (`currentItemChanged`)
- Zweites PCAP Neuladen: Karte zeigt keine Daten im Stillstand (Session-Clear vor Set)
- Message-Typ-Filter zeigt keine Daten wenn nicht MAPEM+SPATEM ausgewaehlt (Filter-Reset bei leerer Auswahl)

### Testing

- Teststand nach v1.8: **377 passed, 12 skipped**
- Neue Tests: Validator, XML-Parser, KML-Export-Fix, Real-XML-Files (Landau, Woerth)
- Performance-Profiling dokumentiert unter docs/profiling/

## [1.4.0] - 2026-04-19

### Added

- MAP-Normalisierung fuer `laneRole`, `connections`, `targetLaneId` und Stopline-Fallback
- Kartenlayer fuer `Inbound-Lanes`, `Outbound-Lanes`, `Connections`, `Stoplines` und `Requests`
- SPAT-Faerbung auf Connection-Ebene statt nur auf kompletter Lane-Ebene
- SRM/SSEM-Overlays auf Inbound-Lane, Outbound-Lane und Connection
- Dominante vs. sekundaere Prioarisierung mit visueller Abstufung
- Seitliche Entzerrung mehrerer Priorisierungen auf derselben Connection
- Operative Request-Zustaende im Szenenmodell:
  `pending`, `acknowledged`, `granted`, `rejected`, `timeout`
- Sichtbarkeit kuerzlich beantworteter Requests im Szenenpanel
- Request-Legende im Szenenpanel
- Tab-Struktur in der rechten Leiste mit `Details` und `Szene`
- Detailanzeige fuer `Identitaets-Hinweis`
- Tests fuer ASN.1-Schema-Updatepfad
- Playback-spezifische Kartenregressionen fuer Slice-Rendering, kurzen Trail und Follow-Verhalten

### Changed

- Karte rendert beim Playback jetzt den Zustand bis zur aktuellen Wiedergabeposition statt den Endzustand der ganzen Datei
- Bewegte Objekte zeigen im Playback nur noch einen kurzen Trail statt der gesamten bisherigen Historie
- MAPEM und SPATEM werden nicht mehr als normale Marker gerendert, sondern nur noch als Infrastruktur-Layer
- Karte bleibt beim Playback stabil und folgt einem Objekt nur nach explizitem Klick
- ASN.1-Schema-Update invalidiert jetzt sauber In-Memory- und `.pkl`-Caches

### Fixed

- Kartenzustand aktualisierte sich beim Playback nicht zeitkonsistent
- Ortsfeste RSU fuer MAP/SPAT wurde unnoetig als Marker dargestellt
- ASN.1-Schema-Update scheiterte bei eingebettetem, nicht-leerem `assets/asn1`-Ordner ohne `.git`
- Schema-Refresh arbeitete vorher mit potenziell veralteten kompilierten Caches weiter

### Testing

- Teststand nach aktueller Aenderungsrunde: `142 passed`

## [1.3.0] - 2026-04-18

### Added

- Persistentes App-Memory fuer letzte Sitzung, letzte Verzeichnisse und Sitzungszusammenfassungen
- Drag & Drop fuer `.pcap`, `.pcapng` und `.cap`
- Hintergrund-Parsing mit Fortschrittsanzeige und Abbrechen-Funktion
- globale Exception-Behandlung beim App-Start
- PKI-/Security-Detailanzeige fuer ETSI-TS-103-097-bezogene Felder
- Szenen-Aggregation mit `IntersectionState`, `SignalGroupState`, `SpatForecast`, `ActiveRequest` und `SceneSnapshot`
- Szenenpanel in der UI mit Kreuzungsstatus, offenen Anforderungen, Inline-Warnungen und 30s-Phasen-Timelines
- Clock-Skew-Erkennung zwischen SPAT-Zeit und PCAP-Zeitstempel
- ETA-Verifikation ueber CAM-Trajektorien und MAP-Referenzpunkte
- ASN.1-Schema-Update aus Git
- Integritaetspruefung fuer Schemadateien
- Schema-Provenance im KML-Export
- Festplatten-Cache fuer kompilierte ASN.1-Schemata
- Reale Test-PCAP-Dateien und umfassendere `pytest`-Suite

### Changed

- Parser-Robustheit fuer `pyshark` und `scapy` deutlich erweitert
- ITS-Nachrichtenerkennung verbessert durch BTP-Port-Logik und `messageId`-Fallback aus dem ITS-PDU-Header
- GeoNetworking-/BTP-Erkennung fuer direkten ITS-G5-Traffic erweitert
- UI visuell in Richtung SWARCO-ITS-inspirierter Operator-Oberflaeche ueberarbeitet
- KML-Export auf Windows-sichere Dateinamen und Kollisionsvermeidung gehaertet
- MAPEM-, SPATEM-, SREM- und SSEM-Zusatzfelder in `decoded_data` deutlich vertieft

### Fixed

- KML-Export scheiterte bei Station-IDs mit unter Windows ungueltigen Zeichen wie `:`
- KML-Dateinamenskollisionen nach Sanitizing werden nun aufgeloest
- Parser-Fallback bei fehlendem BTP-Port ueber ITS-PDU-Header
- stabilerer Lade-Workflow bei grossen oder fehlerhaften Captures

### Testing

- Teststand zum dokumentierten Zeitpunkt: `102 passed`

## [Unreleased]

### Planned

- weitere GUI-Integrationstests fuer `main_window.py`
- Offline-Kartenunterstuetzung
- weitere Exportformate wie CSV, GeoJSON und GPX
- tiefere PKI-Ketten- und Signaturvalidierung
