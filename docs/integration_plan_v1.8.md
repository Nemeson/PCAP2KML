# Integrationsplan v1.8 — "Analyse-Tiefe"

**Stand:** 2026-05-02
**Branch:** target `release/1.8.0` (abzweigend von `master` nach v1.7.0-Merge)
**Theme:** V2X-Message vollständig verstehen + Replay flüssig + IVIM + Standards-Anzeige

---

## 0. Zielbild

Nach v1.8 gilt:
1. Replay läuft auf allen Test-PCAPs ruckelfrei (p95 < 18 ms Frametime).
2. Jede Message ist im Decode-Tree feldgenau inspizierbar; Trigger nutzerkonfigurierbar.
3. Map + Liste + Statistik filtern synchron nach Stations-ID/Type/Zeit.
4. IVIM ist erster-klassiger Message-Type wie CAM/DENM.
5. Statistik-Tab zeigt verwendete Standards (C-Roads / C2C-CC / ETSI / BSI), noch keine Verstöße.
6. Pipeline kann hinter `MessageSource`-Abstraktion getauscht werden — Live-Capture-Feature folgt in v2.0 ohne Pipeline-Refactor.

---

## 1. Epic-Übersicht & Reihenfolge

| # | Epic | Vorbed. | Risiko | Aufwand |
|---|------|---------|--------|---------|
| E1 | Replay-Stutter-Diagnose & Fix | — | Mittel (Befund offen) | M-L |
| E6 | `MessageSource`-Abstraktion | — | Niedrig (Refactor mit Tests) | M |
| E2 | Message-Inspector | E6 hilfreich | Niedrig | M |
| E3 | Filterleiste | E2 (FilterModel-Reuse) | Niedrig | S-M |
| E5 | Statistik-Tab Phase 1 | E3 | Niedrig | M |
| E4 | IVIM-Support | — (parallel) | Mittel (Schema, Testdaten) | M |
| E7 | Code-Signing-Vorbereitung | — (extern) | Niedrig technisch, hoch organisatorisch | S |

**Empfohlene Branch-Strategie:** Feature-Branches pro Epic gegen `release/1.8.0`. E1 zuerst gemergt — andere bauen auf stabilem Replay auf.

---

## 2. Epic 1 — Replay-Stutter-Diagnose & Fix

### Ausgangslage
v1.7-Stabilisierung (`70ee200`, `a84e4e3`, `d59aa55`, `1d4ceef`, `07bf0dd`, `a6402a4`) hat Architektur-Symptome adressiert (resize-Freeze, Thread-Safety, Payload-Worker, Catch-up-Flush, Interaction-Bridge), Stutter persistiert aber laut Nutzer auf allen PCAPs.

### T1.1 — Stutter-Profiling-Lauf
- `cProfile` in Player-Thread während 60-s-Replay
- Qt-Frame-Logger (Tick-Soll vs. Ist) als CSV
- JS-Bridge-Call-Counter pro Tick
- RenderPayloadWorker-Queue-Länge sampeln
- GC-Pause-Logger (`gc.callbacks`)
- Tile-Load-Telemetry aus Leaflet via `tileloadstart`/`tileload`-Events
- **Output:** `docs/stutter_profile.md` mit Top-3-Bottlenecks, Frametime-Histogramm pro Test-PCAP (klein/mittel/groß aus `testfiles/`)

**Akzeptanz:** Bericht identifiziert quantifizierbar die Hauptursache(n). Keine Code-Änderung in T1.1.

### T1.2 — Frame-Pacing-Audit
- QTimer-Drift-Messung gegen `time.perf_counter()`
- Catch-up-Logik aus `07bf0dd` auf Coalescing prüfen
- Hypothese: Mehrere Stations-Updates innerhalb eines Ticks → mehrere `runJavaScript()`-Calls → JS-Bridge-Latenz dominiert. Fix: Batch-API `updateMarkers(payloadArray)` statt N×`updateMarker`

**Akzeptanz:** Bridge-Calls/Tick-Median ≤ 2 (statt N), gemessen in T1.1-Setup.

### T1.3 — Fix-Tickets (datengetrieben)
Spezifikation **nach** T1.1. Wahrscheinliche Kandidaten:
- Marker-Diff-Update statt Vollupdate
- Tile-Preload für sichtbare Region
- GC-Tuning oder explizite `gc.collect()` außerhalb Tick
- Payload-Worker-Backpressure (Queue-Limit + drop-oldest)

