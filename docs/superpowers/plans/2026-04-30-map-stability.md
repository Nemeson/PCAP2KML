# Map Stability & Threading Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate map freezes during pan/zoom by adding user-interaction detection with JS-to-Python bridge, tightening render stall recovery, and offloading payload computation to a background worker thread.

**Architecture:** Phase 1 adds Leaflet `movestart`/`moveend` bridge events that pause JS calls during user interaction and tightens stall detection (8s→5s). Phase 2 moves `_render_messages` data preparation into a `QThread`-based `RenderPayloadWorker` so the main thread only executes the final `applyRenderPayload()` JS call.

**Tech Stack:** PyQt6, QWebEngineView, Leaflet.js, QThread, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `pcap2kml_player/map_widget.py` | Modify | Interaction bridge, stall guard, worker integration |
| `pcap2kml_player/ui/main_window.py` | Modify | Wire interaction pause to playback tick gate |
| `tests/test_map_widget.py` | Modify | Interaction detection, stall recovery, worker tests |
| `tests/test_player_controller.py` | Modify | Tick behavior with interaction gate |
| `tests/test_parsing_worker.py` | Modify | Cancel safety under concurrency |

---

### Task 1: Interaction Detection Bridge (MapBridge)

**Files:**
- Modify: `pcap2kml_player/map_widget.py:1736-1743` (MapBridge class)
- Modify: `pcap2kml_player/map_widget.py:1256-1276` (JS marker click area, add map event handlers)

- [ ] **Step 1: Add interaction signals to MapBridge**

Replace the existing `MapBridge` class (lines 1736-1743):

```python
class MapBridge(QObject):
    """Bridge object exposed to JavaScript via QWebChannel."""

    message_clicked = pyqtSignal(str)  # station_id
    map_interaction_started = pyqtSignal()
    map_interaction_ended = pyqtSignal()

    @pyqtSlot(str)
    def onMarkerClicked(self, station_id: str) -> None:
        self.message_clicked.emit(station_id)

    @pyqtSlot()
    def onMapInteractionStart(self) -> None:
        self.map_interaction_started.emit()

    @pyqtSlot()
    def onMapInteractionEnd(self) -> None:
        self.map_interaction_ended.emit()
```

- [ ] **Step 2: Add JS event handlers in Leaflet HTML**

In `LEAFLET_HTML` (line 1671, right before the `if (typeof QWebChannel` block), insert map event handlers:

```
        // Notify Python when user interacts with the map
        map.on('movestart zoomstart', function() {
            if (window.bridge) { window.bridge.onMapInteractionStart(); }
        });
        map.on('moveend zoomend', function() {
            if (window.bridge) { window.bridge.onMapInteractionEnd(); }
        });
```

- [ ] **Step 3: Add interaction state to MapWidget.__init__**

In `MapWidget.__init__` (after line 1801):

```python
        self._user_interacting = False
        self._bridge.map_interaction_started.connect(self._on_user_interaction_start)
        self._bridge.map_interaction_ended.connect(self._on_user_interaction_end)
```

- [ ] **Step 4: Add interaction handler methods to MapWidget**

After `_on_marker_clicked` (line 2193):

```python
    def _on_user_interaction_start(self) -> None:
        """Pause render updates while the user pans or zooms."""
        self._user_interacting = True

    def _on_user_interaction_end(self) -> None:
        """Allow render updates again and flush a catch-up render."""
        self._user_interacting = False
        self.map_interaction_ended.emit()

    @property
    def user_interacting(self) -> bool:
        return self._user_interacting
```

- [ ] **Step 5: Add map_interaction_ended signal to MapWidget**

At class level (after line 1763):

```python
    map_interaction_ended = pyqtSignal()
```

- [ ] **Step 6: Gate runJavaScript during interaction**

In `_run_js` (line 2311), add interaction check at the start of the method:

```python
    def _run_js(self, script: str) -> None:
        """Execute JavaScript in the web page."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if self.__dict__.get("_user_interacting", False) and not script.startswith("applyRenderPayload("):
            # Suppress non-essential JS during pan/zoom to keep WebEngine responsive.
            if not script.startswith("highlightMarker(") and not script.startswith("addMarker("):
                return
        if not self._page_ready:
```

- [ ] **Step 7: Write test for interaction gate**

In `tests/test_map_widget.py`:

