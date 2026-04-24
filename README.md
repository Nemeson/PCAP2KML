# PCAP2KML Player

Desktop-Anwendung zur Analyse, Wiedergabe und Kartendarstellung von V2X-Nachrichten aus PCAP-Dateien.

Stand: 2026-04-22  
Aktueller dokumentierter Funktionsstand: v1.7

## Uebersicht

PCAP2KML Player ist auf ITS-G5 / ETSI-V2X-Workflows ausgelegt. Die App liest `.pcap`, `.pcapng` und `.cap`, dekodiert erkannte ITS-Nachrichten sowie NMEA/GNSS-Daten und stellt sie in einer operativen Desktop-Oberflaeche dar.

Unterstuetzte Nachrichtentypen:

- CAM
- DENM
- MAPEM
- SPATEM
- SREM
- SSEM
- NMEA / GNSS

## Kernfunktionen

- Multi-Datei-PCAP-Import mit Hintergrund-Parsing, Fortschrittsanzeige und Abbrechen
- Drag & Drop fuer Capture-Dateien
- Persistente "Letzte Sitzung"-Funktion mit Dateiliste und Sitzungszusammenfassung
- Interaktive Leaflet-Karte im Desktop-Fenster
- Synchronisierte Wiedergabe mit `Play`, `Pause`, `Stop`, Scrubbing und Geschwindigkeiten von `0.1x` bis `10x`
- Live-Filter nach Nachrichtentyp und Station-ID
- Detailansicht pro Nachricht inklusive PKI-/Security-Felder
- KML-Export pro Station
- ASN.1-Schema-Update mit Cache-Invalidierung und Integritaetspruefung
- Szenen-Aggregation fuer MAP/SPAT/SREM/SSEM
- 30s-Phasenprognose und Request-Korrelation
- Clock-Skew- und ETA-Verifikation
- TXA/RXA-Soft-Merge mit kanonischer Sicht
- Priorisierungsfehler-Panel fuer SREM/SSEM
- Problemstellen-Replay
- CSV/JSON-Export der Priorisierungsfehler inklusive TXA/RXA-Provenance
- JSON-Analyse-Report fuer Issue-Verteilung, Kreuzungen und Source-Rollen

## Karten- und Playback-Stand

Die Kartenlogik ist inzwischen deutlich ueber Marker und einfache Trajektorien hinaus erweitert:

- Basiskarten sind im Leaflet-Layer-Control umschaltbar:
  - `Hell / Schwarz-Weiss`
  - `OSM Standard`
  - `Dunkel`
  - `Satellit`
- Die zuletzt gewaehlte Basiskarte wird lokal im WebEngine-Profil gespeichert
- MAP und SPAT werden als Infrastruktur-Layer statt als normale RSU-Marker gerendert
- MAP-Lanes sind nach `Inbound` und `Outbound` getrennt
- Connections werden schematisch zwischen Lanes dargestellt
- Stoplines werden fuer Inbound-Lanes als eigener Layer gezeichnet
- SPAT faerbt die zugehoerigen Connections nach `MovementState`
- SRM/SSEM werden als Priorisierungs-Overlays auf Inbound-Lane, Outbound-Lane und Connection dargestellt
- Dominante und sekundaere Priorisierungen werden unterschiedlich stark visualisiert
- Mehrere Requests auf derselben Connection werden seitlich entzerrt
- Karten-Updates werden gebuendelt an QtWebEngine uebergeben und Leaflet rendert Linien per Canvas,
  damit grosse TXA/RXA-Merges beim Laden nicht durch viele einzelne JavaScript-Aufrufe einfrieren
- Im Playback werden grosse Karten-Slices gedrosselt und laufende Render-Payloads zusammengefasst,
  damit langsame Notebooks keine wachsende QtWebEngine-Warteschlange aufbauen
- Der Toolbar-Modus `Leistung` steuert den Detailgrad der Karte:
  - `Normal`: voller Detailgrad mit Tooltips und Trajektorien
  - `Schonend`: reduzierte Playback-Fenster, weniger haeufige Vollrenderings und weniger Hover-Arbeit
  - `Diagnose`: stark reduzierter Kartenumfang fuer schwache Rechner oder Fehleranalyse