**Akzeptanz aller T1-Tickets gemeinsam:** p95-Frametime < 18 ms auf 500-MB-Test-PCAP, keine Stutter-Wahrnehmung visuell.

---

## 3. Epic 6 — `MessageSource`-Abstraktion (parallel zu E1 startbar)

### T6.1 — Interface
```python
# pcap2kml_player/sources/base.py
class MessageSource(Protocol):
    def iter_messages(self) -> Iterator[V2xMessage]: ...
    def seek(self, t_seconds: float) -> None: ...
    @property
    def duration(self) -> float | None: ...   # None für Live
    @property
    def is_live(self) -> bool: ...
    def close(self) -> None: ...
```

### T6.2 — `PcapFileSource`
Refactor: bestehender Parser-Code wandert hinter dieses Interface; `ParsingWorker` konsumiert `MessageSource` statt direkt PCAP-Pfad.

### T6.3 — Design-Doku Live-Sources
`docs/live_capture_design.md` — Skizze für:
- **`CohdaMk6Source`**: Raw-Socket auf Ethernet-Frame, Parser für BTP-A/B + GeoNetworking-Header, Default-Interface konfigurierbar
- **`OpenC2XSource`**: UDP-Multicast (Default 127.0.0.1:9999, Format laut OpenC2X dissector — recherchieren und in Design-Doku festhalten)

Implementation erst v2.0. v1.8 liefert nur Interface + Doku.

### T6.4 — Player-Controller-Anbindung
`PlayerController` nimmt `MessageSource`-Instanz statt PCAP-Pfad. Tests grün halten — bestehender Test-Suite Source-Fixture bauen.

**Akzeptanz E6:** Alle Bestandstests grün, neue Property-Tests für `MessageSource`-Kontrakt, kein Verhalten-Drift im Replay.

---

## 4. Epic 2 — Message-Inspector

### T2.1 — Decode-Tree-Widget
- `pcap2kml_player/ui/inspector_panel.py`
- `QTreeView` mit `QAbstractItemModel`
- Spalten: Feldname | Wert | Typ | Raw-Hex
- Rekursive Konvertierung asn1tools-Decode-Dict → TreeModel-Nodes
- Suchfeld mit Live-Filter (case-insensitive Substring)

### T2.2 — Inspector-Trigger-Konfiguration
**Nutzer-Wunsch — kritisches UX-Detail.**

Settings-Panel `Inspector`:
- Radio-Group:
  - `Klick auf Marker/Listeneintrag` (Default)
  - `Pause-Auto` (Inspector aktualisiert nur wenn Replay pausiert)
  - `Manuell-Hotkey` (`Ctrl+I` öffnet Inspector für aktuell selektierte Message)
  - `Aus` (Inspector-Tab versteckt)
- MouseOver-Tooltip pro Option mit ausführlicher Erklärung:
  - **Klick:** "Inspector aktualisiert sich beim Anklicken eines Markers oder Listeneintrags. Beste Balance zwischen Reaktivität und Performance."
  - **Pause-Auto:** "Während Replay läuft kein Decode — minimaler CPU-Overhead. Beim Pausieren wird die Message an aktueller Cursor-Position dekodiert. Empfohlen für lange Captures."
  - **Manuell-Hotkey:** "Inspector aktualisiert nur bei Tastendruck Strg+I. Ideal für reine Wiedergabe ohne Analyse-Bedarf."
  - **Aus:** "Inspector-Tab vollständig deaktiviert. Spart Speicher und UI-Komplexität."
- Persistenz via `QSettings` (`inspector/trigger_mode`)

### T2.3 — Hex-/Raw-View
- Unter dem Tree: Monospace-Hex-Dump
- Selektion im Tree highlightet Byte-Range im Hex (asn1tools liefert Field-Offsets nicht direkt → eigener Wrapper, der Decode-Pfad → Byte-Range mappt; bei Komplexität in v1.9 verschieben, dann v1.8 nur "Copy as Hex/Base64"-Buttons)

**Akzeptanz E2:** Inspector funktioniert in allen 4 Trigger-Modi, Tooltips sichtbar, Tree zeigt CAM/DENM/IVIM/MAPEM/SPATEM/SREM/SSEM-Felder rekursiv.

