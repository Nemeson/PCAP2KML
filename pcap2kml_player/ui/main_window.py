"""PyQt6 main window for PCAP2KML Player — v2.0 redesigned workspace layout."""

from __future__ import annotations

import csv
import ctypes
import importlib.metadata
import json
import logging
import os
import platform
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import (
    PYQT_VERSION_STR,
    QT_VERSION_STR,
    QRect,
    QSettings,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QPainter,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyleOptionButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..app_memory import AppMemory
from ..data_model import MessageType, SessionData, V2xMessage
from ..kml_exporter import export_kml
from ..map_backend import (
    MAP_PERFORMANCE_DIAGNOSTIC,
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
)
from ..map_widget import MapWidget
from ..parsing_worker import ParsingWorker
from ..player_controller import SPEED_OPTIONS, PlayerController
from ..prioritization_exporter import export_prioritization_issues
from ..scene_model import (
    PrioritizationIssue,
    SceneSnapshot,
    build_prioritization_issues,
    build_scene_snapshot,
    collect_prioritization_issue_occurrences,
)
from .dashboard_dialog import StatisticsDashboard
from .eta_graph_widget import (
    EtaDashboardEvent,
    EtaGraphWidget,
    build_eta_selection_options,
)

logger = logging.getLogger(__name__)

COL_TIMESTAMP = 0
COL_STATION = 1
COL_MSGTYPE = 2
COL_LATLON = 3
COL_SPEED_HEADING = 4
COL_SOURCE = 5
COL_MERGE = 6
NUM_COLUMNS = 7

TABLE_HEADERS = [
    "Timestamp",
    "Station ID",
    "Msg Type",
    "Lat / Lon",
    "Speed / Heading",
    "Quelle",
    "Merge",
]
SCENE_INTERSECTION_HEADERS = [
    "Intersection",
    "Revision",
    "Signalgruppen",
    "Prognose",
    "30s Timeline",
]
SCENE_REQUEST_HEADERS = ["Request", "Station", "Prio", "Status", "Lanes"]
FORECAST_TIMELINE_BUCKETS = 15
MAP_PLAYBACK_RENDER_INTERVAL_SECONDS = 1.25
PERFORMANCE_MODE_NORMAL = MAP_PERFORMANCE_NORMAL
PERFORMANCE_MODE_SAVER = MAP_PERFORMANCE_SAVER
PERFORMANCE_MODE_DIAGNOSTIC = MAP_PERFORMANCE_DIAGNOSTIC
PERFORMANCE_MODE_LABELS = {
    PERFORMANCE_MODE_NORMAL: "Normal",
    PERFORMANCE_MODE_SAVER: "Schonend",
    PERFORMANCE_MODE_DIAGNOSTIC: "Diagnose",
}
PERFORMANCE_RENDER_INTERVAL_SECONDS = {
    PERFORMANCE_MODE_NORMAL: 1.25,
    PERFORMANCE_MODE_SAVER: 2.5,
    PERFORMANCE_MODE_DIAGNOSTIC: 4.0,
}
PERFORMANCE_PLAYBACK_WINDOW_SECONDS = {
    PERFORMANCE_MODE_NORMAL: 120.0,
    PERFORMANCE_MODE_SAVER: 45.0,
    PERFORMANCE_MODE_DIAGNOSTIC: 20.0,
}
MEMORY_WATCH_INTERVAL_MS = 5000
MEMORY_SAVER_THRESHOLD_MB = 1200.0
MEMORY_DIAGNOSTIC_THRESHOLD_MB = 1800.0
MAP_SAFE_MODE_ISSUE_THRESHOLD = 3
MAP_TELEMETRY_HISTORY_LIMIT = 120

# ── Style constants ──────────────────────────────────────────────
STYLE_BG_APP = "#f4f6f9"
STYLE_BG_SURFACE = "#ffffff"
STYLE_BG_TOOLBAR = "#1a2332"
STYLE_BG_STATUS = "#eef1f5"
STYLE_BG_PANEL = "#fafbfc"
STYLE_ACCENT = "#cc3333"
STYLE_ACCENT_HOVER = "#a82828"
STYLE_TEXT_PRIMARY = "#0d1b2a"
STYLE_TEXT_SECONDARY = "#5a6b81"
STYLE_TEXT_MUTED = "#8b97a8"
STYLE_BORDER = "#dde1e7"

TOOLBAR_STYLE = f"""
    QToolBar {{
        background: {STYLE_BG_TOOLBAR};
        border: none;
        padding: 0 8px;
        spacing: 8px;
    }}
"""
TOOLBAR_BTN_STYLE = """
    QPushButton {
        background: transparent;
        color: #e0e4ea;
        border: none;
        border-radius: 5px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 400;
    }
    QPushButton:hover { background: rgba(255,255,255,0.08); }
    QPushButton:pressed { background: rgba(255,255,255,0.14); }
"""
TOOLBAR_BTN_PRIMARY = f"""
    QPushButton {{
        background: {STYLE_ACCENT};
        color: #ffffff;
        border: none;
        border-radius: 5px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {STYLE_ACCENT_HOVER}; }}
"""

WS_TAB_STYLE = f"""
    QPushButton {{
        background: transparent;
        color: {STYLE_TEXT_SECONDARY};
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        padding: 7px 16px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        color: {STYLE_TEXT_PRIMARY};
        background: #e8ecf1;
    }}
    QPushButton:checked {{
        color: {STYLE_ACCENT};
        border-bottom-color: {STYLE_ACCENT};
        font-weight: 600;
    }}
"""

TABLE_STYLE = f"""
    QTableWidget {{
        background: {STYLE_BG_SURFACE};
        alternate-background-color: #eaf5ff;
        color: {STYLE_TEXT_PRIMARY};
        gridline-color: {STYLE_BORDER};
        selection-background-color: #cfe8ff;
        selection-color: #000000;
    }}
    QHeaderView::section {{
        background: #f5f7fb;
        color: {STYLE_TEXT_PRIMARY};
        border: 1px solid {STYLE_BORDER};
        padding: 4px;
        font-weight: 700;
    }}
"""

PANEL_CARD_STYLE = f"""
    QFrame#panelCard {{
        background: {STYLE_BG_SURFACE};
        border: 1px solid {STYLE_BORDER};
        border-radius: 10px;
    }}
"""

STATUS_BAR_STYLE = f"""
    QStatusBar {{
        background: {STYLE_BG_STATUS};
        border-top: 1px solid {STYLE_BORDER};
        color: {STYLE_TEXT_SECONDARY};
        font-size: 12px;
    }}
"""

PLAYBACK_BAR_STYLE = f"""
    QFrame#playbackBar {{
        background: rgba(255,255,255,0.95);
        border: 1px solid {STYLE_BORDER};
        border-radius: 14px;
    }}
"""

CMD_PALETTE_STYLE = f"""
    QDialog#cmdPalette {{
        background: transparent;
    }}
    QFrame#cmdPaletteInner {{
        background: {STYLE_BG_SURFACE};
        border-radius: 14px;
        border: 1px solid {STYLE_BORDER};
    }}
    QLineEdit {{
        border: none;
        border-bottom: 1px solid {STYLE_BORDER};
        padding: 14px 20px;
        font-size: 16px;
        background: transparent;
        color: {STYLE_TEXT_PRIMARY};
    }}
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
        font-size: 13px;
        color: {STYLE_TEXT_PRIMARY};
    }}
    QListWidget::item {{
        padding: 8px 20px;
    }}
    QListWidget::item:selected {{
        background: #eff6ff;
        color: {STYLE_TEXT_PRIMARY};
    }}
"""

SIDEBAR_HEADER_STYLE = f"""
    font-weight: 600;
    font-size: 13px;
    color: {STYLE_TEXT_PRIMARY};
    padding: 10px 14px;
    border-bottom: 1px solid {STYLE_BORDER};
    background: {STYLE_BG_PANEL};
"""


def _current_process_memory_mb() -> float | None:
    """Return current process working set in MiB on Windows."""
    if os.name != "nt":
        return None
    try:

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if not ok:
            return None
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return None


class CommandPalette(QDialog):
    """Fuzzy-search command palette (Ctrl+K)."""

    command_triggered = pyqtSignal(str, object)  # action_id, data

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cmdPalette")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        inner = QFrame()
        inner.setObjectName("cmdPaletteInner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Befehl eingeben... (z.B. 'KML exportieren', 'Szene anzeigen')")
        self._search.textChanged.connect(self._filter)
        self._search.returnPressed.connect(self._execute_current)
        inner_layout.addWidget(self._search)

        self._results = QListWidget()
        self._results.itemActivated.connect(self._execute)
        inner_layout.addWidget(self._results)

        layout.addWidget(inner)

    def populate(self, entries: list[dict[str, object]]) -> None:
        """Populate with {section, label, action_id, data, shortcut} dicts."""
        self._entries = entries
        self._rebuild_all()

    def _rebuild_all(self) -> None:
        self._results.clear()
        current_section = None
        for entry in self._entries:
            section = str(entry.get("section", ""))
            if section != current_section:
                current_section = section
                header = QListWidgetItem(section.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(Qt.GlobalColor.gray)
                font = header.font()
                font.setBold(True)
                font.setPointSize(8)
                header.setFont(font)
                self._results.addItem(header)
            label = str(entry.get("label", ""))
            shortcut = str(entry.get("shortcut", ""))
            text = f"   {label}"
            if shortcut:
                text += f"   ──   {shortcut}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._results.addItem(item)

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        if not query:
            self._rebuild_all()
            return
        self._results.clear()
        current_section = None
        for entry in self._entries:
            label = str(entry.get("label", "")).lower()
            section = str(entry.get("section", ""))
            hint = str(entry.get("shortcut", "")).lower()
            if query in label or query in section.lower() or query in hint:
                if section != current_section:
                    current_section = section
                    header = QListWidgetItem(section.upper())
                    header.setFlags(Qt.ItemFlag.NoItemFlags)
                    header.setForeground(Qt.GlobalColor.gray)
                    font = header.font()
                    font.setBold(True)
                    font.setPointSize(8)
                    header.setFont(font)
                    self._results.addItem(header)
                shortcut = str(entry.get("shortcut", ""))
                text = f"   {str(entry.get('label', ''))}"
                if shortcut:
                    text += f"   ──   {shortcut}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._results.addItem(item)
        if self._results.count() > 0:
            self._results.setCurrentRow(0)

    def _execute(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.command_triggered.emit(str(data.get("action_id", "")), data.get("data"))
        self.accept()

    def _execute_current(self) -> None:
        item = self._results.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            self._execute(item)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._search.setFocus()
        self._search.clear()
        self._rebuild_all()


class IconButton(QPushButton):
    """Custom button that draws vector icons via QPainter.

    Replaces text-based symbols which fail to render in small circular
    buttons on certain Qt stylesheets / DPI configurations.
    """

    def __init__(self, icon_name: str, size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(size, size)
        self.setText("")  # ensure no text layout interferes

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # inherit stylesheet background via style()->drawPrimitive
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelButtonCommand,
            opt,
            painter,
            self,
        )

        # determine effective foreground colour
        fg = self.palette().buttonText().color()
        if not self.isEnabled():
            fg = QColor("#c4cad4")

        rect = self.rect().adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fg))

        if self._icon_name == "play":
            # right-pointing triangle
            path = QPainterPath()
            path.moveTo(rect.left(), rect.top())
            path.lineTo(rect.right(), rect.center().y())
            path.lineTo(rect.left(), rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)

        elif self._icon_name == "pause":
            bar_w = max(2, rect.width() // 5)
            gap = max(1, rect.width() // 8)
            left = QRect(
                rect.center().x() - bar_w - gap // 2,
                rect.top(),
                bar_w,
                rect.height(),
            )
            right = QRect(
                rect.center().x() + gap // 2,
                rect.top(),
                bar_w,
                rect.height(),
            )
            painter.drawRect(left)
            painter.drawRect(right)

        elif self._icon_name == "stop":
            painter.drawRect(rect)

        elif self._icon_name == "prev":
            # left-pointing triangle
            path = QPainterPath()
            path.moveTo(rect.right(), rect.top())
            path.lineTo(rect.left(), rect.center().y())
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)

        elif self._icon_name == "next":
            # right-pointing triangle (same as play)
            path = QPainterPath()
            path.moveTo(rect.left(), rect.top())
            path.lineTo(rect.right(), rect.center().y())
            path.lineTo(rect.left(), rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)

        painter.end()


class MainWindow(QMainWindow):
    """Main application window for PCAP2KML Player — v2.0 workspace design."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCAP2KML Player")
        self.setMinimumSize(1280, 720)
        self.resize(1440, 880)
        self.setAcceptDrops(True)

        self._memory = AppMemory.load()
        self._settings = QSettings("PCAP2KML", "Player")
        self._performance_mode = str(self._settings.value("ui/performance_mode", PERFORMANCE_MODE_NORMAL))
        if self._performance_mode not in PERFORMANCE_MODE_LABELS:
            self._performance_mode = PERFORMANCE_MODE_NORMAL
        self._performance_auto_downgraded = False
        self._last_memory_warning_level = ""
        self._map_backend = str(self._settings.value("ui/map_backend", "webengine"))
        if self._map_backend not in {"webengine", "native"}:
            self._map_backend = "webengine"

        # Session state
        self._session: SessionData | None = None
        self._active_types: set[MessageType] = set(MessageType)
        self._active_stations: set[str] = set()
        self._all_station_ids: set[str] = set()
        self._show_canonical_messages = False
        self._loader_thread: QThread | None = None
        self._loader_worker: ParsingWorker | None = None
        self._message_row_lookup: dict[tuple[str, str], int] = {}
        self._last_highlighted_row: int | None = None
        self._last_detail_key: tuple[str, str] | None = None
        self._pending_detail_message: V2xMessage | None = None
        self._current_prioritization_issues: list[PrioritizationIssue] = []
        self._issue_filter_mode = "all"
        self._issue_filter_intersection = "all"
        self._problem_replay_indices: list[int] = []
        self._message_table_maximized = False
        self._last_scene_update_monotonic = 0.0
        self._last_scene_cache_key: tuple[int, str] | None = None
        self._last_scene_cache_snapshot: SceneSnapshot | None = None
        self._last_map_slice_update_monotonic = 0.0
        self._last_map_slice_index: int | None = None
        self._last_map_messages_id: int | None = None
        self._map_telemetry_history: list[dict[str, object]] = []
        self._map_issue_history: list[str] = []
        self._map_safe_mode_active = False

        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        self._restore_window_state()
        self._refresh_memory_banner()
        self._update_controls_enabled(False)
        self._setup_memory_watchdog()

    # ── UI Setup ──────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the complete v2.0 UI layout."""
        self._setup_toolbar()
        self._setup_workspace_tabs()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._workspace_stack = QStackedWidget()
        self._workspace_stack.addWidget(self._setup_map_workspace())   # index 0
        self._workspace_stack.addWidget(self._setup_eta_workspace())   # index 1
        self._workspace_stack.addWidget(self._setup_issues_workspace())  # index 2
        self._workspace_stack.addWidget(self._setup_raw_workspace())   # index 3
        main_layout.addWidget(self._workspace_stack, stretch=1)

        self._setup_statusbar()

    def _setup_toolbar(self) -> None:
        """Dark toolbar with grouped buttons."""
        toolbar = QToolBar("Hauptwerkzeugleiste")
        toolbar.setMovable(False)
        toolbar.setStyleSheet(TOOLBAR_STYLE)
        self.addToolBar(toolbar)

        # Brand
        brand = QLabel("  PCAP2KML Player")
        brand.setStyleSheet("color: #fff; font-weight: 700; font-size: 14px; padding: 0 8px;")
        toolbar.addWidget(brand)

        # Group 1: Load
        self._btn_load = QPushButton("PCAP laden")
        self._btn_load.setStyleSheet(TOOLBAR_BTN_PRIMARY)
        toolbar.addWidget(self._btn_load)

        self._btn_reload_last = QPushButton("Letzte Sitzung")
        self._btn_reload_last.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_reload_last)

        self._btn_cancel_load = QPushButton("Abbrechen")
        self._btn_cancel_load.setStyleSheet(TOOLBAR_BTN_STYLE)
        self._btn_cancel_load.setEnabled(False)
        toolbar.addWidget(self._btn_cancel_load)

        self._add_toolbar_sep(toolbar)

        # Group 2: Export
        self._btn_export_kml = QPushButton("KML exportieren")
        self._btn_export_kml.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_export_kml)

        self._btn_export_issues = QPushButton("Fehler exportieren")
        self._btn_export_issues.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_export_issues)

        self._btn_export_diagnostics = QPushButton("Diagnose exportieren")
        self._btn_export_diagnostics.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_export_diagnostics)

        self._add_toolbar_sep(toolbar)

        # Group 3: Tools
        self._btn_reload_map = QPushButton("Karte neu laden")
        self._btn_reload_map.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_reload_map)

        self._btn_update_schemas = QPushButton("ASN.1-Schemas")
        self._btn_update_schemas.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_update_schemas)

        self._btn_dashboard = QPushButton("Dashboard")
        self._btn_dashboard.setStyleSheet(TOOLBAR_BTN_STYLE)
        toolbar.addWidget(self._btn_dashboard)

        self._add_toolbar_sep(toolbar)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Command palette trigger
        self._btn_cmd_palette = QPushButton("  Schnellbefehl suchen...    Ctrl+K")
        self._btn_cmd_palette.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06);
                color: #8b97a8;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 12px;
                min-width: 240px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.10);
                border-color: rgba(255,255,255,0.18);
            }
        """)
        toolbar.addWidget(self._btn_cmd_palette)

    @staticmethod
    def _add_toolbar_sep(toolbar: QToolBar) -> None:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.12); margin: 2px 2px;")
        toolbar.addWidget(sep)

    def _setup_workspace_tabs(self) -> None:
        """Row of workspace tab buttons above the content area."""
        container = QWidget()
        container.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-bottom: 1px solid {STYLE_BORDER};")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(2)

        self._ws_tabs: dict[str, QPushButton] = {}
        self._ws_badge_labels: dict[str, QLabel] = {}

        tabs = [
            ("map", "Karte  "),
            ("eta", "ETA Analyse  "),
            ("issues", "Priorisierung  "),
            ("raw", "Rohdaten  "),
        ]
        for ws_id, ws_label in tabs:
            btn = QPushButton(ws_label)
            btn.setCheckable(True)
            btn.setStyleSheet(WS_TAB_STYLE)
            btn.clicked.connect(lambda checked, wid=ws_id: self._switch_workspace(wid))
            layout.addWidget(btn)
            self._ws_tabs[ws_id] = btn

            if ws_id == "issues":
                badge = QLabel("")
                badge.setStyleSheet(
                    "font-size: 10px; font-weight: 700; color: #fff;"
                    "background: #dc2626; border-radius: 8px;"
                    "padding: 1px 6px; margin-left: -4px;"
                )
                badge.hide()
                layout.addWidget(badge)
                self._ws_badge_labels[ws_id] = badge

        layout.addStretch()
        self.addToolBarBreak()  # toolbar above, tabs below
        self._ws_tab_widget = container

        # Add tab widget as a toolbar widget
        tab_toolbar = QToolBar("WorkspaceTabs")
        tab_toolbar.setMovable(False)
        tab_toolbar.setStyleSheet(f"QToolBar {{ background: {STYLE_BG_SURFACE}; border: none; padding: 0; spacing: 0; }}")
        tab_toolbar.addWidget(container)
        self.addToolBar(tab_toolbar)

        self._ws_tabs["map"].setChecked(True)

    def _switch_workspace(self, ws_id: str) -> None:
        indices = {"map": 0, "eta": 1, "issues": 2, "raw": 3}
        self._workspace_stack.setCurrentIndex(indices[ws_id])
        for tid, btn in self._ws_tabs.items():
            btn.setChecked(tid == ws_id)
        # Sync view state across all map instances so they share the same center+zoom
        if ws_id in ("eta", "issues") and hasattr(self._map_widget, "save_view_state"):
            state = self._map_widget.save_view_state()
            if state is not None:
                target_map = self._eta_map if ws_id == "eta" else self._issues_map
                if hasattr(target_map, "restore_view_state"):
                    target_map.restore_view_state(state)

    # ── Workspace 1: Map ──────────────────────────────────────────

    def _setup_map_workspace(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Map area with floating playback bar
        map_area = QWidget()
        map_area.setStyleSheet(f"background: {STYLE_BG_APP};")
        map_layout = QVBoxLayout(map_area)
        map_layout.setContentsMargins(0, 0, 0, 0)

        self._map_widget = MapWidget()
        map_layout.addWidget(self._map_widget, stretch=1)

        # Floating playback bar
        self._setup_floating_playback(map_layout)

        layout.addWidget(map_area, stretch=1)

        # Right sidebar: current message preview
        self._setup_message_sidebar(layout)

        return container

    def _setup_floating_playback(self, parent_layout: QVBoxLayout) -> None:
        """Floating playback bar positioned at bottom of map area."""
        playback = QWidget()
        playback.setObjectName("playbackBar")
        playback.setStyleSheet(PLAYBACK_BAR_STYLE)
        playback.setMaximumWidth(780)

        row = QHBoxLayout(playback)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        self._chk_problem_replay = QCheckBox("Nur Fehler")
        self._chk_problem_replay.setStyleSheet(f"font-size: 11px; color: {STYLE_TEXT_SECONDARY};")

        self._btn_prev_issue = IconButton("prev", 28)
        self._btn_prev_issue.setStyleSheet(self._pb_btn_style())
        self._btn_prev_issue.setEnabled(False)

        self._btn_play = IconButton("play", 38)
        self._btn_play.setStyleSheet(
            f"QPushButton {{ background: {STYLE_ACCENT}; color: #fff; border: none; border-radius: 19px; }}"
            f"QPushButton:hover {{ background: {STYLE_ACCENT_HOVER}; }}"
            f"QPushButton:disabled {{ background: #cbd5e1; }}"
        )

        self._btn_pause = IconButton("pause", 28)
        self._btn_pause.setStyleSheet(self._pb_btn_style())
        self._btn_pause.setEnabled(False)

        self._btn_stop = IconButton("stop", 28)
        self._btn_stop.setStyleSheet(self._pb_btn_style())

        self._btn_next_issue = IconButton("next", 28)
        self._btn_next_issue.setStyleSheet(self._pb_btn_style())
        self._btn_next_issue.setEnabled(False)

        self._lbl_time = QLabel("00:00.0 / 00:00.0")
        self._lbl_time.setStyleSheet(
            f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 13px; font-weight: 600; "
            f"color: {STYLE_TEXT_PRIMARY}; min-width: 130px;"
        )
        self._lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 5px; background: {STYLE_BORDER}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0; "
            f"background: {STYLE_ACCENT}; border-radius: 6px; border: 2px solid #fff; }}"
        )

        self._speed_combo = QComboBox()
        for speed in SPEED_OPTIONS:
            self._speed_combo.addItem(f"{speed}x")
        self._speed_combo.setCurrentIndex(2)
        self._speed_combo.setFixedWidth(60)
        self._speed_combo.setStyleSheet(f"font-size: 11px; color: {STYLE_TEXT_PRIMARY};")

        row.addWidget(self._chk_problem_replay)
        row.addWidget(self._btn_prev_issue)
        row.addWidget(self._btn_play)
        row.addWidget(self._btn_pause)
        row.addWidget(self._btn_stop)
        row.addWidget(self._btn_next_issue)
        row.addWidget(self._lbl_time)
        row.addWidget(self._slider)
        row.addWidget(self._speed_combo)

        # Center the playback bar
        wrapper = QHBoxLayout()
        wrapper.addStretch()
        wrapper.addWidget(playback)
        wrapper.addStretch()
        parent_layout.addLayout(wrapper)

    @staticmethod
    def _pb_btn_style() -> str:
        return (
            "QPushButton { background: #e8ecf1; border: none; border-radius: 14px; font-size: 11px; color: #0d1b2a; }"
            "QPushButton:hover { background: #d4dbe6; }"
            "QPushButton:disabled { background: #f1f3f6; color: #c4cad4; }"
        )

    def _setup_message_sidebar(self, parent_layout: QHBoxLayout) -> None:
        """Right sidebar showing current message preview."""
        sidebar = QWidget()
        sidebar.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-left: 1px solid {STYLE_BORDER};")
        sidebar.setFixedWidth(320)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        header = QLabel("Aktuelle Nachricht")
        header.setStyleSheet(SIDEBAR_HEADER_STYLE)
        sb_layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        self._msg_preview_card = QFrame()
        self._msg_preview_card.setObjectName("panelCard")
        self._msg_preview_card.setStyleSheet(PANEL_CARD_STYLE)
        card_layout = QVBoxLayout(self._msg_preview_card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        self._msg_preview_header = QLabel("Keine Nachricht ausgewählt")
        self._msg_preview_header.setStyleSheet(f"font-weight: 600; color: {STYLE_TEXT_SECONDARY}; font-size: 12px;")
        card_layout.addWidget(self._msg_preview_header)
        self._msg_preview_body = QLabel("")
        self._msg_preview_body.setWordWrap(True)
        self._msg_preview_body.setStyleSheet(f"color: {STYLE_TEXT_PRIMARY}; font-size: 12px;")
        card_layout.addWidget(self._msg_preview_body)
        body_layout.addWidget(self._msg_preview_card)

        body_layout.addStretch()
        sb_layout.addWidget(body)
        parent_layout.addWidget(sidebar)

    # ── Workspace 2: ETA Analysis ─────────────────────────────────

    def _setup_eta_workspace(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top: map + request details sidebar
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)

        # Small map for ETA context
        self._eta_map = MapWidget()
        self._eta_map.setMinimumWidth(280)
        top_splitter.addWidget(self._eta_map)
        top_splitter.setStretchFactor(0, 3)

        # Request details sidebar
        eta_sidebar = QWidget()
        eta_sidebar.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-left: 1px solid {STYLE_BORDER};")
        eta_sidebar.setMinimumWidth(220)
        esb_layout = QVBoxLayout(eta_sidebar)
        esb_layout.setContentsMargins(0, 0, 0, 0)
        esb_layout.setSpacing(0)

        header = QLabel("Request-Details")
        header.setStyleSheet(SIDEBAR_HEADER_STYLE)
        esb_layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        # Vehicle/request selector
        self._eta_station_combo = QComboBox()
        self._eta_station_combo.setMinimumWidth(180)
        self._eta_station_combo.setStyleSheet("font-size: 12px; padding: 4px;")
        body_layout.addWidget(QLabel("Fahrzeug/Request:"))
        body_layout.addWidget(self._eta_station_combo)

        # Metrics cards
        metrics_row = QHBoxLayout()
        self._eta_metric_1 = self._make_metric_card("Letzte ETA", "-")
        self._eta_metric_2 = self._make_metric_card("Granted Latenz", "-")
        self._eta_metric_3 = self._make_metric_card("SSEM Updates", "-")
        metrics_row.addWidget(self._eta_metric_1)
        metrics_row.addWidget(self._eta_metric_2)
        metrics_row.addWidget(self._eta_metric_3)
        body_layout.addLayout(metrics_row)

        # Status timeline
        status_card = QFrame()
        status_card.setObjectName("panelCard")
        status_card.setStyleSheet(PANEL_CARD_STYLE)
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(12, 10, 12, 10)
        sc_header = QLabel("Status-Verlauf")
        sc_header.setStyleSheet(f"font-weight: 600; color: {STYLE_TEXT_SECONDARY}; font-size: 12px;")
        sc_layout.addWidget(sc_header)
        self._eta_status_timeline = QLabel("Keine Sitzung geladen.")
        self._eta_status_timeline.setWordWrap(True)
        self._eta_status_timeline.setStyleSheet(f"color: {STYLE_TEXT_PRIMARY}; font-size: 11px;")
        sc_layout.addWidget(self._eta_status_timeline)
        body_layout.addWidget(status_card)

        self._eta_summary = QLabel("Keine PCAP-Sitzung geladen.")
        self._eta_summary.setWordWrap(True)
        self._eta_summary.setStyleSheet(f"color: {STYLE_TEXT_SECONDARY}; font-size: 11px;")
        body_layout.addWidget(self._eta_summary)

        body_layout.addStretch()
        esb_layout.addWidget(body)
        top_splitter.addWidget(eta_sidebar)
        top_splitter.setSizes([800, 340])

        # Bottom: ETA graph + dashboard
        bottom = QWidget()
        bottom.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-top: 1px solid {STYLE_BORDER};")
        bottom.setMinimumHeight(200)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(6)

        graph_label = QLabel("ETA-Verlauf & Geschwindigkeit")
        graph_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {STYLE_TEXT_PRIMARY};")
        bottom_layout.addWidget(graph_label)

        self._eta_graph = EtaGraphWidget()
        bottom_layout.addWidget(self._eta_graph, stretch=1)

        # Metrics and events tables
        tables_splitter = QSplitter(Qt.Orientation.Horizontal)
        tables_splitter.setChildrenCollapsible(False)
        self._eta_metric_table = QTableWidget(0, 2)
        self._eta_metric_table.setHorizontalHeaderLabels(["Kennzahl", "Wert"])
        self._apply_table_style(self._eta_metric_table)
        tables_splitter.addWidget(self._eta_metric_table)

        self._eta_event_table = QTableWidget(0, 4)
        self._eta_event_table.setHorizontalHeaderLabels(["Zeit", "Typ", "Inhalt", "Details"])
        self._apply_table_style(self._eta_event_table)
        tables_splitter.addWidget(self._eta_event_table)
        tables_splitter.setSizes([260, 500])
        bottom_layout.addWidget(tables_splitter, stretch=2)

        self._btn_export_eta_dashboard = QPushButton("ETA exportieren (CSV/JSON)")
        self._btn_export_eta_dashboard.setStyleSheet(
            f"QPushButton {{ background: {STYLE_BG_PANEL}; border: 1px solid {STYLE_BORDER}; "
            f"border-radius: 6px; padding: 5px 12px; font-size: 11px; color: {STYLE_TEXT_PRIMARY}; }}"
            f"QPushButton:hover {{ background: #e8ecf1; }}"
        )
        bottom_layout.addWidget(self._btn_export_eta_dashboard)

        # Use a vertical splitter so top (map+sidebar) and bottom (graph+tables) are resizable
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.addWidget(top_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.addWidget(bottom)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([500, 400])
        layout.addWidget(main_splitter)
        return container

    @staticmethod
    def _make_metric_card(title: str, value: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {STYLE_BG_PANEL}; border: 1px solid {STYLE_BORDER}; border-radius: 8px; }}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(2)
        vl = QLabel(value)
        vl.setStyleSheet(
            f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 18px; font-weight: 700; color: {STYLE_TEXT_PRIMARY};"
        )
        vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl = QLabel(title)
        tl.setStyleSheet(f"font-size: 10px; color: {STYLE_TEXT_MUTED};")
        tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(vl)
        cl.addWidget(tl)
        return card

    # ── Workspace 3: Prioritization Issues ────────────────────────

    def _setup_issues_workspace(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Use a splitter so map and sidebar sizes are variable
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Map
        self._issues_map = MapWidget()
        self._issues_map.setMinimumWidth(280)
        splitter.addWidget(self._issues_map)
        splitter.setStretchFactor(0, 1)

        # Issue list sidebar
        sidebar = QWidget()
        sidebar.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-left: 1px solid {STYLE_BORDER};")
        sidebar.setMinimumWidth(280)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # Header with filters
        header_row = QWidget()
        header_row.setStyleSheet(SIDEBAR_HEADER_STYLE)
        hr_layout = QHBoxLayout(header_row)
        hr_layout.setContentsMargins(10, 8, 10, 8)
        hr_layout.setSpacing(8)
        hr_layout.addWidget(QLabel("Priorisierungsfehler"))
        self._issue_filter_combo = QComboBox()
        self._issue_filter_combo.addItem("Alle", "all")
        self._issue_filter_combo.addItem("Nur kritisch", "critical")
        self._issue_filter_combo.setStyleSheet("font-size: 11px;")
        hr_layout.addWidget(self._issue_filter_combo)
        self._issue_intersection_combo = QComboBox()
        self._issue_intersection_combo.addItem("Alle Kreuzungen", "all")
        self._issue_intersection_combo.setStyleSheet("font-size: 11px;")
        hr_layout.addWidget(self._issue_intersection_combo)
        self._issue_badge = QLabel("0")
        self._issue_badge.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #fff; background: #dc2626; "
            "border-radius: 9px; padding: 1px 6px;"
        )
        hr_layout.addWidget(self._issue_badge)
        sb_layout.addWidget(header_row)

        # Issue summary
        self._issue_summary = QLabel("Keine Fehler.")
        self._issue_summary.setWordWrap(True)
        self._issue_summary.setStyleSheet(f"color: {STYLE_TEXT_SECONDARY}; font-size: 11px; padding: 6px 12px;")
        sb_layout.addWidget(self._issue_summary)

        # Issue list
        self._issue_list = QListWidget()
        self._issue_list.setAlternatingRowColors(True)
        self._issue_list.setStyleSheet(
            "QListWidget { background: #ffffff; alternate-background-color: #eaf5ff;"
            " color: #0d1b2a; border: none; }"
            "QListWidget::item { padding: 8px 12px; border-bottom: 1px solid #eef1f5; }"
            "QListWidget::item:selected { background: #cfe8ff; color: #000; }"
        )

        sb_layout.addWidget(self._issue_list)
        splitter.addWidget(sidebar)
        layout.addWidget(splitter)
        return container

    # ── Workspace 4: Raw Data ─────────────────────────────────────

    def _setup_raw_workspace(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left: message table + filter row
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._setup_filter_row(left_layout)

        # Message table
        self._msg_table = QTableWidget(0, NUM_COLUMNS)
        self._msg_table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self._msg_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._msg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._msg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._msg_table.setAlternatingRowColors(True)
        self._msg_table.verticalHeader().setVisible(False)
        self._apply_table_style(self._msg_table)
        left_layout.addWidget(self._msg_table, stretch=1)

        layout.addWidget(left, stretch=6)

        # Right: detail inspector (in QDockWidget for docking)
        self._setup_detail_inspector(layout)

        return container

    def _setup_filter_row(self, parent_layout: QVBoxLayout) -> None:
        """Filter row for message types and stations."""
        filter_widget = QWidget()
        filter_widget.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-bottom: 1px solid {STYLE_BORDER};")
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(8, 6, 8, 6)
        filter_layout.setSpacing(10)

        filter_layout.addWidget(QLabel("Nachrichtentyp:"))
        self._type_checkboxes: dict[MessageType, QCheckBox] = {}
        for msg_type in MessageType:
            checkbox = QCheckBox(msg_type.value)
            checkbox.setChecked(True)
            checkbox.setStyleSheet("font-size: 11px;")
            checkbox.stateChanged.connect(self._on_filter_changed)
            self._type_checkboxes[msg_type] = checkbox
            filter_layout.addWidget(checkbox)

        filter_layout.addWidget(QLabel("Stationen:"))
        self._station_list = QListWidget()
        self._station_list.setMaximumHeight(80)
        self._station_list.setMinimumWidth(220)
        self._station_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._station_list.setStyleSheet("font-size: 11px;")
        filter_layout.addWidget(self._station_list)

        self._lbl_filter_hint = QLabel("Alle Typen und Stationen aktiv")
        self._lbl_filter_hint.setStyleSheet(f"color: {STYLE_TEXT_SECONDARY}; font-size: 11px;")
        filter_layout.addWidget(self._lbl_filter_hint)

        self._merge_view_checkbox = QCheckBox("Gemergte Sicht")
        self._merge_view_checkbox.setStyleSheet("font-size: 11px;")
        self._merge_view_checkbox.stateChanged.connect(self._on_merge_view_changed)
        filter_layout.addWidget(self._merge_view_checkbox)
        filter_layout.addStretch()
        parent_layout.addWidget(filter_widget)

    def _setup_detail_inspector(self, parent_layout: QHBoxLayout) -> None:
        """Detail inspector panel (dockable)."""
        inspector = QWidget()
        inspector.setStyleSheet(f"background: {STYLE_BG_SURFACE}; border-left: 1px solid {STYLE_BORDER};")
        inspector.setFixedWidth(360)
        ins_layout = QVBoxLayout(inspector)
        ins_layout.setContentsMargins(0, 0, 0, 0)
        ins_layout.setSpacing(0)

        header = QLabel("Detail-Inspektor")
        header.setStyleSheet(SIDEBAR_HEADER_STYLE)
        ins_layout.addWidget(header)

        scroll = QWidget()
        scroll_layout = QVBoxLayout(scroll)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(8)

        # Basic data card
        basic_card = QFrame()
        basic_card.setObjectName("panelCard")
        basic_card.setStyleSheet(PANEL_CARD_STYLE)
        bc_layout = QVBoxLayout(basic_card)
        bc_layout.setContentsMargins(12, 10, 12, 10)
        bc_layout.addWidget(QLabel("Basisdaten"))
        bc_layout.addWidget(self._make_detail_row("Typ:", "-"))
        bc_layout.addWidget(self._make_detail_row("Station:", "-"))
        bc_layout.addWidget(self._make_detail_row("Zeit:", "-"))
        bc_layout.addWidget(self._make_detail_row("Position:", "-"))
        scroll_layout.addWidget(basic_card)

        # Detail table (same as old _detail_table)
        self._detail_table = QTableWidget(0, 2)
        self._detail_table.setHorizontalHeaderLabels(["Feld", "Wert"])
        self._detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._apply_table_style(self._detail_table)
        scroll_layout.addWidget(self._detail_table)

        # Security/PKI
        sec_card = QFrame()
        sec_card.setObjectName("panelCard")
        sec_card.setStyleSheet(PANEL_CARD_STYLE)
        sc_layout = QVBoxLayout(sec_card)
        sc_layout.setContentsMargins(12, 10, 12, 10)
        sc_layout.addWidget(QLabel("Security / PKI"))
        self._security_label = QLabel("Keine Signaturdaten")
        self._security_label.setStyleSheet(f"font-size: 11px; color: {STYLE_TEXT_MUTED};")
        sc_layout.addWidget(self._security_label)
        scroll_layout.addWidget(sec_card)

        # ECDSA verify button
        self._btn_verify_signature = QPushButton("Signatur prüfen")
        self._btn_verify_signature.setEnabled(False)
        self._btn_verify_signature.clicked.connect(self._on_verify_signature)
        self._btn_verify_signature.hide()
        scroll_layout.addWidget(self._btn_verify_signature)

        scroll_layout.addStretch()
        ins_layout.addWidget(scroll, stretch=1)
        parent_layout.addWidget(inspector)

    def _make_detail_row(self, label: str, value: str) -> QLabel:
        return QLabel(f"<b>{label}</b> {value}")

    # ── Status Bar ─────────────────────────────────────────────────

    def _setup_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self._statusbar.setStyleSheet(STATUS_BAR_STYLE)
        self.setStatusBar(self._statusbar)

        self._status_metrics = QLabel("Noch keine Sitzung geladen")
        self._status_metrics.setStyleSheet(f"color: {STYLE_TEXT_PRIMARY}; font-weight: 600;")

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedWidth(180)

        # Map mode indicator
        self._status_map = QLabel("Karte: Leaflet  |  Leistung: Normal")
        self._status_map.setStyleSheet(f"color: {STYLE_TEXT_SECONDARY}; font-size: 11px;")

        self._status_ram = QLabel("RAM: -")
        self._status_ram.setStyleSheet(
            f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px;"
            f"color: {STYLE_TEXT_MUTED}; margin-left: 8px;"
        )

        self._statusbar.addPermanentWidget(self._status_metrics)
        self._statusbar.addPermanentWidget(self._progress)
        self._statusbar.addPermanentWidget(self._status_map)
        self._statusbar.addPermanentWidget(self._status_ram)
        self._statusbar.showMessage("Bereit - PCAP-Datei laden oder per Drag & Drop ablegen")

    # ── Command Palette ────────────────────────────────────────────

    def _setup_command_palette(self) -> None:
        self._cmd_palette = CommandPalette(self)
        self._cmd_palette.command_triggered.connect(self._on_cmd_palette_action)
        self._cmd_palette.populate(self._cmd_palette_entries())

    def _show_command_palette(self) -> None:
        if not hasattr(self, "_cmd_palette"):
            self._setup_command_palette()
        self._cmd_palette.populate(self._cmd_palette_entries())
        self._cmd_palette.show()
        pt = self.rect().center()
        self._cmd_palette.move(pt.x() - 280, pt.y() - 210)

    @staticmethod
    def _cmd_palette_entries() -> list[dict[str, object]]:
        return [
            {"section": "Workspaces", "label": "Karte (Map)", "action_id": "ws_map", "shortcut": "Ctrl+1"},
            {"section": "Workspaces", "label": "ETA Analyse", "action_id": "ws_eta", "shortcut": "Ctrl+2"},
            {"section": "Workspaces", "label": "Priorisierungsfehler", "action_id": "ws_issues", "shortcut": "Ctrl+3"},
            {"section": "Workspaces", "label": "Rohdaten", "action_id": "ws_raw", "shortcut": "Ctrl+4"},
            {"section": "Aktionen", "label": "KML exportieren", "action_id": "export_kml"},
            {"section": "Aktionen", "label": "Fehler exportieren", "action_id": "export_issues"},
            {"section": "Aktionen", "label": "Diagnose exportieren", "action_id": "export_diagnostics"},
            {"section": "Aktionen", "label": "ASN.1-Schemas aktualisieren", "action_id": "update_schemas"},
            {"section": "Aktionen", "label": "Statistik-Dashboard öffnen", "action_id": "open_dashboard"},
            {"section": "Aktionen", "label": "Karte neu laden", "action_id": "reload_map"},
            {"section": "Navigation", "label": "Zum nächsten Fehler springen", "action_id": "next_issue"},
            {"section": "Navigation", "label": "Zum vorherigen Fehler", "action_id": "prev_issue"},
            {"section": "Navigation", "label": "Playback starten", "action_id": "play"},
            {"section": "Navigation", "label": "Playback pausieren", "action_id": "pause"},
            {"section": "Navigation", "label": "Playback stoppen", "action_id": "stop"},
        ]

    def _on_cmd_palette_action(self, action_id: str, _data: object | None = None) -> None:
        handlers = {
            "ws_map": lambda: self._switch_workspace("map"),
            "ws_eta": lambda: self._switch_workspace("eta"),
            "ws_issues": lambda: self._switch_workspace("issues"),
            "ws_raw": lambda: self._switch_workspace("raw"),
            "export_kml": self._on_export_kml,
            "export_issues": self._on_export_prioritization_issues,
            "export_diagnostics": self._on_export_diagnostics,
            "update_schemas": self._on_update_schemas,
            "open_dashboard": self._on_show_dashboard,
            "reload_map": self._on_reload_map,
            "next_issue": self._player.seek_to_next_focus,
            "prev_issue": self._player.seek_to_previous_focus,
            "play": self._player.play,
            "pause": self._player.pause,
            "stop": self._player.stop,
        }
        handler = handlers.get(action_id)
        if handler:
            handler()

    # ── Helper: table styling ──────────────────────────────────────

    def _apply_table_style(self, table: QTableWidget) -> None:
        table.setStyleSheet(TABLE_STYLE)

    # ── Player Setup ───────────────────────────────────────────────

    def _setup_player(self) -> None:
        self._player = PlayerController(self)

    # ── Signal Connections ─────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Connect UI controls to their handlers."""
        # Toolbar
        self._btn_load.clicked.connect(self._on_load_pcap)
        self._btn_reload_last.clicked.connect(self._on_reload_last_session)
        self._btn_cancel_load.clicked.connect(self._on_cancel_load)
        self._btn_export_kml.clicked.connect(self._on_export_kml)
        self._btn_export_issues.clicked.connect(self._on_export_prioritization_issues)
        self._btn_export_diagnostics.clicked.connect(self._on_export_diagnostics)
        self._btn_reload_map.clicked.connect(self._on_reload_map)
        self._btn_update_schemas.clicked.connect(self._on_update_schemas)
        self._btn_dashboard.clicked.connect(self._on_show_dashboard)
        self._btn_cmd_palette.clicked.connect(self._show_command_palette)

        # ETA
        self._btn_export_eta_dashboard.clicked.connect(self._on_export_eta_dashboard)
        self._eta_event_table.itemClicked.connect(self._on_eta_event_clicked)
        self._eta_station_combo.currentTextChanged.connect(self._on_eta_station_changed)

        # Issue filters
        self._issue_filter_combo.currentIndexChanged.connect(self._on_issue_filter_changed)
        self._issue_intersection_combo.currentIndexChanged.connect(self._on_issue_filter_changed)

        # Playback
        self._btn_play.clicked.connect(self._player.play)
        self._btn_pause.clicked.connect(self._player.pause)
        self._btn_stop.clicked.connect(self._player.stop)
        self._btn_prev_issue.clicked.connect(self._player.seek_to_previous_focus)
        self._btn_next_issue.clicked.connect(self._player.seek_to_next_focus)
        self._chk_problem_replay.toggled.connect(self._on_problem_replay_toggled)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self._slider.sliderMoved.connect(self._on_slider_moved)

        # Message table + filters
        self._station_list.itemSelectionChanged.connect(self._on_station_filter_changed)
        self._msg_table.cellClicked.connect(self._on_table_row_clicked)
        self._issue_list.itemClicked.connect(self._on_prioritization_issue_clicked)

        # Map telemetry
        self._map_widget.telemetry_updated.connect(self._on_map_telemetry_updated)
        self._map_widget.map_issue_detected.connect(self._on_map_issue_detected)

        # Player signals
        self._player.tick.connect(self._on_playback_tick)
        self._player.state_changed.connect(self._on_player_state_changed)
        self._player.position_changed.connect(self._on_player_position_changed)
        self._player.time_updated.connect(self._on_player_time_updated)
        self._player.duration_changed.connect(self._on_duration_changed)

    # ── Performance Mode ───────────────────────────────────────────

    def _setup_memory_watchdog(self) -> None:
        self._memory_watch_timer = QTimer(self)
        self._memory_watch_timer.setInterval(MEMORY_WATCH_INTERVAL_MS)
        self._memory_watch_timer.timeout.connect(self._on_memory_watch_tick)
        self._memory_watch_timer.start()
        self._on_memory_watch_tick()

    def _on_memory_watch_tick(self) -> None:
        memory_mb = _current_process_memory_mb()
        self._update_memory_display(memory_mb)
        if memory_mb is None:
            return
        target_mode = None
        warning_level = ""
        if memory_mb >= MEMORY_DIAGNOSTIC_THRESHOLD_MB:
            target_mode = PERFORMANCE_MODE_DIAGNOSTIC
            warning_level = "diagnostic"
        elif memory_mb >= MEMORY_SAVER_THRESHOLD_MB:
            target_mode = PERFORMANCE_MODE_SAVER
            warning_level = "saver"
        if target_mode and self._performance_mode != target_mode:
            self._set_performance_mode(target_mode, auto=True)
        if warning_level and warning_level != self._last_memory_warning_level:
            self._last_memory_warning_level = warning_level
            self._statusbar.showMessage(
                f"RAM {memory_mb:.0f} MB - Kartenmodus automatisch auf {PERFORMANCE_MODE_LABELS[target_mode]} reduziert"
            )

    def _set_performance_mode(self, mode: str, *, auto: bool) -> None:
        if mode not in PERFORMANCE_MODE_LABELS:
            mode = PERFORMANCE_MODE_NORMAL
        self._performance_mode = mode
        self._performance_auto_downgraded = auto
        if not auto:
            self._settings.setValue("ui/performance_mode", mode)
        self._apply_performance_mode()

    def _apply_performance_mode(self) -> None:
        if hasattr(self, "_map_widget"):
            self._map_widget.set_performance_mode(self._performance_mode)
        self._update_status_map_label()

    def _update_memory_display(self, memory_mb: float | None) -> None:
        mode = self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL)
        mode_label = PERFORMANCE_MODE_LABELS.get(mode, "Normal")
        suffix = " auto" if self.__dict__.get("_performance_auto_downgraded", False) else ""
        if memory_mb is None:
            self._status_ram.setText(f"RAM: - | {mode_label}{suffix}")
            return
        color = "#1f7a3a"
        if memory_mb >= MEMORY_DIAGNOSTIC_THRESHOLD_MB:
            color = "#b91c1c"
        elif memory_mb >= MEMORY_SAVER_THRESHOLD_MB:
            color = "#a16207"
        self._status_ram.setText(f"RAM: {memory_mb:.0f} MB | {mode_label}{suffix}")
        self._status_ram.setStyleSheet(
            f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; color: {color}; "
            f"font-weight: 700; margin-left: 8px;"
        )

    def _update_status_map_label(self) -> None:
        backend = "Leaflet"
        mode = self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL)
        mode_label = PERFORMANCE_MODE_LABELS.get(mode, "Normal")
        self._status_map.setText(f"Karte: {backend}  |  Leistung: {mode_label}")

    def _map_render_interval_seconds(self) -> float:
        return PERFORMANCE_RENDER_INTERVAL_SECONDS.get(
            self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
            PERFORMANCE_RENDER_INTERVAL_SECONDS[PERFORMANCE_MODE_NORMAL],
        )

    def _map_playback_window_seconds(self) -> float | None:
        return PERFORMANCE_PLAYBACK_WINDOW_SECONDS.get(
            self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
            PERFORMANCE_PLAYBACK_WINDOW_SECONDS[PERFORMANCE_MODE_NORMAL],
        )

    # ── Map Backend Switching ──────────────────────────────────────

    def _replace_map_widget(self, backend: str, *, persist: bool = False) -> None:
        logger.info("Replacing map widget: backend=%s persist=%s", backend, persist)
        old_widget = self._map_widget
        self._map_backend = backend
        if persist:
            self._settings.setValue("ui/map_backend", backend)
        self._map_widget = MapWidget()
        # Reconnect signals
        self._map_widget.telemetry_updated.connect(self._on_map_telemetry_updated)
        self._map_widget.map_issue_detected.connect(self._on_map_issue_detected)
        # Replace in layout (find parent container)
        parent = old_widget.parent()
        if parent and parent.layout():
            parent_layout = parent.layout()
            parent_layout.replaceWidget(old_widget, self._map_widget)
        if hasattr(old_widget, "dispose"):
            old_widget.dispose()
        old_widget.setParent(None)
        old_widget.deleteLater()
        self._map_safe_mode_active = False
        self._map_issue_history.clear()
        self._apply_performance_mode()
        if self._session:
            self._map_widget.load_messages(self._player._messages)
            self._eta_map.load_messages(self._player._messages)
            self._issues_map.load_messages(self._player._messages)
        self._statusbar.showMessage("Karte neu geladen", 5000)

    def _should_fallback_to_native_map(self, message: str) -> bool:
        return False

    # ── Load PCAP ──────────────────────────────────────────────────

    def _on_load_pcap(self) -> None:
        start_dir = self._memory.last_directory or str(Path.cwd())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "PCAP-Dateien oeffnen", start_dir,
            "PCAP-Dateien (*.pcap *.pcapng *.cap);;Alle Dateien (*)",
        )
        if paths:
            self._load_paths(paths)

    def _on_reload_last_session(self) -> None:
        paths = self._memory.existing_last_session_files()
        if not paths:
            QMessageBox.information(self, "Keine Sitzung vorhanden",
                "Es wurden keine gueltigen Dateien aus der letzten Sitzung gefunden.")
            return
        self._load_paths(paths)

    def _load_paths(self, paths: list[str]) -> None:
        if self._loader_thread is not None:
            QMessageBox.information(self, "Ladevorgang aktiv",
                "Es laeuft bereits ein Parse-Vorgang. Bitte warte oder brich ihn ab.")
            return
        normalized = [str(Path(path).resolve()) for path in paths]
        self._set_loading_state(True, 0, 100, "PCAP-Dateien werden im Hintergrund geladen...")
        self._loader_thread = QThread(self)
        self._loader_worker = ParsingWorker(normalized)
        self._loader_worker.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader_worker.run)
        self._loader_worker.progress.connect(self._on_load_progress)
        self._loader_worker.finished.connect(self._on_load_finished)
        self._loader_worker.cancelled.connect(self._on_load_cancelled)
        self._loader_worker.finished.connect(self._cleanup_loader)
        self._loader_worker.cancelled.connect(self._cleanup_loader)
        self._loader_thread.start()

    def _on_cancel_load(self) -> None:
        if self._loader_worker is not None:
            self._loader_worker.cancel()
            self._statusbar.showMessage("Abbruch angefordert...")

    def _on_load_progress(self, percent: int, filename: str) -> None:
        self._progress.setValue(percent)
        self._statusbar.showMessage(f"Lade {filename}... {percent}%")

    def _on_load_finished(self, session: SessionData, paths: list[str], errors: list[str]) -> None:
        self._set_loading_state(False)
        if not session.messages:
            self._session = None
            self._clear_session_views()
            self._statusbar.showMessage("Keine verarbeitbaren Nachrichten gefunden")
            self._refresh_memory_banner()
            if errors:
                QMessageBox.warning(self, "Laden fehlgeschlagen", "\n".join(errors))
            else:
                QMessageBox.information(self, "Keine Daten gefunden",
                    "In den geladenen PCAP-Dateien wurden keine verarbeitbaren Nachrichten erkannt.")
            return
        self._session = session
        self._all_station_ids = set(session.station_ids)
        self._active_stations = set(session.station_ids)
        self._active_types = set(MessageType)
        self._populate_station_list()
        self._populate_message_table(session.messages)
        self._map_widget.load_messages(session.messages)
        self._eta_map.load_messages(session.messages)
        self._issues_map.load_messages(session.messages)
        self._reset_playback_render_caches()
        self._player.set_session(session)
        self._refresh_problem_replay_indices(session.messages)
        self._refresh_eta_analysis(session.messages)
        self._detail_table.hide()
        self._update_scene_for_message(session.messages[0], force=True)
        self._update_controls_enabled(True)
        self._update_overview_for_session(paths, session)
        self._memory.remember_files(paths)
        self._memory.remember_session_summary(
            message_count=len(session.messages),
            station_count=len(session.station_ids),
            duration_seconds=session.duration_seconds,
            msg_type_counts={key.value: value for key, value in session.msg_type_counts.items()},
        )
        self._memory.save()
        self._statusbar.showMessage(
            f"{len(session.messages)} Nachrichten geladen - "
            f"{len(session.station_ids)} Stationen - "
            f"Dauer: {self._player.format_time(session.duration_seconds)}"
        )
        if errors:
            QMessageBox.warning(self, "Teilweise geladen",
                "Einige Dateien konnten nicht vollstaendig verarbeitet werden:\n\n" + "\n".join(errors))

    def _on_load_cancelled(self) -> None:
        self._set_loading_state(False)
        self._statusbar.showMessage("Ladevorgang abgebrochen")

    def _cleanup_loader(self, *args) -> None:
        if self._loader_worker is not None:
            try:
                self._loader_worker.finished.disconnect(self._on_load_finished)
                self._loader_worker.finished.disconnect(self._cleanup_loader)
            except (RuntimeError, TypeError):
                pass
            try:
                self._loader_worker.cancelled.disconnect(self._on_load_cancelled)
                self._loader_worker.cancelled.disconnect(self._cleanup_loader)
            except (RuntimeError, TypeError):
                pass
            try:
                self._loader_worker.progress.disconnect(self._on_load_progress)
            except (RuntimeError, TypeError):
                pass
            self._loader_worker.deleteLater()
            self._loader_worker = None
        if self._loader_thread is not None:
            self._loader_thread.quit()
            self._loader_thread.wait()
            try:
                self._loader_thread.started.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._loader_thread.deleteLater()
            self._loader_thread = None

    # ── Export Handlers ────────────────────────────────────────────

    def _on_export_kml(self) -> None:
        if not self._session:
            return
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(self, "KML-Exportverzeichnis waehlen", start_dir)
        if not dir_path:
            return
        try:
            created = export_kml(
                self._session, Path(dir_path),
                active_types=self._active_types if self._active_types != set(MessageType) else None,
                active_stations=(self._active_stations if self._active_stations != self._all_station_ids else None),
                canonical=self._show_canonical_messages,
            )
        except (OSError, PermissionError, ValueError) as exc:
            QMessageBox.critical(self, "Export-Fehler", str(exc))
            return
        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"{len(created)} KML-Dateien exportiert nach {dir_path}")
        QMessageBox.information(self, "Export erfolgreich",
            f"{len(created)} KML-Dateien wurden exportiert nach:\n{dir_path}")

    def _on_export_prioritization_issues(self) -> None:
        if not self._session:
            return
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(self, "Fehleranalyse-Exportverzeichnis waehlen", start_dir)
        if not dir_path:
            return
        try:
            created = export_prioritization_issues(self._player._messages, Path(dir_path))
        except Exception as exc:
            QMessageBox.critical(self, "Export-Fehler", str(exc))
            return
        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"Priorisierungsfehler exportiert nach {dir_path}")
        QMessageBox.information(self, "Export erfolgreich",
            "Priorisierungsfehler wurden exportiert:\n" + "\n".join(str(path) for path in created))

    def _on_export_diagnostics(self) -> None:
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(self, "Diagnose-Exportverzeichnis waehlen", start_dir)
        if not dir_path:
            return
        report_path = Path(dir_path) / "pcap2kml_diagnostics.json"
        try:
            report_path.write_text(
                json.dumps(self._build_diagnostics_report(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Diagnose-Export fehlgeschlagen", str(exc))
            return
        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"Diagnosebericht exportiert nach {report_path}", 5000)
        QMessageBox.information(self, "Diagnose exportiert",
            f"Der Diagnosebericht wurde geschrieben:\n{report_path}")

    def _build_diagnostics_report(self) -> dict[str, object]:
        memory_mb = _current_process_memory_mb()
        package_names = ["PyQt6", "PyQt6-WebEngine", "scapy", "pyshark", "asn1tools", "simplekml"]
        packages: dict[str, str] = {}
        for package_name in package_names:
            try:
                packages[package_name] = importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                packages[package_name] = "not installed"
        session_summary: dict[str, object] = {"loaded": False}
        if self._session:
            session_summary = {
                "loaded": True,
                "sources": [str(source.path) for source in self._session.sources],
                "messages": len(self._session.messages),
                "stations": len(self._session.station_ids),
                "message_types": {
                    msg_type.value: count
                    for msg_type, count in sorted(self._session.msg_type_counts.items(), key=lambda item: item[0].value)
                },
            }
        return {
            "created_at": datetime.now(UTC).isoformat(),
            "application": {
                "performance_mode": self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
                "performance_auto_downgraded": self.__dict__.get("_performance_auto_downgraded", False),
                "map_safe_mode_active": self.__dict__.get("_map_safe_mode_active", False),
                "map_backend": self.__dict__.get("_map_backend", "webengine"),
                "memory_mb": memory_mb,
            },
            "runtime": {
                "python": sys.version, "platform": platform.platform(),
                "qt": QT_VERSION_STR, "pyqt": PYQT_VERSION_STR, "packages": packages,
                "qtwebengine_flags": os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
                "qt_opengl": os.environ.get("QT_OPENGL", ""),
                "qt_opengl_dll": os.environ.get("QT_OPENGL_DLL", ""),
                "qsg_rhi_prefer_software_renderer": os.environ.get("QSG_RHI_PREFER_SOFTWARE_RENDERER", ""),
                "pcap2kml_map_backend": os.environ.get("PCAP2KML_MAP_BACKEND", ""),
                "pcap2kml_disable_gpu": os.environ.get("PCAP2KML_DISABLE_GPU", ""),
            },
            "session": session_summary,
            "map": {
                "latest_telemetry": self._map_telemetry_history[-1] if self._map_telemetry_history else None,
                "telemetry_history": self._map_telemetry_history,
                "issue_history": self._map_issue_history,
            },
        }

    def _on_reload_map(self) -> None:
        if hasattr(self._map_widget, "reload_map_page"):
            self._map_widget.reload_map_page()
        self._map_safe_mode_active = False
        self._map_issue_history.clear()
        self._apply_performance_mode()
        if self._session:
            self._map_widget.load_messages(self._player._messages)
            self._eta_map.load_messages(self._player._messages)
            self._issues_map.load_messages(self._player._messages)
        self._statusbar.showMessage("Karte wurde neu geladen", 4000)

    def _on_update_schemas(self) -> None:
        try:
            from ..asn1_schemas import update_from_git
        except ImportError:
            QMessageBox.warning(self, "Hinweis", "asn1tools ist nicht installiert.")
            return
        if update_from_git():
            self._statusbar.showMessage("ASN.1-Schemas erfolgreich aktualisiert")
            QMessageBox.information(self, "Erfolg", "ASN.1-Schemas wurden aktualisiert.")
            return
        self._statusbar.showMessage("ASN.1-Schema-Update fehlgeschlagen")
        QMessageBox.warning(self, "Fehler",
            "ASN.1-Schemas konnten nicht aktualisiert werden.\nPruefen Sie Internetverbindung und Git-Installation.")

    def _on_show_dashboard(self) -> None:
        if self._session is None:
            QMessageBox.information(self, "Dashboard", "Keine Sitzung geladen.")
            return
        dialog = StatisticsDashboard(self._session, self)
        dialog.exec()

    # ── Filter Logic ───────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        self._active_types = {msg_type for msg_type, checkbox in self._type_checkboxes.items() if checkbox.isChecked()}
        self._apply_filters()

    def _on_merge_view_changed(self, *_args) -> None:
        self._show_canonical_messages = self._merge_view_checkbox.isChecked()
        self._apply_filters()

    def _on_station_filter_changed(self) -> None:
        self._active_stations = {item.text() for item in self._station_list.selectedItems()}
        if not self._active_stations:
            self._active_stations = set(self._all_station_ids)
        self._apply_filters()

    def _apply_filters(self) -> None:
        if not self._session:
            return
        filtered = self._session.filter_messages(
            self._active_types, self._active_stations, canonical=self._show_canonical_messages)
        self._populate_message_table(filtered)
        self._map_widget.load_messages(filtered)
        self._eta_map.load_messages(filtered)
        self._issues_map.load_messages(filtered)
        self._reset_playback_render_caches()
        self._player.set_filtered_messages(filtered)
        self._refresh_problem_replay_indices(filtered)
        self._update_scene_for_message(filtered[0] if filtered else None, force=True)
        self._lbl_filter_hint.setText(f"{len(filtered)} von {len(self._session.messages)} Nachrichten sichtbar")
        self._statusbar.showMessage(f"Filter aktiv: {len(filtered)} / {len(self._session.messages)} Nachrichten")
        self._update_status_metrics(len(filtered))

    def _populate_station_list(self) -> None:
        self._station_list.blockSignals(True)
        self._station_list.clear()
        for station_id in sorted(self._all_station_ids):
            item = QListWidgetItem(station_id)
            self._station_list.addItem(item)
            item.setSelected(True)
        self._station_list.blockSignals(False)

    def _populate_message_table(self, messages: list[V2xMessage] | None = None) -> None:
        if messages is None and self._session:
            messages = self._session.messages
        elif messages is None:
            messages = []
        self._message_row_lookup = {}
        self._last_highlighted_row = None
        self._last_detail_key = None
        self._pending_detail_message = None
        self._msg_table.setUpdatesEnabled(False)
        try:
            self._msg_table.setRowCount(len(messages))
            for row, msg in enumerate(messages):
                timestamp_text = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
                self._message_row_lookup[(timestamp_text, msg.station_id)] = row
                self._msg_table.setItem(row, COL_TIMESTAMP, QTableWidgetItem(timestamp_text))
                self._msg_table.setItem(row, COL_STATION, QTableWidgetItem(msg.station_id))
                self._msg_table.setItem(row, COL_MSGTYPE, QTableWidgetItem(msg.msg_type.value))
                self._msg_table.setItem(row, COL_LATLON,
                    QTableWidgetItem(f"{msg.latitude:.6f}, {msg.longitude:.6f}"))
                speed_str = f"{msg.speed:.1f} m/s" if msg.speed is not None else "-"
                heading_str = f"{msg.heading:.0f} deg" if msg.heading is not None else "-"
                self._msg_table.setItem(row, COL_SPEED_HEADING,
                    QTableWidgetItem(f"{speed_str} / {heading_str}"))
                source_text = msg.source.display_name() if msg.source is not None else "-"
                merge_text = "-"
                if msg.merge_group_id:
                    merge_text = msg.merge_group_id
                    if msg.merge_confidence is not None:
                        merge_text += f" ({msg.merge_confidence:.2f})"
                self._msg_table.setItem(row, COL_SOURCE, QTableWidgetItem(source_text))
                self._msg_table.setItem(row, COL_MERGE, QTableWidgetItem(merge_text))
        finally:
            self._msg_table.setUpdatesEnabled(True)

    # ── Playback Handlers ──────────────────────────────────────────

    def _on_playback_tick(self, msg: V2xMessage | None) -> None:
        if msg is None:
            return
        if self._should_render_full_map_slice(msg):
            self._map_widget.render_playback_slice(
                self._player._messages, self._player.current_index,
                window_seconds=self._map_playback_window_seconds())
        self._map_widget.update_playback_position(msg)
        self._eta_map.update_playback_position(msg)
        self._issues_map.update_playback_position(msg)
        self._update_message_preview(msg)
        self._highlight_table_row(msg)
        self._show_security_detail(msg, auto_focus=False)
        self._update_scene_for_message(msg)
        self._eta_graph.set_current_time(msg.timestamp)

    def _update_message_preview(self, msg: V2xMessage) -> None:
        """Update the right sidebar message preview card."""
        self._msg_preview_header.setText(f"{msg.msg_type.value} · {msg.station_id}  "
            f"<span style='font-size:10px;color:{STYLE_TEXT_MUTED};font-weight:400'>"
            f"{msg.timestamp.strftime('%H:%M:%S.%f')[:-3]}</span>")
        lines = [
            f"<b>Position</b> {msg.latitude:.6f}, {msg.longitude:.6f}",
        ]
        if msg.speed is not None:
            lines.append(f"<b>Speed</b> {msg.speed:.1f} m/s")
        if msg.heading is not None:
            lines.append(f"<b>Heading</b> {msg.heading:.0f} deg")
        if msg.altitude is not None:
            lines.append(f"<b>Altitude</b> {msg.altitude:.1f} m")
        self._msg_preview_body.setText("<br>".join(lines))

    def _should_render_full_map_slice(self, msg: V2xMessage) -> bool:
        messages_id = id(self._player._messages)
        index = self._player.current_index
        now = time.perf_counter()
        if (
            self._last_map_messages_id != messages_id
            or self._last_map_slice_index is None
            or index < self._last_map_slice_index
            or now - self._last_map_slice_update_monotonic >= self._map_render_interval_seconds()
        ):
            should_render = True
        else:
            should_render = False
        if should_render:
            self._last_map_messages_id = messages_id
            self._last_map_slice_index = index
            self._last_map_slice_update_monotonic = now
        return should_render

    def _reset_playback_render_caches(self) -> None:
        self._last_scene_update_monotonic = 0.0
        self._last_scene_cache_key = None
        self._last_scene_cache_snapshot = None
        self._last_map_slice_update_monotonic = 0.0
        self._last_map_slice_index = None
        self._last_map_messages_id = None

    def _highlight_table_row(self, msg: V2xMessage) -> None:
        row = self._message_row_lookup.get(self._message_lookup_key(msg))
        if row is None or row == self._last_highlighted_row:
            return
        self._msg_table.selectRow(row)
        item = self._msg_table.item(row, COL_TIMESTAMP)
        if item is not None and not self._is_table_item_visible(item):
            self._msg_table.scrollToItem(item, QTableWidget.ScrollHint.PositionAtCenter)
        self._last_highlighted_row = row

    def _message_lookup_key(self, msg: V2xMessage) -> tuple[str, str]:
        return (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)

    def _is_table_item_visible(self, item: QTableWidgetItem) -> bool:
        rect = self._msg_table.visualItemRect(item)
        if not rect.isValid():
            return False
        return self._msg_table.viewport().rect().intersects(rect)

    def _on_player_state_changed(self, state: str) -> None:
        self._btn_play.setEnabled(state != "playing" and self._session is not None)
        self._btn_pause.setEnabled(state == "playing")

    def _on_player_position_changed(self, index: int) -> None:
        total = self._player.total_messages
        if total > 0:
            self._slider.blockSignals(True)
            self._slider.setValue(int((index / total) * 1000))
            self._slider.blockSignals(False)

    def _on_duration_changed(self, seconds: float) -> None:
        self._lbl_time.setText(f"00:00.0 / {self._player.format_time(seconds)}")

    def _on_player_time_updated(self, seconds: float) -> None:
        total_time = self._session.duration_seconds if self._session else 0.0
        self._lbl_time.setText(
            f"{self._player.format_time(seconds)} / {self._player.format_time(total_time)}")

    def _on_speed_changed(self, index: int) -> None:
        if 0 <= index < len(SPEED_OPTIONS):
            self._player.set_speed(SPEED_OPTIONS[index])

    def _on_problem_replay_toggled(self, enabled: bool) -> None:
        self._player.set_focus_replay_enabled(enabled)
        if enabled and not self._problem_replay_indices:
            self._statusbar.showMessage("Keine Problemstellen fuer den aktuellen Filter gefunden", 4000)
        elif enabled:
            self._statusbar.showMessage(
                f"Problemstellen-Replay aktiv: {len(self._problem_replay_indices)} Zeitpunkt(e)", 4000)
        else:
            self._statusbar.showMessage("Problemstellen-Replay deaktiviert", 3000)

    def _on_slider_moved(self, value: int) -> None:
        self._player.seek_to_position(value / 1000.0)

    def _on_table_row_clicked(self, row: int, _: int) -> None:
        ts_item = self._msg_table.item(row, COL_TIMESTAMP)
        station_item = self._msg_table.item(row, COL_STATION)
        if not ts_item or not station_item:
            return
        target_timestamp = ts_item.text()
        target_station = station_item.text()
        for index, msg in enumerate(self._player._messages):
            if (msg.timestamp.strftime("%H:%M:%S.%f")[:-3] == target_timestamp
                    and msg.station_id == target_station):
                self._player.seek_to_index(index)
                self._show_security_detail(msg, auto_focus=True, force_refresh=True)
                return

    def _refresh_problem_replay_indices(self, messages: list[V2xMessage]) -> None:
        indices = [occurrence.message_index for occurrence in collect_prioritization_issue_occurrences(messages)]
        self._problem_replay_indices = indices
        self._player.set_focus_indices(indices)
        if hasattr(self, "_btn_prev_issue"):
            has_issues = bool(indices)
            self._btn_prev_issue.setEnabled(has_issues)
            self._btn_next_issue.setEnabled(has_issues)
            self._chk_problem_replay.setEnabled(has_issues)
            if not has_issues:
                self._chk_problem_replay.blockSignals(True)
                self._chk_problem_replay.setChecked(False)
                self._chk_problem_replay.blockSignals(False)
                self._player.set_focus_replay_enabled(False)

    # ── Detail / Security ──────────────────────────────────────────

    def _show_security_detail(self, msg: V2xMessage, *, auto_focus: bool, force_refresh: bool = False) -> None:
        self._pending_detail_message = msg
        detail_key = self._message_lookup_key(msg)
        if not force_refresh and detail_key == self._last_detail_key:
            return
        rows = list(msg.to_detail_rows())
        if msg.security_info is None:
            rows.append(("Sicherheitsheader", "Kein Sicherheitsheader vorhanden oder nicht extrahierbar"))
        else:
            rows.extend(msg.security_info.to_table_rows())
        self._detail_table.setRowCount(len(rows))
        for index, (field, value) in enumerate(rows):
            self._detail_table.setItem(index, 0, QTableWidgetItem(field))
            self._detail_table.setItem(index, 1, QTableWidgetItem(value))
        self._detail_table.show()
        self._last_detail_key = detail_key
        try:
            btn = self._btn_verify_signature
        except RuntimeError:
            btn = None
        if btn is not None:
            if msg.security_info is not None and msg.security_info.signature_r is not None:
                btn.setEnabled(True)
                btn.show()
            else:
                btn.setEnabled(False)
                btn.hide()

    def _on_verify_signature(self) -> None:
        QMessageBox.information(self, "Signaturverifikation",
            "ECDSA-Signaturverifikation ist noch nicht implementiert.\n\n"
            "Benötigt werden:\n  - Zertifikat der ausstellenden CA\n"
            "  - Öffentlicher Schlüssel des Absenders\n"
            "  - Vollständiger signierter Payload\n\n"
            "Wenn du diese Funktion benötigst, öffne bitte ein Issue oder kontaktiere das Entwicklerteam.")

    # ── Scene Panel ────────────────────────────────────────────────

    def _update_scene_for_message(self, msg: V2xMessage | None, *, force: bool = False) -> None:
        if msg is None or not self._player._messages:
            self._refresh_prioritization_issues([])
            self._last_scene_cache_key = None
            self._last_scene_cache_snapshot = None
            if hasattr(self, "_ws_badge_labels") and "issues" in self._ws_badge_labels:
                self._ws_badge_labels["issues"].hide()
            return
        now = time.perf_counter()
        if not force and self._player.state == "playing" and now - self._last_scene_update_monotonic < 0.25:
            return
        scene_key = (id(self._player._messages), msg.timestamp.isoformat())
        if scene_key == self._last_scene_cache_key and self._last_scene_cache_snapshot is not None:
            scene = self._last_scene_cache_snapshot
        else:
            scene = build_scene_snapshot(self._player._messages, msg.timestamp)
            self._last_scene_cache_key = scene_key
            self._last_scene_cache_snapshot = scene
        self._last_scene_update_monotonic = now
        issues = build_prioritization_issues(scene)
        self._refresh_prioritization_issues(issues)
        critical_count = sum(1 for i in issues if i.severity == "error")
        if hasattr(self, "_ws_badge_labels") and "issues" in self._ws_badge_labels:
            badge = self._ws_badge_labels["issues"]
            if critical_count > 0:
                badge.setText(str(critical_count))
                badge.show()
            else:
                badge.hide()

    # ── Prioritization Issues ──────────────────────────────────────

    def _refresh_prioritization_issues(self, issues: list[PrioritizationIssue]) -> None:
        self._current_prioritization_issues = issues
        if not hasattr(self, "_issue_list"):
            return
        self._issue_list.clear()
        self._refresh_issue_intersection_filter(issues)
        if not issues:
            self._issue_summary.setText("Keine priorisierungsrelevanten Fehler im aktuellen Zeitpunkt.")
            self._issue_badge.setText("0")
            return
        filtered_issues = self._filter_prioritization_issues(issues)
        errors = sum(1 for issue in filtered_issues if issue.severity == "error")
        warnings_count = len(filtered_issues) - errors
        filter_suffix = "" if len(filtered_issues) == len(issues) else f" von {len(issues)}"
        self._issue_summary.setText(
            f"{errors} Fehler, {warnings_count} Warnung(en){filter_suffix}. Klick fokussiert Request.")
        self._issue_badge.setText(str(len(filtered_issues)))
        if not filtered_issues:
            self._issue_summary.setText(f"Keine Fehler im aktuellen Filter ({len(issues)} insgesamt).")
            return
        for issue in filtered_issues:
            item = QListWidgetItem(self._format_issue_item(issue))
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue.message)
            self._issue_list.addItem(item)

    def _refresh_issue_intersection_filter(self, issues: list[PrioritizationIssue]) -> None:
        if not hasattr(self, "_issue_intersection_combo"):
            return
        current = self._issue_intersection_combo.currentData() or "all"
        intersection_ids = sorted({issue.intersection_id for issue in issues})
        self._issue_intersection_combo.blockSignals(True)
        self._issue_intersection_combo.clear()
        self._issue_intersection_combo.addItem("Alle Kreuzungen", "all")
        for intersection_id in intersection_ids:
            self._issue_intersection_combo.addItem(f"I{intersection_id}", str(intersection_id))
        index = self._issue_intersection_combo.findData(current)
        self._issue_intersection_combo.setCurrentIndex(index if index >= 0 else 0)
        self._issue_intersection_combo.blockSignals(False)
        self._issue_filter_intersection = str(self._issue_intersection_combo.currentData() or "all")

    def _filter_prioritization_issues(self, issues: list[PrioritizationIssue]) -> list[PrioritizationIssue]:
        mode = getattr(self, "_issue_filter_mode", "all")
        intersection_filter = getattr(self, "_issue_filter_intersection", "all")
        filtered = issues
        if mode == "critical":
            filtered = [issue for issue in filtered if issue.severity == "error"]
        if mode == "intersection" and intersection_filter == "all":
            return filtered
        if intersection_filter != "all":
            try:
                intersection_id = int(intersection_filter)
            except ValueError:
                return filtered
            filtered = [issue for issue in filtered if issue.intersection_id == intersection_id]
        return filtered

    def _on_issue_filter_changed(self, *_args) -> None:
        if hasattr(self, "_issue_filter_combo"):
            self._issue_filter_mode = str(self._issue_filter_combo.currentData() or "all")
        if hasattr(self, "_issue_intersection_combo"):
            self._issue_filter_intersection = str(self._issue_intersection_combo.currentData() or "all")
        issues = list(getattr(self, "_current_prioritization_issues", []))
        if issues:
            self._refresh_prioritization_issues(issues)

    def _format_issue_item(self, issue: PrioritizationIssue) -> str:
        lane_text = f"{issue.in_lane or '-'} -> {issue.out_lane or '-'}"
        delay_text = f"\nDelay: {issue.delay_seconds:.2f}s" if issue.delay_seconds is not None else ""
        return (
            f"{issue.issue_type}\n"
            f"I{issue.intersection_id} | Req {issue.request_id}/Seq {issue.sequence_number}\n"
            f"Lane {lane_text} | {issue.station_id}{delay_text}\n"
            f"{issue.source_summary}"
        )

    def _on_prioritization_issue_clicked(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(issue, PrioritizationIssue):
            return
        self._map_widget.highlight_request(issue.intersection_id, issue.request_id, issue.sequence_number)
        self._map_widget.focus_intersection(issue.intersection_id)
        self._select_eta_issue(issue)
        self._select_issue_message(issue)

    def _select_eta_issue(self, issue: PrioritizationIssue) -> None:
        prefix = f"REQ:{issue.intersection_id}:{issue.request_id}:{issue.sequence_number}:{issue.station_id}:"
        for index in range(self._eta_station_combo.count()):
            key = self._eta_station_combo.itemData(index)
            if isinstance(key, str) and key.startswith(prefix):
                self._eta_station_combo.setCurrentIndex(index)
                return

    def _select_issue_message(self, issue: PrioritizationIssue) -> None:
        for index, msg in enumerate(self._player._messages):
            if msg.msg_type not in {MessageType.SREM, MessageType.SSEM}:
                continue
            if (
                self._coerce_detail_int(msg.decoded_data.get("intersectionId")) == issue.intersection_id
                and self._coerce_detail_int(msg.decoded_data.get("requestId")) == issue.request_id
                and self._coerce_detail_int(msg.decoded_data.get("sequenceNumber")) == issue.sequence_number
            ):
                self._player.seek_to_index(index)
                self._highlight_table_row(msg)
                self._show_security_detail(msg, auto_focus=True, force_refresh=True)
                return

    def _coerce_detail_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        if isinstance(value, tuple) and len(value) >= 2:
            return self._coerce_detail_int(value[1])
        if isinstance(value, dict):
            for key in ("id", "value", "requestId", "requestID", "sequenceNumber"):
                nested = self._coerce_detail_int(value.get(key))
                if nested is not None:
                    return nested
        return None

    # ── ETA Analysis ───────────────────────────────────────────────

    def _refresh_eta_analysis(self, messages: list[V2xMessage]) -> None:
        options = build_eta_selection_options(messages)
        current_key = self._eta_station_combo.currentData()
        self._eta_station_combo.blockSignals(True)
        self._eta_station_combo.clear()
        for option in options:
            self._eta_station_combo.addItem(option.label, option.key)
        if current_key:
            for index in range(self._eta_station_combo.count()):
                if self._eta_station_combo.itemData(index) == current_key:
                    self._eta_station_combo.setCurrentIndex(index)
                    break
        self._eta_station_combo.blockSignals(False)
        selected_key = self._eta_station_combo.currentData()
        self._eta_graph.set_messages(messages)
        self._eta_graph.set_selection(selected_key)
        self._eta_graph.set_current_time(messages[0].timestamp if messages else None)
        self._eta_summary.setText(self._eta_graph.summary_text())
        self._refresh_eta_metrics()
        self._refresh_eta_dashboard()

    def _on_eta_station_changed(self, station_id: str) -> None:
        self._eta_graph.set_selection(self._eta_station_combo.currentData())
        self._eta_summary.setText(self._eta_graph.summary_text())
        self._refresh_eta_metrics()
        self._refresh_eta_dashboard()

    def _refresh_eta_metrics(self) -> None:
        data = self._eta_graph.dashboard_data()
        if data.metrics:
            for i, (metric, value) in enumerate(data.metrics[:3]):
                metric_widgets = [self._eta_metric_1, self._eta_metric_2, self._eta_metric_3]
                if i < len(metric_widgets):
                    card = metric_widgets[i]
                    vl = card.findChild(QLabel)
                    if vl:
                        vl.setText(str(value))

    def _refresh_eta_dashboard(self) -> None:
        if not hasattr(self, "_eta_metric_table") or not hasattr(self, "_eta_event_table"):
            return
        data = self._eta_graph.dashboard_data()
        self._eta_metric_table.setRowCount(len(data.metrics))
        for row, (metric, value) in enumerate(data.metrics):
            self._eta_metric_table.setItem(row, 0, QTableWidgetItem(metric))
            self._eta_metric_table.setItem(row, 1, QTableWidgetItem(value))
        self._eta_event_table.setRowCount(len(data.events))
        for row, event in enumerate(data.events):
            values = [event.time_text, event.kind, event.content, event.details]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, event)
                self._eta_event_table.setItem(row, column, item)

    def _on_eta_event_clicked(self, item: QTableWidgetItem) -> None:
        event = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(event, EtaDashboardEvent):
            return
        if event.message_type is not None and self._seek_eta_event_message(event):
            return
        self._focus_eta_event_request(event)

    def _seek_eta_event_message(self, event: EtaDashboardEvent) -> bool:
        for index, msg in enumerate(self._player._messages):
            if msg.msg_type != event.message_type:
                continue
            if abs((msg.timestamp - event.timestamp).total_seconds()) > 0.001:
                continue
            if not self._message_matches_eta_event_selection(msg, event):
                continue
            self._player.seek_to_index(index)
            self._highlight_table_row(msg)
            self._show_security_detail(msg, auto_focus=True, force_refresh=True)
            self._focus_eta_event_request(event)
            self._statusbar.showMessage(f"ETA-Ereignis geoeffnet: {event.kind} {event.time_text}", 4000)
            return True
        self._focus_eta_event_request(event)
        self._statusbar.showMessage(
            f"Keine passende Nachricht fuer ETA-Ereignis {event.time_text} gefunden", 4000)
        return False

    def _message_matches_eta_event_selection(self, msg: V2xMessage, event: EtaDashboardEvent) -> bool:
        key_parts = (event.selection_key or "").split(":")
        if len(key_parts) < 6 or key_parts[0] != "REQ":
            return True
        intersection_id = self._coerce_detail_int(key_parts[1])
        request_id = self._coerce_detail_int(key_parts[2])
        sequence_number = self._coerce_detail_int(key_parts[3])
        station_id = key_parts[4]
        if msg.msg_type == MessageType.SREM and msg.station_id != station_id:
            return False
        return (
            self._coerce_detail_int(msg.decoded_data.get("intersectionId")) == intersection_id
            and self._coerce_detail_int(msg.decoded_data.get("requestId")) == request_id
            and self._coerce_detail_int(msg.decoded_data.get("sequenceNumber")) == sequence_number
        )

    def _focus_eta_event_request(self, event: EtaDashboardEvent) -> None:
        key_parts = (event.selection_key or "").split(":")
        if len(key_parts) < 6 or key_parts[0] != "REQ":
            return
        intersection_id = self._coerce_detail_int(key_parts[1])
        request_id = self._coerce_detail_int(key_parts[2])
        sequence_number = self._coerce_detail_int(key_parts[3])
        if intersection_id is None or request_id is None or sequence_number is None:
            return
        self._map_widget.highlight_request(intersection_id, request_id, sequence_number)
        self._map_widget.focus_intersection(intersection_id)

    def _on_export_eta_dashboard(self) -> None:
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(self, "ETA-Dashboard-Exportverzeichnis waehlen", start_dir)
        if not dir_path:
            return
        target_dir = Path(dir_path)
        data = self._eta_graph.dashboard_data()
        csv_path = target_dir / "eta_dashboard.csv"
        json_path = target_dir / "eta_dashboard.json"
        try:
            self._write_eta_dashboard_exports(data, csv_path, json_path)
        except Exception as exc:
            QMessageBox.critical(self, "ETA-Export fehlgeschlagen", str(exc))
            return
        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"ETA-Dashboard exportiert nach {target_dir}", 5000)
        QMessageBox.information(self, "ETA exportiert",
            f"ETA-Dashboard wurde exportiert:\n{csv_path}\n{json_path}")

    def _write_eta_dashboard_exports(self, data, csv_path: Path, json_path: Path) -> None:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["Bereich", "Kennzahl/Zeit", "Typ", "Inhalt", "Details"])
            for metric, value in data.metrics:
                writer.writerow(["Kennzahl", metric, "", value, ""])
            for event in data.events:
                writer.writerow(["Ereignis", event.time_text, event.kind, event.content, event.details])
        json_payload = {
            "metrics": [{"name": metric, "value": value} for metric, value in data.metrics],
            "events": [{
                "time": event.time_text, "kind": event.kind, "content": event.content,
                "details": event.details, "timestamp": event.timestamp.isoformat(),
                "message_type": event.message_type.value if event.message_type else None,
                "selection_key": event.selection_key,
            } for event in data.events],
        }
        json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Map Telemetry ──────────────────────────────────────────────

    def _on_map_telemetry_updated(self, telemetry: dict[str, object]) -> None:
        history = self.__dict__.get("_map_telemetry_history", [])
        history.append(dict(telemetry))
        del history[:-MAP_TELEMETRY_HISTORY_LIMIT]
        dropped_total = sum(
            int(telemetry.get(key, 0) or 0) for key in (
                "budget_dropped_markers", "budget_dropped_infrastructure",
                "budget_dropped_trajectories", "budget_dropped_trajectory_points",
            )
        )
        if dropped_total and self._performance_mode == PERFORMANCE_MODE_NORMAL:
            self._set_performance_mode(PERFORMANCE_MODE_SAVER, auto=True)
            self._statusbar.showMessage(
                "Karten-Payload war zu gross - Leistung automatisch auf Schonend reduziert", 5000)

    def _on_map_issue_detected(self, message: str) -> None:
        logger.info("Map issue detected: %s", message)
        issues = self.__dict__.get("_map_issue_history", [])
        issues.append(message)
        del issues[:-20]
        if self._should_fallback_to_native_map(message):
            logger.warning("Fatal map issue — switching to native fallback: %s", message)
            self._replace_map_widget("webengine", persist=False)
            self._statusbar.showMessage(
                f"Karte auf Native-Fallback gewechselt: {message}", 8000)
            return
        if self.__dict__.get("_map_safe_mode_active", False):
            return
        if len(issues) < MAP_SAFE_MODE_ISSUE_THRESHOLD:
            self._statusbar.showMessage(f"Kartenhinweis: {message}", 5000)
            return
        self._map_safe_mode_active = True
        self._set_performance_mode(PERFORMANCE_MODE_DIAGNOSTIC, auto=True)
        self._statusbar.showMessage(
            "Karten-Safe-Mode aktiv: wiederholte WebEngine/JavaScript-Probleme erkannt", 8000)

    # ── State Management ───────────────────────────────────────────

    def _update_controls_enabled(self, enabled: bool) -> None:
        self._btn_play.setEnabled(enabled)
        self._btn_pause.setEnabled(False)
        self._btn_stop.setEnabled(enabled)
        self._btn_export_kml.setEnabled(enabled)
        self._btn_export_issues.setEnabled(enabled)
        self._btn_export_diagnostics.setEnabled(True)
        self._btn_reload_map.setEnabled(True)
        self._slider.setEnabled(enabled)
        self._speed_combo.setEnabled(enabled)
        has_issues = enabled and bool(self._problem_replay_indices)
        self._btn_prev_issue.setEnabled(has_issues)
        self._btn_next_issue.setEnabled(has_issues)
        self._chk_problem_replay.setEnabled(has_issues)
        self._btn_reload_last.setEnabled(bool(self._memory.existing_last_session_files()))

    def _set_loading_state(self, loading: bool, minimum: int = 0, maximum: int = 0, status_message: str = "") -> None:
        self._progress.setVisible(loading)
        self._progress.setRange(minimum, maximum)
        self._progress.setValue(minimum)
        self._btn_load.setEnabled(not loading)
        self._btn_reload_last.setEnabled(not loading and bool(self._memory.existing_last_session_files()))
        self._btn_cancel_load.setEnabled(loading)
        if status_message:
            self._statusbar.showMessage(status_message)

    def _update_overview_for_session(self, paths: list[str], session: SessionData) -> None:
        self._update_status_metrics(len(session.messages))

    def _refresh_memory_banner(self) -> None:
        last_files = self._memory.existing_last_session_files()
        if last_files:
            self._status_metrics.setText("Bereit fuer letzte Sitzung")
            return
        self._status_metrics.setText("Noch keine Sitzung geladen")

    def _update_status_metrics(self, visible_messages: int) -> None:
        if not self._session:
            self._status_metrics.setText("Noch keine Sitzung geladen")
            return
        self._status_metrics.setText(
            f"Sichtbar: {visible_messages} | Stationen: {len(self._active_stations)} | "
            f"Dauer: {self._player.format_time(self._session.duration_seconds)}"
        )

    def _clear_session_views(self) -> None:
        self._map_widget.clear()
        self._msg_table.setRowCount(0)
        self._message_row_lookup = {}
        self._last_highlighted_row = None
        self._last_detail_key = None
        self._pending_detail_message = None
        self._problem_replay_indices = []
        self._refresh_prioritization_issues([])
        self._detail_table.hide()
        if hasattr(self, "_eta_station_combo"):
            self._eta_station_combo.blockSignals(True)
            self._eta_station_combo.clear()
            self._eta_station_combo.blockSignals(False)
        if hasattr(self, "_eta_graph"):
            self._eta_graph.set_messages([])
            self._eta_graph.set_selection(None)
            self._eta_graph.set_current_time(None)
            self._refresh_eta_dashboard()
        if hasattr(self, "_eta_summary"):
            self._eta_summary.setText("Keine PCAP-Sitzung geladen.")
        self._reset_playback_render_caches()
        self._issue_filter_mode = "all"
        self._issue_filter_intersection = "all"
        if hasattr(self, "_issue_filter_combo"):
            self._issue_filter_combo.blockSignals(True)
            self._issue_filter_combo.setCurrentIndex(0)
            self._issue_filter_combo.blockSignals(False)
        if hasattr(self, "_issue_intersection_combo"):
            self._issue_intersection_combo.blockSignals(True)
            self._issue_intersection_combo.clear()
            self._issue_intersection_combo.addItem("Alle Kreuzungen", "all")
            self._issue_intersection_combo.blockSignals(False)
        self._player.set_filtered_messages([])
        self._player.set_focus_indices([])
        self._player.set_focus_replay_enabled(False)
        self._all_station_ids.clear()
        self._active_stations.clear()
        self._station_list.clear()
        self._show_canonical_messages = False
        if hasattr(self, "_merge_view_checkbox"):
            self._merge_view_checkbox.blockSignals(True)
            self._merge_view_checkbox.setChecked(False)
            self._merge_view_checkbox.blockSignals(False)
        self._lbl_filter_hint.setText("Alle Typen und Stationen aktiv")
        self._update_controls_enabled(False)

    # ── Window State ───────────────────────────────────────────────

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._memory.save()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(
            url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".pcap", ".pcapng", ".cap"}
            for url in urls
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".pcap", ".pcapng", ".cap"}
        ]
        if paths:
            self._load_paths(paths)
            event.acceptProposedAction()
            return
        event.ignore()
