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

## Phase 3: Karten- und Visualisierung (IN ARBEIT)

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

## Offene Punkte

- **MapLibre-Integration**: Erfordert WebEngine- oder Qt-Widget-Backend für Vektor-Tiles.
- **Offline-Karten**: MBTiles oder PMTiles als Assets einbinden.
- **Diagramme**: Matplotlib oder PyQtGraph als optionale Dependency.
- **PKI-Integration**: Echte ECDSA-Verifikation nur auf explizite Anfrage.

---

## Empfohlene Nächste Schritte

1. **MapLibre-Integration** (Phase 3) — höchste Priorität für Offline-Karten
2. **Diagramme im Dashboard** (Phase 4) — Matplotlib/PyQtGraph für visuelle Statistiken
3. **Pre-commit-Hooks** (Phase 5) — Automatische Formatierung vor Commit
4. **PyInstaller-Bundle** (Phase 5) — Verteilungsfertige Windows-Exe

---

*Letzte Aktualisierung: 2026-04-25*