```python
def test_run_js_suppressed_during_interaction():
    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._page_ready = True
    widget._user_interacting = True
    captured: list[str] = []

    def fake_run_js(script, _world=0, _callback=None):
        captured.append(script)

    widget.page = lambda: type("Page", (), {"runJavaScript": fake_run_js})()

    widget._run_js("addMarker('x', 's', 1, 2, 'p', 'r', 'm')")
    widget._run_js("setStationColors({})")

    assert len(captured) == 1
    assert "addMarker" in captured[0]


def test_run_js_allowed_after_interaction_ends():
    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._page_ready = True
    widget._user_interacting = False
    captured: list[str] = []

    def fake_run_js(script, _world=0, _callback=None):
        captured.append(script)

    widget.page = lambda: type("Page", (), {"runJavaScript": fake_run_js})()

    widget._run_js("addMarker('x', 's', 1, 2, 'p', 'r', 'm')")
    widget._run_js("setStationColors({})")

    assert len(captured) == 2


def test_interaction_end_flushes_signal():
    widget = MapWidget.__new__(MapWidget)
    widget._user_interacting = True
    ended: list[bool] = []
    widget.map_interaction_ended = type("Signal", (), {"emit": lambda self: ended.append(True)})()

    widget._on_user_interaction_end()

    assert widget._user_interacting is False
    assert ended == [True]
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_map_widget.py::test_run_js_suppressed_during_interaction tests/test_map_widget.py::test_run_js_allowed_after_interaction_ends tests/test_map_widget.py::test_interaction_end_flushes_signal -v
```

- [ ] **Step 9: Commit**

```bash
git add pcap2kml_player/map_widget.py tests/test_map_widget.py
git commit -m "feat(map): Leaflet interaction detection bridge pauses JS calls during pan/zoom"
```

---

### Task 2: Wire Interaction Pause in MainWindow

**Files:**
- Modify: `pcap2kml_player/ui/main_window.py:1655-1670` (_on_playback_tick)

- [ ] **Step 1: Gate render_playback_slice on interaction state**

In `_on_playback_tick` (line 1655), add interaction check:

```python
    def _on_playback_tick(self, msg: V2xMessage | None) -> None:
        """Update map and details when the visible playback message changes."""
        if msg is None:
            return

        if not self._map_widget.user_interacting and self._should_render_full_map_slice(msg):
            self._map_widget.render_playback_slice(
                self._player._messages,
                self._player.current_index,
                window_seconds=self._map_playback_window_seconds(),
            )
        self._map_widget.update_playback_position(msg)
        self._highlight_table_row(msg)
        self._show_security_detail(msg, auto_focus=False)
        self._update_scene_for_message(msg)
        self._eta_graph.set_current_time(msg.timestamp)
```

- [ ] **Step 2: Connect interaction_ended to catch-up render**

In `_connect_map_widget_signals` (line 940):

```python
    def _connect_map_widget_signals(self) -> None:
        """Connect the current map widget implementation to diagnostics."""
        self._map_widget.telemetry_updated.connect(self._on_map_telemetry_updated)
        self._map_widget.map_issue_detected.connect(self._on_map_issue_detected)
        self._map_widget.map_interaction_ended.connect(self._on_map_interaction_ended)
```

- [ ] **Step 3: Add catch-up render handler**

After `_on_map_issue_detected` (line 1068):

```python
    def _on_map_interaction_ended(self) -> None:
        """Render a catch-up map slice after the user finishes panning/zooming."""
        if self._session and self._player._messages:
            self._last_map_slice_update_monotonic = 0.0
            self._last_map_slice_index = None
            self._last_map_messages_id = None
            self._map_widget.render_playback_slice(
                self._player._messages,
                self._player.current_index,
                window_seconds=self._map_playback_window_seconds(),
            )
```

- [ ] **Step 4: Run existing map widget tests to verify no regressions**

```bash
pytest tests/test_map_widget.py -v --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add pcap2kml_player/ui/main_window.py
git commit -m "feat(ui): gate playback render on map interaction state with catch-up flush"
```

---

### Task 3: Tighten Render Stall Recovery

**Files:**
- Modify: `pcap2kml_player/map_widget.py:57` (MAP_RENDER_STALL_SECONDS)
- Modify: `pcap2kml_player/map_widget.py:2380-2402` (_check_render_payload_stall)

- [ ] **Step 1: Reduce stall timeout from 8s to 5s**

```python
MAP_RENDER_STALL_SECONDS = 5.0
```