- Ein RAM-Waechter zeigt den aktuellen Arbeitsspeicher in der Toolbar und reduziert bei hoher Last
  automatisch auf `Schonend` bzw. `Diagnose`
- Karten-Payloads haben je Modus feste Budgets fuer Marker, Infrastruktur, Trajektorien und
  Trajektorienpunkte; bei Ueberschreitung wird automatisch vereinfacht statt die WebEngine zu
  ueberlasten
- Wiederholte Karten-/JavaScript-Probleme aktivieren automatisch den Karten-Safe-Mode `Diagnose`
- `Diagnose exportieren` schreibt einen technischen JSON-Bericht mit Runtime-, Paket-, RAM-,
  Sitzungs-, Karten- und Fehlerhistorie
- Die `ETA Analyse` enthaelt jetzt ein Fahrzeug-/Request-Dashboard mit Kennzahlen
  und chronologischer SREM/SSEM-/Diagnose-Ereignistabelle
- ETA-Ereignisse sind interaktiv: SREM/SSEM-Zeilen springen zur Nachricht,
  Diagnosezeilen fokussieren Request und Karte
- Die aktuelle ETA-Dashboard-Auswertung kann als CSV und JSON exportiert werden
- Leaflet-JavaScript, CSS und Standardbilder liegen lokal unter `pcap2kml_player/assets/leaflet`;
  zur Laufzeit werden JavaScript und CSS direkt ins Karten-HTML eingebettet,
  nur wenn diese Assets fehlen, wird auf das CDN zurueckgefallen
- Playback-Renderings arbeiten mit Indexgrenzen statt mit kopierten Nachrichten-Prefixes;
  Popups/Tooltips werden in Leaflet wiederverwendet und beim Entfernen explizit geloest,
  damit die RAM-Nutzung ueber laengere Wiedergaben stabil bleibt
- MAP-/SPAT-Punktlayer sind standardmaessig deaktiviert
- SSEM/SSM erzeugt keine Punktmarker oder Trajektorien
- Connections zeigen per Mouseover den aktiven MovementState und Timing-Felder
- Timeouts werden nicht als Kartenroute dargestellt, sondern im Fehlerpanel gelistet

Playback-Verhalten:

- Die Karte zeigt waehrend der Wiedergabe nur den Zustand bis zur aktuellen Zeitposition, nicht den Endzustand der gesamten Datei
- Bewegte Objekte zeigen nur die aktuelle Position plus einen kurzen Trail
- Die Karte bleibt waehrend der Wiedergabe stabil stehen
- Wenn ein bewegtes Objekt angeklickt wird, folgt die Karte diesem Objekt im Playback

## UI im aktuellen Stand

Die Hauptansicht besteht aus vier Arbeitsbereichen:

1. Kopfbereich mit Sitzungsstatus, Dateianzahl, Nachrichtenzahl und Stationen
2. Filterzeile fuer Nachrichtentypen und Stationen
3. Karten- und rechte Arbeitsleiste
4. Playback-Leiste mit Slider, Zeitanzeige und Geschwindigkeitsumschaltung

Die rechte Arbeitsleiste ist jetzt in zwei Ebenen organisiert:

- oben immer sichtbar: Nachrichtentabelle
- darunter als Tabs:
  - `Details` fuer Nachrichten-, PKI- und Identitaetshinweise
  - `Szene` fuer Kreuzungszustand, Phasenprognose, Requests und Warnungen
  - `ETA Analyse` fuer request-zentrierte ETA-, Speed- und SSEM-Statusbaender
    plus Kennzahlen- und Ereignistabelle pro Fahrzeug/Request
    inklusive Klick-Synchronisation und CSV/JSON-Export

Rechts neben der Karte befindet sich das Panel `Priorisierungsfehler`. Es zeigt
aktuelle Timeouts, Rejected, Late Granted, ETA-Konflikte und weitere
Priorisierungsprobleme. Klick auf einen Eintrag synchronisiert Karte,
Nachrichtentabelle, Detailansicht und ETA-Analyse.

