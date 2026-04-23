# ETA-Analyse

Stand: 2026-04-22

Die ETA-Analyse ist request-zentriert. Sie ist nicht mehr nur eine einfache
Zeitreihe pro Station, sondern eine Diagnoseansicht fuer eine konkrete
Priorisierungsanforderung.

Die Ansicht besteht jetzt aus drei Ebenen:

- Graph fuer ETA, Geschwindigkeit, SREM, SSEM und Diagnosemarker
- Kennzahlentabelle fuer die aktuell ausgewaehlte Request-/Merge-Spur
- Ereignistabelle fuer SREM-, SSEM- und Diagnoseereignisse in Zeitreihenfolge

## Auswahl

Die Auswahl erfolgt ueber:

```text
Intersection-ID
Request-ID
Sequence Number
Station-ID
Merge-Gruppe, falls vorhanden
```

Label-Beispiel:

```text
I72 R6/S86 | 2228620000 | Merge merge-12
```

## Zeitachse

Die Zeitachse startet relativ zur ersten passenden SREM:

```text
t = 0.0 s -> erste SREM der gewaehlten Request-Spur
```

Das macht Requests vergleichbar, auch wenn mehrere PCAPs oder Kreuzungen geladen
werden.

## Dargestellte Reihen

- Blaue Kurve: Restzeit bis Stopline
- Gruene Kurve: geglaettete Geschwindigkeit
- Vertikale blaue Linien: SREM-Updates
- Farbiges Band: SSEM-Status
- Diagnosemarker: ETA-Spruenge, fehlendes SSEM, spaetes Granted, ETA-Konflikte

## Dashboard-Kennzahlen

Die Kennzahlentabelle zeigt zur aktuellen Auswahl:

- Auswahl/Request-Spur
- Station
- Anzahl SREM-Samples
- Anzahl SSEM-Updates
- Anzahl ETA-Samples
- Anzahl verifizierter ETA-Werte
- maximale ETA-Abweichung
- mittlere Geschwindigkeit
- letzter SSEM-Status
- Anzahl Diagnosehinweise

Damit ist auch ohne Interpretation der Kurven sofort sichtbar, ob eine
Priorisierung sauber beantwortet wurde, ob die ETA verifizierbar war und ob ein
kritischer Status dominiert.

## Ereignistabelle

Die Ereignistabelle listet chronologisch:

- SREM-Updates mit Request-ID, Sequence Number und ETA-Restzeit
- SSEM-Updates mit Status/Inhalt, z. B. `processing`, `granted`, `rejected`
- Diagnoseereignisse wie ETA-Sprung, fehlende SSEM-Antwort oder Stopline ohne
  Granted

Die Tabelle ergaenzt den Graphen fuer kleine Bildschirme und fuer Faelle, in
denen viele Ereignisse im Graphen dicht nebeneinander liegen.

Klickverhalten:

- Klick auf ein SREM- oder SSEM-Ereignis springt zur passenden Nachricht in der
  Wiedergabe, markiert die Nachrichtentabelle und oeffnet die Detailansicht.
- Klick auf ein Diagnoseereignis fokussiert die zugehoerige Request-Geometrie
  auf der Karte und hebt die Request-Spur hervor.
- Wenn eine konkrete Nachricht nicht gefunden wird, bleibt die Request-Fokussierung
  trotzdem aktiv und die Statusleiste zeigt einen Hinweis.

## Dashboard-Export

Der Button `ETA exportieren` schreibt die aktuelle Dashboard-Auswahl in ein
gewaehltes Verzeichnis:

- `eta_dashboard.csv`
- `eta_dashboard.json`

Die CSV ist fuer schnelle manuelle Pruefung gedacht und nutzt Semikolon als
Trennzeichen. Die JSON-Datei enthaelt dieselben Kennzahlen und Ereignisse mit
technischen Feldern wie ISO-Zeitstempel, Nachrichtentyp und Selection-Key.

## Geschwindigkeit

Die Geschwindigkeit wird als kleiner gleitender Mittelwert dargestellt. Das ist
absichtlich geglaettet, weil einzelne PCAP-/GNSS-Jitter sonst den fachlichen
Trend ueberdecken.

## Stopline-Verifikation

Die ETA-Verifikation nutzt bevorzugt:

```text
MAP Stopline der inLane
```

Fallback:

```text
MAP RefPoint
```

Eine ETA gilt aktuell als genau, wenn die Abweichung hoechstens 2 Sekunden
betraegt.

## SREM/SSEM-Darstellung

SREM:

```text
vertikale Eventlinie mit Request-ID, Sequence und ETA-Restzeit
```

SSEM:

```text
Statusband, z. B. processing -> granted
```

Dadurch ist sichtbar, ob die Antwort der Infrastruktur rechtzeitig vor der
Stopline-Passage kam.

## Diagnosehinweise

Die ETA-Ansicht nutzt dieselben fachlichen Annahmen wie die Priorisierungsanalyse.
Sie hebt unter anderem hervor:

- ETA springt stark
- ETA steigt trotz Annaeherung
- SREM ohne SSEM
- kein `granted`
- spaetes `granted`
- Stopline-Passage ohne `granted`
- ETA-Abweichung groesser Toleranz