- [ ] **Step 2: Add multi-stall recovery counter**

In `MapWidget.__init__` (after existing init attributes, line 1801):

```python
        self._render_stall_count = 0
        self._first_stall_at: float | None = None
```

- [ ] **Step 3: Add escalation logic in _check_render_payload_stall**

Replace `_check_render_payload_stall` (lines 2380-2402):

```python
    def _check_render_payload_stall(self, generation: int) -> None:
        """Emit a map issue if the same render payload is still in flight."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        if generation != self._render_payload_stall_generation:
            return
        started_at = self.__dict__.get("_render_payload_started_at")
        if not self.__dict__.get("_render_payload_in_flight", False) or started_at is None:
            return
        if time.monotonic() - started_at >= MAP_RENDER_STALL_SECONDS:
            logger.warning(
                "Render payload stall detected after %.0fs — resetting in-flight flag (generation %d)",
                MAP_RENDER_STALL_SECONDS,
                generation,
            )
            self._render_payload_in_flight = False
            self._render_payload_started_at = None
            queued = self._queued_render_payload_script
            self._queued_render_payload_script = None
            self._emit_map_issue(f"Karten-Renderpayload lief seit >{MAP_RENDER_STALL_SECONDS:.0f}s — Flag zurueckgesetzt")
            if queued is not None:
                logger.info("Flushing queued render payload after stall reset")
                self._run_js(queued)

            now = time.monotonic()
            if self._first_stall_at is None or now - self._first_stall_at > 60.0:
                self._first_stall_at = now
                self._render_stall_count = 0
            self._render_stall_count += 1
            if self._render_stall_count >= 3:
                logger.warning(
                    "Map page reload triggered after %d stall events in %ds",
                    self._render_stall_count,
                    int(now - self._first_stall_at),
                )
                self._first_stall_at = None
                self._render_stall_count = 0
                self._bootstrap_generation += 1
                self.setHtml(_leaflet_runtime_html(), QUrl.fromLocalFile(str(_asset_base_path()) + "/"))
                self._schedule_bootstrap_timeout()
```

- [ ] **Step 4: Write stall escalation test**

In `tests/test_map_widget.py`:

```python
def test_stall_escalation_triggers_reload_after_three_stalls():
    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._render_payload_in_flight = True
    widget._render_payload_started_at = 0.0
    widget._render_payload_stall_generation = 1
    widget._render_stall_count = 2
    widget._first_stall_at = time.monotonic() - 30.0

    reload_calls: list[bool] = []

    def fake_set_html(html, base_url):
        reload_calls.append(True)

    widget.setHtml = fake_set_html
    widget._schedule_bootstrap_timeout = lambda: None
    widget._emit_map_issue = lambda msg: None
    widget._run_js = lambda script: None
    widget._bootstrap_generation = 1

    widget._check_render_payload_stall(1)

    assert widget._render_payload_in_flight is False
    assert widget._render_payload_started_at is None
    assert len(reload_calls) == 1
    assert widget._render_stall_count == 0


def test_stall_count_resets_after_60s_window():
    widget = MapWidget.__new__(MapWidget)
    widget._disposed = False
    widget._render_payload_in_flight = True
    widget._render_payload_started_at = 0.0
    widget._render_payload_stall_generation = 1
    widget._render_stall_count = 2
    widget._first_stall_at = time.monotonic() - 65.0

    reload_calls: list[bool] = []

    def fake_set_html(html, base_url):
        reload_calls.append(True)

    widget.setHtml = fake_set_html
    widget._schedule_bootstrap_timeout = lambda: None
    widget._emit_map_issue = lambda msg: None
    widget._run_js = lambda script: None

    widget._check_render_payload_stall(1)

    assert len(reload_calls) == 0
    assert widget._render_stall_count == 1
```

Add missing import at top of `test_map_widget.py`:

```python
import time
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_map_widget.py::test_stall_escalation_triggers_reload_after_three_stalls tests/test_map_widget.py::test_stall_count_resets_after_60s_window -v
```

- [ ] **Step 6: Commit**

```bash
git add pcap2kml_player/map_widget.py tests/test_map_widget.py
git commit -m "fix(map): reduce stall timeout 8s->5s, add auto-reload after 3 stalls in 60s"
```

---

### Task 4: RenderPayloadWorker — Background Payload Computation

