from __future__ import annotations

from datetime import UTC, datetime

from pcap2kml_player.data_model import MessageType, SessionData, V2xMessage
from pcap2kml_player.scene_model import PrioritizationIssue
from pcap2kml_player.ui import main_window as main_window_module
from pcap2kml_player.ui.eta_graph_widget import EtaDashboardData, EtaDashboardEvent
from pcap2kml_player.ui.main_window import (
    COL_LATLON,
    COL_MERGE,
    COL_MSGTYPE,
    COL_SOURCE,
    COL_SPEED_HEADING,
    COL_STATION,
    COL_TIMESTAMP,
    MAP_PLAYBACK_RENDER_INTERVAL_SECONDS,
    MEMORY_DIAGNOSTIC_THRESHOLD_MB,
    PERFORMANCE_MODE_DIAGNOSTIC,
    PERFORMANCE_MODE_NORMAL,
    PERFORMANCE_MODE_SAVER,
    MainWindow,
)


def _message(second: int, station_id: str = "car-1") -> V2xMessage:
    return V2xMessage(
        timestamp=datetime(2026, 4, 19, 12, 0, second, tzinfo=UTC),
        station_id=station_id,
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )


class _Rect:
    def __init__(self, visible: bool):
        self._visible = visible

    def isValid(self) -> bool:
        return True

    def intersects(self, _other) -> bool:
        return self._visible


class _Viewport:
    def rect(self) -> _Rect:
        return _Rect(True)


class _FakeTable:
    def __init__(self, visible_rows: set[int] | None = None):
        self.visible_rows = visible_rows or set()
        self.selected_rows: list[int] = []
        self.scrolled_rows: list[int] = []
        self._items: dict[tuple[int, int], object] = {}
        self.hidden_columns: dict[int, bool] = {}

    def setRowCount(self, _count: int) -> None:
        return None

    def setItem(self, row: int, column: int, item: object) -> None:
        self._items[(row, column)] = item

    def item(self, row: int, column: int) -> object | None:
        return self._items.get((row, column))

    def selectRow(self, row: int) -> None:
        self.selected_rows.append(row)

    def scrollToItem(self, item: object, _hint: object) -> None:
        for (row, _column), candidate in self._items.items():
            if candidate is item:
                self.scrolled_rows.append(row)
                return

    def visualItemRect(self, item: object) -> _Rect:
        for (row, _column), candidate in self._items.items():
            if candidate is item:
                return _Rect(row in self.visible_rows)
        return _Rect(False)

    def viewport(self) -> _Viewport:
        return _Viewport()

    def setColumnHidden(self, column: int, hidden: bool) -> None:
        self.hidden_columns[column] = hidden


class _FakePlayerForMapThrottle:
    def __init__(self):
        self._messages = [_message(0), _message(1)]
        self.current_index = 0
        self.seek_indices: list[int] = []

    def seek_to_index(self, index: int) -> None:
        self.seek_indices.append(index)
        self.current_index = index


