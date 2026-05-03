# PCAP2KML Player — Roadmap

**Stand:** 2026-05-02 | **Aktive Version:** 1.7.0 | **Branch:** release/1.7.0

Detaillierter Integrationsplan v1.8: [`integration_plan_v1.8.md`](integration_plan_v1.8.md)
Aktuelles Performance-Profil: [`profiling/stutter_profile.md`](profiling/stutter_profile.md)

---

## Status auf einen Blick

| Release | Theme | Status |
|---------|-------|--------|
| v1.0–v1.7 | Stabilisierung, ASN.1, Tests, Map-Stability | **abgeschlossen** |
| v1.8 | Analyse-Tiefe + IVIM + Darstellungs-Fixes + Live-Capture-Architektur-Prep | in Arbeit |
| v1.9 | Visualisierung (Heatmap, Track-Vergleich, Conformance-Checker) | geplant |
| v2.0 | Live-Capture (Cohda + OpenC2X), CLI, MSI/Signing, Auto-Update, Plugin-API | geplant |

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

### Aus 1.7-Restbestand uebernommen ins v1.8/spaeter
- [ ] PKI: Zertifikatsketten vollstaendig parsen + Signaturverifikation in Haupt-App integrieren _(opt-in, nur auf User-Request)_
- [ ] Szenen: vollstaendige Segmentliste fuer naechste 30 s je SignalGroup
- [ ] mypy 100 % clean (Qt-Overrides aktuell teilweise ignoriert)
- [ ] Pre-commit-Hooks
- [ ] Diagramme im Statistik-Dashboard (Matplotlib oder PyQtGraph)
- [ ] Geschwindigkeits-/Heading-Histogramme

---

## v1.8 — Analyse-Tiefe (in Arbeit)

**Theme:** Engineer kann eine V2X-Message vollstaendig verstehen, ohne den PCAP extern zu oeffnen. Replay laeuft fluessig.

| Status | Ticket |
|--------|--------|
| ✅ done | **T1.1** Stutter-Profiling — Befund O(N)-Vollscan dokumentiert |
| ✅ done | **T1.3a** Bisect-Cut + Reorder + Index-Cache (rxa p95 −82 %, txa p95 −69 %) |
| ✅ done | **T1.3b** Trail-Window-Default (bereits in Production) |
| ◻ open | **T1.2** JS-Bridge-Latenz in Live-App messen |
| ◻ open | **T1.3c** `_display_anchor_points` Cache (naechster Hebel: Frametime-Gate p95 < 18 ms) |
| ◻ open | **T1.3d** Inkrementelles Marker-Update (Delta statt Full-Repaint) |
| ◻ open | **T1.3e** orjson, falls nach c/d noch noetig |
| ◻ open | **T2** Message-Inspector (Decode-Tree + Hex/Raw + konfigurierbarer Trigger mit MouseOver-Tooltips) |
| ◻ open | **T3** Filterleiste (Multi-Select Stations-ID × Type × Zeit, persistent, FilterModel-Reuse) |
| ◻ open | **T4** IVIM-Support (ETSI TS 103 301 v2.2.1, ISO-14823-Icons, KML, synthetische Test-Fixtures) |
| ◻ open | **T5** Statistik-Tab Phase 1 (eigener Tab, post-hoc, **read-only Standards-Profil-Anzeige**: C-Roads, C2C-CC, ETSI, BSI) |
| ◻ open | **T6** `MessageSource`-Abstraktion (Refactor ohne UI-Aenderung, Live-Capture-Vorbereitung) |
| ◻ open | **T7** Code-Signing-Cert beschaffen (parallel laufender Track) |

**Coverage-Ziel:** 83 %  |  **CI Performance-Gate:** p95-Frametime < 18 ms auf 100/500 MB Test-PCAPs

---

## v1.9 — Visualisierung (geplant)

**Theme:** Mehrere Stationen und Datendichten gleichzeitig erfassbar machen.

- ◻ Heatmap-Layer (Density, Speed, RSSI sofern verfuegbar)
- ◻ Track-Vergleich RSU↔Vehicle gemischt, n Stationen synchron, Diff-View
- ◻ Replay-Export als MP4/GIF
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
- ◻ PyInstaller-Bundle fuer Windows
- ◻ Auto-Update gegen GitHub-Releases
- ◻ Plugin-API fuer Custom-Decoder

**Coverage-Ziel:** 89 %

---

## Release-uebergreifende Continuous-Themen

- Coverage +3 % pro Release (80 → 89 bei v2.0)
- Performance-Benchmark im CI mit Regression-Gate (100 / 500 / 1000 MB Capture)
- Streaming-Parser umstellen, sobald Captures > 1 GB realistisch werden
- Diagnostics-Bundle-Export (Logs + Sysinfo + PCAP-Header) als Menuepunkt fuer Bug-Reports

---

## Rahmenentscheidungen (2026-05-02)

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

---

## Verweise

- Detail-Plan v1.8: [`integration_plan_v1.8.md`](integration_plan_v1.8.md)
- Performance-Befund: [`profiling/stutter_profile.md`](profiling/stutter_profile.md)
- Teststrategie: [`../tests/TESTING_STRATEGY.md`](../tests/TESTING_STRATEGY.md)
- Benutzerhandbuch: [`benutzerhandbuch.html`](benutzerhandbuch.html)
- Changelog: [`../CHANGELOG.md`](../CHANGELOG.md)

---

*Letzte Aktualisierung: 2026-05-02*
