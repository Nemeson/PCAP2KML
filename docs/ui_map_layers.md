# Kartenlayer und UI-Verhalten

Stand: 2026-04-21

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
