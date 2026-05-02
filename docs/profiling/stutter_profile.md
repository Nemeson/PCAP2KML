# T1.1 — Stutter-Profiling-Bericht

**Datum:** 2026-05-02
**Branch:** release/1.7.0
**Methode:** Pure-CPU-Profil von `_compute_render_payload` ueber simulierte Tick-Schleife
(Tick-Intervall 50 ms = `TICK_INTERVAL_MS` aus `player_controller.py`).
WebEngine/JS-Bridge nicht gemessen — Folgemessung in Live-App noetig (T1.2).

---

## TL;DR

**Bestaetigt:** Replay-Stutter ist primaer eine Folge von **O(N)-Vollscan in `_compute_render_payload`**
(`map_widget.py:1776`). Die Funktion iteriert bei jedem Tick **alle Messages** von Index 0 bis
`max_index+1`. Wachstumsfaktor erste 10 % → letzte 10 % auf rxa: **27×**. Bei dichteren PCAPs
addiert sich Marker-/Trail-Aufbau und JSON-Serialisierung. Tick-Budget 50 ms wird auf praktisch
allen realistischen PCAPs **um Faktor 4–35 ueberschritten**.

| PCAP | Msgs | Dauer s | p50 ms | p95 ms | p99 ms | max ms | first10% | last10% | Wachstum | Verhaeltnis zu 50-ms-Budget |
|------|------|---------|--------|--------|--------|--------|----------|---------|----------|------------------------------|
| SREM with OCIT.pcap | 41 | 30.8 | 0.22 | 0.55 | 0.85 | 1.18 | 0.05 | 0.45 | 9× | unkritisch |
| rxa_22082025.pcap | 1974 | 493.3 | **101.9** | **238.0** | 304.0 | 735.6 | 7.8 | 210.8 | **27×** | p50 ≈ 2× Budget, p95 ≈ 4.8× |
| txa_22082025.pcap | 4932 | 493.3 | **220.7** | **780.0** | 970.0 | 1769.6 | 66.6 | 223.5 | 3.4× | p50 ≈ 4.4× Budget, p95 ≈ **15.6×** |

Frametime-Gate v1.8: **p95 < 18 ms** — derzeit auf realistischen PCAPs verfehlt um Faktor 13–43.

---

## Detailbefund

### 1. O(N)-Vollscan pro Tick (Hauptursache)

`_compute_render_payload` (Z. 1776 ff.):
```python
for index, msg in enumerate(messages):
    if index >= end_index:
        break
    if not _has_display_position(msg) or not _is_near_display_anchors(msg, display_anchors):
        continue
    if (window_start_timestamp is not None
        and msg_timestamp < window_start_timestamp
        and msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS):
        continue
    ...
```

- Schleife laeuft **ab Index 0**, nicht ab Trail-Window-Start
- `window_start_timestamp`-Filter wirkt **innerhalb** der Schleife → ueberspringt nur, scant aber
- `_display_anchor_points(messages, max_index=...)` wird ebenfalls pro Tick neu berechnet

Konsequenz: bei rxa wachsen die letzten 10 % der Ticks auf 211 ms an (von 7.8 ms zu Beginn).
Wachstum ist linear in `end_index`. Auf 1-GB-PCAPs (Roadmap-Ziel) waere das untragbar.

### 2. Marker-/Trail-Dichte addiert konstanten Overhead

txa hat 2.5× so viele Messages wie rxa, aber gleiche Dauer → mehr Stationen pro Frame.
- **first10% mean txa = 67 ms** vs. **rxa = 7.8 ms** → 8.5× Startaufwand
- Wachstum nur 3.4× weil Plateau frueh erreicht
- Indikator: JSON-Serialisierung der grossen Payload dominiert mit ueber Marker-/Trail-Aufbau

p95 payload bleibt klein (rxa 20.5 KB, txa 18.7 KB), Hauptkosten liegen also **vor** der
Serialisierung — beim Aufbau des Marker-Dicts und der Trail-Listen.

### 3. RenderPayloadWorker schuetzt UI, lindert Stutter aber nur teilweise

