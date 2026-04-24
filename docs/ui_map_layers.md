# Kartenlayer und UI-Verhalten

Stand: 2026-04-22

## Standardlayer

Standardmaessig sichtbar:

- Stationen
- Trajektorien
- Inbound-Lanes
- Outbound-Lanes
- Connections
- Stoplines
- aktive/kuezlich beantwortete Requests

Standardmaessig nicht sichtbar:

- MAP-Punkte
- SPAT-Punkte

SREM/SSEM erzeugen keine punktfoermigen Marker.

## MAP/SPAT

MAP wird als Lane-/Connection-/Stopline-Geometrie dargestellt.
SPAT faerbt Connections anhand des aktiven MovementState.

## Connection-Hover

Mouseover auf Connections zeigt:

```text
Connection
Lane X -> Lane Y
Signal Group
MovementState
Timing-Felder, falls vorhanden
```

Beim Hover wird die Connection temporaer breiter und mit voller Deckkraft
dargestellt.

## Request-Routen

Requests werden auf Lanes oder Connections dargestellt:

```text
pending      blau
acknowledged gelb
granted      gruen
rejected     rot
```

Dominante Requests sind breit und deckend. Sekundaere Requests sind duenn,
transparenter und gestrichelt.

Timeouts werden nicht als Kartelement dargestellt. Sie erscheinen im
Priorisierungsfehler-Panel.

## Priorisierungsfehler-Panel

Das Panel sitzt rechts neben der Karte und zeigt aktuelle Issues fuer den
Playback-Zeitpunkt.

Filter:

- `Alle`: alle aktuellen Issues
- `Nur kritisch`: nur Severity `error`
- `Aktuelle Kreuzung`: Kreuzungsfilter anwenden
- Kreuzungsauswahl: einzelne Intersection isolieren

Die Filter wirken nur auf das Panel. Die Kartenlayer bleiben stabil, damit eine
Fehleranalyse nicht unbeabsichtigt MAP/SPAT- oder Request-Geometrie ausblendet.

Klick auf ein Issue synchronisiert:

- Karte
- Request-Highlight
- ETA-Auswahl
- Nachrichtentabelle
- Detailtab

## Problemstellen-Replay

Die Playback-Leiste bietet:

```text
Nur Problemstellen
Fehler zurueck
Naechster Fehler
```

Der Modus springt nur zu Zeitpunkten, an denen erstmals ein
Priorisierungsproblem erkannt wurde.

## Performance-Schutz

Die Karte rendert Linien und Polylines per Leaflet-Canvas statt ueber viele
einzelne SVG/DOM-Elemente. Beim initialen Laden wird ein gebuendeltes
Render-Payload an QtWebEngine uebergeben, statt jede Lane, Connection, Route
und Trajektorie als einzelnen JavaScript-Aufruf zu senden.

Waehrend des Playbacks werden vollstaendige Karten-Slices gedrosselt. Wenn auf
langsamen Notebooks ein grosses Payload noch im WebView verarbeitet wird, wird
nicht jede Zwischenversion nachgereicht; stattdessen bleibt nur das neueste
Payload in der Warteschlange. Das verhindert, dass QtWebEngine nach einigen
Sekunden Wiedergabe durch eine anwachsende JavaScript-Queue einfriert.

Zusaetzlich kopiert der Playback-Renderer keine wachsenden Nachrichten-Prefixes
mehr. Er arbeitet mit Indexgrenzen auf der bestehenden Nachrichtenliste. Das ist
wichtig fuer lange TXA/RXA-Merges, weil sonst alle paar Sekunden neue grosse
Python-Listen und JSON-Zwischenobjekte entstehen. Wiederverwendete Leaflet-Layer
aktualisieren Popups und Tooltips per `setContent`; beim Entfernen werden
Events, Popups und Tooltips geloest, damit der QtWebEngine-Prozess keine alten
Layer-Objekte ueber laengere Wiedergaben haelt.

