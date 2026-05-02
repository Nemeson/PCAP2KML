# PCAP2KML Player — Aktualisierte Roadmap

**Stand:** 2026-04-25 | **Version:** 1.7.0+

---

## Phase 1: Stabilisierung & Testing (ABGESCHLOSSEN)

- [x] Test-Suite mit pytest
- [x] Unit- und Integrationstests für Kernmodule
- [x] Globales Exception-Handling
- [x] ASN.1-Decoding-Fehler-Logging
- [x] Parser-Robustheit (Timeout, pyshark, GeoNetworking)
- [x] Drag & Drop, Letzte Sitzung, UX-Auffrischung

---

## Phase 2: ASN.1-Decoding-Verbesserung (ABGESCHLOSSEN)

- [x] Erweiterte Nachrichtenfelder (CAM, DENM, MAPEM, SPATEM, SREM/SSEM)
- [x] Schema-Management (Download, Integritätsprüfung, Fallback)
- [x] Performance: Lazy-Compiling, Cache

---

## Phase 2.5: PKI-Signatur-Analyse (TEILWEISE)

- [x] **A1 — Parser-Vervollständigung**: `assurance_level`, `station_type`, `validity`, `region`, `ITS-AID`
- [x] **A2 — UI-Platzhalter**: "Signatur prüfen"-Button mit Hinweisdialog
- [x] **A3 — ECDSA-Verifikation**: Standalone-Skript (`scripts/verify_ecdsa.py`), opt-in via `cryptography`
- [ ] Zertifikatsketten vollständig parsen (erfordert echte ASN.1/UPER-Decodierung)
- [ ] Signaturverifikation in Haupt-App integrieren

**Anmerkung**: Echte kryptografische Verifikation ist auf explizite **Benutzeranfrage** beschränkt (Sicherheits-/Compliance-Anforderungen).

---

## Phase 2.6: Szenen-Aggregation & Phasenprognose (TEILWEISE)

- [x] Szenen-Datenmodell (IntersectionState, SignalGroupState, SpatForecast)
- [x] MAP-zu-SPaT-Join
- [x] SREM-zu-SSEM-Korrelation
- [x] Timeout-Detektor, Uhrenversatz-Check, ETA-Verifikation
- [x] **Flow-Freigabe-Check**: Lane-Connectivity + `resolve_flow_status()`
- [x] Phasenprognose-Panel (aktueller Stand)
- [ ] Segmentliste für die nächsten 30 s je SignalGroup (vollständige Segmentierung)

---

## Phase 3: Karten- und Visualisierung (TEILWEISE)

### Bereits implementiert
- [x] **Export-Formate**: GeoJSON, CSV, GPX, KML Tour
- [x] **Statistik-Dashboard**: Eigenständiger Dialog mit Nachrichtenraten, Speed/Heading
- [x] **JS-Escaping**: Sicherheit gegen Script-Injection

### Stubs / Vorbereitet
- [ ] Offline-Kartenunterstützung (Vector-Tiles / MapLibre)
- [ ] Heatmap-Overlay + Cluster-Ansicht
- [ ] Koordinaten- und Maßstabsanzeige
- [ ] Screenshot-Export
- [ ] Dichte-Timeline + Loop-Modus + Lesezeichen + Frame-Navigation

**Nächste Schritte**: MapLibre-Integration für Offline-Vector-Tiles (MBTiles / PMTiles), dann Heatmap/Cluster als MapLibre-Layer.

---

## Phase 4: Analyse und Export (TEILWEISE)

- [x] KML-Export (bestehend)
- [x] **GeoJSON-Export** (neu)
- [x] **CSV-Export** (neu)
- [x] **GPX-Export** (neu)
- [x] **Zeitanimierte KML-Tour** (neu)
- [x] **Statistik-Dashboard** (neu)
- [ ] Statistik-Dashboard: Diagramme/Charts (Matplotlib / PyQtGraph)
- [ ] Geschwindigkeits-/Heading-Verteilung als Histogramm

---