---

## 5. Epic 3 — Filterleiste

### T3.1 — UI
- Toolbar/Sidebar mit:
  - Stations-ID-Multiselect (Combo mit Suchfeld)
  - Message-Type-Checkbox-Liste
  - Zeit-Range-Slider (Doppel-Handle)
- Reset-Button

### T3.2 — `FilterModel` als Single-Source-of-Truth
- `pcap2kml_player/state/filter_model.py`
- Qt-Signal `filter_changed`
- Map-Widget, Message-Liste, Statistik-Tab, Inspector subscribed

### T3.3 — Persistenz & Profile
- Session-Persistenz via `QSettings`
- "Filter-Profil speichern" → Named-Slots in `~/.pcap2kml/filter_profiles.json`

**Akzeptanz E3:** Filter ändern aktualisiert Map + Liste + Stats konsistent in < 200 ms auf 500-MB-PCAP.

---

## 6. Epic 4 — IVIM-Support

### T4.1 — ASN.1-Schema
- ETSI TS 103 301 v2.2.1 IVIM-Modul ergänzen
- Schema-Update-Mechanismus aus `70da852` (ETSI Forge GitLab) auf IVIM erweitern
- Versions-Verifikation in Schema-Cache

### T4.2 — Parser-Integration
- `MessageType.IVIM` in `data_model.py`
- Felder: `iviIdentificationNumber`, `serviceProviderId`, `iviStatus`, `glc` (GeographicLocationContainer), `giv` (GeneralIviContainer), `rcc` (RoadConfigurationContainer), `tc` (TextContainer), `lac` (LayoutContainer)
- Parser-Pfad in `parsing_worker.py` (pyshark + scapy)

### T4.3 — Map-Layer
- Eigener Layer "IVIM (Schilder)"
- Marker mit Sign-Code-Icon-Mapping aus ISO 14823 Lookup-Tabelle (`pcap2kml_player/standards/iso14823_signs.json`)
- Popup zeigt Schild-Bedeutung + Gültigkeitsbereich (`glc`)

### T4.4 — Test-Fixtures (synthetisch primär, Plugtest fallback)
- `tests/fixtures/ivim_generator.py`: `asn1tools.compile()` + Sample-JSONs, deterministisch (Seed)
- 3 Szenarien: einfaches Tempolimit-Schild, Baustellen-Warnung, dynamische Spurzuweisung
- Ablage als generierte `.pcap` in `testfiles/ivim_synth/`
- Falls reales Plugtest-Capture findbar (ETSI ITS Plugtests Public Datasets recherchieren) → in `testfiles/ivim_real/`

### T4.5 — KML-Export
- `simplekml`-Style für IVIM-Sign-Marker
- Gültigkeitsbereich als `Polygon` aus `glc.referencePosition` + `parts`

**Akzeptanz E4:** IVIM-Messages aus synthetischen Fixtures werden erkannt, gerendert, exportiert. Coverage IVIM-Modul ≥ 75 %.

---

## 7. Epic 5 — Statistik-Tab Phase 1

### T5.1 — Tab-Struktur
- Neuer `QTabWidget`-Tab "Analyse" neben Map/Liste
- Berechnung post-hoc nach `parsing_finished`-Signal
- Lazy: erste Anzeige triggert Compute, Caching im Tab-State

### T5.2 — Metriken
- Update-Rate pro Stations-ID × Message-Type (gleitendes 5-s-Fenster) als kleine Sparkline
- Message-Count-Tabelle
- Lücken-Detektor (Heuristik: > 1.5 × Median-Intervall der jeweiligen Station)
- Geschwindigkeitsverteilung (Histogramm aus CAM-`speedValue`)

### T5.3 — Standards-Profil-Anzeige (Phase 1, read-only)
**Nutzer-Wunsch — konkret abgesteckt für v1.8.**

Sektion "Verwendete Standards":
- Aus `ItsPduHeader`: `protocolVersion` pro Message-Type extrahieren
- Mapping → ETSI-Spec mit Version aus `pcap2kml_player/standards/etsi_versions.json`
- Compliance-Profile-Hinweise (read-only) aus Mapping-Datei:
  - **C-Roads** Day-1 / Day-1.5 Service-Set
  - **C2C-CC** Basic System Profile (BSP) v3.0
  - **ETSI** EN 302 637-2 (CAM), EN 302 637-3 (DENM), TS 103 301 (IVIM/MAPEM/SPATEM/SREM/SSEM)
  - **BSI** TR-03164 (sofern Security-Header dekodierbar)