## Performance-Modi

Die Toolbar enthaelt den Modus `Leistung`:

```text
Normal | Schonend | Diagnose
```

Die Modi sind bewusst nicht nur optische Presets, sondern reduzieren die
tatsaechliche Renderarbeit:

| Modus | Ziel | Kartenverhalten |
|---|---|---|
| `Normal` | Desktop-Rechner und kurze Mitschnitte | voller Detailgrad, Hover-Tooltips, Trajektorien |
| `Schonend` | groessere TXA/RXA-Merges oder schwache Notebooks | kuerzeres Playback-Zeitfenster, staerker gedrosselte Vollrenderings, keine Hover-Tooltips |
| `Diagnose` | eingefrorene Karte, RAM-Druck, Fehleranalyse | sehr kurzes Playback-Zeitfenster, keine Trajektorien, keine Labels, nur zentrale Infrastruktur-Layer |

Playback-Fenster:

- `Normal`: letzte 120 Sekunden
- `Schonend`: letzte 45 Sekunden
- `Diagnose`: letzte 20 Sekunden

Vollrenderings werden je nach Modus auf ca. 1,25 s, 2,5 s bzw. 4,0 s
gedrosselt. Zwischen diesen Vollrenderings wird weiterhin die aktuelle
Playback-Position aktualisiert.

## Payload-Budgets und Telemetrie

Jeder Kartenmodus besitzt feste Budgets fuer:

- Marker
- Infrastruktur-Objekte
- Trajektorien
- Trajektorienpunkte

Wenn ein Render-Payload groesser wird als der Modus zulaesst, wird er vor dem
Versand an QtWebEngine gekuerzt. Dabei werden aktuelle Marker und aktuelle
Trajektorienpunkte bevorzugt behalten. Die Karte protokolliert zu jedem Payload:

- Performance-Modus
- sichtbare Nachrichten
- Anzahl Marker, Infrastruktur-Objekte und Trajektorien
- Anzahl Trajektorienpunkte
- JSON-Payload-Groesse in Bytes
- Anzahl gekuerzter Objekte je Budgetklasse
- ob ein bereits wartendes Render-Payload durch ein neueres ersetzt wurde

Diese Telemetrie wird im Hauptfenster begrenzt historisiert und im
Diagnosebericht exportiert. Wenn bereits im Modus `Normal` Objekte wegen Budgets
ausgelassen werden muessen, schaltet die App automatisch auf `Schonend`. Das ist
ein fruehes Schutzsignal: lieber die Kartendetails reduzieren als eine wachsende
WebEngine-Warteschlange riskieren.

## RAM-Waechter

Der RAM-Waechter prueft alle fuenf Sekunden den Arbeitsspeicher des
App-Prozesses. Die Anzeige sitzt direkt neben dem Performance-Dropdown.

Schwellwerte:

- ab ca. 1200 MB: automatische Reduktion auf `Schonend`
- ab ca. 1800 MB: automatische Reduktion auf `Diagnose`

Die Reduktion ist absichtlich defensiv: wenn ein Notebook unter Speicherdruck
geraet, ist eine noch lesbare Analyse wichtiger als ein vollstaendiger
Kartenlayer-Satz. Waehlt der Bediener danach manuell wieder einen Modus aus,
wird die automatische Markierung zurueckgesetzt.

## Karten-Safe-Mode

Die eingebettete WebEngine meldet JavaScript-Fehler an die Python-UI weiter.
Zusaetzlich meldet die Karte:

- fehlgeschlagenes Laden der Leaflet-Seite
- Render-Payloads, die laenger als acht Sekunden in der WebEngine laufen
- wiederholte `ReferenceError`- oder `TypeError`-Meldungen aus der Karte