## Phase 5: Architektur und Verteilung (IN ARBEIT)

- [x] **pyproject.toml** mit ruff, mypy, pytest, Coverage
- [x] **GitHub Actions CI** (Windows)
- [x] **Lokales CI-Skript** (`scripts/run_ci.ps1`)
- [ ] Type-Checking: 100% mypy-clean (derzeit teilweise ignoriert für Qt-Overrides)
- [ ] Pre-commit-Hooks
- [ ] PyInstaller-Bundle für Windows
- [ ] Headless-Kommandozeilenmodus

---

## Phase 6: Test-Strategie & Qualitätssicherung (ABGESCHLOSSEN)

- [x] **Teststrategie** (`tests/TESTING_STRATEGY.md`) — Pyramide, Risikomatrix, Marks
- [x] **Fixture-Hierarchie** (`tests/conftest.py`, `factories.py`, `conftest_pcap.py`)
- [x] **Coverage-Gate** 80% — aktuell 80.2% Line (306/306 Tests passing)
- [x] **pytest-Marks**: unit, integration, gui, e2e, property, slow, benchmark, pcap_real
- [x] **Unit-Test-Erweiterung**: 39 neue Tests (security_parser, player_controller, map_backend)
- [x] **Bugfixes**: Race-Condition in `_cleanup_loader`, Exception-Handler robust für headless
- [ ] 90% Branch Coverage (aktuell ~65%; erfordert 200+ Parser/Scene-Tests)
- [ ] Property-Tests (Hypothesis — malformed ASN.1/NMEA Frames)
- [ ] GUI-Tests mit pytest-qt (headless `QT_QPA_PLATFORM=offscreen`)

---

## Zusammenfassung der Änderungen

| Branch | Inhalt | Tests |
|--------|--------|-------|
| `bugfix/optimization-round` | Thread-Safety, Signal-Leaks, Timer-Lifecycle, Performance | 245/245 |
| `feature/ci-toolchain` | ruff, mypy, GitHub Actions CI | 254/254 |
| `feature/scene-aggregation-flow` | Lane-Connectivity, Flow-Freigabe-Check | 254/254 |
| `feature/pki-verification` | PKI-Parser, UI-Platzhalter, ECDSA-Skript | 254/254 |
| `feature/phase-d-visualization` | Dashboard, Export-Formate (GeoJSON/CSV/GPX/KML) | 267/267 |
| `feature/testing-strategy` | Teststrategie, Fixtures, 39 neue Tests | 306/306 |

**Gesamt auf `master`: 306 Tests, 80.2% Coverage, 25.7s Laufzeit**

---

- **MapLibre-Integration**: Erfordert WebEngine- oder Qt-Widget-Backend für Vektor-Tiles.
- **Offline-Karten**: MBTiles oder PMTiles als Assets einbinden.
- **Diagramme**: Matplotlib oder PyQtGraph als optionale Dependency.
- **PKI-Integration**: Echte ECDSA-Verifikation nur auf explizite Anfrage.

---

## Empfohlene Nächste Schritte (nach Priorität)

1. **MapLibre-Integration** (Phase 3) — höchste Priorität für Offline-Karten
2. **Diagramme im Dashboard** (Phase 4) — Matplotlib/PyQtGraph für visuelle Statistiken
3. **Pre-commit-Hooks** (Phase 5) — Automatische Formatierung vor Commit
4. **PyInstaller-Bundle** (Phase 5) — Verteilungsfertige Windows-Exe

---

# Release-Plan v1.8 → v2.0 (beschlossen 2026-05-02)

Themen sauber pro Release abgegrenzt. Live-Capture als Architektur-Vorbereitung in 1.8, Feature in 2.0.
Detaillierter Integrationsplan v1.8: siehe [`integration_plan_v1.8.md`](integration_plan_v1.8.md).

## v1.8 — Analyse-Tiefe

**Theme:** Engineer kann eine V2X-Message vollständig verstehen, ohne den PCAP extern zu öffnen. Replay läuft flüssig.