Das Panel bietet Filter fuer `Alle`, `Nur kritisch`, `Aktuelle Kreuzung` und eine
Kreuzungsauswahl. Kritische Fehler koennen dadurch gezielt pro Intersection
isoliert werden, ohne die Karte mit zusaetzlichen Markern zu ueberladen.

### Layout fuer kleine Bildschirme

Die Toolbar enthaelt einen Layoutmodus:

```text
Auto | Desktop | Kompakt
```

`Auto` schaltet unterhalb von ca. 1320 px Fensterbreite in den Kompaktmodus. Der
Kompaktmodus ist auf 1280x720 optimiert und priorisiert die Karte:

- Kopfbereich ist einklappbar
- Nachrichtentabelle zeigt kompakt nur `Timestamp`, `Station ID`, `Msg Type` und
  `Speed / Heading`
- Toolbar- und Playback-Beschriftungen werden verkuerzt
- Priorisierungsfehler-Panel klappt ohne kritische Fehler automatisch ein
- Kritische Priorisierungsfehler klappen das Panel wieder auf

Das Szenenpanel zeigt derzeit:

- Kreuzungen mit MAP-/SPAT-Revisionen
- Signalgruppen-Zusammenfassung
- kompakte 30s-Phasen-Timelines
- offene und kuerzlich beantwortete Priorisierungsanforderungen
- operative Request-Zustaende: `pending`, `acknowledged`, `granted`, `rejected`, `timeout`
- Inline-Warnungen bei fehlender MAP-Basis, Revisionsmismatch, Timeout und Clock Skew
- Kennzahlen wie `Msgs/s` und mittlere ETA-Abweichung

Die Playback-Leiste enthaelt zusaetzlich `Nur Problemstellen`, `Fehler zurueck`
und `Naechster Fehler`. Damit springt die Wiedergabe nur zwischen Zeitpunkten,
an denen ein Priorisierungsproblem erstmals erkannt wird.

### Performance-Modus und RAM-Waechter

Die Toolbar enthaelt zusaetzlich den Modus `Leistung`:

```text
Normal | Schonend | Diagnose
```

`Normal` ist fuer leistungsstarke Rechner gedacht und zeigt die vollstaendige
Kartenanalyse. `Schonend` reduziert die Playback-Arbeit auf ein kuerzeres
Zeitfenster, drosselt Vollrenderings staerker und deaktiviert Hover-Tooltips im
laufenden Kartenbetrieb. `Diagnose` ist der Sicherheitsmodus fuer problematische
Notebooks: Trajektorien, Labels und nicht zwingend notwendige Infrastruktur
werden unterdrueckt, damit die WebEngine moeglichst wenig Layer verwalten muss.

Der Modus wird in den Benutzereinstellungen gespeichert. Der RAM-Waechter prueft
alle fuenf Sekunden den Arbeitsspeicher des App-Prozesses. Ab ca. 1200 MB wird
automatisch auf `Schonend`, ab ca. 1800 MB auf `Diagnose` reduziert. Eine
manuelle Auswahl im Dropdown hebt diese automatische Reduktion wieder auf.

Zusaetzlich begrenzt die Karte die Groesse jedes Render-Payloads. Wenn ein Payload
mehr Marker, Infrastruktur-Objekte oder Trajektorienpunkte enthaelt als der
aktuelle Modus vorsieht, werden alte bzw. nachrangige Kartenelemente gekuerzt und
die Telemetrie protokolliert, wie viele Objekte ausgelassen wurden. Im Modus
`Normal` fuehrt eine Budget-Ueberschreitung automatisch zu `Schonend`, weil das
ein fruehes Warnsignal fuer einen moeglichen WebEngine-Stau ist.

Die Playback-Zeitfenster sind bewusst abgestuft:

| Modus | Vollrender-Intervall | Playback-Fenster |
|---|---:|---:|
| `Normal` | 1,25 s | 120 s |
| `Schonend` | 2,5 s | 45 s |
| `Diagnose` | 4,0 s | 20 s |