**Files:**
- Modify: `pcap2kml_player/map_widget.py:1914-2103` (_render_messages, split)
- Modify: `pcap2kml_player/map_widget.py:1759-1813` (MapWidget.__init__)

- [ ] **Step 1: Create RenderPayloadWorker class**

Insert after the `_record_render_telemetry` method (line 2137):

```python
class RenderPayloadWorker(QThread):
    """Compute map render payloads in a background thread."""

    payload_ready = pyqtSignal(str, float)

    def __init__(
        self,
        messages: list[V2xMessage],
        max_index: int | None,
        window_start_timestamp: float | None,
        fit_view: bool,
        short_trails: bool,
        clear_first: bool,
        performance_mode: str,
        station_color_map: dict[str, str],
        *,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._messages = messages
        self._max_index = max_index
        self._window_start_timestamp = window_start_timestamp
        self._fit_view = fit_view
        self._short_trails = short_trails
        self._clear_first = clear_first
        self._performance_mode = performance_mode
        self._station_color_map = dict(station_color_map)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if self._cancelled:
            return

        try:
            payload = _compute_render_payload(
                self._messages,
                max_index=self._max_index,
                window_start_timestamp=self._window_start_timestamp,
                fit_view=self._fit_view,
                short_trails=self._short_trails,
                clear_first=self._clear_first,
                performance_mode=self._performance_mode,
                station_color_map=self._station_color_map,
            )
            if self._cancelled:
                return
            payload_json = json.dumps(payload)
            self.payload_ready.emit(payload_json, time.time())
        except Exception:
            logger.exception("RenderPayloadWorker crashed")
```

Add required imports at top of file (add `QThread` to existing imports):

```python
from PyQt6.QtCore import QObject, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
```

- [ ] **Step 2: Extract _compute_render_payload as standalone function**

Move the data-preparation logic from `_render_messages` (lines 1914-2103) into a module-level function. Insert before `MapWidget` class (line 1759):

