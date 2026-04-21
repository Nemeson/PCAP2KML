# TXA/RXA-PCAP-Merge

Stand: 2026-04-21

Der PCAP-Merge fuehrt Beobachtungen aus mehreren Capture-Dateien zusammen, ohne
die Rohbeobachtungen zu verlieren.

## Ziel

TXA- und RXA-Dateien koennen gleichzeitig geladen werden. Nachrichten werden
anhand von Zeit, Position, Nachrichtentyp und fachlichen Identitaetsfeldern soft
gemergt.

## Rollen

Die Rolle einer Capture-Datei wird konservativ aus dem Dateinamen abgeleitet:

```text
txa, _tx, -tx, transmit, send -> TXA
rxa, _rx, -rx, receive        -> RXA
sonst                         -> UNKNOWN
```

## Provenance

Jede Nachricht kann eine `MessageSource` tragen:

```text
filename
source_index
role
parser_backend
packet_index
```

Zusammengefuehrte Gruppen erhalten:

```text
merge_group_id
merge_confidence
merge_reason
```

## Kanonische Sicht

Die UI kann zwischen allen Beobachtungen und einer kanonischen Sicht wechseln.
Die kanonische Sicht zeigt pro Merge-Gruppe nur eine repraesentative Nachricht.

## Bedeutung fuer SREM/SSEM

Die Priorisierungsanalyse arbeitet fachlich auf:

```text
intersection_id
request_id
sequence_number
station_id
```

Die Merge-Gruppe bleibt fuer UI-Auswahl und Export-Provenance erhalten, damit
ersichtlich bleibt, ob die Beobachtung aus TXA, RXA oder beiden Quellen stammt.

Der Priorisierungsfehler-Export schreibt dafuer in der bedienerlesbaren CSV
deutsche Spaltenueberschriften und in `prioritization_issues_machine.csv` sowie
`prioritization_issues.json` die stabilen technischen Felder:

```text
source_summary
source_roles
source_files
merge_group_id
merge_confidence
```

Der zusaetzliche Report aggregiert die Issue-Anzahl nach Source-Rolle, sodass
schnell erkennbar ist, ob ein Problem vor allem in TXA, RXA oder gemergten
Beobachtungen sichtbar wird.

## Bekannte Grenzen

- Provenance ist nur vollstaendig, wenn Parser und Merge-Modell die
  zugrundeliegenden Nachrichten mit `MessageSource` annotieren konnten.
- Bei sehr grossen Multi-Intersection-PCAPs sollte die Issue-Historie spaeter
  noch feingranularer inkrementell statt durch Snapshot-Bildung je Ereignis
  berechnet werden.
