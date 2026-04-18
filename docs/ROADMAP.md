# PCAP2KML Player - Roadmap

**Stand:** 2026-04-18 | **Version:** 1.3

---

## Phase 1: Stabilisierung & Testing

### 1.1 Unit- und Integrationstests
- [x] Test-Suite mit `pytest` aufsetzen (`tests/`)
- [x] `test_data_model.py` - `V2xMessage`, `SessionData`, Filterlogik
- [x] `test_nmea_parser.py` - GPGGA/GPRMC-Parsing mit echten und fehlerhaften Saetzen
- [x] `test_pcap_parser.py` - Parsing mit echten Test-PCAPs
- [x] `test_kml_exporter.py` - KML-Generierung und Filteroptionen
- [x] Fix: Regressionstests fuer `map_widget.py` und `parsing_worker.py` ergaenzt (JS-Escaping, Fehlerpfad im Worker)
- [x] Reale Test-PCAP-Dateien in `testfiles/` einbinden
- [ ] Ziel: 80%+ Testabdeckung (aktuell 92 Tests gruen; Gesamt-Coverage 47% — Kernmodule: security_parser 80%, scene_model 96%, kml_exporter 95%, nmea_parser 89%, data_model 87%, app_memory 86%, player_controller 74%, asn1_schemas 61%, pcap_parser 56%. UI/main/map_widget/parsing_worker ohne Tests)

### 1.2 Fehlerbehandlung & Robustheit
- [x] Globales Exception-Handling fuer unbehandelte Fehler
- [x] Fortschrittsanzeige beim Laden von PCAP-Dateien
- [x] Abbrechen-Button beim Laden langer PCAPs (`ParsingWorker.cancel`)
- [x] ASN.1-Decoding-Fehler pro Nachricht strukturierter loggen (`get_decoding_error_stats`)
- [x] Pruefung auf fehlende Abhaengigkeiten beim Start
- [x] Fix: `ParsingWorker.finished` auf explizite Listen-Signaturen verengt (`pyqtSignal(object, list, list)`)

### 1.3 Parser-Robustheit
- [x] Timeout-Handling fuer `pyshark.FileCapture` (`PYSHARK_OPEN_TIMEOUT_S`)
- [x] Bessere pyshark-Filterstrategie (ITS-Layer + BTP-Ports statt `"gps"`)
- [x] Direkte GeoNetworking/BTP-Erkennung fuer EtherType `0x8947`
- [x] GeoNetworking-Header-Extraktion fuer Quell-/Zieladresse (`GN-Quelladresse` in details)
- [x] ITS-PDU-Header-Message-ID als Fallback zur Nachrichtentyp-Erkennung (`_infer_msg_type_from_pdu`)
- [x] Fix: ITS-PDU-`messageId=3` als SPATEM-Fallback aufgenommen und Security-Mapping konsistent getestet
- [x] Fix: NMEA-Checksum-Validierung fuer GPGGA/GPRMC mit Legacy-Fallback bei fehlender Checksum

### 1.4 UX und Session-Workflow
- [x] Persistentes App-Memory fuer letzte Sitzung, letzte Verzeichnisse und Session-Zusammenfassung
- [x] Drag & Drop fuer `.pcap`, `.pcapng` und `.cap`
- [x] "Letzte Sitzung"-Funktion
- [x] SWARCO-ITS-inspirierte UX-Auffrischung fuer die Hauptansicht

---

## Phase 2: ASN.1-Decoding-Verbesserung

### 2.1 Erweiterte Nachrichtenfelder
- [x] CAM: driveDirection, vehicleLength/Width, exteriorLights, yawRate
- [x] DENM: `causeCode`, `subCauseCode`, `validityDuration`, `informationQuality`
- [x] MAPEM: intersectionId, revision, laneCount, speedLimits
- [x] SPATEM: intersectionId, revision, signalGroupCount, moy, timeStamp
- [x] SREM/SSEM: requestId, sequenceNumber, importanceLevel, inLane/outLane, ETA
- [x] `decoded_data: dict` am `V2xMessage` fuer tiefergehende Rohdaten

### 2.2 Schema-Management
- [x] Automatisches Herunterladen neuer ASN.1-Schemata (`update_from_git`)
- [x] Schemaversionen im KML-Export vermerken (`_format_schema_provenance`)
- [x] Integritaetspruefung fuer Schemadateien (`verify_schema_integrity` via SHA-256)
- [x] Fallback auf integrierte Schemata bei Download-Fehler (git-pull returned False -> local schemas used)

### 2.3 Performance
- [x] Lazy-Compiling fuer Schemata (`get_compiled_schema` on demand)
- [x] Compiled-Schema-Cache auf Festplatte (`assets/cache/*.pkl`)
- [ ] Batch-Decoding fuer grosse PCAPs (offen, erst bei Throughput-Problem priorisieren)
- [ ] Known Issue: Pickle-Cache ohne separate Integritaetspruefung des `.pkl`-Inhalts — zurueckgestellt, da aktueller Cache-Key nur Schemaeingaben absichert

---

## Phase 2.5: PKI-Signatur-Analyse

### Bereits umgesetzt
- [x] `SecurityInfo`-Datenklasse
- [x] `security_parser.py` fuer ETSI TS 103 097
- [x] Extraktion aus Rohpayloads und dekodierten Nachrichten
- [x] Detailtabelle in der UI fuer PKI-Informationen
- [x] Fix: ITS-AID-Kommentare und `messageID`-Zuordnung in `security_parser.py` mit Parser-Mapping abgeglichen