class _FakeMapWidget:
    def __init__(self):
        self.telemetry_updated = _FakeSignal()
        self.map_issue_detected = _FakeSignal()
        self.map_interaction_ended = _FakeSignal()
        self.modes: list[str] = []
        self._user_interacting = False
        self.render_calls: list[tuple[list[V2xMessage], int, float | None]] = []
        self.reloads = 0
        self.loaded_messages: list[list[V2xMessage]] = []
        self.highlighted_requests: list[tuple[int, int, int]] = []
        self.focused_intersections: list[int] = []
        self.parent = object()
        self.deleted = False
        self.disposed = False

    @property
    def user_interacting(self) -> bool:
        return self._user_interacting

    def set_performance_mode(self, mode: str) -> None:
        self.modes.append(mode)

    def render_playback_slice(
        self,
        messages: list[V2xMessage],
        current_index: int,
        *,
        window_seconds: float | None = None,
    ) -> None:
        self.render_calls.append((messages, current_index, window_seconds))

    def update_playback_position(self, _msg: V2xMessage) -> None:
        return None

    def reload_map_page(self) -> None:
        self.reloads += 1

    def load_messages(self, messages: list[V2xMessage]) -> None:
        self.loaded_messages.append(messages)

    def highlight_request(self, intersection_id: int, request_id: int, sequence_number: int) -> None:
        self.highlighted_requests.append((intersection_id, request_id, sequence_number))

    def focus_intersection(self, intersection_id: int) -> None:
        self.focused_intersections.append(intersection_id)

    def setParent(self, parent) -> None:
        self.parent = parent

    def deleteLater(self) -> None:
        self.deleted = True

    def dispose(self) -> None:
        self.disposed = True


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _FakeMapAreaLayout:
    def __init__(self):
        self.removed = []
        self.inserted = []

    def removeWidget(self, widget) -> None:
        self.removed.append(widget)

    def insertWidget(self, index: int, widget, stretch: int = 0) -> None:
        self.inserted.append((index, widget, stretch))


class _FakeCombo:
    def __init__(self):
        self.items: list[tuple[str, str]] = []
        self.current_index = -1
        self.signals_blocked = False

    def addItem(self, label: str, data: str) -> None:
        self.items.append((label, data))

    def itemData(self, index: int) -> str:
        return self.items[index][1]

    def currentData(self) -> str | None:
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index][1]
        return None

    def count(self) -> int:
        return len(self.items)

    def findData(self, data: str) -> int:
        for index, (_label, item_data) in enumerate(self.items):
            if item_data == data:
                return index
        return -1

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = index

    def blockSignals(self, blocked: bool) -> None:
        self.signals_blocked = blocked


class _FakeSettings:
    def __init__(self):
        self.values: dict[str, object] = {}

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


class _FakeStatusBar:
    def __init__(self):
        self.messages: list[str] = []

    def showMessage(self, message: str, *_args) -> None:
        self.messages.append(message)


class _FakeLabel:
    def __init__(self):
        self.text = ""
        self.style = ""
        self.tooltip = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setStyleSheet(self, style: str) -> None:
        self.style = style

    def setToolTip(self, text: str) -> None:
        self.tooltip = text


class _FakeTabs:
    def __init__(self, index: int = 1):
        self._index = index
        self.visible = True
        self.history: list[int] = []

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        self._index = index
        self.history.append(index)

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class _FakeButton:
    def __init__(self):
        self.text = ""
        self.tooltip = ""
        self.checked = False

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def blockSignals(self, _blocked: bool) -> None:
        return None

    def setChecked(self, checked: bool) -> None:
        self.checked = checked

    def setFixedWidth(self, _width: int) -> None:
        return None


class _FakePanel:
    def __init__(self):
        self.minimum_width = None
        self.maximum_width = None

    def setMinimumWidth(self, width: int) -> None:
        self.minimum_width = width

    def setMaximumWidth(self, width: int) -> None:
        self.maximum_width = width


class _FakeVisibleWidget:
    def __init__(self):
        self.visible = True

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class _FakeLabel:
    def __init__(self):
        self.text = ""
        self.style = ""
        self.tooltip = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def setStyleSheet(self, style: str) -> None:
        self.style = style


class _FakeSettings:
    def __init__(self):
        self.values: dict[str, object] = {}

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


class _FakeSplitter:
    def __init__(self):
        self.sizes: list[int] = []

    def setSizes(self, sizes: list[int]) -> None:
        self.sizes = sizes


class _FakeDetailTable:
    def __init__(self):
        self.row_count = 0
        self.items: dict[tuple[int, int], object] = {}
        self.visible = False

    def setRowCount(self, count: int) -> None:
        self.row_count = count

    def setItem(self, row: int, column: int, item: object) -> None:
        self.items[(row, column)] = item

    def show(self) -> None:
        self.visible = True