- Tabelle: Message-Type | Detected Version | Matching Standard | Source-Reference
- Klick auf Eintrag öffnet Spec-Link

**Wichtig:** Nur Anzeige. Kein Pass/Fail. Conformance-Checker kommt in v1.9.

**Akzeptanz E5:** Tab zeigt Metriken + Standards-Tabelle für CAM/DENM/IVIM/MAPEM/SPATEM/SREM/SSEM auf Test-PCAPs.

---

## 8. Epic 7 — Code-Signing-Vorbereitung (organisatorisch)

### T7.1 — Cert-Typ-Entscheidung
- **EV (Extended Validation):** Sofort SmartScreen-vertrauenswürdig, ~300–500 €/Jahr, Hardware-Token
- **OV (Organization Validation):** SmartScreen-Reputation-Build-up nötig, ~150–250 €/Jahr
- Empfehlung: EV für Enterprise-Distribution

### T7.2 — Quotes einholen
DigiCert / Sectigo / GlobalSign — Lieferzeit EV typ. 5–10 Werktage (Hardware-Token-Versand).

### T7.3 — CI-Hook ohne Cert vorbereiten
- `signtool.exe sign /tr <timestamp-url> /td sha256 /fd sha256 /a $exe`
- GitHub-Actions-Workflow `release.yml` mit Step "Sign EXE" (deaktiviert per Default, aktiv via Secret-Existenz-Check)

**Akzeptanz E7:** Workflow signiert nach Cert-Lieferung ohne Code-Änderung.

---

## 9. Continuous in v1.8

### Coverage-Gate
`pyproject.toml` / pytest-cov auf `--cov-fail-under=83` ziehen (aktuell 80).

### Performance-Benchmark im CI
- pytest-benchmark gegen `testfiles/perf_*.pcap` (klein/mittel/groß)
- Regression-Gate: > 10 % Frametime-Verschlechterung gegenüber Baseline → Fail

### Diagnostics-Bundle-Export
- Menüpunkt "Hilfe → Diagnose-Bundle erstellen"
- ZIP enthält: aktuelle Logs, `platform.uname()`, Python-Version, Qt-Version, geladene Schemas, PCAP-Header (ohne Payload)
- Speicherort konfigurierbar

---

## 10. Risiken & Mitigation

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|--------------------|------------|
| Stutter-Hauptursache liegt außerhalb Code (z.B. WebEngine-GPU-Treiber) | Mittel | T1.1 deckt auf; ggf. Software-Rendering-Fallback-Option |
| asn1tools-Performance bei IVIM-Decode | Niedrig | bestehender Lazy-Compile-Cache greift |
| Live-Capture-Spec OpenC2X unklar | Mittel | T6.3-Doku-Phase deckt Recherche-Bedarf vor Implementation v2.0 |
| Code-Signing-Cert-Lieferung verzögert | Niedrig-Mittel | T7 läuft parallel ab Sprint 1 |
| Plugtest-Captures für IVIM nicht beschaffbar | Mittel | Synthetischer Generator T4.4 ist Primär-Quelle, daher unkritisch |

---

## 11. Definition of Done v1.8

- [ ] Alle E1-Akzeptanzkriterien erfüllt (Frametime-Gate)
- [ ] Inspector in 4 Trigger-Modi nutzbar, Tooltips deutsch
- [ ] Filter wirkt synchron auf alle Surfaces
- [ ] IVIM end-to-end (Parse → Map → KML) funktioniert auf synth. Fixtures
- [ ] Statistik-Tab zeigt Standards-Profil für alle Message-Types
- [ ] `MessageSource`-Refactor durchgeführt, alle Tests grün
- [ ] Coverage ≥ 83 %
- [ ] Performance-CI-Gate aktiv
- [ ] CHANGELOG.md aktualisiert
- [ ] User-Doku (`benutzerhandbuch.html`) für Inspector + Filter ergänzt
- [ ] Cert-Quotes eingeholt, Workflow-Hook vorhanden

---

*Plan ist Arbeitsgrundlage; Anpassungen werden im PR pro Epic dokumentiert.*
