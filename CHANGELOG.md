# Changelog

Dieses Changelog dokumentiert den aktuell rekonstruierten Entwicklungsstand der App auf Basis des vorhandenen Repos.

Das Format orientiert sich an Keep a Changelog.  
Eine lueckenlose Historie vor dem dokumentierten Stand wurde nicht rueckwirkend aus Commits rekonstruiert.

## [2026.0607] - 2026-06-07

### Added
- **Zweistufige Navigationsleiste**: Die UI nutzt nun ein zweistufiges Workspace-Navigationslayout mit den Hauptgruppen `MAP-Analyse`, `Priorisierungs-Analyse`, `Compliance`, `Signalzustandsanalyse` und `Rohdaten` sowie den jeweils zugeordneten Unter-Tabs (z. B. `Karte`, `Track-Vergleich`, `ETA Analyse`, `Priorisierung`, `PKI Analyse`, `Analyse Ergebnisse`, `SPAT-Vorhersagequalität`, `Rohdaten`).
- **Signalzustandsanalyse (SPAT-Vorhersagequalität)**:
  - Ein neues Modul zur Bewertung historischer Signalphasenübergangsprognosen basierend auf MAP/SPAT-Sequenzen aus PCAP-Traces.
  - **Dashboard**: Leaflet-Karte mit farblich codierten Kreuzungs-MAE-Markern, Übersichttabelle mit MAE, RMSE, Bias, On-Time-Quote und flexiblem Zeitraum-, Stunden-, Wochentags- und Signalgruppen-Filter.
  - **Signalzeitenplan-Gantt (spat_gantt)**: Horizontale Phasenbalken pro Signalgruppe über der Zeit seit Aufnahmestart, inklusive Korrelation und Overlay von SRM-Priorisierungsanforderungen (als Sternsymbol).
  - **Prognosehorizont**: Diagramm zur Visualisierung der Vorhersagehorizonte ($T_{\text{likely}} - T_{\text{send}}$) über der Aufnahmezeit in separaten Subplots pro Signalgruppe.
  - **Detailansicht**: Detaillierte Kennzahlentabelle und Matplotlib-basierte Subplots für Fehler-Timeline (mit einstellbarer On-Time-Fehlerschwelle), Fehler-Histogramm und Predicted-vs-Actual Scatterplot der Signalübergangszeiten.
  - **Qualitätsansicht**: Vollständigkeits-Analyse (Timing-Daten: gültig, fehlend, ungültig) als Kreisdiagramm und MAE-Tageszeitverlauf (Gegenüberstellung von Wochentagen und Wochenende).
- **Farbcodierung & Barrierefreiheit**: Dynamische Propagation des gewählten Standard- oder Rot/Grün-Farbmodus in die neuen Qualitäts-, Detail-, Gantt- und Prognosehorizont-Diagramme.
- **Fehlerbehebungen und UI-Tests**: Robustes Exception-Handling und testrelevante Widget-Prüfungen in `_workspace_builder.py` zur fehlerfreien Ausführung der GUI-Testsuite auch bei simulierten Replay-Durchläufen.

## [1.8.0rc2] - 2026-05-22

Release candidate 2 for 1.8. Focuses on performance-optimized test suites, smoothed Leaflet animation rendering, and start usability helpers.

### Added
- **Wireshark Startup Hint (German)**: QMessageBox hint on application startup advising that PCAP parsing is faster with Wireshark/tshark installed/running, featuring a QSettings-persisted checkbox ("Do not show this hint again").
- **Interpolated Marker Movement & Easing**: Added non-linear interpolation for Leaflet marker updates. Instead of linear paths, markers now animate using smooth easing scaled to actual GNSS update intervals.
- **Fast Test Suite**: Excluded slow real PCAP integrations by default under fast runs, resolving suite freezes.

### Fixed
- **Leaflet Memory Leak**: Resolved a Tween request animation ID leak in `removeMarkers` in `leaflet_template.py`.
- **Test Optimization**: Replaced `txa 3.pcap` (12.1MB) with the lightweight `SREM with OCIT.pcap` (8.5KB) in message source contract and parsing worker tests.

## [1.8.0rc1] - 2026-05-08

Release candidate for 1.8. The release focuses on MAP-XML usability, Leaflet stability and release cleanup.

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
- **Message-Inspector Phase 2** mit Decode-Tree, Hex-/Raw-View und konfigurierbarem Trigger
  - `QTreeView` mit rekursivem Decode-Tree (Feldname, Wert, Typ, Raw-Hex)
  - Monospace-Hex-Dump mit Copy-Buttons für Hex/Base64
  - Trigger-Modi: Klick, Pause-Auto, Manuell (Ctrl+I), Aus — persistiert via QSettings
- **Workspace-UX-Hardening (T8.3)**
  - Tastatur-Shortcuts Ctrl+1..4 für Workspace-Wechsel
  - Verbesserte aktive/inaktive Tab-Zustände mit visuellem Feedback
  - Leere Fehlerliste mit Icon + Filter-Reset-Button
  - Detail-Inspektor in allen Workspaces verfügbar