- **Replay-Stutter beheben** — Profiling auf jedem PCAP, Frame-Pacing-Audit, Fix-Tickets datengetrieben
- **Message-Inspector** — ASN.1-Decode-Tree mit Hex/Raw-View, konfigurierbarer Trigger (Klick / Pause-Auto / Hotkey / Aus) inkl. MouseOver-Erklärungen
- **Filterleiste** — Multi-Select Stations-ID × Message-Type × Zeitfenster, persistent, wirkt auf Map+Liste+Statistik
- **IVIM-Support** — ETSI TS 103 301 v2.2.1, Map-Layer mit ISO-14823-Icons, KML-Export, synthetische Test-Fixtures
- **Statistik-Tab (Phase 1)** — eigener Reiter, post-hoc, mit Update-Rate, Lücken-Detektor, **verwendete Standards** (C-Roads, C2C-CC, ETSI, BSI) read-only anzeigen
- **`MessageSource`-Abstraktion** — Refactor ohne UI-Änderung als Vorbereitung für Live-Capture
- **Code-Signing-Cert beschaffen** (Track parallel, Lieferzeit 5–10 Tage)

**Coverage-Ziel:** 83 % | **Performance-Gate CI:** p95-Frametime < 18 ms auf 100/500 MB Test-PCAPs

## v1.9 — Visualisierung

**Theme:** Mehrere Stationen und Datendichten gleichzeitig erfassbar machen.

- **Heatmap-Layer** (Density, Speed, RSSI sofern vorhanden)
- **Track-Vergleich** RSU↔Vehicle gemischt, n Stationen synchron, Diff-View
- **Replay-Export** als MP4/GIF
- **Konfliktanalyse** SREM↔SPATEM, MAPEM-Geometrie-Plausibilität, CAM-Heading-Sprung-Detektor
- **Statistik-Tab Phase 2** — Conformance-Checker mit Pass/Warn/Fail-Tabelle gegen C-Roads/C2C-CC/ETSI/BSI-Profile
- *(Optional, Feature-Flag)* 3D-View via Cesium

**Coverage-Ziel:** 86 %

## v2.0 — Live-Capture & Distribution

**Theme:** Aus dem Offline-Tool wird ein Live-Operationswerkzeug mit Enterprise-Distribution.

- **Live-Capture** über Cohda MK6 (Raw-Socket, BTP/GeoNet) und OpenC2X (UDP-Multicast) — Ringbuffer, Pause/Record
- **CLI-Modus** für Batch-Konvertierung (PCAP → KML/GeoJSON ohne UI)
- **MSI-Installer + Code-Signing** (signtool.exe in CI, EV- oder OV-Cert)
- **Auto-Update** gegen GitHub-Releases
- **Plugin-API** für Custom-Decoder

**Coverage-Ziel:** 89 %

---

## Release-übergreifende Continuous-Themen

- Coverage +3 % pro Release (80 → 89 bei v2.0)
- Performance-Benchmark im CI mit Regression-Gate (100 MB / 500 MB / 1 GB Capture)
- Streaming-Parser umstellen, sobald Captures > 1 GB realistisch werden
- Diagnostics-Bundle-Export (Logs + Sysinfo + PCAP-Header) als Menüpunkt für Bug-Reports

---

## Rahmenentscheidungen

| Punkt | Entscheidung |
|-------|--------------|
| Primärnutzer | Internes Team, später externe V2X-Engineers |
| Hauptschmerz | Replay-Stutter + Analyse-Tiefe |
| Live-Capture | Architektur in v1.8, Feature in v2.0 |
| Live-Capture-Targets | Cohda MK6 + OpenC2X |
| Code-Signing | Cert muss beschafft werden (kritischer Pfad v2.0) |
| Anonymisierung | Nicht erforderlich (interne Daten) |
| IVIM-Testdaten | Synthetisch generiert, ETSI Plugtest-Captures als Fallback |
| Standards-Compliance | v1.8 read-only (Profil-Anzeige), v1.9 aktiver Checker |

---

*Letzte Aktualisierung: 2026-05-02*
