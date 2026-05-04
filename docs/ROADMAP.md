# PCAP2KML Player — Roadmap

**Stand:** 2026-05-04 | **Aktive Version:** 1.7.0 | **Branch:** master

Hinweis: Die Produktversion ist weiterhin 1.7.0. Die Oberflaeche nutzt bereits
den neuen v2.0-Workspace-Entwurf mit den Workspaces `Karte`, `ETA Analyse`,
`Priorisierung` und `Rohdaten`.

Detaillierter Integrationsplan v1.8: [`integration_plan_v1.8.md`](integration_plan_v1.8.md)
Aktuelles Performance-Profil: [`profiling/stutter_profile.md`](profiling/stutter_profile.md)

---

## Status auf einen Blick

| Release | Theme | Status |
|---------|-------|--------|
| v1.0–v1.7 | Stabilisierung, ASN.1, Tests, Map-Stability | **abgeschlossen** |
| v1.8 | Analyse-Tiefe + Workspace-UI-Hardening + IVIM + Live-Capture-Architektur-Prep | in Arbeit |
| v1.9 | Visualisierung (Heatmap, Track-Vergleich, Conformance-Checker) | geplant |
| v2.0 | Live-Capture (Cohda + OpenC2X), CLI, MSI/Signing, Auto-Update, Plugin-API | geplant, Release-Scope klaeren |

---

## Abgeschlossen bis v1.7

### Stabilisierung & Testing
- [x] pytest-Test-Suite mit 306 Tests, 80.2 % Coverage
- [x] Unit-/Integrations-/E2E-/Property-/GUI-Tests, pytest-Marks (unit, integration, gui, e2e, property, slow, benchmark, pcap_real)
- [x] Fixture-Hierarchie (`tests/conftest.py`, `factories.py`, `conftest_pcap.py`)
- [x] Globales Exception-Handling, robust auch im Headless-Modus
- [x] Race-Condition in `_cleanup_loader` behoben, Worker-Lifecycle gehaertet
- [x] ruff + mypy + GitHub Actions CI (Windows), lokales `scripts/run_ci.ps1`

### Parser & ASN.1
- [x] Erweiterte Nachrichtenfelder (CAM, DENM, MAPEM, SPATEM, SREM, SSEM)
- [x] Schema-Management mit Download, Integritaetspruefung, Fallback (ETSI Forge GitLab)
- [x] Lazy-Compiling, Cache, Timeout-Handling
- [x] Pyshark + scapy Dual-Backend mit automatischer Auswahl
- [x] Drag & Drop, Letzte Sitzung, Recent-Files

### Szenen-Aggregation
- [x] Datenmodell (IntersectionState, SignalGroupState, SpatForecast)
- [x] MAP-zu-SPaT-Join, SREM-zu-SSEM-Korrelation
- [x] Timeout-Detektor, Uhrenversatz-Check, ETA-Verifikation
- [x] Lane-Connectivity, `resolve_flow_status()`, Phasenprognose-Panel

### Karten- und Export-Funktionalitaet
- [x] WebEngine/Leaflet ausschliesslich, Native-Map-Widget entfernt
- [x] Auto-Recovery bei Map-Fehlern
- [x] Export-Formate: KML, GeoJSON, CSV, GPX, KML-Tour
- [x] Statistik-Dashboard als eigenstaendiger Dialog
- [x] JS-Escaping gegen Script-Injection

### PKI-Signatur (Teilweise)
- [x] Parser-Vervollstaendigung (`assurance_level`, `station_type`, `validity`, `region`, `ITS-AID`)
- [x] UI-Platzhalter "Signatur pruefen" mit Hinweisdialog
- [x] Standalone-ECDSA-Verifikationsskript (`scripts/verify_ecdsa.py`)

### v1.7 Map-Stability & Threading-Hardening
- [x] Leaflet-Interaction-Detection-Bridge — pausiert JS-Calls bei Pan/Zoom
- [x] Catch-up-Flush nach Interaction-End
- [x] Stall-Timeout 8s -> 5s, Auto-Reload nach 3 Stalls in 60 s
- [x] RenderPayloadWorker — Payload-Berechnung off-thread
- [x] QueuedConnection fuer worker-Signale, ParsingWorker-Cancel-Check
- [x] resizeEvent-Interaction-Gate verhindert Map-Freeze beim Maximieren
- [x] i18n, ThemeManager, Konstanten-Konsolidierung, CI-Erweiterungen

