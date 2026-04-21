# SREM/SSEM-Priorisierungsanalyse

Stand: 2026-04-21

Dieses Dokument beschreibt die neue Fehleranalyse fuer SREM/SSEM-Priorisierung,
die Kartenanzeige, das Fehlerpanel, den Problemstellen-Replay und den CSV/JSON-
Export, TXA/RXA-Provenance, Filter und Analyse-Report.

## Ziel

Die Priorisierung soll nicht mehr als Sammlung von Punktmarkern erscheinen. Die
Analyse trennt deshalb drei Ebenen:

- Karte: nur raeumlich relevante Routen, Lanes, Connections und Stoplines.
- Fehlerpanel: operative Probleme wie Timeouts, Rejected oder ETA-Konflikte.
- Detail-/ETA-Analyse: Rohfelder, Request-Korrelation, Statusbaender und ETA-Fehler.

Dadurch bleibt die Karte lesbar, waehrend Fehler trotzdem prominent sichtbar sind.

## Datenfluss

```text
PCAP-Dateien
-> V2xMessage Stream
-> SceneSnapshot
-> ActiveRequest / RequestVisualState / EtaVerification
-> PrioritizationIssue
-> Kartenpanel / Problemstellen-Replay / CSV-JSON Export / Report
```

Die Fehlerlogik liegt bewusst im `scene_model.py`. Die UI zeigt nur die fachlich
berechneten Ergebnisse an und entscheidet nicht selbst, ob ein Request fehlerhaft
ist.

## Request-Korrelation

SREM und SSEM werden ueber folgende Felder korreliert:

```text
intersection_id
request_id
sequence_number
station_id
```

SREM-Felder:

```text
intersectionId
requestId
sequenceNumber
importanceLevel
requestorType
inLane
outLane
eta
```

SSEM-Felder:

```text
intersectionId
requestId
sequenceNumber
requestState
```

Bei TXA/RXA-Merge bleibt die Merge-Gruppe an den Nachrichten erhalten. Die
ETA-Auswahl nutzt diese Information im Label, die Fehleranalyse arbeitet aber auf
der fachlichen Request-Korrelation.

## Fehlerobjekt

Ein Fehler wird als `PrioritizationIssue` modelliert:

```python
PrioritizationIssue(
    issue_type="TIMEOUT",
    severity="error",
    intersection_id=72,
    request_id=6,
    sequence_number=86,
    station_id="2228620000",
    in_lane=1,
    out_lane=3,
    status="timeout",
    delay_seconds=1.42,
    message="SREM ohne rechtzeitige SSEM-Antwort.",
    source_roles=("TXA", "RXA"),
    source_files=("rsu_txa.pcap", "rsu_rxa.pcap"),
    merge_group_id="merge-00001",
    timestamp=...
)
```

Diese Struktur ist stabil genug fuer UI, Replay und Export.

## TXA/RXA-Provenance

Jeder Issue uebernimmt die bekannten Quellen aus der korrelierten SREM und, falls
vorhanden, aus der passenden SSEM. Dadurch ist im Fehlerpanel und Export
sichtbar, ob der Befund aus TXA, RXA oder einer kombinierten Merge-Gruppe stammt.

Exportierte Felder:

```text
source_summary
source_roles
source_files
merge_group_id
merge_confidence
```

`source_summary` ist fuer Menschen gedacht, die Einzelspalten sind fuer
Weiterverarbeitung in Excel, Python oder BI-Werkzeugen stabiler.

## Fehlertypen

### TIMEOUT

Eine SREM ist offen, aber es wurde innerhalb der erwarteten Frist keine passende
SSEM-Antwort gefunden.

Aktuelle Fristen:

```text
importanceLevel >= 10: 0.5 s
sonstige Requests:    1.0 s
```

Timeouts werden nicht mehr als Kartenroute dargestellt. Sie erscheinen im
Fehlerpanel und im Problemstellen-Replay.

### REJECTED

Eine passende SSEM wurde gefunden, aber ihr Status weist auf Ablehnung hin.

Erkannte Statusworte:

```text
reject
deny
cancel
terminated
```

### LATE_GRANTED

Eine SSEM mit `granted` wurde gefunden, kam aber spaeter als die erwartete
Antwortfrist. Das ist fachlich wichtig, weil ein spaetes Granted operativ trotzdem
wirkungslos sein kann.

### MISSING_MAP_MATCH

Der Request kann nicht vollstaendig auf MAP-Geometrie gemappt werden. Typische
Gruende:

- `inLane` fehlt
- `outLane` fehlt
- Lane-ID passt nicht zur MAP-Lane
- Connection `inLane -> outLane` ist in MAP nicht vorhanden

### ETA_CONFLICT

Die vorhergesagte ETA weicht um mehr als 2 Sekunden von der verifizierten
Stopline-Ankunft ab.

Die Ankunft wird bevorzugt gegen die MAP-Stopline der Inbound-Lane verifiziert.
Falls keine Stopline vorhanden ist, wird auf den MAP-RefPoint zurueckgefallen.

### STOPLINE_WITHOUT_GRANTED

Das Fahrzeug erreicht die Stopline, bevor ein `granted` vorliegt. Das ist ein
starker operativer Fehlerindikator.