def test_populate_message_table_builds_lookup_without_full_window_init():
    window = MainWindow.__new__(MainWindow)
    window._session = None
    window._message_row_lookup = {}
    window._last_highlighted_row = None
    window._msg_table = _FakeTable()

    first = _message(0, "car-1")
    second = _message(1, "car-2")

    window._populate_message_table([first, second])

    assert window._message_row_lookup[window._message_lookup_key(first)] == 0
    assert window._message_row_lookup[window._message_lookup_key(second)] == 1


def test_highlight_table_row_skips_scroll_when_row_is_already_visible():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    key = (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)
    table = _FakeTable(visible_rows={2})
    timestamp_item = object()
    table.setItem(2, COL_TIMESTAMP, timestamp_item)

    window._msg_table = table
    window._message_row_lookup = {key: 2}
    window._last_highlighted_row = None

    window._highlight_table_row(msg)

    assert table.selected_rows == [2]
    assert table.scrolled_rows == []
    assert window._last_highlighted_row == 2


def test_highlight_table_row_avoids_repeat_selection_for_same_row():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    key = (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)
    table = _FakeTable()
    timestamp_item = object()
    table.setItem(3, COL_TIMESTAMP, timestamp_item)

    window._msg_table = table
    window._message_row_lookup = {key: 3}
    window._last_highlighted_row = 3

    window._highlight_table_row(msg)

    assert table.selected_rows == []
    assert table.scrolled_rows == []


def test_show_security_detail_defers_refresh_when_scene_tab_is_active():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    window._context_tabs = _FakeTabs(index=1)
    window._detail_table = _FakeDetailTable()
    window._pending_detail_message = None
    window._last_detail_key = None

    window._show_security_detail(msg, auto_focus=False)

    assert window._pending_detail_message is msg
    assert window._detail_table.row_count == 0
    assert window._last_detail_key is None


def test_on_context_tab_changed_renders_pending_details():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    window._context_tabs = _FakeTabs(index=0)
    window._detail_table = _FakeDetailTable()
    window._pending_detail_message = msg
    window._last_detail_key = None

    window._on_context_tab_changed(0)

    assert window._detail_table.row_count > 0
    assert window._last_detail_key == window._message_lookup_key(msg)


def test_toggle_message_table_maximized_hides_context_tabs():
    window = MainWindow.__new__(MainWindow)
    window._context_tabs = _FakeTabs(index=1)
    window._btn_toggle_message_table = _FakeButton()
    window._right_splitter = _FakeSplitter()
    window._message_table_maximized = False

    window._toggle_message_table_maximized(True)
    assert window._message_table_maximized is True
    assert window._context_tabs.visible is False
    assert window._right_splitter.sizes == [1, 0]
    assert window._btn_toggle_message_table.text == "Tabellenbereich wiederherstellen"

    window._toggle_message_table_maximized(False)
    assert window._message_table_maximized is False
    assert window._context_tabs.visible is True
    assert window._right_splitter.sizes == [460, 280]
    assert window._btn_toggle_message_table.text == "Tabelle maximieren"


def test_filter_prioritization_issues_by_severity_and_intersection():
    window = MainWindow.__new__(MainWindow)
    window._issue_filter_mode = "critical"
    window._issue_filter_intersection = "42"
    now = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
    issues = [
        PrioritizationIssue(
            issue_type="TIMEOUT",
            severity="error",
            intersection_id=42,
            request_id=1,
            sequence_number=1,
            station_id="bus-1",
            message="timeout",
            timestamp=now,
        ),
        PrioritizationIssue(
            issue_type="ETA_CONFLICT",
            severity="warning",
            intersection_id=42,
            request_id=2,
            sequence_number=1,
            station_id="bus-2",
            message="eta",
            timestamp=now,
        ),
        PrioritizationIssue(
            issue_type="REJECTED",
            severity="error",
            intersection_id=7,
            request_id=3,
            sequence_number=1,
            station_id="bus-3",
            message="rejected",
            timestamp=now,
        ),
    ]

    filtered = window._filter_prioritization_issues(issues)

    assert [issue.request_id for issue in filtered] == [1]