Nach drei Kartenproblemen aktiviert das Hauptfenster automatisch den
Performance-Modus `Diagnose`. Der Safe-Mode ist bewusst konservativ: er zeigt
weniger Nebenlayer, unterdrueckt Labels und Trajektorien und reduziert damit die
Zahl verwalteter Leaflet-Objekte. Der Bediener kann die Karte anschliessend ueber
`Karte neu laden` neu initialisieren. Dabei wird die Safe-Mode-Fehlerhistorie
geleert und die aktuelle Sitzung erneut gerendert.

Ein einzelnes blockiertes oder langsames Render-Payload wird nicht mehr als
fataler WebEngine-Startfehler bewertet. Es zaehlt weiterhin fuer den Safe-Mode,
loest aber keinen automatischen Native-Fallback aus. So bleibt die geografische
Leaflet-Karte erhalten, waehrend die Datenmenge reduziert wird.

## Diagnosebericht

`Diagnose exportieren` schreibt `pcap2kml_diagnostics.json`. Der Bericht ist fuer
Fehleranalyse auf anderen Rechnern gedacht und enthaelt:

- Erstellzeitpunkt in UTC
- Python-, Qt-, PyQt- und Plattforminformationen
- Versionen der Kernpakete
- aktive QtWebEngine/Chromium-Flags
- aktuelle RAM-Nutzung
- aktueller Performance-Modus und Safe-Mode-Status
- Sitzungsquellen, Nachrichtenanzahl, Stationen und Nachrichtentypverteilung
- letzte Karten-Telemetrie und Telemetrie-Historie
- Kartenfehler-Historie

Damit lassen sich typische Notebook-Probleme wie graue Karte, WebEngine-Freeze,
uebergrosse Payloads oder fehlende Paketversionen deutlich schneller eingrenzen.

## Lokale Leaflet-Assets

Leaflet wird nicht mehr nur vom CDN geladen. Die App liefert folgende Dateien
lokal unter `pcap2kml_player/assets/leaflet` aus:

- `leaflet.js`
- `leaflet.css`
- Standardbilder fuer Layer-Control und Marker

Die eingebettete HTML-Karte nutzt diese lokalen Dateien zuerst. Falls sie in
einer Entwickler- oder Paketierungsumgebung fehlen, faellt die Karte auf das
offizielle Leaflet-CDN zurueck. Dadurch startet die Karte robuster auf Rechnern
mit eingeschraenkter Netzverbindung und die EXE ist weniger an CDN-Verfuegbarkeit
gebunden. Kartenkacheln selbst bleiben weiterhin Online-Tiles der jeweiligen
Basiskartenanbieter.

Zur Laufzeit werden die lokal mitgelieferten Leaflet-JavaScript- und CSS-Dateien
direkt in das HTML eingebettet. Das vermeidet QtWebEngine-Probleme mit relativen
`file://`-Skriptpfaden auf einzelnen Windows-Rechnern. Wenn Leaflet trotzdem
nicht initialisiert werden kann, zeigt der Kartenbereich eine sichtbare Meldung
und die Python-UI erfasst den Fehler im Karten-Safe-Mode bzw. Diagnosebericht.

Zusätzlich startet QtWebEngine standardmaessig mit Software-Rendering. Das ist
auf Notebooks und Remote-/Docking-Setups robuster als GPU-Compositing, weil
Chromium/Qt sonst je nach Treiber eine graue WebEngine-Flaeche anzeigen kann.
Der Softwarepfad nutzt `QT_OPENGL=software` sowie
`QT_OPENGL_DLL=<PyQt6>\\Qt6\\bin\\opengl32sw.dll`,
`QSG_RHI_PREFER_SOFTWARE_RENDERER=1` und deaktiviert GPU-Compositing ueber
Chromium-Flags. Das ist fuer Qt 6 auf Windows der robustere Pfad als ein
ANGLE-SwiftShader-Erzwingen. GPU-Rendering kann fuer Vergleichstests mit
`PCAP2KML_ENABLE_GPU=1` wieder aktiviert werden. Die Startup-Logs geben
`QT_OPENGL_DLL` inzwischen explizit aus, damit bei Problemrechnern sofort
sichtbar ist, ob wirklich die mit PyQt6 ausgelieferte `opengl32sw.dll`
verwendet wird.

