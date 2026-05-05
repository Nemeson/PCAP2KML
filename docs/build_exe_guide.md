# EXE-Erzeugung – Build-Anleitung

Diese Anleitung beschreibt, wie aus dem PCAP2KML-Player-Quellcode eine eigenstaendige Windows-EXE (Single-File) erzeugt wird.

## Voraussetzungen

- **Windows 10/11** mit PowerShell 5.1 oder hoeher
- **Python 3.12+** (empfohlen: 3.14) – muss im PATH liegen (`py --version`)
- **Git** (optional, fuer ASN.1-Schema-Updates)

## Schnellstart

1. **Repository oeffnen**
   ```powershell
   cd C:\Pfad\zu\PCAP2KML
   ```

2. **Build-Skript ausfuehren**
   ```powershell
   .\scripts\build_exe.ps1 -InstallMissing
   ```
   
   Das Skript prueft alle Abhaengigkeiten, installiert fehlende Pakete und startet PyInstaller.

3. **Ergebnis**
   - Die fertige EXE liegt unter: `dist\PCAP2KML-Player.exe`
   - Groesse: ca. 180–250 MB (PyInstaller bundlelt Python + Qt + Chromium)

## Skript-Optionen

| Option | Beschreibung |
|--------|-------------|
| `-InstallMissing` | Installiert fehlende Python-Pakete automatisch |
| `-Clean` | Loescht `dist/`, `build/` und `*.spec` vor dem Build |

## Manuelle Variante (falls das Skript fehlschlaegt)

```powershell
# 1. Abhaengigkeiten pruefen
py -m pip install -r pcap2kml_player\requirements.txt
py -m pip install pyinstaller>=6.0

# 2. PyInstaller direkt aufrufen
py -m PyInstaller `
  --noconfirm `
  --onefile `
  --name "PCAP2KML-Player" `
  --collect-all PyQt6 `
  --collect-all PyQt6.QtWebEngineWidgets `
  --add-data "pcap2kml_player\requirements.txt;pcap2kml_player" `
  --add-data "pcap2kml_player\assets;pcap2kml_player\assets" `
  --add-data "docs\benutzerhandbuch.html;docs" `
  pcap2kml_launcher.py
```

## Was wird mitgebundelt?

PyInstaller packt folgende Ressourcen in die EXE:

- **Python-Runtime** + alle Abhaengigkeiten aus `requirements.txt`
- **PyQt6** inkl. QtWebEngine (Chromium-Browser fuer Karte)
- **Leaflet.js** + CSS (lokal unter `pcap2kml_player/assets/leaflet/`)
- **ASN.1-Schemata** (lokal unter `pcap2kml_player/assets/asn1/`)
- **Benutzerhandbuch** (`docs/benutzerhandbuch.html`)
- **Lizenz und README**

## Troubleshooting

### SmartScreen / Windows Defender blockt die EXE

Die EXE ist nicht signiert (T7 – Code-Signing steht noch aus). Unter Windows erscheint eine Warnung:

1. Klick auf **"Weitere Informationen"**
2. **"Trotzdem ausfuehren"** waehlen

In Unternehmensumgebungen muss die EXE ggf. in die Ausnahmeliste aufgenommen werden.

### Karte bleibt leer / QtWebEngine fehlt

Falls die EXE gestartet wird, aber die Karte grau bleibt:

```powershell
# Pruefen ob QtWebEngineProcess.exe neben der EXE liegt
# Bei --onefile wird es automatisch entpackt – normalerweise kein manuelles Eingreifen noetig.
```

Falls doch: PyInstaller ohne `--onefile` (Directory-Modus) verwenden:
```powershell
py -m PyInstaller --name "PCAP2KML-Player" --collect-all PyQt6 pcap2kml_launcher.py
```

### Build bricht ab wegen fehlender DLLs

```powershell
# PyInstaller neu installieren
py -m pip install --upgrade pyinstaller

# Clean-Build erzwingen
.\scripts\build_exe.ps1 -Clean -InstallMissing
```

### EXE ist zu gross

Die Groesse kommt hauptsaechlich durch QtWebEngine (Chromium). Optionen zur Reduktion:

1. `--exclude-module PyQt6.QtWebEngineWidgets` **nicht** verwenden – die Karte braucht WebEngine
2. UPX-Kompression aktivieren (falls UPX installiert):
   ```powershell
   py -m PyInstaller --upx-dir C:\Tools\upx [...]
   ```

## Output-Struktur nach Build

```
dist/
  PCAP2KML-Player.exe          # Fertige Single-File-EXE
build/
  PCAP2KML-Player/             # Temporaere Build-Dateien
*.spec                         # PyInstaller-Spezifikation (autogeneriert)
```

## Automatisierung / CI

Das Skript ist fuer manuelle Builds optimiert. Fuer CI-Pipelines (GitHub Actions etc.):

```yaml
# Beispiel: .github/workflows/build.yml (Auszug)
- name: Build EXE
  shell: pwsh
  run: |
    .\scripts\build_exe.ps1 -InstallMissing

- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: PCAP2KML-Player
    path: dist/PCAP2KML-Player.exe
```

## Versionshinweis

- **Aktuelles Build-Skript:** `scripts/build_exe.ps1`
- **PyInstaller-Version:** >= 6.0 empfohlen
- **Getestet mit:** Python 3.14.4, PyInstaller 6.x, Windows 11
