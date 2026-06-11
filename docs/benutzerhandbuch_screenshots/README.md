# Benutzerhandbuch-Screenshots

Screenshots für `docs/benutzerhandbuch.html` und `docs/aktuelle_funktionen_screenshots.md`.

## Verzeichnisstruktur

```
docs/benutzerhandbuch_screenshots/
├── vollversion/      # 14 PNGs mit gültiger Lizenz (grüner Banner)
├── demo/             # 14 PNGs ohne Lizenz (roter Demo-Banner)
└── README.md         # Diese Datei
```

## Automatisch generierte Screenshots (Capture-Skript)

**Alle 14 Screenshots pro Modus** werden via Capture-Skript erzeugt:

```bash
# 1. Vollversion-Screenshots (grüner Lizenz-Banner)
python -m pcap2kml_player.main capture \\
    --mode vollversion \\
    --output-dir docs/benutzerhandbuch_screenshots/vollversion

# 2. Demo-Screenshots (roter Demo-Banner)
python -m pcap2kml_player.main capture \\
    --mode demo \\
    --output-dir docs/benutzerhandbuch_screenshots/demo
```

**Voraussetzungen:**
- Python ≥ 3.11
- PyQt6 + QtWebEngineWidgets installiert
- `testfiles/Berlin/rxa_22082025.pcap` + `testfiles/Berlin/txa_22082025.pcap` vorhanden
- **Reales Display** (nicht headless! Leaflet braucht WebEngine-Render)
- Auflösung: mindestens 1920×1080 (Fenster wird auf 1920×1080 gesetzt)
- Profil: **Analyst** (volle Feature-Sicht)

**Was das Skript macht:**
1. Startet die App mit `LicenseManager.is_licensed()` mockt (demo → False, vollversion → True)
2. Lädt `rxa_22082025.pcap` + `txa_22082025.pcap` via `parse_pcap` + `merge_sessions`
3. Wechselt für jeden Recipe zum richtigen Workspace + Sub-Tab
4. Ruft ggf. Setup-Funktionen auf (Dashboard, Schnellbefehl, etc.)
5. Wartet 300ms (Repaint), macht `window.grab()` → PNG
6. Speichert als `<output_dir>/<stem>.png`

**Reihenfolge (pro Modus identisch):**

| Datei | Workspace | Sub-Tab | Setup |
|---|---|---|---|
| `01_hauptfenster_karte.png` | `map` | — | 1.5s warten (Leaflet-Tiles) |
| `02_schnellbefehl_palette.png` | — | — | Cmd+K-Palette öffnen |
| `03_statistik_dashboard.png` | — | — | Dashboard-Dialog (non-blocking) |
| `04_eta_analyse.png` | `eta` | — | — |
| `05_priorisierungsfehler.png` | `issues` | — | — |
| `06_rohdaten_inspektor.png` | `raw` | — | — |
| `07_map_spat_pruefung.png` | `map_validation` | — | — |
| `08_pcap_kartenausschnitt.png` | `map` | — | JS `setView(52.427970, 13.526802, 19)` |
| `09_map_xml_kartenausschnitt.png` | `map` | — | MAP-XML laden + JS `setView(49.2034845, 8.1241752, 19)` |
| `10_wireshark_start_hinweis.png` | — | — | Wireshark-Hinweis-Dialog |
| `11_spat_vorhersagequalitaet.png` | `spat_quality` | 0 (Dashboard) | — |
| `12_spat_gantt.png` | `spat_quality` | 3 (Gantt) | — |
| `13_spat_prognosehorizont.png` | `spat_quality` | 4 (Prognose) | — |
| `14_lizenz_dialog.png` | — | — | Hilfe → Lizenz |

### Wenn ein Karten-Screenshot leer bleibt

Die Karten-Screenshots (01, 08, 09) brauchen funktionierendes QtWebEngine. Falls dein System Probleme hat, kannst du sie nachträglich manuell aufnehmen:

1. App mit demselben Modus starten
2. Workspace „Karte" + gewünschtes Zoom/Kartenzentrum
3. Win+Shift+S für Snipping Tool
4. Speichern als `01_hauptfenster_karte.png` / `08_pcap_kartenausschnitt.png` / `09_map_xml_kartenausschnitt.png`

## Workflow-Empfehlung

```bash
# 1. PNG-Verzeichnis vorbereiten
mkdir -p docs/benutzerhandbuch_screenshots/{vollversion,demo}

# 2. Capture-Skript laufen lassen (Vollversion zuerst)
python -m pcap2kml_player.main capture \\
    --mode vollversion \\
    --output-dir docs/benutzerhandbuch_screenshots/vollversion

# 3. Demo-Screenshots (mit Demo-Lizenz-Konfiguration)
#    → App neu starten, ggf. Lizenz-Datei löschen (Demo-Modus)
python -m pcap2kml_player.main capture \\
    --mode demo \\
    --output-dir docs/benutzerhandbuch_screenshots/demo

# 4. Optional: Wenn Karten-Screenshots leer sind, nachträglich manuell:
#    → App starten, in richtigen Modus + Zoom navigieren
#    → Win+Shift+S für Snipping Tool
#    → Speichern in docs/benutzerhandbuch_screenshots/{modus}/

# 5. HTML + MD updaten (vom Agent)
#    → benutzerhandbuch.html und aktuelle_funktionen_screenshots.md werden automatisch angepasst
```

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `QWebEngineView must be imported before QApplication` | Skript pre-importiert `QtWebEngineWidgets`. Falls Crash: Reihenfolge prüfen. |
| `MapWidget hangs` | Sicherstellen, dass kein headless platform gesetzt ist. App muss Display haben. |
| `testfiles not found` | Working-Directory muss `C:\PythonTools\PCAP2KML` sein. Test-Daten liegen in `testfiles/Berlin/`, nicht direkt in `testfiles/`. |
| `QSettings show_wireshark_hint` schon dismissed | Vor Skript-Lauf: `HKCU\Software\C-ITS-Inspector\Inspector\show_wireshark_hint = true` setzen, oder App neu installieren. |
| PNG hat komische Größe | Fenster zu klein. Vor Skript-Lauf: 1920×1080 sicherstellen, DPI-Scaling prüfen. |
| `grab()` blockiert dauerhaft | QWebEngineView rendert nicht. Display/WebEngine prüfen. |
