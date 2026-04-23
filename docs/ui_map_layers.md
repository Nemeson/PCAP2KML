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