## Kartenanzeige

Die Karte zeigt keine SREM/SSEM-Punktmarker mehr. Stattdessen werden Requests als
Routen auf Lanes oder Connections dargestellt.

Darstellung:

```text
pending      blau
acknowledged gelb
granted      gruen
rejected     rot
dominant     breit, hohe Deckkraft
sekundaer    duenn, transparent, gestrichelt
timeout      nicht auf der Karte, nur Fehlerpanel
```

MAP/SPAT-Punktlayer sind nicht standardmaessig aktiv. Lanes, Connections,
Stoplines und aktive Requests bleiben sichtbar.

## Connection-Mouseover

MAP-Connections zeigen beim Mouseover den zugeordneten aktiven SPAT-MovementState.

Beispiel:

```text
Connection
Lane 1 -> Lane 3
Signal Group: 5
MovementState: stop-And-Remain
likelyTime: 42
timeConfidence: high
```

Wenn kein SPAT-Match vorhanden ist:

```text
MovementState: nicht verfuegbar
```

## Fehlerpanel

Das Panel `Priorisierungsfehler` sitzt am Kartenrand. Es zeigt die aktuellen
Issues fuer den Playback-Zeitpunkt.

Filter:

```text
Alle
Nur kritisch
Aktuelle Kreuzung
Kreuzungsauswahl
```

`Nur kritisch` zeigt nur Issues mit Severity `error`. Die Kreuzungsauswahl kann
zusammen mit `Nur kritisch` genutzt werden, um z. B. nur kritische Fehler an
Kreuzung 72 zu betrachten.

Klick auf einen Eintrag:

- fokussiert die Intersection
- hebt die passende Request-Route hervor, falls vorhanden
- waehlt die ETA-Request-Spur
- springt zur passenden SREM/SSEM-Nachricht
- oeffnet die Detailansicht

## Problemstellen-Replay

Die Playback-Leiste enthaelt:

```text
Nur Problemstellen
Fehler zurueck
Naechster Fehler
```

Der Player behaelt die vollstaendige Nachrichtenspur, emittiert im
Problemstellenmodus aber nur Zeitpunkte, an denen erstmals ein fachlicher Issue
auftritt. Dadurch bleiben MAP/SPAT-Kontext und Scene-Snapshot korrekt.

Die Issue-Historie wird zentral als `PrioritizationIssueOccurrence` berechnet.
Dadurch nutzen Export und Replay dieselben Erstauftretenszeitpunkte. Die
Berechnung wird fuer unveraenderte Message-Listen gecacht, damit grosse TXA/RXA-
Merges nicht bei jedem Export oder Replay-Aufbau mehrfach rekonstruiert werden.

## Export

Der Toolbar-Button `Fehler exportieren` schreibt:

```text
prioritization_issues.csv
prioritization_issues_machine.csv
prioritization_issues.json
prioritization_report.json
```

`prioritization_issues.csv` ist fuer die manuelle Analyse in Excel/LibreOffice
gedacht und nutzt deutsche, bedienerlesbare Spaltenueberschriften:

```text
Zeitstempel
Fehlertyp
Schweregrad
Kreuzung
Request-ID
Sequenznummer
Station
Einfahrts-Lane
Ausfahrts-Lane
SSEM-Status
Verzoegerung [s]
Beschreibung
Quelle
Quellrollen
Quelldateien
Merge-Gruppe
Merge-Konfidenz
```

`prioritization_issues_machine.csv` und `prioritization_issues.json` behalten
die stabilen technischen Feldnamen fuer Skripte, Regressionstests und
Weiterverarbeitung:

```text
timestamp
issue_type
severity
intersection_id
request_id
sequence_number
station_id
in_lane
out_lane
status
delay_seconds
message
source_summary
source_roles
source_files
merge_group_id
merge_confidence
```

Die Export-Historie enthaelt pro fachlichem Fehler die erste Auftretenszeit.
Timeouts werden daher nicht bei jedem spaeteren Playback-Zeitpunkt erneut
dupliziert.

Der Report `prioritization_report.json` enthaelt eine kompakte Zusammenfassung:

```text
total_issues
issues_by_type
issues_by_severity
issues_by_intersection
source_roles
mean_late_grant_delay_seconds
```

Damit laesst sich eine Sitzung schnell bewerten, ohne zuerst die Detailzeilen zu
filtern.

## Bekannte Grenzen

- `MISSING_MAP_MATCH` ist aktuell noch grob und unterscheidet nicht alle
  Detailursachen.
- Provenance ist nur so gut wie die Parser-/Merge-Metadaten der zugrunde
  liegenden Nachrichten.
- Das Fehlerpanel zeigt weiterhin den aktuellen Playback-Zeitpunkt; die
  vollstaendige Historie liegt im Export.

## Naechste sinnvolle Erweiterungen

- Detaildiagnose fuer MAP-Matches: fehlende `inLane`, fehlende `outLane`, fehlende
  Connection, fehlende SignalGroup.
- Quality Score pro Request: `OK`, `WARN`, `ERROR`.
- Multi-Intersection-Dashboard mit Requests, Granted, Timeout, ETA-MAE pro
  Kreuzung.
- UI-Umschalter zwischen aktueller Ansicht und kompletter Issue-Historie.