Dadurch bleiben aktuelle Bewegungen und Priorisierungen sichtbar, waehrend alte
Kartenobjekte nicht dauerhaft im Browserprozess mitgefuehrt werden.

### Karten-Safe-Mode und Diagnosebericht

Die Karte meldet JavaScript-Fehler, fehlgeschlagene WebView-Ladevorgaenge und
Renderpayloads, die laenger als acht Sekunden in der QtWebEngine haengen. Nach
drei solchen Ereignissen aktiviert die App automatisch den Safe-Mode `Diagnose`.
Der Safe-Mode reduziert Labels, Trajektorien und Nebenlayer, damit eine graue
oder eingefrorene Karte wieder bedienbar wird. Langsame Renderpayloads loesen
bewusst keinen Native-Fallback mehr aus, weil sie meist durch Datenmenge und
nicht durch einen defekten WebEngine-Start entstehen.

Die Toolbar bietet ausserdem:

```text
Diagnose exportieren | Karte neu laden
```

`Diagnose exportieren` schreibt `pcap2kml_diagnostics.json` in ein ausgewaehltes
Verzeichnis. Der Bericht enthaelt:

- Python-, Qt- und PyQt-Version
- installierte Kernpakete
- aktive QtWebEngine/Chromium-Flags
- aktuelle RAM-Nutzung
- Performance-Modus und Safe-Mode-Status
- geladene Quellen, Nachrichtenzahl, Stationen und Nachrichtentypverteilung
- letzte Karten-Telemetrie und begrenzte Telemetrie-Historie
- Karten-/JavaScript-Fehlerhistorie

`Karte neu laden` initialisiert die eingebettete Leaflet-Seite neu, leert die
Safe-Mode-Fehlerhistorie und rendert die aktuelle Sitzung erneut.

## Architektur

### Parser und Decoding

- `pcap_parser.py` nutzt `pyshark` bevorzugt und faellt auf `scapy` zurueck
- Direkte GeoNetworking-/BTP-Erkennung fuer EtherType `0x8947`
- Fallback-Nachrichtenerkennung ueber ITS-PDU-Header `messageId`
- NMEA-Parsing fuer GNSS-Daten
- ASN.1-Decoding ueber `asn1tools`
- MAP-Normalisierung fuer Lane-Rollen, Connections und Stopline-Fallback

### Playback und Visualisierung

- `player_controller.py` steuert die synchronisierte Wiedergabe
- `map_widget.py` bettet Leaflet in `QWebEngineView` ein
- `ui/main_window.py` verbindet Playback, Filter, Export, Detailbereich und Szenenpanel

### Szenenmodell

`scene_model.py` aggregiert den flachen Nachrichtenstrom in fachliche Zustandsobjekte:

- `IntersectionState`
- `SignalGroupState`
- `SpatForecast`
- `ActiveRequest`
- `RequestVisualState`
- `SceneSnapshot`
- `EtaVerification`
- `PrioritizationIssue`
- `PrioritizationIssueOccurrence`

Die Issue-Historie wird zentral berechnet und fuer unveraenderte Message-Listen
gecacht. Problemstellen-Replay und Export nutzen dadurch dieselben
Erstauftretenszeitpunkte.

### Security / PKI

`security_parser.py` extrahiert bereits Grundinformationen aus ETSI TS 103 097 Security-Containern, darunter Signer-Typ, Signaturdaten, Gueltigkeit und weitere Zertifikatsfelder. Die tiefe Signatur- und Kettenpruefung ist noch nicht vollstaendig umgesetzt.

## ASN.1-Schema-Update

Das Schema-Update arbeitet jetzt robust in zwei Modi:

- vorhandenes Git-Checkout in `assets/asn1`: `git pull`
- eingebetteter lokaler Schema-Ordner ohne `.git`: temporaerer Clone in ein Temp-Verzeichnis, danach Uebernahme nur der relevanten `.asn`-Dateien

Nach einem erfolgreichen Update werden In-Memory- und `.pkl`-Caches invalidiert, damit neue Schemata sofort wirksam sind.