### Naechste Schritte
- [ ] Zertifikatsketten vollstaendig parsen
- [ ] Zertifikatsgueltigkeit pruefen
- [ ] Signaturverifikation (ECDSA)
- [ ] Vertrauenskette validieren
- [ ] CRL-Pruefung
- [ ] Zertifikatskette als Baumstruktur anzeigen

---

## Phase 2.6: Szenen-Aggregation & Phasenprognose

Ziel: Den reinen Nachrichtenstrom zu einer interpretierbaren Szene aggregieren,
damit Visualisierungs-Assistenten und Nutzer Fragen wie "welche Phase ist aktiv?"
oder "ist mein Flow frei?" beantworten koennen.

### 2.6.1 Szenen-Datenmodell
- [x] `IntersectionState` (MAP + aktuellster SPaT pro `intersectionId`)
- [x] `SignalGroupState` mit `movementPhaseState`, `minEndTime`, `maxEndTime`, `likelyTime`, `timeConfidence`
- [x] `SpatForecast` (Phasensegmente der naechsten 30 s pro Signalgruppe mit Confidence)
- [x] `ActiveRequest` (SREM + optional korrespondierendes SSEM, `importanceLevel`, `requestor.role`, `inLane`, `outLane`, ETA)
- [x] `SceneSnapshot` als Join von `timelinePosition` + allen obigen States

### 2.6.2 Aggregations-Engine
- [x] MAP-zu-SPaT-Join ueber `intersectionId` (Revisions-Check ueber `IntersectionState.revision_mismatch`)
- [x] SREM-zu-SSEM-Korrelation ueber `requestID` + `sequenceNumber`
- [x] Timeout-Detektor: SREM ohne SSEM-Antwort nach > 1 s
- [x] Uhrenversatz-Check (DSRC-`minute`/`second` vs. PCAP-Zeitstempel)
- [x] ETA-Verifikation (prognostizierte vs. tatsaechliche Ankunft via CAM-Trajektorie)

### 2.6.3 Phasenprognose
- [x] Fortschreibung des aktuellen `movementPhaseState` bis `minEndTime`/`maxEndTime`
- [x] Konfidenz-Mapping aus `timeConfidence` (ETSI TS 103 301) nach {high, medium, low}
- [ ] Segmentliste fuer die naechsten 30 s je SignalGroup
- [ ] Flow-Freigabe-Check (Ingress- zu Egress-Lane ueber `connectsTo` in MAPEM)

### 2.6.4 UI-Panel
- [x] Phasenprognose-Panel (Signalgruppen-Zeitbalken, naechste 30 s)
- [x] Panel "Offene Anforderungen" mit Prioritaet, ETA, Restzeit
- [x] Inline-Warnungen: fehlende MAP, veraltete Revision, Uhrenversatz, Timeout, konkurrierende Prioritaeten
- [x] Statistik-Felder: msgs/sec, drops, Revisionen, ETA-Genauigkeit

### Referenzen
- ETSI TS 103 301 (MAPEM/SPATEM/SREM/SSEM Facilities)
- SAE J2735 (MovementPhaseState)
- ISO/TS 19091 (DSRC-Zeitbasis, Anwendungsprofil Kreuzung)
- ETSI TS 102 894-2 (Common Data Dictionary)

---

## Phase 3: Karten- und Visualisierungsverbesserung

- [x] Fix: JS-Escaping fuer `station_id`-, Popup- und Farbwerte im `MapWidget` gegen Script-Injektion gehaertet
- [ ] Offline-Kartenunterstuetzung
- [ ] Kartenlayer-Auswahl
- [ ] Heatmap-Overlay
- [ ] Cluster-Ansicht bei vielen Markern
- [ ] Koordinaten- und Massstabsanzeige
- [ ] Screenshot-Export
- [ ] Dichte-Timeline fuer Playback
- [ ] Loop-Modus
- [ ] Lesezeichen in der Zeitleiste
- [ ] Frame-fuer-Frame-Navigation

---

## Phase 4: Analyse und Export

- [x] Fix: KML-Farbkollision zwischen CAM und DENM behoben, Einzigartigkeit per Test abgesichert
- [ ] Statistik-Dashboard
- [ ] Zeitlicher Verlauf der Nachrichtenraten
- [ ] Geschwindigkeits-/Heading-Verteilung pro Station
- [ ] CSV-Export gefilterter Daten
- [ ] Zeitanimierte KML-Dateien
- [ ] GeoJSON-Export
- [ ] GPX-Export

## Offene Punkte aus Bugfix-Runde

- [ ] Known Issue: `PlayerController.set_filtered_messages()` nutzt weiterhin eine eigene Duration-Berechnung — zurueckgestellt, da funktional stabil und ausserhalb der priorisierten Fixes

---

## Phase 5: Architektur und Verteilung

- [ ] Type-Checking mit mypy oder pyright in CI
- [ ] Linting mit ruff
- [ ] Einheitliche Formatierung
- [ ] Pre-commit-Hooks
- [ ] GitHub Actions CI-Pipeline
- [ ] PyInstaller-Bundle fuer Windows
- [ ] Streaming-Parser fuer sehr grosse Dateien
- [ ] Hintergrund-Thread fuer Parsing
- [ ] Plugin-System fuer zusaetzliche Decoder
- [ ] Headless-Kommandozeilenmodus

---

## Empfohlene naechste Schritte

1. `test_nmea_parser.py` und `test_kml_exporter.py` ergaenzen, um die Testbasis auf den restlichen Kern auszuweiten.
2. ASN.1-Decoding fuer `MAPEM` und `SPATEM` fachlich vertiefen, damit die UI mehr als Typ und Position anzeigen kann.
3. Lade-Workflow in einen Hintergrund-Thread verschieben und danach einen Abbrechen-Button nachziehen.