Der seit `d59aa55` aktive `RenderPayloadWorker` laeuft off-thread, daher kein UI-Freeze.
Jedoch:
- `payload_ready` triggert `applyRenderPayload(...)` als `runJavaScript`-Call
- Bei Tick-Rate 50 ms und Payload-Compute > 200 ms backloggt sich die Worker-Queue
- Catch-up-Flush (`07bf0dd`) versucht das aufzuholen → sichtbarer Stutter beim Wiederanlauf

Die JS-Bridge-Latenz selbst wurde in T1.1 nicht direkt gemessen (kein WebEngine im Profiler).
Folge-Messung in Live-App: T1.2.

---

## Fix-Plan (T1.3-Tickets)

### T1.3a — Index-Cut basierend auf `window_start_timestamp` (HIGH)
- `bisect_left` ueber sortierte `messages[i].timestamp` finden Start-Index
- Schleife `for index in range(start_index, end_index)` statt 0-bis-end
- **Erwarteter Effekt:** O(N) → O(W) wobei W = Trail-Window-Groesse (sekunden-, nicht
  capture-langengebunden). Wachstumsfaktor 27× sollte auf < 2× sinken.

### T1.3b — Trail-Window-Begrenzung in Default-Render (HIGH)
- Default 30 s Trail (statt unbegrenzt seit Capture-Start)
- Konfigurierbar in Performance-Settings
- **Erwarteter Effekt:** rxa first10% ≈ last10% (kein Wachstum).

### T1.3c — Display-Anchor-Cache (MID)
- `_display_anchor_points` Ergebnis bei stabilem `max_index` cachen
- Invalidierung nur bei Filter-Change oder Seek
- **Erwarteter Effekt:** ein redundanter Vollscan pro Tick eliminiert (~ Halbierung CPU).

### T1.3d — Inkrementelles Marker-Update statt Vollaufbau (MID-HIGH)
- Statt jedes Tick komplettes Payload: nur Delta seit letztem Render
- JS-API erweitert: `updateMarkers(deltaPayload)` neben `applyRenderPayload(full)`
- Full-Render nur bei Seek/Filter-Change
- **Erwarteter Effekt:** typ. Tick haelt nur 1–10 Stationen-Updates statt N.

### T1.3e — JSON-Serialisierung mit orjson (LOW, evtl. unnoetig nach a/b)
- `orjson.dumps` statt `json.dumps` (ca. 3–5×)
- Nur sinnvoll wenn nach a–d die Serialisierung noch sichtbar ist

### T1.2 — JS-Bridge-Latenz-Messung (separat)
- WebEngine-basierter Lauf mit Telemetrie-Hook auf `runJavaScript`-Roundtrip
- Bestaetigt oder widerlegt JS-Seite als sekundaeren Bottleneck
- Vor T1.3d wichtig (entscheidet ob inkrementelles Update wirklich noetig)

---

## Akzeptanz fuer Epic 1 (Wiederholung)

Nach Fix-Implementation Profiler erneut laufen lassen. Ziel:
- p95 < 18 ms auf rxa und txa
- Wachstumsfaktor first10% → last10% < 1.5×
- Visuell kein Stutter wahrnehmbar in Live-App

---

## Rohdaten

- [SREM with OCIT.pcap](SREM_with_OCIT_normal.csv) — 616 Ticks
- [rxa_22082025.pcap](rxa_22082025_normal.csv) — 9866 Ticks
- [txa_22082025.pcap](txa_22082025_normal.csv) — 9867 Ticks

Reproduktion:
```
python -m scripts.profiling.profile_replay --all
```

---

## Offen

- **rxa 1.pcap** (5.9 MB) und **txa 3.pcap** (12 MB) noch nicht profiliert — folgt im naechsten
  Lauf, sind aber nach den Trends bereits eindeutig: erwartet > Faktor 30× Budget.
- **2024-04-24_LB72_RSU_PCAP** — Verzeichnis mit Captures, separater Lauf.
- T1.2 (JS-Bridge-Latenz) — eigenes Ticket, vor T1.3d notwendig.
