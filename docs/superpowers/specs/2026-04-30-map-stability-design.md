# PCAP2KML Player — Map Stability & Threading Hardening

**Status:** Design approved
**Date:** 2026-04-30
**Branch:** TBD

---

## Problem Statement

The embedded Leaflet map (QWebEngineView) freezes during user interaction (pan/zoom) while playback is active. Root causes:

1. **Aggressive re-rendering**: Every 50ms tick rebuilds full JSON payloads (markers, infrastructure overlays, trajectories) — even when nothing changed.
2. **Main-thread overload**: `_infrastructure_overlays_for_messages()` computes synchronous MAP/SPAT joins and lane geometries on the main thread, competing with JS execution.
3. **Render queue congestion**: `_render_payload_in_flight` flag with simple queueing creates backpressure from rapid tick sequences.
4. **No backpressure**: No throttling, no frame budgets, no detection of whether the last render actually completed.

## Goals

- Map remains responsive during pan/zoom while playback is running
- Main thread stays available for Qt event loop processing
- Render pipeline can recover from stalls without user intervention
- Test coverage for critical render paths increases to 85%+

## Non-Goals

- Native GPU rendering acceleration for QtWebEngine (out of scope)
- Leaflet/MapLibre migration (separate roadmap item)
- Full async rendering architecture rewrite (incremental improvement)

---

## Design

### Phase 1: Quick Wins

#### 1.1 Playback Render Throttling

`PlayerController._on_tick` ticks at 50ms but `MapWidget` receives renders at minimum 150ms intervals.

- Add `_last_render_time` float to `MapWidget`
- Before executing `render_playback_slice`, check if 150ms elapsed since last render
- If too soon, skip the render entirely — markers remain at last rendered position
- Exception: final tick of playback always renders

#### 1.2 Marker-Only Updates During Playback

Infrastructure overlays (MAP, SPAT, connections, stoplines, requests) are static within a playback slice — they only depend on the latest message index, not intermediate ticks.

- New method `render_playback_markers_only()` updates only:
  - Dynamic station markers (position, popup)
  - Current marker highlight
  - Follow-marker pan
- Infrastructure overlays are NOT recomputed during playback ticks
- Trajectories update every 5th render only

#### 1.3 User Interaction Pause

Leaflet emits `movestart` and `moveend` events. During user interaction, playback renders are paused.

- `MapBridge` gets `onMapInteractionStart()` / `onMapInteractionEnd()` slots
- JS calls these via `map.on('movestart')` / `map.on('moveend')` and `zoomstart` / `zoomend`
- `MapWidget._user_interacting` flag: when True, all `render_playback_slice` calls are skipped
- On `moveend`, a single catch-up render executes

#### 1.4 Render Stall Guard

`_render_payload_in_flight` with a 5-second stall limit.

- Timer `_stall_timer` already exists (8s). Reduce to 5s.
- On stall: reset `_render_payload_in_flight`, drain one queued payload, emit warning
- After 3 stall events within 60s → trigger map page reload

### Phase 2: Systematic Hardening

#### 2.1 Payload Computation in Background Thread

New `RenderPayloadWorker(QThread)` computes render data off the main thread.

```
RenderPayloadWorker
├── input: list[V2xMessage], max_index, render_mode, performance_mode
├── compute: _render_messages() data preparation logic
├── output: pre-computed dict ready for json.dumps()
└── signal: payload_ready(dict)
```

`MapWidget` receives pre-computed payload via signal and only calls `page().runJavaScript("applyRenderPayload(...)")`.

- `_infrastructure_overlays_for_messages()` runs in worker thread
- `build_scene_snapshot()` runs in worker thread
- Only JS execution stays on main thread

Thread safety requirements:
- Worker must not access any Qt widgets
- Input data (`V2xMessage` list) is read-only — shared safely
- `_station_color_map` is synchronized via mutex or pre-computed

#### 2.2 Auto-Recovery

- Bootstrap timeout (existing, 6s): triggers map page reload after 3 failures
- Render process termination (existing): reloads map page, now preserves render state for re-application
- New: after reload, if session is loaded, auto-re-render current playback state

#### 2.3 Thread-Safety Audit

- All cross-thread signal connections use `Qt.ConnectionType.QueuedConnection`
- `sip.isdeleted()` guard before every `runJavaScript()` call — done via `_execute_js`
- `QTimer` lifecycle tied to `dispose()`: timers are `deleteLater()`-ed and set to None
- `_cancel_check_fn` in `ParsingWorker` uses closure replacement (already atomic)

#### 2.4 Test Coverage

| Test File | New Tests | Focus |
|-----------|-----------|-------|
| `test_map_widget.py` | +8 | Render throttling, interaction pause, queue coalescing, stall recovery, marker-only update |
| `test_player_controller.py` | +4 | Tick behavior with throttling, focus replay with skipped renders |
| `test_parsing_worker.py` | +3 | Thread safety at cancel(), double-cancel, edge cases |
| `test_map_backend.py` | +2 | Render budget trimming, payload bounds edge cases |

Coverage target: 80.2% → **85%+**

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Render throttling causes visible lag | Low | Low | 150ms is well below human perception threshold for map updates |
| Worker thread crashes on edge-case data | Medium | Low | Guard with try/except in worker; main thread catches via signal |
| Interaction pause causes stale view | Low | Low | Catch-up render on `moveend` ensures final state is correct |
| Background thread increases memory | Low | Low | Worker runs sequentially (one payload at a time); no duplication |