### v1.8 Vorarbeiten (bereits gemerged in 1.7-Branch)
- [x] **T1.1** Stutter-Diagnose-Profiler ([scripts/profiling/profile_replay.py](../scripts/profiling/profile_replay.py))
- [x] **T1.1** Stutter-Profiling-Bericht ([docs/profiling/stutter_profile.md](profiling/stutter_profile.md))
- [x] **T1.3a** Bisect-Index-Cut + Reorder + Index-Cache in `_compute_render_payload`
       — rxa p95: 238 → 43 ms (-82 %), txa p95: 780 → 243 ms (-69 %)
- [x] **T1.3b** Trail-Window-Default in Production bereits aktiv (120 s normal / 45 s saver / 20 s diagnostic)
- [x] v2.0-Workspace-UI in der aktuellen EXE gesichtet:
      dunkle Toolbar, Workspace-Tabs, Statusleiste, Schnellbefehl, Dashboard,
      ETA-Analyse, Priorisierung und Rohdaten/Detail-Inspektor
- [x] Benutzerhandbuch mit aktuellen Screenshots aus `dist\PCAP2KML-Player.exe`
      aktualisiert ([benutzerhandbuch.html](benutzerhandbuch.html),
      [screenshots/](screenshots/))
- [x] PyInstaller-EXE-Build vorhanden (`dist\PCAP2KML-Player.exe`);
      reproduzierbare Release-Pipeline, Installer und Signing bleiben offen

### Aus 1.7-Restbestand uebernommen ins v1.8/spaeter
- [ ] PKI: Zertifikatsketten vollstaendig parsen + Signaturverifikation in Haupt-App integrieren _(opt-in, nur auf User-Request)_
- [ ] Szenen: vollstaendige Segmentliste fuer naechste 30 s je SignalGroup
- [ ] mypy 100 % clean (Qt-Overrides aktuell teilweise ignoriert)
- [ ] Pre-commit-Hooks
- [ ] Diagramme im Statistik-Dashboard (Matplotlib oder PyQtGraph)
- [ ] Geschwindigkeits-/Heading-Histogramme
- [ ] Doku-Review-Gate: Roadmap, README und Benutzerhandbuch muessen vor Release
      gegen die gebaute EXE gegengeprueft werden

---

## v1.8 — Analyse-Tiefe (in Arbeit)

**Theme:** Engineer kann eine V2X-Message vollstaendig verstehen, ohne den PCAP extern zu oeffnen. Replay laeuft fluessig.

| Status | Ticket |
|--------|--------|
| ✅ done | **T1.1** Stutter-Profiling — Befund O(N)-Vollscan dokumentiert |
| ✅ done | **T1.3a** Bisect-Cut + Reorder + Index-Cache (rxa p95 −82 %, txa p95 −69 %) |
| ✅ done | **T1.3b** Trail-Window-Default (bereits in Production) |
| ✅ done | **T8.1** Benutzerhandbuch auf v2.0-Workspace-UI aktualisiert, Screenshots aus aktueller EXE erneuert |
| ◻ open | **T8.2** UI-Screenshot-Smoke-Test automatisieren (App starten, Test-PCAP laden, Workspaces aufnehmen, Doku-Refs pruefen) |
| ◻ open | **T8.3** Workspace-UX-Hardening: Tastaturfokus, aktive Tab-Zustaende, Detail-Inspektor-Auswahl, leere Fehlerliste klarer machen |
| ◻ open | **T1.2** JS-Bridge-Latenz in Live-App messen |
| ◻ open | **T1.3c** `_display_anchor_points` Cache (naechster Hebel: Frametime-Gate p95 < 18 ms) |
| ◻ open | **T1.3d** Inkrementelles Marker-Update (Delta statt Full-Repaint) |
| ◻ open | **T1.3e** orjson, falls nach c/d noch noetig |
| ◻ open | **T2** Message-Inspector Phase 2 (Decode-Tree + Hex/Raw + konfigurierbarer Trigger mit MouseOver-Tooltips; aktueller Rohdaten-Detail-Inspektor ist Basis) |
| ◻ open | **T3** Filterleiste Phase 2 (Multi-Select Stations-ID × Type × Zeit, persistent, FilterModel-Reuse; aktueller Rohdatenfilter ist Basis) |
| ◻ open | **T4** IVIM-Support (ETSI TS 103 301 v2.2.1, ISO-14823-Icons, KML, synthetische Test-Fixtures) |
| ◻ open | **T5** Statistik/Dashboard Phase 1 (bestehenden Dialog erweitern: Diagramme, Histogramme, read-only Standards-Profil-Anzeige C-Roads/C2C-CC/ETSI/BSI) |
| ◻ open | **T6** `MessageSource`-Abstraktion (Refactor ohne UI-Aenderung, Live-Capture-Vorbereitung) |
| ◻ open | **T7** Code-Signing-Cert beschaffen (parallel laufender Track) |