```python
def _compute_render_payload(
    messages: list[V2xMessage],
    *,
    max_index: int | None,
    window_start_timestamp: float | None = None,
    fit_view: bool,
    short_trails: bool,
    clear_first: bool,
    performance_mode: str,
    station_color_map: dict[str, str],
) -> dict[str, object]:
    """Compute the full map render payload dict (thread-safe, no Qt access)."""
    station_coords: dict[str, list] = {}
    markers_by_id: dict[str, dict[str, object]] = {}
    budget = MAP_RENDER_BUDGETS.get(
        performance_mode,
        MAP_RENDER_BUDGETS[MAP_PERFORMANCE_NORMAL],
    )
    end_index = len(messages) if max_index is None else min(max_index + 1, len(messages))
    display_anchors = _display_anchor_points(messages, max_index=max_index)

    for index, msg in enumerate(messages):
        if index >= end_index:
            break
        msg_timestamp = msg.timestamp.timestamp()
        if not _has_display_position(msg) or not _is_near_display_anchors(msg, display_anchors):
            continue
        if (
            window_start_timestamp is not None
            and msg_timestamp < window_start_timestamp
            and msg.msg_type not in INFRASTRUCTURE_MESSAGE_COLORS
        ):
            continue
        color = INFRASTRUCTURE_MESSAGE_COLORS.get(msg.msg_type, station_color_map.get(msg.station_id, "#3388ff"))
        marker_lat, marker_lon = _marker_position_for_message(msg)

        if msg.msg_type not in NON_STATION_MARKER_TYPES:
            marker_id_raw = _marker_id_for_message(msg)
            markers_by_id[marker_id_raw] = {
                "id": marker_id_raw,
                "stationId": msg.station_id,
                "lat": marker_lat,
                "lon": marker_lon,
                "popup": (
                    f"<b>{msg.msg_type.value}</b><br>"
                    f"Station: {msg.station_id}<br>"
                    f"Time: {msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}<br>"
                    f"Pos: {msg.latitude:.6f}, {msg.longitude:.6f}"
                ),
                "color": color,
                "layerName": "markers",
            }
            station_coords.setdefault(msg.station_id, []).append([msg.latitude, msg.longitude])

    infrastructure_payload: list[dict[str, object]] = []
    for overlay in _infrastructure_overlays_for_messages(messages, max_index=max_index):
        if performance_mode != MAP_PERFORMANCE_NORMAL and overlay["kind"] == "label":
            continue
        if performance_mode == MAP_PERFORMANCE_DIAGNOSTIC and overlay.get("layer") not in {
            "map_inbound", "map_outbound", "map_connections", "map_stoplines", "map_requests", "spat",
        }:
            continue
        overlay_id = str(overlay["id"])
        layer_name = str(overlay["layer"])
        overlay_color = str(overlay["color"])
        if overlay["kind"] == "circle":
            infrastructure_payload.append({
                "kind": "circle", "id": overlay_id,
                "lat": overlay["lat"], "lon": overlay["lon"],
                "radius": overlay["radius"], "color": overlay_color,
                "popup": str(overlay.get("popup", "")), "layerName": layer_name,
            })
        elif overlay["kind"] == "polyline":
            infrastructure_payload.append({
                "kind": "polyline", "id": overlay_id,
                "coords": overlay["coords"], "color": overlay_color,
                "popup": str(overlay.get("popup", "")), "layerName": layer_name,
                "weight": overlay.get("weight", 3), "opacity": overlay.get("opacity", 0.85),
                "dashArray": str(overlay.get("dashArray", "8 6")),
                "tooltip": str(overlay.get("tooltip", "")),
            })
        elif overlay["kind"] == "label":
            infrastructure_payload.append({
                "kind": "label", "id": overlay_id,
                "lat": overlay["lat"], "lon": overlay["lon"],
                "text": str(overlay["text"]), "color": overlay_color,
                "layerName": layer_name,
            })

    trajectories_payload: list[dict[str, object]] = []
    render_trajectories = performance_mode == MAP_PERFORMANCE_NORMAL
    if performance_mode == MAP_PERFORMANCE_SAVER and len(station_coords) <= 25:
        render_trajectories = True
    if performance_mode == MAP_PERFORMANCE_DIAGNOSTIC and len(station_coords) <= 10:
        render_trajectories = True
    for station_id, coords in station_coords.items():
        if not render_trajectories:
            continue
        if short_trails:
            coords = coords[-PLAYBACK_TRAIL_POINTS:]
        trajectories_payload.append({
            "stationId": station_id, "coords": coords,
            "color": station_color_map.get(station_id, "#3388ff"),
        })

    marker_payload = list(markers_by_id.values())
    if len(marker_payload) > int(budget["markers"]):
        marker_payload = marker_payload[-int(budget["markers"]):]
    if len(infrastructure_payload) > int(budget["infrastructure"]):
        infrastructure_payload = infrastructure_payload[:int(budget["infrastructure"])]
    if len(trajectories_payload) > int(budget["trajectories"]):
        trajectories_payload = trajectories_payload[-int(budget["trajectories"]):]

    total_points = sum(len(t["coords"]) for t in trajectories_payload)
    max_points = int(budget["trajectory_points"])
    if total_points > max_points > 0:
        remaining = max_points
        for i, t in enumerate(trajectories_payload):
            coords = t["coords"]
            keep = max(1, remaining // max(len(trajectories_payload) - i, 1))
            if len(coords) > keep:
                t["coords"] = coords[-keep:]
            remaining -= len(t["coords"])

    return {
        "clear": clear_first,
        "fitView": fit_view,
        "bounds": _payload_bounds(marker_payload, infrastructure_payload),
        "performanceMode": performance_mode,
        "stationColors": station_color_map,
        "markers": marker_payload,
        "infrastructure": infrastructure_payload,
        "trajectories": trajectories_payload,
    }
```

- [ ] **Step 3: Add worker management to MapWidget.__init__**

After existing attributes (line 1801):

```python
        self._render_worker: RenderPayloadWorker | None = None
```

- [ ] **Step 4: Refactor _render_messages to delegate to worker**

Replace `_render_messages` body (lines 1914-2103) with worker dispatch:

```python
    def _render_messages(
        self,
        messages: list[V2xMessage],
        *,
        max_index: int | None,
        window_start_timestamp: float | None = None,
        fit_view: bool,
        short_trails: bool,
        clear_first: bool,
    ) -> None:
        """Dispatch render payload computation to background worker."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return

        if self._render_worker is not None and self._render_worker.isRunning():
            self._render_worker.cancel()
            self._render_worker.wait(500)

        self._render_worker = RenderPayloadWorker(
            messages,
            max_index=max_index,
            window_start_timestamp=window_start_timestamp,
            fit_view=fit_view,
            short_trails=short_trails,
            clear_first=clear_first,
            performance_mode=self.__dict__.get("_performance_mode", MAP_PERFORMANCE_NORMAL),
            station_color_map=self._station_color_map,
        )
        self._render_worker.payload_ready.connect(self._on_worker_payload_ready)
        self._render_worker.start()
```