## Projektstruktur

```text
PCAP2KML/
├── docs/
│   └── ROADMAP.md
├── pcap2kml_player/
│   ├── app_memory.py
│   ├── asn1_schemas.py
│   ├── data_model.py
│   ├── kml_exporter.py
│   ├── main.py
│   ├── map_widget.py
│   ├── nmea_parser.py
│   ├── parsing_worker.py
│   ├── pcap_parser.py
│   ├── player_controller.py
│   ├── scene_model.py
│   ├── security_parser.py
│   ├── ui/
│   │   └── main_window.py
│   ├── assets/
│   │   ├── asn1/
│   │   └── cache/
│   └── requirements.txt
├── testfiles/
├── tests/
├── CHANGELOG.md
└── README.md
```

## Voraussetzungen

- Windows 10 oder 11
- Python 3.11+
- Wireshark / TShark optional, aber empfohlen fuer `pyshark`

Hinweis: Ohne `TShark` funktioniert die App weiterhin ueber den `scapy`-Fallback, allerdings mit moeglicherweise eingeschraenkter Decoderabdeckung je Capture.

## Installation

```powershell
cd C:\PythonTools\PCAP2KML\pcap2kml_player
py -m pip install -r requirements.txt
```

## Anwendung starten

```powershell
cd C:\PythonTools\PCAP2KML
py pcap2kml_player\main.py
```

Alternativ kann der Windows-Launcher verwendet werden. Er prueft zuerst die
Python-Requirements und bietet bei fehlenden Paketen eine optionale
Nachinstallation per `pip` an:

```powershell
cd C:\PythonTools\PCAP2KML
py pcap2kml_launcher.py
```

### QtWebEngine/Grafiktreiber-Hinweis

Auf manchen Windows-Rechnern schreibt QtWebEngine/Chromium Meldungen wie
`QueryVideoProcessorCustomExtForHDR: Failed to retrieve D3D11 device` ins
Terminal. Die App setzt beim Start konservative Chromium-Flags gegen fragile
DirectComposition-/HDR-/Video-Overlay-Pfade und bevorzugt im Standardbetrieb
Software-OpenGL plus den Qt-Software-Rasterizer:

```text
--disable-direct-composition
--disable-features=DirectComposition,DirectCompositionVideoOverlays,UseHDRTransferFunction
--disable-accelerated-video-decode
--disable-gpu-memory-buffer-video-frames
--force-color-profile=srgb
--disable-gpu
--disable-gpu-compositing
--disable-accelerated-2d-canvas
--disable-webgl
--disable-webgl2
--disable-gpu-rasterization
--disable-oop-rasterization
```

Die letzten fuenf Flags sind entscheidend fuer Rechner, auf denen Chromiums
GPU-Prozess `kFatalFailure: Failed to create shared context for virtualization`
meldet. Ohne diese Flags versucht Chromium trotz `--disable-gpu` GLES-Kontexte
fuer Canvas-2D-Beschleunigung und WebGL zu erstellen — die Kontexterstellung
schlaegt fehl und die Karte bleibt leer. Mit `--disable-accelerated-2d-canvas`
verwendet Chromium stattdessen CPU-basiertes Skia fuer alle Canvas-Operationen,
was den Leaflet-Renderer auf beliebiger Hardware funktionsfaehig haelt.

Ergaenzend dazu werden gesetzt:

```text
QT_OPENGL=software
QT_OPENGL_DLL=<PyQt6>\Qt6\bin\opengl32sw.dll
QSG_RHI_PREFER_SOFTWARE_RENDERER=1
```

