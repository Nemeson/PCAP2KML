# T1.1 + T1.3a/b — Stutter-Profiling-Bericht

**Datum:** 2026-05-02
**Branch:** feat/t1.3-stutter-fix
**Methode:** Pure-CPU-Profil von `_compute_render_payload` ueber simulierte Tick-Schleife
(Tick-Intervall 50 ms = `TICK_INTERVAL_MS` aus `player_controller.py`).
WebEngine/JS-Bridge nicht gemessen.

> **Hinweis:** Der Profiler ueberschreibt diese Datei beim Lauf mit einer Kurz-Tabelle.
> Diese analytische Fassung ist Ende-Stand; bei erneutem Lauf wieder einspielen.

---

## TL;DR

T1.3a (Bisect-Index-Cut + Reorder + Index-Cache) liefert massive Verbesserung:

| PCAP | Metrik | Vorher (kein Window) | Nachher (Fix, Window 120 s) | Verbesserung |
|------|--------|----------------------|------------------------------|--------------|
| rxa_22082025 | p50 | 101.94 ms | **22.39 ms** | **-78 %** |
| rxa_22082025 | p95 | 237.95 ms | **43.16 ms** | **-82 %** |
| rxa_22082025 | max | 735.60 ms | **60.20 ms** | **-92 %** |
| txa_22082025 | p50 | 220.68 ms | **168.35 ms** | -24 % |
| txa_22082025 | p95 | 780.00 ms | **243.02 ms** | -69 % |
| txa_22082025 | max | 1769.65 ms | **363.36 ms** | -79 % |

Frametime-Gate v1.8 (p95 < 18 ms) auf rxa noch nicht erreicht (43 ms),
auf txa weiter deutlich daneben (243 ms). T1.3c (Display-Anchor-Cache) ist
naechster Hebel.

---

## Methodische Anmerkung

Erstlauf zeigte den **Worst-Case ohne `window_start_timestamp`** (Profiler-Default).
Production setzt das Window aktiv (Default 120 s in `PERFORMANCE_PLAYBACK_WINDOW_SECONDS[NORMAL]`).
Der Vergleich oben ist daher: **alter Code ohne Window** vs. **neuer Code mit Window 120 s**.

Das ist der relevante Vergleich, weil:
- Der **alte Code** im Production-Pfad (mit Window) hat den Window-Filter zwar drin, aber nur als
  `continue` mitten in der Schleife — der O(N)-Vollscan-Overhead bleibt
- Der **neue Code** cuttet den Praefix per `bisect_left` komplett heraus

Realistische User-Wahrnehmung folgt mit T1.2 (Live-App-Messung).

---

## Was T1.3a tut

### Vorher
```python
for index, msg in enumerate(messages):
    if index >= end_index: break
    msg_timestamp = msg.timestamp.timestamp()
    if not _has_display_position(msg) or not _is_near_display_anchors(msg, display_anchors):
        continue
    if window_start_timestamp is not None and msg_timestamp < window_start_timestamp \
       and msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS:
        continue
    ...
```

Probleme:
1. Vollscan ab Index 0 (kein Cut)
2. Geometrie-Filter VOR Window-Filter — `_is_near_display_anchors` laeuft auch fuer Pre-Window-Msgs
3. `msg.timestamp.timestamp()` datetime->float pro Message

### Nachher
```python
timestamps, infra_indices = _message_index(messages)   # gecacht per id(messages)
window_start_index = bisect.bisect_left(timestamps, window_start_timestamp, hi=end_index)

for index in range(window_start_index, end_index):
    _process(index)             # Window-bound Messages
if window_start_index > 0:
    for index in infra_indices: # Infrastructure: window-exempt
        if index >= window_start_index: break
        _process(index)
```

Effekte:
- bisect_left → O(log N) Praefix-Skip statt O(N)
- Index-Cache → Timestamps + Infrastructure-Indizes einmal pro Session, nicht pro Tick
- Pre-Window-Messages umgehen Geometrie-Filter komplett
- Verhalten unveraendert: Infrastructure-Messages weiterhin window-exempt
- 22 bestehende Render-Payload-Tests bleiben gruen

---

## Was noch fehlt fuer Frametime-Gate

### T1.3c — `_display_anchor_points` Cache (HIGH, naechster Schritt)
- Wird pro Tick neu berechnet, scant `messages[:max_index]` komplett
- Cache nach `(id(messages), max_index)` persistieren
- Erwarteter Effekt: weiterer ~50 % Reduktion auf rxa, deutlich mehr auf txa

### T1.3d — Inkrementelles Marker-Update (MID-HIGH)
- Statt Full-Repaint pro Tick nur Delta zur vorherigen Render
- JS-API: `updateMarkers(deltaPayload)` neben `applyRenderPayload(full)`
- Erwarteter Effekt: typ. 1–10 Stationen-Updates pro Tick statt N

### T1.2 — JS-Bridge-Latenz (vor T1.3d)
- WebEngine-basierte Messung von `runJavaScript`-Roundtrip
- Entscheidet, ob T1.3d noetig ist oder T1.3c reicht

---

## Rohdaten

| Datei | Beschreibung |
|-------|--------------|
| [SREM_with_OCIT_normal.csv](SREM_with_OCIT_normal.csv) | 41 msgs, Worst-Case ohne Window |
| [rxa_22082025_normal.csv](rxa_22082025_normal.csv) | 1974 msgs, vor Fix, ohne Window |
| [rxa_22082025_normal_w120s.csv](rxa_22082025_normal_w120s.csv) | 1974 msgs, nach Fix, Window 120 s |
| [txa_22082025_normal.csv](txa_22082025_normal.csv) | 4932 msgs, vor Fix, ohne Window |
| [txa_22082025_normal_w120s.csv](txa_22082025_normal_w120s.csv) | 4932 msgs, nach Fix, Window 120 s |

Reproduktion:
```
python -m scripts.profiling.profile_replay --window 120 --all
```