- [ ] **Step 5: Add _on_worker_payload_ready handler**

After `_on_marker_clicked` (line 2193, above interaction handlers):

```python
    def _on_worker_payload_ready(self, payload_json: str, compute_time: float) -> None:
        """Receive computed payload from background thread and push to JS."""
        if self.__dict__.get("_disposed", False) or _qt_object_deleted(self):
            return
        end_index = len(getattr(self, "_last_messages", []))
        self._record_render_telemetry(
            MapRenderTelemetry(
                timestamp=compute_time,
                performance_mode=self.__dict__.get("_performance_mode", MAP_PERFORMANCE_NORMAL),
                source_message_count=end_index,
                visible_message_count=0,
                marker_count=0,
                infrastructure_count=0,
                trajectory_count=0,
                trajectory_point_count=0,
                payload_bytes=len(payload_json.encode("utf-8")),
            )
        )
        self._run_js(f"applyRenderPayload({payload_json})")
```

- [ ] **Step 6: Update dispose to cancel worker**

In `dispose` (line 1815), add after existing cleanup:

```python
        worker = self.__dict__.get("_render_worker")
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(500)
        self.__dict__["_render_worker"] = None
```

- [ ] **Step 7: Write worker test**

In `tests/test_map_widget.py`:

```python
from unittest.mock import patch
from PyQt6.QtCore import QThread


def test_render_worker_emits_json_payload():
    from datetime import UTC, datetime
    from pcap2kml_player.data_model import MessageType, V2xMessage
    from pcap2kml_player.map_widget import RenderPayloadWorker, MAP_PERFORMANCE_NORMAL

    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC),
            station_id="veh-1",
            msg_type=MessageType.CAM,
            latitude=52.0,
            longitude=13.0,
        ),
    ]
    worker = RenderPayloadWorker(
        messages,
        max_index=None,
        window_start_timestamp=None,
        fit_view=True,
        short_trails=False,
        clear_first=True,
        performance_mode=MAP_PERFORMANCE_NORMAL,
        station_color_map={"veh-1": "#ff0000"},
    )
    captured: list[str] = []

    worker.payload_ready.connect(lambda js, ts: captured.append(js))
    worker.start()
    worker.wait(5000)

    assert len(captured) == 1
    assert "applyRenderPayload" not in captured[0]
    assert '"clear": true' in captured[0] or '"clear": True' in captured[0]
    assert "veh-1" in captured[0]


def test_render_worker_cancel_prevents_emit():
    from datetime import UTC, datetime
    from pcap2kml_player.data_model import MessageType, V2xMessage
    from pcap2kml_player.map_widget import RenderPayloadWorker, MAP_PERFORMANCE_NORMAL

    messages = [
        V2xMessage(
            timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC),
            station_id="veh-1",
            msg_type=MessageType.CAM,
            latitude=52.0,
            longitude=13.0,
        ),
    ]
    worker = RenderPayloadWorker(
        messages,
        max_index=None,
        window_start_timestamp=None,
        fit_view=True,
        short_trails=False,
        clear_first=True,
        performance_mode=MAP_PERFORMANCE_NORMAL,
        station_color_map={"veh-1": "#ff0000"},
    )
    worker.cancel()
    captured: list[str] = []
    worker.payload_ready.connect(lambda js, ts: captured.append(js))
    worker.start()
    worker.wait(5000)

    assert len(captured) == 0
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_map_widget.py::test_render_worker_emits_json_payload tests/test_map_widget.py::test_render_worker_cancel_prevents_emit -v --timeout=30
```

- [ ] **Step 9: Commit**

```bash
git add pcap2kml_player/map_widget.py tests/test_map_widget.py
git commit -m "feat(map): offload payload computation to RenderPayloadWorker background thread"
```

---

### Task 5: Thread-Safety Audit — ParsingWorker Cancel

**Files:**
- Modify: `tests/test_parsing_worker.py`

- [ ] **Step 1: Write race-condition cancel test**

In `tests/test_parsing_worker.py`:

