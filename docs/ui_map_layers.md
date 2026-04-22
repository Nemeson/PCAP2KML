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