Damit wird der problematische D3D11-/SceneGraph-Treiberpfad auf vielen
Windows-Rechnern umgangen. Leaflet/WebEngine bleibt der Standard, damit
Basiskarten wie OSM, Schwarz-Weiss, Dunkel und Satellit verfuegbar bleiben.
Falls QtWebEngine trotz Software-OpenGL weiterhin keinen GLES-Kontext erstellen
kann, erkennt die App das automatisch: Nach dem Laden der Seite prueft ein
JavaScript-Probe, ob Leaflet tatsaechlich initialisiert wurde. Schlaegt diese
Pruefung vor dem ersten erfolgreichen Bootstrap fehl oder laeuft sie in einen
6-Sekunden-Timeout, wechselt die App selbstaendig auf den nativen Backend -
auch dann, wenn `loadFinished(ok=True)` bereits gefeuert hat (was trotz
defektem GL-Kontext passiert). Sobald Leaflet einmal erfolgreich initialisiert
wurde, werden spaete Bootstrap-Timeouts ignoriert; dadurch verschwindet die
geografische Karte nach dem Laden groesserer PCAPs nicht mehr aufgrund eines
verzoegerten Timers. Ebenso loest ein
Chromium-Render-Prozess-Absturz (`renderProcessTerminated`) sofort einen Wechsel
aus. Dieser automatische Wechsel wird nicht dauerhaft gespeichert; der naechste
App-Start versucht es erneut mit Leaflet. Der native Backend kann auch manuell
ueber `Karte: Native` in der Toolbar gewaehlt werden. Er zeigt Marker, kurze
Trajektorien, Inbound-/Outbound-Lanes, Connections, Stoplines und
Request-Overlays direkt in Qt ohne Leaflet-Tiles und ohne
QtWebEngine-GPU-Compositor, damit die Analyse auf problematischen Notebooks
weiterhin nutzbar bleibt. Beim Backend-Wechsel wird das alte WebEngine-Widget
vor `deleteLater()` explizit entschaerft: ausstehende JavaScript-Callbacks,
Renderqueues und Timer werden verworfen, damit spaete WebEngine-Callbacks nicht
mehr auf ein bereits geloeschtes Qt/C++-Objekt zugreifen.

Der Karten-Backend kann fuer Tests auch explizit gesetzt werden:

```powershell
$env:PCAP2KML_MAP_BACKEND="native"
py pcap2kml_launcher.py
```

Oder fuer einen Vergleich mit der Leaflet-/WebEngine-Karte:

```powershell
$env:PCAP2KML_MAP_BACKEND="webengine"
py pcap2kml_launcher.py
```

Falls Karte oder WebEngine auf einem Rechner trotzdem instabil laufen, kann
Software-Rendering weiterhin explizit gesetzt werden:

```powershell
$env:PCAP2KML_DISABLE_GPU="1"
py pcap2kml_launcher.py
```

Fuer gezielte Tests auf stabilen Rechnern kann GPU-Rendering wieder aktiviert
werden:

```powershell
$env:PCAP2KML_ENABLE_GPU="1"
py pcap2kml_launcher.py
```

Die Meldung `The cached device pixel ratio value was stale on window expose` ist
eine QtWebEngine/DPI-Warnung. Die Karte invalidiert ihre Leaflet-Groesse bei
Show/Resize erneut, damit Fensterwechsel und Remote-Desktop-Skalierung robuster
werden.

## Windows-EXE erstellen

Die Anwendung kann als einfache Start-EXE gebaut werden. Die EXE ist ein
Bootstrapper: sie prueft beim Start die Requirements, kann fehlende Pakete nach
Bestaetigung nachinstallieren und startet danach die eigentliche PyQt-App.

```powershell
cd C:\PythonTools\PCAP2KML
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -InstallMissing
```

Ergebnis:

```text
dist\PCAP2KML-Player.exe
```

Ohne `-InstallMissing` bricht das Buildskript mit einer Liste fehlender Pakete ab,
statt automatisch etwas nachzuladen.

Das Buildskript nimmt `pcap2kml_player/assets` in das PyInstaller-Paket auf,
damit die lokalen Leaflet-Dateien auch in der EXE verfuegbar sind.

## Abhaengigkeiten

| Paket | Zweck |
|---|---|
| `PyQt6` | Desktop-GUI |
| `PyQt6-WebEngine` | eingebettete Karte |
| `scapy` | Fallback-PCAP-Backend |
| `pyshark` | bevorzugtes PCAP-Backend ueber TShark |
| `asn1tools` | ASN.1-Decoding |
| `simplekml` | KML-Erzeugung |