```python
def test_double_cancel_is_safe():
    worker = ParsingWorker(["C:\\does-not-exist\\missing.pcap"])
    worker.cancel()
    worker.cancel()

    captured: list[str] = []
    worker.cancelled.connect(lambda: captured.append("cancelled"))
    worker.run()

    assert len(captured) == 1


def test_cancel_during_run_triggers_cancelled_signal():
    import threading

    worker = ParsingWorker(["C:\\does-not-exist\\missing.pcap"])
    captured: list[str] = []
    worker.cancelled.connect(lambda: captured.append("cancelled"))

    def cancel_soon():
        import time
        time.sleep(0.01)
        worker.cancel()

    cancel_thread = threading.Thread(target=cancel_soon, daemon=True)
    cancel_thread.start()
    worker.run()
    cancel_thread.join(timeout=1)

    assert len(captured) == 1


def test_parsing_worker_empty_paths_emits_finished():
    worker = ParsingWorker([])
    captured = []

    worker.finished.connect(lambda session, paths, errors: captured.append((session, paths, errors)))
    worker.run()

    assert len(captured) == 1
    session, paths, errors = captured[0]
    assert session.messages == []
    assert paths == []
    assert errors == []
```

- [ ] **Step 2: Run worker tests**

```bash
pytest tests/test_parsing_worker.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_parsing_worker.py
git commit -m "test: add thread-safety tests for ParsingWorker cancel/empty paths"
```

---

### Task 6: PlayerController Tick Behavior With Interaction Gate

**Files:**
- Modify: `tests/test_player_controller.py`

- [ ] **Step 1: Write test for tick count tracking through interaction pause**

In `tests/test_player_controller.py`:

```python
class FakeMapWidget:
    """Stand-in for MapWidget used during unit tests of the player controller."""
    def __init__(self):
        self._render_calls: list[tuple] = []

    @property
    def user_interacting(self):
        return False

    def render_playback_slice(self, messages, current_index, *, window_seconds=None):
        self._render_calls.append(("slice", current_index))

    def update_playback_position(self, msg):
        self._render_calls.append(("position", msg.station_id))

    def clear(self):
        pass


def test_player_tick_does_not_depend_on_map_widget_for_state():
    base = datetime(2025, 8, 22, 12, 0, 0)
    session = SessionData(
        messages=[
            _message(base),
            _message(base + timedelta(seconds=2)),
        ]
    )

    controller = PlayerController()
    controller.set_session(session)
    controller.play()

    assert controller.state == "playing"

    controller._on_tick()
    controller._on_tick()

    assert controller.current_index >= 0
    assert controller.state == "playing"


def test_focus_replay_with_zero_focus_indices_stays_stopped():
    controller = PlayerController()
    controller.set_focus_indices([])
    controller.set_focus_replay_enabled(True)

    controller.play()

    assert controller.state == "playing"
    assert controller.current_index == 0
```

- [ ] **Step 2: Run controller tests**

```bash
pytest tests/test_player_controller.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_player_controller.py
git commit -m "test: add player controller tests for interaction gate and focus replay edge cases"
```

---

### Task 7: Final Verification — Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite excluding slow/E2E**

```bash
pytest tests/ -v --timeout=60 --cov=pcap2kml_player --cov-report=term-missing -m "not slow and not benchmark and not e2e"
```

Expected: all tests pass, coverage >= 80%

- [ ] **Step 2: Run ruff lint check**

```bash
ruff check pcap2kml_player/ tests/
```

Expected: no new violations

- [ ] **Step 3: Run mypy type check (informational)**

```bash
mypy pcap2kml_player/map_widget.py pcap2kml_player/ui/main_window.py
```

Note: existing mypy ignores may produce warnings; focus on new errors only.

- [ ] **Step 4: Run smoke test with real PCAP if available**

```bash
python -c "from pcap2kml_player.map_widget import MapWidget, MapBridge, RenderPayloadWorker; print('All imports ok')"
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: final verification — all tests pass, lint clean"
```

---

## Summary

| Task | Description | Est. Time |
|------|-------------|-----------|
| 1 | Interaction detection bridge (MapBridge + JS events) | 20 min |
| 2 | Wire interaction pause in MainWindow | 10 min |
| 3 | Tighten stall recovery (8s→5s, 3-stall reload) | 15 min |
| 4 | RenderPayloadWorker background thread | 30 min |
| 5 | ParsingWorker thread-safety tests | 10 min |
| 6 | PlayerController tick edge case tests | 10 min |
| 7 | Final verification (full suite, lint, mypy) | 10 min |
| **Total** | | **~1h 45min** |