- **Inkrementelles Marker-Update (T1.3e)**
  - Delta-Update statt Full-Repaint via `updateMarkers`/`removeMarkers` JS-Bridge
  - Reduziert JS-Bridge-Latenz bei großen Payloads
- **Filterleiste Phase 2 (T3)**
  - Multi-Select Station-ID × Nachrichtentyp × Zeitfenster
  - Zeitfilter via `QDateTimeEdit` (HH:mm:ss.zzz)
  - Filter-Persistenz via QSettings (`filter/active_types`, `filter/active_stations`, `filter/time_start`, `filter/time_end`, `filter/canonical`)
  - `_sync_filter_ui_from_state()` verhindert Signal-Storms beim Restore
- **Statistik/Dashboard Phase 1 (T5)**
  - Matplotlib-Diagramme: Nachrichtentyp-Verteilung (Bar) und Nachrichtenrate-Timeline (Line)
  - Histogramme: Speed- und Heading-Verteilung pro Session
  - Read-only Standards-Profil-Tab (C-Roads, C2C-CC, ETSI, BSI) mit Status-Anzeige
- **MessageSource-Abstraktion (T6)**
  - `PlayerController` und Import-Pipeline nutzen durchgängig `MessageSource`
  - `SessionMessageSource` und `CombinedMessageSource` für Player und kombinierte Sitzungen
  - Design-Doku für zukünftige Live-Capture-Quellen (`CohdaMk6Source`, `OpenC2XSource`)
- **IVIM-Support (T4)**
  - ITS-PDU-Header messageId 13 und BTP-Port 2010 erkannt
  - Extra-Field-Extraktor: `iviIdentificationNumber`, `serviceProviderId`, `timeStamp`, `second`, `roadSignCount`, `textMessageCount`
  - Positionsextraktion via generischem Fallback (GeoNetworking LPV oder `referencePosition`)
  - KML-Export (`ff800080`), Map-Farben (`#9333ea` / `#6a3d9a`), Security-ITS-AID `0x7A`
  - Infrastruktur-Marker ohne Trajektorie (`NON_STATION_MARKER_TYPES`)
- **MAP XML SVG-Referenzgenerator** (`scripts/generate_map_svg.py`)
  - Erzeugt SVG-Visualisierung aus MAP-XML für Fehlerdiagnose
  - Farbcodiert: Inbound=grün, Outbound=blau, Connections=orange/grau
- **Leaflet MAP-XML technical plan rendering**
  - Renders MAP-only sessions as lane surfaces, stoplines and approach/connection geometry
  - Uses the same lane-local NodeXY normalization basis as the SVG reference generator
  - Auto-fits the map view to MAP bounds on XML import and WebEngine reload

### Changed

- `_display_anchor_points` Cache verhindert O(N)-Rescan pro Render-Tick
- `_refresh_problem_replay_indices` und `_update_scene_for_message` laufen deferred
- `station_ids` ist jetzt `@property` (dynamisch aus messages)
- `Letzte Sitzung`-Button deaktiviert wenn bereits PCAP geladen
- `Abbrechen`-Button entfernt (ParsingWorker hatte keinen effektiven Cancel)
- PyInstaller-Skript bundlet Benutzerhandbuch (`--add-data docs\benutzerhandbuch.html;docs`)
- Release version set to `1.8.0rc1` in package metadata and runtime fallback
- Temporary project-local debug log files and trace hooks removed for release

### Fixed

- MAP-XML lane deltas are reset per lane, so app rendering matches the SVG reference geometry
- MAP-only imports no longer keep stale persisted filters that hide the single MAPEM message
- Leaflet auto-fit retries after payload render and falls back to the MAP center if `fitBounds` is delayed
- Dashboard import no longer hard-crashes the app when optional chart dependencies are missing
- Time filters are restored without mixing offset-aware and offset-naive datetimes
- MAP XML Connections laufen jetzt von Stopline-Mitte zu Stopline-Mitte statt von Lane-Knoten
- SVG-Referenzgenerator und App-Renderer nutzen beide dieselbe Stopline-Logik
- PlayButton springt nach Erreichen des Endes nicht zurueck (Bedingung `>= len()-1`)
- Pfeilnavigation in Rohdaten aktualisiert nicht die Datentabelle (`currentItemChanged`)
- Zweites PCAP Neuladen: Karte zeigt keine Daten im Stillstand (Session-Clear vor Set)
- Message-Typ-Filter zeigt keine Daten wenn nicht MAPEM+SPATEM ausgewaehlt (Filter-Reset bei leerer Auswahl)

### Testing

- RC-Check 2026-05-08: `compileall` fuer `pcap2kml_player`, `scripts` und `tests` erfolgreich
- RC-Check 2026-05-08: Landau MAP-XML Parser liefert 1 MAPEM, 32 Lanes, 123 NodeXY-Punkte und 30 Connections
- Voller `pytest`-Lauf im aktuellen Quell-Environment blockiert, weil `pytest`/`PyQt6` fehlen und PyPI wegen DNS-Fehler nicht erreichbar war
- Letzter dokumentierter kompletter Teststand vor RC-Cleanup: **434 passed, 12 skipped**
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