Wenn QtWebEngine auch mit dieser Konfiguration keinen GLES-Kontext erzeugen
kann, kann in der Toolbar `Karte: Native` der native Qt-Kartenbackend gewaehlt
werden. Dieser Backend verwendet `QGraphicsView` statt Leaflet und rendert
Marker, kurze Trajektorien, Inbound-/Outbound-Lanes, Connections, Stoplines und
Request-Overlays direkt in Qt. Dadurch fehlen Online-Kartenkacheln und
Basiskartenumschaltung, aber die Analyse bleibt auf betroffenen Notebooks
bedienbar. Fuer gezielte Vergleiche kann der Backend auch
ueber `PCAP2KML_MAP_BACKEND=native` oder `PCAP2KML_MAP_BACKEND=webengine`
festgelegt werden. Der Diagnosebericht enthaelt den konkret aktiven
Backend-Namen sowie `QT_OPENGL`, `QT_OPENGL_DLL` und die aktiven
Chromium-Flags.

**Automatischer Fallback-Mechanismus**

Nach `loadFinished` startet ein JavaScript-Probe (`typeof L !== 'undefined' &&
typeof map !== 'undefined'`). Nur wenn dieser Probe `true` zurueckgibt, gilt der
Bootstrap als erfolgreich (`_bootstrap_probe_succeeded = True`). Ein paralleler
6-Sekunden-Timer prueft *dieses Flag* - nicht `loadFinished` - und loest vor dem
ersten erfolgreichen Bootstrap bei Nichterfuellung einen `map_issue_detected`-
Event aus. Das verhindert das Szenario, bei dem `loadFinished(ok=True)` trotz
defektem GL-Kontext feuert und den Timer faelschlicherweise abwuergt.

Nach einem erfolgreichen Leaflet-Bootstrap setzt die Karte zusaetzlich
`_ever_bootstrapped = True`. Spaeter eintreffende Bootstrap-Timeouts werden dann
ignoriert, weil sie typischerweise durch blockierte Event-Loops oder alte Timer
entstehen koennen. Dadurch bleibt die geografische Leaflet-Karte auch nach dem
Laden und Filtern grosser PCAPs erhalten.

Beim initialen `fitView` verwendet Leaflet nicht mehr nur die aktuell
registrierten Layer, sondern explizite, validierte Bounds aus dem Python-
Render-Payload. Diese Bounds umfassen Marker, Trajektorien-nahe Infrastruktur,
Inbound-/Outbound-Lanes, Connections, Stoplines und Request-Overlays. Falls
keine gueltigen Bounds vorhanden sind, faellt die Karte weiterhin auf
`fitToMarkers()` zurueck.

Zusaetzlich ist das `renderProcessTerminated`-Signal des `QWebEnginePage`
verbunden. Ein Chromium-Absturz setzt `_bootstrap_probe_succeeded = False` und
loest ebenfalls einen Fallback aus.

`_on_map_issue_detected` erkennt fatale Fehlerkategorien (u.a. `"Karten-WebView"`,
`"Leaflet"`, `"WebEngine"`, `"Render-Prozess"`) und ruft `_replace_map_widget`
mit `persist=False` auf, damit der naechste App-Start wieder Leaflet versucht.
Vor dem Entfernen des alten Widgets ruft das Hauptfenster `dispose()` auf. Das
alte Leaflet/WebEngine-Widget leert dadurch ausstehende Render-Payloads,
invalidiert Timer-Generationen und ignoriert spaete JavaScript-Callbacks, die
sonst nach `deleteLater()` noch auf ein bereits geloeschtes Qt/C++-Objekt
zeigen koennten.