def test_reset_playback_render_caches_clears_state_without_recursion():
    window = MainWindow.__new__(MainWindow)
    window._last_scene_update_monotonic = 1.0
    window._last_scene_cache_key = (123, "2026-04-19T12:00:00+00:00")
    window._last_scene_cache_snapshot = object()
    window._last_map_slice_update_monotonic = 2.0
    window._last_map_slice_index = 99
    window._last_map_messages_id = 456

    window._reset_playback_render_caches()

    assert window._last_scene_update_monotonic == 0.0
    assert window._last_scene_cache_key is None
    assert window._last_scene_cache_snapshot is None
    assert window._last_map_slice_update_monotonic == 0.0
    assert window._last_map_slice_index is None
    assert window._last_map_messages_id is None


def test_map_slice_render_is_throttled_even_for_priority_messages(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._player = _FakePlayerForMapThrottle()
    window._last_map_messages_id = id(window._player._messages)
    window._last_map_slice_index = 0
    window._last_map_slice_update_monotonic = 100.0
    window._player.current_index = 1
    monkeypatch.setattr(main_window_module.time, "perf_counter", lambda: 100.2)

    msg = V2xMessage(
        timestamp=datetime(2026, 4, 19, 12, 0, 1, tzinfo=UTC),
        station_id="rsu-srem",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
    )

    assert window._should_render_full_map_slice(msg) is False


def test_map_slice_render_runs_after_throttle_interval(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._player = _FakePlayerForMapThrottle()
    window._last_map_messages_id = id(window._player._messages)
    window._last_map_slice_index = 0
    window._last_map_slice_update_monotonic = 100.0
    window._player.current_index = 1
    monkeypatch.setattr(
        main_window_module.time,
        "perf_counter",
        lambda: 100.0 + MAP_PLAYBACK_RENDER_INTERVAL_SECONDS + 0.01,
    )

    assert window._should_render_full_map_slice(_message(1)) is True


def test_performance_mode_is_forwarded_to_map_and_persisted():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Schonend", PERFORMANCE_MODE_SAVER)
    window._performance_mode_combo.setCurrentIndex(1)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._performance_auto_downgraded = False

    window._on_performance_mode_changed()

    assert window._performance_mode == PERFORMANCE_MODE_SAVER
    assert window._map_widget.modes[-1] == PERFORMANCE_MODE_SAVER
    assert window._settings.values["ui/performance_mode"] == PERFORMANCE_MODE_SAVER


def test_single_map_issue_shows_status_message_without_fallback():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    window._map_issue_history = []
    window._map_safe_mode_active = False

    window._on_map_issue_detected("WebEngine Render-Prozess beendet")

    assert window._map_safe_mode_active is False
    assert window._map_issue_history == ["WebEngine Render-Prozess beendet"]
    assert "Kartenhinweis" in window._statusbar.messages[-1]


def test_nonfatal_map_issue_shows_status_hint():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    window._map_issue_history = []
    window._map_safe_mode_active = False

    window._on_map_issue_detected("ReferenceError")

    assert window._map_issue_history == ["ReferenceError"]
    assert "Kartenhinweis" in window._statusbar.messages[-1]


def test_memory_watchdog_auto_reduces_performance_mode(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._last_memory_warning_level = ""
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Schonend", PERFORMANCE_MODE_SAVER)
    window._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    monkeypatch.setattr(
        main_window_module,
        "_current_process_memory_mb",
        lambda: MEMORY_DIAGNOSTIC_THRESHOLD_MB + 10.0,
    )

    window._on_memory_watch_tick()

    assert window._performance_mode == PERFORMANCE_MODE_DIAGNOSTIC
    assert window._map_widget.modes[-1] == PERFORMANCE_MODE_DIAGNOSTIC
    assert window._performance_auto_downgraded is True
    assert "ui/performance_mode" not in window._settings.values
    assert "Diagnose" in window._statusbar.messages[-1]


def test_playback_tick_passes_performance_window(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._player = _FakePlayerForMapThrottle()
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_DIAGNOSTIC
    window._last_map_messages_id = None
    window._last_map_slice_index = None
    window._last_map_slice_update_monotonic = 0.0
    window._highlight_table_row = lambda _msg: None
    window._show_security_detail = lambda _msg, auto_focus=False: None
    window._update_scene_for_message = lambda _msg: None
    window._eta_graph = type("Eta", (), {"set_current_time": lambda self, _ts: None})()
    monkeypatch.setattr(main_window_module.time, "perf_counter", lambda: 10.0)

    window._on_playback_tick(window._player._messages[0])

    assert window._map_widget.render_calls
    assert window._map_widget.render_calls[-1][2] == 20.0


def test_map_telemetry_budget_drop_reduces_to_saver_mode():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Schonend", PERFORMANCE_MODE_SAVER)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    window._map_telemetry_history = []

    window._on_map_telemetry_updated(
        {
            "budget_dropped_markers": 1,
            "budget_dropped_infrastructure": 0,
            "budget_dropped_trajectories": 0,
            "budget_dropped_trajectory_points": 0,
        }
    )

    assert window._performance_mode == PERFORMANCE_MODE_SAVER
    assert window._map_widget.modes[-1] == PERFORMANCE_MODE_SAVER
    assert "ui/performance_mode" not in window._settings.values
    assert "Payload" in window._statusbar.messages[-1]


def test_repeated_map_issues_enable_diagnostic_safe_mode():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    window._map_issue_history = []
    window._map_safe_mode_active = False
    window._player = _FakePlayerForMapThrottle()
    window._session = None

    window._on_map_issue_detected("ReferenceError")
    window._on_map_issue_detected("TypeError")
    window._on_map_issue_detected("Render stalled")

    assert window._performance_mode == PERFORMANCE_MODE_DIAGNOSTIC
    assert window._map_safe_mode_active is True
    assert "Safe-Mode" in window._statusbar.messages[-1]


def test_render_payload_stall_triggers_safe_mode_with_recovery_reload():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._performance_mode_combo = _FakeCombo()
    window._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
    window._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
    window._settings = _FakeSettings()
    window._memory_watch_label = _FakeLabel()
    window._statusbar = _FakeStatusBar()
    window._map_issue_history = ["minor 1", "minor 2"]
    window._map_safe_mode_active = False
    window._player = _FakePlayerForMapThrottle()
    window._session = SessionData(messages=window._player._messages)

    window._on_map_issue_detected("Karten-Renderpayload laeuft seit mehr als 8s")

    assert window._map_safe_mode_active is True
    assert window._performance_mode == PERFORMANCE_MODE_DIAGNOSTIC
    assert window._map_widget.modes[-1] == PERFORMANCE_MODE_DIAGNOSTIC
    assert window._map_widget.reloads == 1


def test_reload_map_resets_safe_mode_and_rerenders_session():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    window._player = _FakePlayerForMapThrottle()
    window._session = SessionData(messages=window._player._messages)
    window._performance_mode = PERFORMANCE_MODE_DIAGNOSTIC
    window._memory_watch_label = _FakeLabel()
    window._map_issue_history = ["ReferenceError"]
    window._map_safe_mode_active = True
    window._statusbar = _FakeStatusBar()

    window._on_reload_map()

    assert window._map_widget.reloads == 1
    assert window._map_safe_mode_active is False
    assert window._map_issue_history == []
    assert window._map_widget.render_calls[-1][0] == window._player._messages


def test_build_diagnostics_report_contains_runtime_session_and_map(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    messages = [_message(0)]
    session = SessionData(messages=messages, station_ids={"car-1"})
    session.msg_type_counts = {MessageType.CAM: 1}
    window._session = session
    window._performance_mode = PERFORMANCE_MODE_SAVER
    window._performance_auto_downgraded = True
    window._map_safe_mode_active = False
    window._map_telemetry_history = [{"payload_bytes": 123}]
    window._map_issue_history = ["ReferenceError"]
    monkeypatch.setattr(main_window_module, "_current_process_memory_mb", lambda: 321.0)

    report = window._build_diagnostics_report()

    assert report["application"]["performance_mode"] == PERFORMANCE_MODE_SAVER
    assert report["application"]["memory_mb"] == 321.0
    assert report["session"]["loaded"] is True
    assert report["session"]["messages"] == 1
    assert report["map"]["latest_telemetry"]["payload_bytes"] == 123
    assert "python" in report["runtime"]


def test_eta_event_message_seek_focuses_matching_srem():
    window = MainWindow.__new__(MainWindow)
    srem = V2xMessage(
        _message(0).timestamp,
        "bus-1",
        MessageType.SREM,
        52.0,
        13.0,
        decoded_data={"intersectionId": 72, "requestId": 6, "sequenceNumber": 86},
    )
    window._player = _FakePlayerForMapThrottle()
    window._player._messages = [_message(0), srem]
    window._map_widget = _FakeMapWidget()
    window._statusbar = _FakeStatusBar()
    window._highlight_table_row = lambda _msg: None
    window._show_security_detail = lambda _msg, auto_focus=False, force_refresh=False: None
    event = EtaDashboardEvent(
        time_text=srem.timestamp.strftime("%H:%M:%S.%f")[:-3],
        kind="SREM",
        content="SREM 6/86",
        details="",
        timestamp=srem.timestamp,
        message_type=MessageType.SREM,
        selection_key="REQ:72:6:86:bus-1:raw",
    )

    assert window._seek_eta_event_message(event) is True

    assert window._player.seek_indices == [1]
    assert window._map_widget.highlighted_requests == [(72, 6, 86)]
    assert window._map_widget.focused_intersections == [72]


def test_eta_diagnostic_event_focuses_request_without_message_seek():
    window = MainWindow.__new__(MainWindow)
    window._map_widget = _FakeMapWidget()
    event = EtaDashboardEvent(
        time_text="12:00:03.000",
        kind="Diagnose",
        content="ETA-Fehler +3.0s",
        details="",
        timestamp=_message(0).timestamp,
        message_type=None,
        selection_key="REQ:72:6:86:bus-1:raw",
    )

    window._focus_eta_event_request(event)

    assert window._map_widget.highlighted_requests == [(72, 6, 86)]
    assert window._map_widget.focused_intersections == [72]


def test_write_eta_dashboard_exports_creates_csv_and_json(tmp_path):
    window = MainWindow.__new__(MainWindow)
    event = EtaDashboardEvent(
        time_text="12:00:00.000",
        kind="SSEM",
        content="granted",
        details="SSEM granted",
        timestamp=_message(0).timestamp,
        message_type=MessageType.SSEM,
        selection_key="REQ:72:6:86:bus-1:raw",
    )
    data = EtaDashboardData(
        metrics=[("Station", "bus-1"), ("SSEM-Updates", "1")],
        events=[event],
    )
    csv_path = tmp_path / "eta_dashboard.csv"
    json_path = tmp_path / "eta_dashboard.json"

    window._write_eta_dashboard_exports(data, csv_path, json_path)

    assert "Kennzahl" in csv_path.read_text(encoding="utf-8-sig")
    payload = main_window_module.json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metrics"][0]["name"] == "Station"
    assert payload["events"][0]["kind"] == "SSEM"


def test_toggle_issue_panel_collapses_and_expands_content():
    window = MainWindow.__new__(MainWindow)
    window._issue_panel = _FakePanel()
    window._issue_content = _FakeVisibleWidget()
    window._issue_panel_title = _FakeLabel()
    window._btn_toggle_issue_panel = _FakeButton()

    window._toggle_issue_panel_collapsed(True)

    assert window._issue_panel_collapsed is True
    assert window._issue_content.visible is False
    assert window._issue_panel.maximum_width == 44
    assert window._issue_panel_title.text == "!"
    assert window._btn_toggle_issue_panel.text == ">"

    window._toggle_issue_panel_collapsed(False)

    assert window._issue_panel_collapsed is False
    assert window._issue_content.visible is True
    assert window._issue_panel.minimum_width == 260
    assert window._issue_panel_title.text == "Priorisierungsfehler"
    assert window._btn_toggle_issue_panel.text == "Einklappen"


def test_apply_compact_message_columns_hides_non_compact_columns():
    window = MainWindow.__new__(MainWindow)
    table = _FakeTable()
    window._msg_table = table

    window._apply_compact_message_columns(True)

    assert table.hidden_columns[COL_TIMESTAMP] is False
    assert table.hidden_columns[COL_STATION] is False
    assert table.hidden_columns[COL_MSGTYPE] is False
    assert table.hidden_columns[COL_SPEED_HEADING] is False
    assert table.hidden_columns[COL_LATLON] is True
    assert table.hidden_columns[COL_SOURCE] is True
    assert table.hidden_columns[COL_MERGE] is True

    window._apply_compact_message_columns(False)

    assert all(hidden is False for hidden in table.hidden_columns.values())


def test_issue_panel_policy_collapses_only_without_critical_in_compact_mode():
    window = MainWindow.__new__(MainWindow)
    window._is_compact_layout = True
    window._issue_panel_collapsed = False
    window._issue_panel = _FakePanel()
    window._issue_content = _FakeVisibleWidget()
    window._issue_panel_title = _FakeLabel()
    window._btn_toggle_issue_panel = _FakeButton()
    warning = PrioritizationIssue(
        issue_type="ETA_CONFLICT",
        severity="warning",
        intersection_id=42,
        request_id=1,
        sequence_number=1,
        station_id="bus-1",
        message="warning",
        timestamp=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
    )
    critical = PrioritizationIssue(
        issue_type="TIMEOUT",
        severity="error",
        intersection_id=42,
        request_id=2,
        sequence_number=1,
        station_id="bus-2",
        message="critical",
        timestamp=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
    )

    window._apply_issue_panel_policy([warning])

    assert window._issue_panel_collapsed is True

    window._apply_issue_panel_policy([critical])

    assert window._issue_panel_collapsed is False


def test_set_overview_collapsed_hides_content_and_persists_setting():
    window = MainWindow.__new__(MainWindow)
    window._settings = _FakeSettings()
    window._overview_content = _FakeVisibleWidget()
    window._overview_compact_label = _FakeLabel()
    window._btn_toggle_overview = _FakeButton()
    window._session = None

    window._set_overview_collapsed(True)

    assert window._overview_collapsed is True
    assert window._overview_content.visible is False
    assert window._btn_toggle_overview.text == "Header anzeigen"
    assert window._settings.values["ui/header_collapsed"] is True


def test_build_diagnostics_report_includes_map_backend_and_opengl_env(monkeypatch):

    monkeypatch.setenv("QT_OPENGL", "software")

    window = MainWindow.__new__(MainWindow)
    window._session = None
    window._performance_mode = PERFORMANCE_MODE_NORMAL
    window._performance_auto_downgraded = False
    window._map_safe_mode_active = False
    window._map_telemetry_history = []
    window._map_issue_history = []

    report = window._build_diagnostics_report()

    assert report["application"]["map_backend"] == "webengine"
    assert report["runtime"]["qt_opengl"] == "software"