**Coverage-Ziel:** 83 %  |  **CI Performance-Gate:** p95-Frametime < 18 ms auf 100/500 MB Test-PCAPs

---

## v1.9 — Visualisierung (geplant)

**Theme:** Mehrere Stationen und Datendichten gleichzeitig erfassbar machen.

- ◻ Heatmap-Layer (Density, Speed, RSSI sofern verfuegbar)
- ◻ Track-Vergleich RSU↔Vehicle gemischt, n Stationen synchron, Diff-View
- ◻ Replay-Export als MP4/GIF
- ◻ Screenshot-Export als UI-Funktion (aktuelle Karte / aktueller Workspace / gesamtes Fenster)
- ◻ Frame-fuer-Frame-Navigation plus Loop-Bereich fuer kurze Analysefenster
- ◻ Dichte-Timeline unterhalb des Playbacks mit Message-Typ-Farben und Fehler-Markern
- ◻ Konfliktanalyse SREM↔SPATEM, MAPEM-Geometrie-Plausibilitaet, CAM-Heading-Sprung-Detektor
- ◻ **Statistik-Tab Phase 2** — Conformance-Checker mit Pass/Warn/Fail gegen C-Roads / C2C-CC / ETSI / BSI
- ◻ MapLibre-Integration fuer Offline-Vector-Tiles (MBTiles / PMTiles)
- ◻ _(Optional, Feature-Flag)_ 3D-View via Cesium

**Coverage-Ziel:** 86 %

---

## v2.0 — Live-Capture & Distribution (geplant)

**Theme:** Aus dem Offline-Tool wird ein Live-Operationswerkzeug mit Enterprise-Distribution.

- ◻ Live-Capture ueber Cohda MK6 (Raw-Socket, BTP/GeoNet) und OpenC2X (UDP-Multicast), Ringbuffer, Pause/Record
- ◻ CLI-Modus fuer Batch-Konvertierung (PCAP → KML/GeoJSON ohne UI)
- ◻ MSI-Installer + Code-Signing (signtool.exe in CI, EV- oder OV-Cert)
- ◻ PyInstaller-Bundle als reproduzierbarer Release-Job mit Smoke-Test und Artefakt-Checksumme
- ◻ Auto-Update gegen GitHub-Releases
- ◻ Plugin-API fuer Custom-Decoder
- ◻ Crash-/Diagnostics-Bundle direkt aus der EXE exportieren (Logs, Settings, Sysinfo, PCAP-Header, Karten-Telemetrie)

**Coverage-Ziel:** 89 %

---

## Release-uebergreifende Continuous-Themen

- Coverage +3 % pro Release (80 → 89 bei v2.0)
- Performance-Benchmark im CI mit Regression-Gate (100 / 500 / 1000 MB Capture)
- Streaming-Parser umstellen, sobald Captures > 1 GB realistisch werden
- Diagnostics-Bundle-Export (Logs + Sysinfo + PCAP-Header) als Menuepunkt fuer Bug-Reports
- Doku- und Screenshot-Regression: mindestens ein Smoke-Run pro Release-Kandidat
  gegen die gebaute EXE, damit README/Roadmap/Benutzerhandbuch nicht vom UI abdriften

---

## Roadmap-Erweiterungsvorschlaege zur Priorisierung

Diese Punkte sind noch nicht als Release-Zusage zu verstehen. Sie sollten vor
Einplanung fachlich priorisiert werden:

1. **Automatisierte UI-Doku-Erzeugung**
   - App mit Fixture-PCAP starten, Workspaces automatisch durchklicken,
     Screenshots erzeugen und HTML-Referenzen pruefen.
   - Nutzen: verhindert veraltete Screenshots und falsche UI-Beschreibungen.

2. **Analyse-Session-Bookmarks**
   - Nutzer kann Zeitpunkte, Nachrichten oder Fehler als Bookmark markieren,
     kommentieren und exportieren.
   - Nutzen: bessere Uebergabe zwischen Entwicklern, Testern und Feldteams.

3. **Vergleichsmodus Capture A/B**
   - Zwei PCAP-Sitzungen synchron vergleichen, z. B. vor/nach RSU-Konfiguration.
   - Nutzen: sehr stark fuer Regressionen, Feldtests und Abnahme.

4. **Replay-Profile**
   - Vordefinierte Ansichten wie "Performance", "Priorisierung", "PKI",
     "Map-Konflikte" oder "Operator".
   - Nutzen: reduziert UI-Komplexitaet fuer verschiedene Rollen.

5. **Privacy-/Redaction-Export**
   - Station-IDs, MACs, Positionsdetails oder Zertifikatsdaten vor Weitergabe
     pseudonymisieren.
   - Nutzen: spaeter wichtig, sobald externe Engineers oder Lieferanten
     Captures erhalten.

6. **Headless Report Mode**
   - CLI erzeugt HTML/PDF-Analysebericht inkl. Kartenbildern, Fehlerliste,
     Statistik und Export-Artefakten.
   - Nutzen: CI, Batch-Analyse und reproduzierbare Testberichte.

---

## Offene Produktfragen

1. Soll der neue Workspace-UI-Stand als Teil von v1.8 ausgeliefert werden, oder
   soll daraus offiziell ein v2.0-UI-Release werden, bevor Live-Capture kommt?
2. Welche Zielgruppe hat Prioritaet: internes Analyse-Team, Feldtester,
   externe V2X-Engineers oder CI/Batch-Nutzer?
3. Ist Live-Capture fuer v2.0 wichtiger als ein stabiler Installer mit Signing
   und Auto-Update, oder sollen Distributionsthemen zuerst kommen?
4. Welche Test-PCAPs duerfen dauerhaft als Screenshot-/Regression-Fixtures
   genutzt werden?
5. Soll die Roadmap deutsch bleiben, oder fuer externe Nutzer zweisprachig
   werden?

---

## Rahmenentscheidungen (2026-05-04)

| Punkt | Entscheidung |
|-------|--------------|
| Primaernutzer | Internes Team, spaeter externe V2X-Engineers |
| Hauptschmerz | Replay-Stutter + Analyse-Tiefe |
| Live-Capture | Architektur in v1.8, Feature in v2.0 |
| Live-Capture-Targets | Cohda MK6 + OpenC2X |
| Code-Signing | Cert muss beschafft werden (kritischer Pfad v2.0) |
| Anonymisierung | Nicht erforderlich (interne Daten) |
| IVIM-Testdaten | Synthetisch generiert, ETSI Plugtest-Captures als Fallback |
| Standards-Compliance | v1.8 read-only (Profil-Anzeige), v1.9 aktiver Checker |
| PKI-Signaturpruefung | Bleibt opt-in auf User-Request, keine Default-Aktivierung |
| Workspace-UI | Aktueller EXE-Stand nutzt v2.0-Workspace-Design; Release-Zuordnung noch klaeren |
| Doku-Screenshots | Muessen aus aktueller EXE erzeugt oder explizit als Mockup markiert werden |

---

## Verweise

- Detail-Plan v1.8: [`integration_plan_v1.8.md`](integration_plan_v1.8.md)
- Performance-Befund: [`profiling/stutter_profile.md`](profiling/stutter_profile.md)
- Teststrategie: [`../tests/TESTING_STRATEGY.md`](../tests/TESTING_STRATEGY.md)
- Benutzerhandbuch: [`benutzerhandbuch.html`](benutzerhandbuch.html)
- Changelog: [`../CHANGELOG.md`](../CHANGELOG.md)

---

*Letzte Aktualisierung: 2026-05-04*