## Bedienung

### Laden

- `PCAP laden` oeffnet einen Dateidialog
- `.pcap`, `.pcapng` und `.cap` koennen direkt ins Fenster gezogen werden
- `Letzte Sitzung` laedt die zuletzt erfolgreich geoeffneten Dateien erneut
- `Laden abbrechen` stoppt einen laufenden Parse-Vorgang
- `ASN.1-Schemas aktualisieren` aktualisiert die lokalen ETSI-Schemata

### Filtern und Abspielen

- Nachrichtentypen lassen sich per Checkbox ein- und ausblenden
- Stationen lassen sich in der Stationsliste selektieren
- Der Slider springt an beliebige Zeitpunkte
- Die Karte aktualisiert sich waehrend des Playbacks zeitkonsistent
- Bewegte Objekte koennen fuer ein Follow-Verhalten angeklickt werden

### Export

- `KML exportieren` schreibt eine KML-Datei pro Station
- Dateinamen werden fuer Windows sicher bereinigt
- Kollisionen nach Sanitizing werden automatisch aufgeloest
- Exportierte Dokumente enthalten die verwendeten ASN.1-Schemaversionen
- `Fehler exportieren` schreibt die Priorisierungsfehler als CSV und JSON:
  - `prioritization_issues.csv`
  - `prioritization_issues_machine.csv`
  - `prioritization_issues.json`
  - `prioritization_report.json`
- `prioritization_issues.csv` nutzt bedienerlesbare deutsche Spaltenueberschriften
- `prioritization_issues_machine.csv` und `prioritization_issues.json` behalten die stabilen
  technischen Feldnamen fuer Weiterverarbeitung
- Die Issue-Zeilen enthalten `source_roles`, `source_files`, `merge_group_id` und
  `merge_confidence`
- Der Report fasst `issues_by_type`, `issues_by_severity`,
  `issues_by_intersection`, `source_roles` und die mittlere Late-Grant-Latenz
  zusammen

## Weiterfuehrende Dokumentation

- [SREM/SSEM-Priorisierungsanalyse](docs/prioritization_analysis.md)
- [ETA-Analyse](docs/eta_analysis.md)
- [TXA/RXA-PCAP-Merge](docs/pcap_merge.md)
- [Kartenlayer und UI-Verhalten](docs/ui_map_layers.md)

## Test- und Qualitaetsstand

Die aktuelle Testsuite deckt Parser, Kartenlogik, Playback, Export, Sicherheitsparser und Szenenmodell breit ab.

- Aktueller Stand: `245 passed`
  - inklusive Runtime-/Entry-Point-Tests fuer Software-OpenGL, `QT_OPENGL_DLL`
    und den QtWebEngine-Startup-Pfad
- Vorhandene Testbereiche:
  - App-Memory
  - ASN.1-Schema-Update
  - Datenmodell
  - NMEA-Parser
  - PCAP-Parser
  - Parser-Zusatzfelder
  - KML-Export
  - Kartenlogik / Overlay-Erzeugung
  - Player-Controller
  - Security-Parser
  - Szenenmodell

Direkte GUI-Interaktionstests fuer die komplette `main_window.py` sind weiterhin vergleichsweise leichtgewichtig; der Schwerpunkt liegt dort derzeit auf Compile-/Integrationsstabilitaet und modellnahen Regressionen.

## Bekannte Grenzen

- Kein vollstaendiger PKI-Chain-Validator
- Noch kein GeoJSON- oder GPX-Export
- Noch keine Offline-Kartenkacheln; Leaflet selbst wird lokal gebuendelt
- Keine vollwertige Frame-fuer-Frame-Navigation
- Keine Headless-CLI

## Roadmap

Der detaillierte Umsetzungsstand liegt in [docs/ROADMAP.md](C:/PythonTools/PCAP2KML/docs/ROADMAP.md).

## Changelog

Das projektspezifische Aenderungsprotokoll liegt in [CHANGELOG.md](C:/PythonTools/PCAP2KML/CHANGELOG.md).
