"""PyQt6 main window for PCAP2KML Player."""

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
    QSettings,
    Qt,
    QThread,
    QTimer,
)
from PyQt6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..app_memory import AppMemory
from ..data_model import MessageType, SessionData, V2xMessage
from ..kml_exporter import export_kml
from ..map_backend import (
    MAP_BACKEND_NATIVE,
    MAP_BACKEND_WEBENGINE,
    MAP_BACKENDS,
    MAP_PERFORMANCE_DIAGNOSTIC,
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
    create_map_widget,
    selected_map_backend_name,
)
from ..parsing_worker import ParsingWorker
from ..player_controller import SPEED_OPTIONS, PlayerController
from ..prioritization_exporter import export_prioritization_issues
from ..scene_model import (
    ActiveRequest,
    PrioritizationIssue,
    SceneSnapshot,
    build_prioritization_issues,
    build_scene_snapshot,
    collect_prioritization_issue_occurrences,
    find_overdue_requests,
    get_clock_skew_warnings,
    get_eta_accuracy_seconds,
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
COMPACT_LAYOUT_WIDTH = 1320
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
LAYOUT_MODE_AUTO = "auto"
LAYOUT_MODE_DESKTOP = "desktop"
LAYOUT_MODE_COMPACT = "compact"
COMPACT_MESSAGE_COLUMNS = {COL_TIMESTAMP, COL_STATION, COL_MSGTYPE, COL_SPEED_HEADING}


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


class MainWindow(QMainWindow):
    """Main application window for PCAP2KML Player."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCAP2KML Player")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)
        self.setAcceptDrops(True)

        self._memory = AppMemory.load()
        self._settings = QSettings("PCAP2KML", "Player")
        self._layout_preference = str(self._settings.value("ui/layout_mode", LAYOUT_MODE_AUTO))
        if self._layout_preference not in {
            LAYOUT_MODE_AUTO,
            LAYOUT_MODE_DESKTOP,
            LAYOUT_MODE_COMPACT,
        }:
            self._layout_preference = LAYOUT_MODE_AUTO
        self._performance_mode = str(self._settings.value("ui/performance_mode", PERFORMANCE_MODE_NORMAL))
        if self._performance_mode not in PERFORMANCE_MODE_LABELS:
            self._performance_mode = PERFORMANCE_MODE_NORMAL
        self._performance_auto_downgraded = False
        self._last_memory_warning_level = ""
        self._map_backend = str(self._settings.value("ui/map_backend", selected_map_backend_name()))
        if self._map_backend not in MAP_BACKENDS:
            self._map_backend = MAP_BACKEND_WEBENGINE
        self._is_compact_layout = False
        self._overview_collapsed = self._settings.value(
            "ui/header_collapsed",
            False,
            type=bool,
        )

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
        self._issue_panel_collapsed = False
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
        self._apply_responsive_layout(force=True)
        self._setup_memory_watchdog()

    def _setup_ui(self) -> None:
        """Build the complete UI layout."""
        self._setup_toolbar()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        self._setup_overview_panel(main_layout)
        self._setup_filter_row(main_layout)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._map_widget = create_map_widget(backend=self._map_backend)
        self._splitter.addWidget(self._setup_map_area())
        self._splitter.addWidget(self._setup_message_list())
        self._splitter.setStretchFactor(0, 7)
        self._splitter.setStretchFactor(1, 3)
        main_layout.addWidget(self._splitter, stretch=1)

        self._setup_playback_controls(main_layout)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_metrics = QLabel("Noch keine Sitzung geladen")
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedWidth(180)
        self._statusbar.addPermanentWidget(self._status_metrics)
        self._statusbar.addPermanentWidget(self._progress)
        self._statusbar.showMessage("Bereit - PCAP-Datei laden oder per Drag & Drop ablegen")

    def _setup_map_area(self) -> QWidget:
        """Create the map with a compact prioritization issue side panel."""
        container = QWidget()
        layout = QHBoxLayout(container)
        self._map_area_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._map_widget, stretch=1)

        issue_panel = QFrame()
        self._issue_panel = issue_panel
        issue_panel.setObjectName("PrioritizationIssuePanel")
        issue_panel.setMinimumWidth(260)
        issue_panel.setMaximumWidth(320)
        issue_panel.setStyleSheet(
            "QFrame#PrioritizationIssuePanel {background: #f8fbff; border: 1px solid #d7dde8; border-radius: 10px;}"
        )
        issue_layout = QVBoxLayout(issue_panel)
        issue_layout.setContentsMargins(10, 10, 10, 10)
        issue_layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self._issue_panel_title = QLabel("Priorisierungsfehler")
        self._issue_panel_title.setStyleSheet("font-weight: 700; color: #10233f;")
        self._btn_toggle_issue_panel = QPushButton("Einklappen")
        self._btn_toggle_issue_panel.setCheckable(True)
        self._btn_toggle_issue_panel.setToolTip("Priorisierungsfehler-Panel ein- oder ausklappen")
        self._btn_toggle_issue_panel.toggled.connect(self._toggle_issue_panel_collapsed)
        header_row.addWidget(self._issue_panel_title, stretch=1)
        header_row.addWidget(self._btn_toggle_issue_panel)
        issue_layout.addLayout(header_row)

        self._issue_content = QWidget()
        issue_content_layout = QVBoxLayout(self._issue_content)
        issue_content_layout.setContentsMargins(0, 0, 0, 0)
        issue_content_layout.setSpacing(6)

        self._issue_summary = QLabel("Keine Fehler.")
        self._issue_summary.setWordWrap(True)
        self._issue_summary.setStyleSheet("color: #42546b; font-size: 11px;")
        issue_content_layout.addWidget(self._issue_summary)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        self._issue_filter_combo = QComboBox()
        self._issue_filter_combo.addItem("Alle", "all")
        self._issue_filter_combo.addItem("Nur kritisch", "critical")
        self._issue_filter_combo.addItem("Aktuelle Kreuzung", "intersection")
        self._issue_filter_combo.setToolTip("Priorisierungsfehler nach Schwere oder Kreuzung filtern")
        self._issue_filter_combo.currentIndexChanged.connect(self._on_issue_filter_changed)
        self._issue_intersection_combo = QComboBox()
        self._issue_intersection_combo.addItem("Alle Kreuzungen", "all")
        self._issue_intersection_combo.setToolTip("Fehler auf eine Kreuzung eingrenzen")
        self._issue_intersection_combo.currentIndexChanged.connect(self._on_issue_filter_changed)
        filter_row.addWidget(self._issue_filter_combo, stretch=1)
        filter_row.addWidget(self._issue_intersection_combo, stretch=1)
        issue_content_layout.addLayout(filter_row)

        self._issue_list = QListWidget()
        self._issue_list.setAlternatingRowColors(True)
        self._issue_list.setStyleSheet(
            "QListWidget {"
            " background: #ffffff;"
            " alternate-background-color: #eaf5ff;"
            " color: #10233f;"
            " border: 1px solid #d7dde8;"
            " border-radius: 10px;"
            " selection-background-color: #cfe8ff;"
            " selection-color: #000000;"
            "}"
            "QListWidget::item { padding: 7px; border: none; color: #10233f; }"
            "QListWidget::item:alternate { background: #eaf5ff; color: #10233f; }"
            "QListWidget::item:selected { background: #cfe8ff; color: #000000; }"
        )
        self._issue_list.itemClicked.connect(self._on_prioritization_issue_clicked)
        issue_content_layout.addWidget(self._issue_list, stretch=1)
        issue_layout.addWidget(self._issue_content, stretch=1)

        layout.addWidget(issue_panel)
        return container

    def _setup_toolbar(self) -> None:
        """Create the toolbar with file operations."""
        toolbar = QToolBar("Hauptwerkzeugleiste")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._btn_load = QPushButton("PCAP laden")
        self._btn_load.setToolTip("Eine oder mehrere PCAP-Dateien oeffnen")
        toolbar.addWidget(self._btn_load)

        self._btn_reload_last = QPushButton("Letzte Sitzung")
        self._btn_reload_last.setToolTip("Zuletzt geoeffnete Dateien erneut laden")
        toolbar.addWidget(self._btn_reload_last)

        self._btn_cancel_load = QPushButton("Laden abbrechen")
        self._btn_cancel_load.setToolTip("Aktuellen Parse-Vorgang abbrechen")
        self._btn_cancel_load.setEnabled(False)
        toolbar.addWidget(self._btn_cancel_load)

        toolbar.addSeparator()

        self._btn_export_kml = QPushButton("KML exportieren")
        self._btn_export_kml.setToolTip("KML-Dateien fuer alle gefilterten Entitaeten exportieren")
        toolbar.addWidget(self._btn_export_kml)

        self._btn_export_issues = QPushButton("Fehler exportieren")
        self._btn_export_issues.setToolTip(
            "Priorisierungsfehler als lesbare CSV, Maschinen-CSV, JSON und Report exportieren"
        )
        toolbar.addWidget(self._btn_export_issues)

        self._btn_export_diagnostics = QPushButton("Diagnose exportieren")
        self._btn_export_diagnostics.setToolTip(
            "Technischen Diagnosebericht mit RAM-, Karten- und Paketinformationen schreiben"
        )
        toolbar.addWidget(self._btn_export_diagnostics)

        self._btn_reload_map = QPushButton("Karte neu laden")
        self._btn_reload_map.setToolTip("WebEngine-Karte neu initialisieren und aktuelle Sitzung erneut rendern")
        toolbar.addWidget(self._btn_reload_map)

        toolbar.addSeparator()

        self._btn_update_schemas = QPushButton("ASN.1-Schemas aktualisieren")
        self._btn_update_schemas.setToolTip("ASN.1-Schemadateien aus dem Git-Repo aktualisieren")
        toolbar.addWidget(self._btn_update_schemas)

        self._btn_dashboard = QPushButton("Dashboard")
        self._btn_dashboard.setToolTip("Statistik-Dashboard anzeigen")
        toolbar.addWidget(self._btn_dashboard)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Layout:"))
        self._layout_mode_combo = QComboBox()
        self._layout_mode_combo.addItem("Auto", LAYOUT_MODE_AUTO)
        self._layout_mode_combo.addItem("Desktop", LAYOUT_MODE_DESKTOP)
        self._layout_mode_combo.addItem("Kompakt", LAYOUT_MODE_COMPACT)
        self._layout_mode_combo.setToolTip("Layoutmodus automatisch oder manuell waehlen")
        self._layout_mode_combo.setFixedWidth(110)
        for index in range(self._layout_mode_combo.count()):
            if self._layout_mode_combo.itemData(index) == self._layout_preference:
                self._layout_mode_combo.setCurrentIndex(index)
                break
        toolbar.addWidget(self._layout_mode_combo)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Karte:"))
        self._map_backend_combo = QComboBox()
        self._map_backend_combo.addItem("Leaflet", MAP_BACKEND_WEBENGINE)
        self._map_backend_combo.addItem("Native", MAP_BACKEND_NATIVE)
        self._map_backend_combo.setToolTip("Leaflet/WebEngine mit Basiskarten oder native Qt-Fallbackkarte waehlen")
        self._map_backend_combo.setFixedWidth(110)
        for index in range(self._map_backend_combo.count()):
            if self._map_backend_combo.itemData(index) == self._map_backend:
                self._map_backend_combo.setCurrentIndex(index)
                break
        toolbar.addWidget(self._map_backend_combo)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Leistung:"))
        self._performance_mode_combo = QComboBox()
        self._performance_mode_combo.addItem("Normal", PERFORMANCE_MODE_NORMAL)
        self._performance_mode_combo.addItem("Schonend", PERFORMANCE_MODE_SAVER)
        self._performance_mode_combo.addItem("Diagnose", PERFORMANCE_MODE_DIAGNOSTIC)
        self._performance_mode_combo.setToolTip(
            "Kartenrendering fuer starke Rechner, schwache Notebooks oder Diagnose reduzieren"
        )
        self._performance_mode_combo.setFixedWidth(120)
        for index in range(self._performance_mode_combo.count()):
            if self._performance_mode_combo.itemData(index) == self._performance_mode:
                self._performance_mode_combo.setCurrentIndex(index)
                break
        toolbar.addWidget(self._performance_mode_combo)

        self._memory_watch_label = QLabel("RAM: -")
        self._memory_watch_label.setToolTip("Arbeitsspeicher des App-Prozesses")
        toolbar.addWidget(self._memory_watch_label)

    def _setup_overview_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the SWARCO-inspired overview header."""
        panel = QFrame()
        self._overview_panel = panel
        panel.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #d7dde8; border-radius: 16px; }")
        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(12, 10, 12, 10)
        outer_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self._overview_compact_label = QLabel("PCAP2KML Player")
        self._overview_compact_label.setStyleSheet("font-weight: 700; color: #10233f;")
        self._btn_toggle_overview = QPushButton("Header einklappen")
        self._btn_toggle_overview.setCheckable(True)
        self._btn_toggle_overview.setToolTip("Kopfbereich ein- oder ausklappen")
        self._btn_toggle_overview.toggled.connect(self._set_overview_collapsed)
        header_row.addWidget(self._overview_compact_label, stretch=1)
        header_row.addWidget(self._btn_toggle_overview)
        outer_layout.addLayout(header_row)

        self._overview_content = QWidget()
        layout = QHBoxLayout(self._overview_content)
        layout.setContentsMargins(0, 0, 0, 0)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        self._lbl_title = QLabel("PCAP2KML Player")
        self._lbl_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #10233f;")
        self._lbl_subtitle = QLabel("Datenorientierte V2X-Analyse in einer klaren, operativen SWARCO-ITS-Anmutung.")
        self._lbl_subtitle.setStyleSheet("color: #5a6b81;")
        self._lbl_memory = QLabel("")
        self._lbl_memory.setStyleSheet("color: #b2192b; font-weight: 700;")

        text_layout.addWidget(self._lbl_title)
        text_layout.addWidget(self._lbl_subtitle)
        text_layout.addWidget(self._lbl_memory)

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)
        self._stat_files = self._create_stat_card("Dateien", "0")
        self._stat_messages = self._create_stat_card("Nachrichten", "0")
        self._stat_stations = self._create_stat_card("Stationen", "0")
        stats_layout.addWidget(self._stat_files)
        stats_layout.addWidget(self._stat_messages)
        stats_layout.addWidget(self._stat_stations)

        layout.addLayout(text_layout, stretch=1)
        layout.addLayout(stats_layout)
        outer_layout.addWidget(self._overview_content)
        parent_layout.addWidget(panel)
        self._set_overview_collapsed(self._overview_collapsed)

    def _create_stat_card(self, title: str, value: str) -> QFrame:
        """Create a compact summary card."""
        card = QFrame()
        card.setMinimumWidth(130)
        card.setStyleSheet("QFrame { background: #f5f7fb; border: 1px solid #d7dde8; border-radius: 14px; }")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        label_title = QLabel(title)
        label_title.setStyleSheet("color: #667891; font-size: 12px; font-weight: 600;")
        label_value = QLabel(value)
        label_value.setObjectName("value")
        label_value.setStyleSheet("color: #10233f; font-size: 22px; font-weight: 700;")
        layout.addWidget(label_title)
        layout.addWidget(label_value)
        return card

    def _set_stat_card_value(self, card: QFrame, value: str) -> None:
        """Update the numeric value of a stat card."""
        label = card.findChild(QLabel, "value")
        if label:
            label.setText(value)
        self._update_compact_overview_text()

    def _set_overview_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the overview header."""
        self._overview_collapsed = collapsed
        self._settings.setValue("ui/header_collapsed", collapsed)
        if hasattr(self, "_overview_content"):
            self._overview_content.setVisible(not collapsed)
        if hasattr(self, "_btn_toggle_overview"):
            self._btn_toggle_overview.setText("Header anzeigen" if collapsed else "Header einklappen")
            self._btn_toggle_overview.setChecked(collapsed)
        self._update_compact_overview_text()

    def _update_compact_overview_text(self) -> None:
        """Render a compact one-line session summary for small screens."""
        if not hasattr(self, "_overview_compact_label"):
            return
        if self._session is not None:
            text = (
                "PCAP2KML | "
                f"{len(self._session.sources) or 1} Datei(en) | "
                f"{len(self._session.messages)} Nachrichten | "
                f"{len(self._session.station_ids)} Stationen"
            )
        else:
            text = "PCAP2KML Player | Bereit zum Laden einer PCAP-Sitzung"
        self._overview_compact_label.setText(text)

    def _setup_filter_row(self, parent_layout: QVBoxLayout) -> None:
        """Create the filter row with type and station filters."""
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)

        filter_layout.addWidget(QLabel("Nachrichtentyp:"))
        self._type_checkboxes: dict[MessageType, QCheckBox] = {}
        for msg_type in MessageType:
            checkbox = QCheckBox(msg_type.value)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self._on_filter_changed)
            self._type_checkboxes[msg_type] = checkbox
            filter_layout.addWidget(checkbox)

        filter_layout.addSpacing(16)
        filter_layout.addWidget(QLabel("Stationen:"))

        self._station_list = QListWidget()
        self._station_list.setMaximumHeight(92)
        self._station_list.setMinimumWidth(260)
        self._station_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        filter_layout.addWidget(self._station_list)

        self._lbl_filter_hint = QLabel("Alle Typen und Stationen aktiv")
        self._lbl_filter_hint.setStyleSheet("color: #667891;")
        filter_layout.addWidget(self._lbl_filter_hint)
        self._merge_view_checkbox = QCheckBox("Gemergte Sicht")
        self._merge_view_checkbox.setToolTip("TXA/RXA-Mehrfachbeobachtungen nur einmal kanonisch anzeigen")
        self._merge_view_checkbox.stateChanged.connect(self._on_merge_view_changed)
        filter_layout.addWidget(self._merge_view_checkbox)
        filter_layout.addStretch()
        parent_layout.addWidget(filter_widget)

    def _setup_message_list(self) -> QWidget:
        """Create the message table plus a tabbed context area."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        header_label = QLabel("Nachrichten")
        header_label.setStyleSheet("font-weight: 700; color: #10233f;")
        self._btn_toggle_message_table = QPushButton("Tabelle maximieren")
        self._btn_toggle_message_table.setCheckable(True)
        self._btn_toggle_message_table.setToolTip(
            "Die Nachrichtentabelle auf kleinen Bildschirmen voruebergehend vergroessern"
        )
        header_row.addWidget(header_label)
        header_row.addStretch()
        header_row.addWidget(self._btn_toggle_message_table)
        layout.addLayout(header_row)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        self._msg_table = QTableWidget(0, NUM_COLUMNS)
        self._msg_table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self._msg_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._msg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._msg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._msg_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._msg_table)
        self._msg_table.verticalHeader().setVisible(False)
        table_layout.addWidget(self._msg_table)

        self._context_tabs = QTabWidget()
        self._context_tabs.setDocumentMode(True)
        self._context_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._context_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #d7dde8; border-radius: 10px; background: #ffffff; }"
            "QTabBar::tab { padding: 8px 12px; color: #42546b; }"
            "QTabBar::tab:selected { color: #10233f; font-weight: 700; }"
        )

        details_tab = QWidget()
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(10, 10, 10, 10)
        details_layout.setSpacing(6)

        detail_label = QLabel("Nachrichten- und PKI-Details")
        detail_label.setStyleSheet("font-weight: 700; color: #10233f;")
        details_layout.addWidget(detail_label)

        self._detail_table = QTableWidget(0, 2)
        self._detail_table.setHorizontalHeaderLabels(["Feld", "Wert"])
        self._detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._detail_table)
        self._detail_table.hide()
        details_layout.addWidget(self._detail_table, stretch=1)

        self._btn_verify_signature = QPushButton("Signatur prüfen")
        self._btn_verify_signature.setToolTip("ECDSA-Signaturverifikation (noch nicht implementiert)")
        self._btn_verify_signature.setEnabled(False)
        self._btn_verify_signature.clicked.connect(self._on_verify_signature)
        self._btn_verify_signature.hide()
        details_layout.addWidget(self._btn_verify_signature)

        self._context_tabs.addTab(details_tab, "Details")

        scene_tab = QWidget()
        scene_layout = QVBoxLayout(scene_tab)
        scene_layout.setContentsMargins(10, 10, 10, 10)
        scene_layout.setSpacing(6)
        self._setup_scene_panel(scene_layout)
        self._context_tabs.addTab(scene_tab, "Szene")

        eta_tab = QWidget()
        eta_layout = QVBoxLayout(eta_tab)
        eta_layout.setContentsMargins(10, 10, 10, 10)
        eta_layout.setSpacing(8)
        self._setup_eta_panel(eta_layout)
        self._context_tabs.addTab(eta_tab, "ETA Analyse")

        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.addWidget(table_container)
        self._right_splitter.addWidget(self._context_tabs)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.setStretchFactor(0, 3)
        self._right_splitter.setStretchFactor(1, 2)
        self._right_splitter.setSizes([460, 280])
        layout.addWidget(self._right_splitter, stretch=1)

        return panel

    def _apply_table_readability_style(self, table: QTableWidget) -> None:
        """Use readable light-blue alternating rows and black selected text."""
        table.setStyleSheet(
            "QTableWidget {"
            " background: #ffffff;"
            " alternate-background-color: #eaf5ff;"
            " color: #10233f;"
            " gridline-color: #d7dde8;"
            " selection-background-color: #cfe8ff;"
            " selection-color: #000000;"
            "}"
            "QHeaderView::section {"
            " background: #f5f7fb;"
            " color: #10233f;"
            " border: 1px solid #d7dde8;"
            " padding: 4px;"
            " font-weight: 700;"
            "}"
        )

    def _setup_scene_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the scene aggregation panel for phase forecasts and requests."""
        scene_label = QLabel("Szenenlage & Phasenprognose")
        scene_label.setStyleSheet("font-weight: 700; color: #10233f; padding-top: 4px;")
        parent_layout.addWidget(scene_label)

        self._scene_panel = QFrame()
        self._scene_panel.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #d7dde8; border-radius: 12px; }"
        )
        scene_layout = QVBoxLayout(self._scene_panel)
        scene_layout.setContentsMargins(10, 10, 10, 10)
        scene_layout.setSpacing(8)

        self._scene_summary = QLabel("Keine Szene verfuegbar. Lade eine PCAP-Datei und starte die Wiedergabe.")
        self._scene_summary.setWordWrap(True)
        self._scene_summary.setStyleSheet("color: #42546b;")
        scene_layout.addWidget(self._scene_summary)

        self._scene_warning_label = QLabel("")
        self._scene_warning_label.setWordWrap(True)
        self._scene_warning_label.setStyleSheet("color: #b2192b; font-weight: 600;")
        self._scene_warning_label.hide()
        scene_layout.addWidget(self._scene_warning_label)

        self._scene_metrics = QLabel("")
        self._scene_metrics.setWordWrap(True)
        self._scene_metrics.setStyleSheet("color: #5a6b81;")
        scene_layout.addWidget(self._scene_metrics)

        self._scene_legend = QLabel(
            "Timeline-Legende: G=Freigabe, R=Halt, C=Clearance, P=Vorlauf, !=Konflikt, ? unbekannt"
        )
        self._scene_legend.setWordWrap(True)
        self._scene_legend.setStyleSheet("color: #667891; font-size: 11px;")
        scene_layout.addWidget(self._scene_legend)

        self._scene_request_legend = QLabel(
            "Request-Legende: pending=blau, acknowledged=gelb, granted=gruen, "
            "rejected=rot, timeout=dunkelrot | dominante Anfrage = kraeftig, weitere = gestrichelt"
        )
        self._scene_request_legend.setWordWrap(True)
        self._scene_request_legend.setStyleSheet("color: #667891; font-size: 11px;")
        scene_layout.addWidget(self._scene_request_legend)

        self._scene_intersection_table = QTableWidget(0, len(SCENE_INTERSECTION_HEADERS))
        self._scene_intersection_table.setHorizontalHeaderLabels(SCENE_INTERSECTION_HEADERS)
        self._scene_intersection_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._scene_intersection_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._scene_intersection_table.verticalHeader().setVisible(False)
        self._scene_intersection_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._scene_intersection_table)
        self._scene_intersection_table.setMaximumHeight(170)
        self._scene_intersection_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._scene_intersection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scene_layout.addWidget(self._scene_intersection_table)

        self._scene_requests_table = QTableWidget(0, len(SCENE_REQUEST_HEADERS))
        self._scene_requests_table.setHorizontalHeaderLabels(SCENE_REQUEST_HEADERS)
        self._scene_requests_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._scene_requests_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._scene_requests_table.verticalHeader().setVisible(False)
        self._scene_requests_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._scene_requests_table)
        self._scene_requests_table.setMaximumHeight(150)
        self._scene_requests_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._scene_requests_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scene_layout.addWidget(self._scene_requests_table)

        parent_layout.addWidget(self._scene_panel, stretch=2)

    def _setup_eta_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the ETA analysis graph tab."""
        header = QLabel("ETA-Verlauf, Fahrzeuggeschwindigkeit und SRM/SSEM-Updates")
        header.setStyleSheet("font-weight: 700; color: #10233f;")
        parent_layout.addWidget(header)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel("Request/Merge-Spur:"))
        self._eta_station_combo = QComboBox()
        self._eta_station_combo.setMinimumWidth(180)
        controls.addWidget(self._eta_station_combo)
        self._btn_export_eta_dashboard = QPushButton("ETA exportieren")
        self._btn_export_eta_dashboard.setToolTip(
            "Aktuelle ETA-Kennzahlen und SREM/SSEM-Ereignisse als CSV und JSON exportieren"
        )
        controls.addWidget(self._btn_export_eta_dashboard)
        controls.addStretch()
        parent_layout.addLayout(controls)

        self._eta_summary = QLabel("Keine PCAP-Sitzung geladen.")
        self._eta_summary.setWordWrap(True)
        self._eta_summary.setStyleSheet("color: #42546b;")
        parent_layout.addWidget(self._eta_summary)

        self._eta_graph = EtaGraphWidget()
        parent_layout.addWidget(self._eta_graph, stretch=1)

        dashboard_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._eta_metric_table = QTableWidget(0, 2)
        self._eta_metric_table.setHorizontalHeaderLabels(["Kennzahl", "Wert"])
        self._eta_metric_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._eta_metric_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        self._eta_metric_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._eta_metric_table.verticalHeader().setVisible(False)
        self._eta_metric_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._eta_metric_table)
        dashboard_splitter.addWidget(self._eta_metric_table)

        self._eta_event_table = QTableWidget(0, 4)
        self._eta_event_table.setHorizontalHeaderLabels(["Zeit", "Typ", "Inhalt", "Details"])
        self._eta_event_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._eta_event_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._eta_event_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._eta_event_table.verticalHeader().setVisible(False)
        self._eta_event_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._eta_event_table)
        dashboard_splitter.addWidget(self._eta_event_table)
        dashboard_splitter.setStretchFactor(0, 1)
        dashboard_splitter.setStretchFactor(1, 2)
        dashboard_splitter.setSizes([240, 460])
        parent_layout.addWidget(dashboard_splitter, stretch=1)

        suggestions = QLabel(
            "ETA-Diagnose: Restzeit bis MAP-Stopline als blaue Kurve, geglaettete "
            "Geschwindigkeit als gruene Kurve, SREM als vertikale Ereignislinien und "
            "SSEM als farbige Statusbaender. Diagnosemarker zeigen ETA-Spruenge, "
            "fehlende SSEM, spaetes/fehlendes granted und Stopline-Passage ohne granted."
        )
        suggestions.setWordWrap(True)
        suggestions.setStyleSheet("color: #667891; font-size: 11px;")
        parent_layout.addWidget(suggestions)

    def _setup_playback_controls(self, parent_layout: QVBoxLayout) -> None:
        """Create the playback control bar."""
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(4, 2, 4, 2)

        self._btn_play = QPushButton("Play")
        self._btn_pause = QPushButton("Pause")
        self._btn_stop = QPushButton("Stop")
        self._btn_prev_issue = QPushButton("Fehler zurueck")
        self._btn_next_issue = QPushButton("Naechster Fehler")
        self._chk_problem_replay = QCheckBox("Nur Problemstellen")
        self._btn_play.setFixedWidth(72)
        self._btn_pause.setFixedWidth(72)
        self._btn_stop.setFixedWidth(72)
        self._btn_prev_issue.setToolTip("Zur vorherigen priorisierungsrelevanten Problemstelle springen")
        self._btn_next_issue.setToolTip("Zur naechsten priorisierungsrelevanten Problemstelle springen")
        self._chk_problem_replay.setToolTip(
            "Playback emittiert nur Nachrichten an Zeitpunkten mit Priorisierungsfehlern"
        )

        layout.addWidget(self._btn_play)
        layout.addWidget(self._btn_pause)
        layout.addWidget(self._btn_stop)
        layout.addWidget(self._chk_problem_replay)
        layout.addWidget(self._btn_prev_issue)
        layout.addWidget(self._btn_next_issue)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        layout.addWidget(self._slider, stretch=1)

        layout.addWidget(QLabel("Geschw.:"))
        self._speed_combo = QComboBox()
        for speed in SPEED_OPTIONS:
            self._speed_combo.addItem(f"{speed}x")
        self._speed_combo.setCurrentIndex(2)
        self._speed_combo.setFixedWidth(84)
        layout.addWidget(self._speed_combo)

        self._lbl_time = QLabel("00:00.0 / 00:00.0")
        self._lbl_time.setFixedWidth(140)
        layout.addWidget(self._lbl_time)

        parent_layout.addWidget(controls)

    def _setup_player(self) -> None:
        """Initialize the playback controller."""
        self._player = PlayerController(self)

    def _connect_signals(self) -> None:
        """Connect UI controls to their handlers."""
        self._btn_load.clicked.connect(self._on_load_pcap)
        self._btn_reload_last.clicked.connect(self._on_reload_last_session)
        self._btn_cancel_load.clicked.connect(self._on_cancel_load)
        self._btn_export_kml.clicked.connect(self._on_export_kml)
        self._btn_export_issues.clicked.connect(self._on_export_prioritization_issues)
        self._btn_export_diagnostics.clicked.connect(self._on_export_diagnostics)
        self._btn_reload_map.clicked.connect(self._on_reload_map)
        self._btn_update_schemas.clicked.connect(self._on_update_schemas)
        self._btn_dashboard.clicked.connect(self._on_show_dashboard)
        self._layout_mode_combo.currentIndexChanged.connect(self._on_layout_mode_changed)
        self._map_backend_combo.currentIndexChanged.connect(self._on_map_backend_changed)
        self._performance_mode_combo.currentIndexChanged.connect(self._on_performance_mode_changed)
        self._connect_map_widget_signals()
        self._btn_export_eta_dashboard.clicked.connect(self._on_export_eta_dashboard)
        self._eta_event_table.itemClicked.connect(self._on_eta_event_clicked)

        self._btn_play.clicked.connect(self._player.play)
        self._btn_pause.clicked.connect(self._player.pause)
        self._btn_stop.clicked.connect(self._player.stop)
        self._btn_prev_issue.clicked.connect(self._player.seek_to_previous_focus)
        self._btn_next_issue.clicked.connect(self._player.seek_to_next_focus)
        self._chk_problem_replay.toggled.connect(self._on_problem_replay_toggled)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._station_list.itemSelectionChanged.connect(self._on_station_filter_changed)
        self._msg_table.cellClicked.connect(self._on_table_row_clicked)
        self._btn_toggle_message_table.toggled.connect(self._toggle_message_table_maximized)
        self._context_tabs.currentChanged.connect(self._on_context_tab_changed)
        self._eta_station_combo.currentTextChanged.connect(self._on_eta_station_changed)

        self._player.tick.connect(self._on_playback_tick)
        self._player.state_changed.connect(self._on_player_state_changed)
        self._player.position_changed.connect(self._on_player_position_changed)
        self._player.time_updated.connect(self._on_player_time_updated)
        self._player.duration_changed.connect(self._on_duration_changed)

    def _connect_map_widget_signals(self) -> None:
        """Connect the current map widget implementation to diagnostics."""
        self._map_widget.telemetry_updated.connect(self._on_map_telemetry_updated)
        self._map_widget.map_issue_detected.connect(self._on_map_issue_detected)

    def _on_layout_mode_changed(self, *_args) -> None:
        """Persist and apply the selected responsive layout mode."""
        self._layout_preference = str(self._layout_mode_combo.currentData() or LAYOUT_MODE_AUTO)
        self._settings.setValue("ui/layout_mode", self._layout_preference)
        self._apply_responsive_layout(force=True)

    def _on_map_backend_changed(self, *_args) -> None:
        """Persist and switch the visible map implementation."""
        backend = str(self._map_backend_combo.currentData() or MAP_BACKEND_WEBENGINE)
        if backend not in MAP_BACKENDS or backend == self._map_backend:
            return
        self._replace_map_widget(backend, persist=True)

    def _replace_map_widget(self, backend: str, *, persist: bool = False) -> None:
        """Swap Leaflet/WebEngine and native map backends without losing the session."""
        logger.info("Replacing map widget: backend=%s persist=%s", backend, persist)
        old_widget = self._map_widget
        self._map_backend = backend
        if persist:
            self._settings.setValue("ui/map_backend", backend)
        self._map_widget = create_map_widget(backend=backend)
        self._connect_map_widget_signals()
        self._map_area_layout.removeWidget(old_widget)
        if hasattr(old_widget, "dispose"):
            old_widget.dispose()
        old_widget.setParent(None)
        # Invalidate any pending QTimer/WebEngine callbacks on the old widget
        # before deleteLater().  QtWebEngine can still finish async JS after the
        # Python object is alive but the wrapped C++ view has been destroyed.
        if hasattr(old_widget, "_bootstrap_generation"):
            old_widget._bootstrap_generation = -1
        if hasattr(old_widget, "_render_payload_stall_generation"):
            old_widget._render_payload_stall_generation = -1
        if hasattr(old_widget, "_bootstrap_probe_succeeded"):
            old_widget._bootstrap_probe_succeeded = True
        if hasattr(old_widget, "_render_payload_in_flight"):
            old_widget._render_payload_in_flight = False
        if hasattr(old_widget, "_queued_render_payload_script"):
            old_widget._queued_render_payload_script = None
        old_widget.deleteLater()
        self._map_area_layout.insertWidget(0, self._map_widget, stretch=1)
        if hasattr(self, "_map_backend_combo"):
            combo_index = self._map_backend_combo.findData(backend)
            if combo_index >= 0:
                self._map_backend_combo.blockSignals(True)
                self._map_backend_combo.setCurrentIndex(combo_index)
                self._map_backend_combo.blockSignals(False)
        self._map_safe_mode_active = False
        self._map_issue_history.clear()
        self._apply_performance_mode()
        if self._session:
            self._map_widget.load_messages(self._player._messages)
        label = "Leaflet" if backend == MAP_BACKEND_WEBENGINE else "Native"
        self._statusbar.showMessage(f"Kartenbackend gewechselt: {label}", 5000)

    def _on_performance_mode_changed(self, *_args) -> None:
        """Persist and apply the selected map performance mode."""
        self._performance_mode = str(self._performance_mode_combo.currentData() or PERFORMANCE_MODE_NORMAL)
        if self._performance_mode not in PERFORMANCE_MODE_LABELS:
            self._performance_mode = PERFORMANCE_MODE_NORMAL
        self._performance_auto_downgraded = False
        self._settings.setValue("ui/performance_mode", self._performance_mode)
        self._apply_performance_mode()

    def _apply_performance_mode(self) -> None:
        """Forward the current performance mode to the map and status UI."""
        if hasattr(self, "_map_widget"):
            self._map_widget.set_performance_mode(self._performance_mode)
        if hasattr(self, "_memory_watch_label"):
            self._update_memory_watch_label(_current_process_memory_mb())

    def _setup_memory_watchdog(self) -> None:
        """Start a lightweight watchdog that can reduce map detail under memory pressure."""
        self._memory_watch_timer = QTimer(self)
        self._memory_watch_timer.setInterval(MEMORY_WATCH_INTERVAL_MS)
        self._memory_watch_timer.timeout.connect(self._on_memory_watch_tick)
        self._memory_watch_timer.start()
        self._apply_performance_mode()
        self._on_memory_watch_tick()

    def _on_memory_watch_tick(self) -> None:
        """Update RAM display and automatically lower map detail if needed."""
        memory_mb = _current_process_memory_mb()
        self._update_memory_watch_label(memory_mb)
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
        """Set performance mode without recursively triggering UI handlers."""
        if mode not in PERFORMANCE_MODE_LABELS:
            mode = PERFORMANCE_MODE_NORMAL
        self._performance_mode = mode
        self._performance_auto_downgraded = auto
        if not auto:
            self._settings.setValue("ui/performance_mode", mode)
        if hasattr(self, "_performance_mode_combo"):
            index = self._performance_mode_combo.findData(mode)
            if index >= 0:
                self._performance_mode_combo.blockSignals(True)
                self._performance_mode_combo.setCurrentIndex(index)
                self._performance_mode_combo.blockSignals(False)
        self._apply_performance_mode()

    def _update_memory_watch_label(self, memory_mb: float | None) -> None:
        """Render the current memory and performance mode in the toolbar."""
        if not hasattr(self, "_memory_watch_label"):
            return
        mode = self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL)
        mode_label = PERFORMANCE_MODE_LABELS.get(mode, "Normal")
        suffix = " auto" if self.__dict__.get("_performance_auto_downgraded", False) else ""
        if memory_mb is None:
            self._memory_watch_label.setText(f"RAM: - | {mode_label}{suffix}")
            return
        color = "#1f7a3a"
        if memory_mb >= MEMORY_DIAGNOSTIC_THRESHOLD_MB:
            color = "#b91c1c"
        elif memory_mb >= MEMORY_SAVER_THRESHOLD_MB:
            color = "#a16207"
        self._memory_watch_label.setText(f"RAM: {memory_mb:.0f} MB | {mode_label}{suffix}")
        self._memory_watch_label.setStyleSheet(f"color: {color}; font-weight: 700;")

    def _map_render_interval_seconds(self) -> float:
        """Return current full-slice render throttle for map playback."""
        return PERFORMANCE_RENDER_INTERVAL_SECONDS.get(
            self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
            PERFORMANCE_RENDER_INTERVAL_SECONDS[PERFORMANCE_MODE_NORMAL],
        )

    def _map_playback_window_seconds(self) -> float | None:
        """Return the playback time window rendered on the map."""
        return PERFORMANCE_PLAYBACK_WINDOW_SECONDS.get(
            self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
            PERFORMANCE_PLAYBACK_WINDOW_SECONDS[PERFORMANCE_MODE_NORMAL],
        )

    def _on_map_telemetry_updated(self, telemetry: dict[str, object]) -> None:
        """Keep a bounded history of map render diagnostics."""
        history = self.__dict__.setdefault("_map_telemetry_history", [])
        history.append(dict(telemetry))
        del history[:-MAP_TELEMETRY_HISTORY_LIMIT]

        dropped_total = sum(
            int(telemetry.get(key, 0) or 0)
            for key in (
                "budget_dropped_markers",
                "budget_dropped_infrastructure",
                "budget_dropped_trajectories",
                "budget_dropped_trajectory_points",
            )
        )
        if dropped_total and self.__dict__.get("_performance_mode") == PERFORMANCE_MODE_NORMAL:
            self._set_performance_mode(PERFORMANCE_MODE_SAVER, auto=True)
            self._statusbar.showMessage(
                "Karten-Payload war zu gross - Leistung automatisch auf Schonend reduziert",
                5000,
            )

    def _on_map_issue_detected(self, message: str) -> None:
        """Switch to safe map mode after repeated WebEngine/JavaScript problems."""
        logger.info("Map issue detected: %s", message)
        issues = self.__dict__.setdefault("_map_issue_history", [])
        issues.append(message)
        del issues[:-20]
        if self._should_fallback_to_native_map(message):
            logger.warning(
                "Fatal map issue — switching to native fallback (persist=False): %s",
                message,
            )
            self._replace_map_widget(MAP_BACKEND_NATIVE, persist=False)
            self._statusbar.showMessage(
                f"Karte auf Native-Fallback gewechselt: {message}",
                8000,
            )
            return
        if self.__dict__.get("_map_safe_mode_active", False):
            return
        if len(issues) < MAP_SAFE_MODE_ISSUE_THRESHOLD:
            self._statusbar.showMessage(f"Kartenhinweis: {message}", 5000)
            return

        self._map_safe_mode_active = True
        self._set_performance_mode(PERFORMANCE_MODE_DIAGNOSTIC, auto=True)
        self._statusbar.showMessage(
            "Karten-Safe-Mode aktiv: wiederholte WebEngine/JavaScript-Probleme erkannt",
            8000,
        )

    def _should_fallback_to_native_map(self, message: str) -> bool:
        """Return whether a WebEngine issue should trigger the native map fallback."""
        if self.__dict__.get("_map_backend", MAP_BACKEND_WEBENGINE) != MAP_BACKEND_WEBENGINE:
            return False
        fatal_markers = (
            "Karten-WebView",
            "Leaflet",
            "WebEngine",
            "Bootstrap",
            "Initialisierungstimeout",
            "Render-Prozess",
        )
        return any(marker in message for marker in fatal_markers)

    def _on_reload_map(self) -> None:
        """Reload the WebEngine map and re-render the current session."""
        if hasattr(self._map_widget, "reload_map_page"):
            self._map_widget.reload_map_page()
        self._map_safe_mode_active = False
        self._map_issue_history.clear()
        self._apply_performance_mode()
        if self._session:
            self._map_widget.load_messages(self._player._messages)
        self._statusbar.showMessage("Karte wurde neu geladen", 4000)

    def _on_export_diagnostics(self) -> None:
        """Write a technical diagnostics report for support and regression analysis."""
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Diagnose-Exportverzeichnis waehlen",
            start_dir,
        )
        if not dir_path:
            return
        report_path = Path(dir_path) / "pcap2kml_diagnostics.json"
        try:
            report_path.write_text(
                json.dumps(self._build_diagnostics_report(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Diagnose-Export fehlgeschlagen", str(exc))
            return

        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"Diagnosebericht exportiert nach {report_path}", 5000)
        QMessageBox.information(
            self,
            "Diagnose exportiert",
            f"Der Diagnosebericht wurde geschrieben:\n{report_path}",
        )

    def _build_diagnostics_report(self) -> dict[str, object]:
        """Build a support-friendly diagnostics snapshot."""
        memory_mb = _current_process_memory_mb()
        package_names = [
            "PyQt6",
            "PyQt6-WebEngine",
            "scapy",
            "pyshark",
            "asn1tools",
            "simplekml",
        ]
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
                    for msg_type, count in sorted(
                        self._session.msg_type_counts.items(),
                        key=lambda item: item[0].value,
                    )
                },
            }

        return {
            "created_at": datetime.now(UTC).isoformat(),
            "application": {
                "performance_mode": self.__dict__.get("_performance_mode", PERFORMANCE_MODE_NORMAL),
                "performance_auto_downgraded": self.__dict__.get(
                    "_performance_auto_downgraded",
                    False,
                ),
                "map_safe_mode_active": self.__dict__.get("_map_safe_mode_active", False),
                "map_backend": self.__dict__.get("_map_backend", selected_map_backend_name()),
                "memory_mb": memory_mb,
            },
            "runtime": {
                "python": sys.version,
                "platform": platform.platform(),
                "qt": QT_VERSION_STR,
                "pyqt": PYQT_VERSION_STR,
                "packages": packages,
                "qtwebengine_flags": os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
                "qt_opengl": os.environ.get("QT_OPENGL", ""),
                "qt_opengl_dll": os.environ.get("QT_OPENGL_DLL", ""),
                "qsg_rhi_prefer_software_renderer": os.environ.get(
                    "QSG_RHI_PREFER_SOFTWARE_RENDERER",
                    "",
                ),
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

    def _effective_layout_mode(self) -> str:
        """Return the concrete layout mode for the current window size."""
        if self._layout_preference == LAYOUT_MODE_COMPACT:
            return LAYOUT_MODE_COMPACT
        if self._layout_preference == LAYOUT_MODE_DESKTOP:
            return LAYOUT_MODE_DESKTOP
        return LAYOUT_MODE_COMPACT if self.width() < COMPACT_LAYOUT_WIDTH else LAYOUT_MODE_DESKTOP

    def _apply_responsive_layout(self, *, force: bool = False) -> None:
        """Apply compact/desktop presentation tweaks without reparenting widgets."""
        compact = self._effective_layout_mode() == LAYOUT_MODE_COMPACT
        if not force and compact == self._is_compact_layout:
            return
        self._is_compact_layout = compact
        self._apply_compact_message_columns(compact)
        self._apply_compact_control_sizes(compact)
        self._apply_issue_panel_policy(getattr(self, "_current_prioritization_issues", []))
        if compact and hasattr(self, "_right_splitter"):
            self._right_splitter.setSizes([360, 220])
        elif hasattr(self, "_right_splitter") and not self._message_table_maximized:
            self._right_splitter.setSizes([460, 280])

    def _apply_compact_message_columns(self, compact: bool) -> None:
        """Show only the chosen compact message columns on small screens."""
        if not hasattr(self, "_msg_table"):
            return
        for column in range(NUM_COLUMNS):
            self._msg_table.setColumnHidden(
                column,
                compact and column not in COMPACT_MESSAGE_COLUMNS,
            )

    def _apply_compact_control_sizes(self, compact: bool) -> None:
        """Reduce fixed widths and button labels in compact layout."""
        if not hasattr(self, "_btn_play"):
            return
        button_width = 58 if compact else 72
        self._btn_play.setFixedWidth(button_width)
        self._btn_pause.setFixedWidth(button_width)
        self._btn_stop.setFixedWidth(button_width)
        self._speed_combo.setFixedWidth(74 if compact else 84)
        self._lbl_time.setFixedWidth(118 if compact else 140)
        self._btn_prev_issue.setText("Fehler <" if compact else "Fehler zurueck")
        self._btn_next_issue.setText("Fehler >" if compact else "Naechster Fehler")
        self._btn_export_kml.setText("KML" if compact else "KML exportieren")
        self._btn_export_issues.setText("Fehler Export" if compact else "Fehler exportieren")
        self._btn_export_diagnostics.setText("Diagnose" if compact else "Diagnose exportieren")
        self._btn_reload_map.setText("Karte neu" if compact else "Karte neu laden")
        self._btn_update_schemas.setText("Schemas" if compact else "ASN.1-Schemas aktualisieren")

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Switch Auto layout when the window crosses compact width."""
        super().resizeEvent(event)
        if getattr(self, "_layout_preference", LAYOUT_MODE_AUTO) == LAYOUT_MODE_AUTO:
            self._apply_responsive_layout()

    def _on_load_pcap(self) -> None:
        """Open a file dialog and load selected PCAP files."""
        start_dir = self._memory.last_directory or str(Path.cwd())
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "PCAP-Dateien oeffnen",
            start_dir,
            "PCAP-Dateien (*.pcap *.pcapng *.cap);;Alle Dateien (*)",
        )
        if paths:
            self._load_paths(paths)

    def _on_reload_last_session(self) -> None:
        """Reload the last successful session from persistent memory."""
        paths = self._memory.existing_last_session_files()
        if not paths:
            QMessageBox.information(
                self,
                "Keine Sitzung vorhanden",
                "Es wurden keine gueltigen Dateien aus der letzten Sitzung gefunden.",
            )
            return
        self._load_paths(paths)

    def _load_paths(self, paths: list[str]) -> None:
        """Parse the provided PCAP paths in the background."""
        if self._loader_thread is not None:
            QMessageBox.information(
                self,
                "Ladevorgang aktiv",
                "Es laeuft bereits ein Parse-Vorgang. Bitte warte oder brich ihn ab.",
            )
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
        """Request cancellation of the current load process."""
        if self._loader_worker is not None:
            self._loader_worker.cancel()
            self._statusbar.showMessage("Abbruch angefordert...")

    def _on_load_progress(self, percent: int, filename: str) -> None:
        """Update the progress UI while the worker is parsing."""
        self._progress.setValue(percent)
        self._statusbar.showMessage(f"Lade {filename}... {percent}%")

    def _on_load_finished(self, session: SessionData, paths: list[str], errors: list[str]) -> None:
        """Finalize a successful background parse."""
        self._set_loading_state(False)

        if not session.messages:
            self._session = None
            self._clear_session_views()
            self._statusbar.showMessage("Keine verarbeitbaren Nachrichten gefunden")
            self._refresh_memory_banner()
            if errors:
                QMessageBox.warning(self, "Laden fehlgeschlagen", "\n".join(errors))
            else:
                QMessageBox.information(
                    self,
                    "Keine Daten gefunden",
                    "In den geladenen PCAP-Dateien wurden keine verarbeitbaren Nachrichten erkannt.",
                )
            return

        self._session = session
        self._all_station_ids = set(session.station_ids)
        self._active_stations = set(session.station_ids)
        self._active_types = set(MessageType)

        self._populate_station_list()
        self._populate_message_table(session.messages)
        self._map_widget.load_messages(session.messages)
        self._reset_playback_render_caches()
        self._player.set_session(session)
        self._refresh_problem_replay_indices(session.messages)
        self._refresh_eta_analysis(session.messages)
        self._detail_table.hide()
        self._update_scene_for_message(session.messages[0], force=True)
        self._update_controls_enabled(True)
        self._update_overview_for_session(paths, session)
        self._apply_responsive_layout(force=True)

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
            QMessageBox.warning(
                self,
                "Teilweise geladen",
                "Einige Dateien konnten nicht vollstaendig verarbeitet werden:\n\n" + "\n".join(errors),
            )

    def _on_load_cancelled(self) -> None:
        """Restore the UI after a cancelled load."""
        self._set_loading_state(False)
        self._statusbar.showMessage("Ladevorgang abgebrochen")

    def _cleanup_loader(self, *args) -> None:
        """Dispose the worker thread after completion or cancellation."""
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
            # Disconnect thread.started before deleting worker, since the slot
            # references self._loader_worker which is about to be set to None.
            try:
                self._loader_thread.started.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._loader_thread.deleteLater()
            self._loader_thread = None

    def _on_export_kml(self) -> None:
        """Export KML files for all filtered entities."""
        if not self._session:
            return

        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "KML-Exportverzeichnis waehlen",
            start_dir,
        )
        if not dir_path:
            return

        try:
            created = export_kml(
                self._session,
                Path(dir_path),
                active_types=self._active_types if self._active_types != set(MessageType) else None,
                active_stations=(self._active_stations if self._active_stations != self._all_station_ids else None),
                canonical=self._show_canonical_messages,
            )
        except (OSError, PermissionError, ValueError) as exc:  # pragma: no cover
            QMessageBox.critical(self, "Export-Fehler", str(exc))
            return

        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"{len(created)} KML-Dateien exportiert nach {dir_path}")
        QMessageBox.information(
            self,
            "Export erfolgreich",
            f"{len(created)} KML-Dateien wurden exportiert nach:\n{dir_path}",
        )

    def _on_export_prioritization_issues(self) -> None:
        """Export prioritization issue diagnostics as CSV and JSON."""
        if not self._session:
            return

        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Fehleranalyse-Exportverzeichnis waehlen",
            start_dir,
        )
        if not dir_path:
            return

        try:
            created = export_prioritization_issues(self._player._messages, Path(dir_path))
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Export-Fehler", str(exc))
            return

        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"Priorisierungsfehler exportiert nach {dir_path}")
        QMessageBox.information(
            self,
            "Export erfolgreich",
            "Priorisierungsfehler wurden exportiert:\n" + "\n".join(str(path) for path in created),
        )

    def _on_update_schemas(self) -> None:
        """Update ASN.1 schemas from the Git repository."""
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
        QMessageBox.warning(
            self,
            "Fehler",
            "ASN.1-Schemas konnten nicht aktualisiert werden.\nPruefen Sie Internetverbindung und Git-Installation.",
        )

    def _on_show_dashboard(self) -> None:
        """Open the statistics dashboard for the current session."""
        if self._session is None:
            QMessageBox.information(self, "Dashboard", "Keine Sitzung geladen.")
            return
        dialog = StatisticsDashboard(self._session, self)
        dialog.exec()

    def _on_filter_changed(self) -> None:
        """Handle message type filter changes."""
        self._active_types = {msg_type for msg_type, checkbox in self._type_checkboxes.items() if checkbox.isChecked()}
        self._apply_filters()

    def _on_merge_view_changed(self, *_args) -> None:
        """Switch between raw observations and canonical merged messages."""
        self._show_canonical_messages = self._merge_view_checkbox.isChecked()
        self._apply_filters()

    def _on_station_filter_changed(self) -> None:
        """Handle station filter changes."""
        self._active_stations = {item.text() for item in self._station_list.selectedItems()}
        if not self._active_stations:
            self._active_stations = set(self._all_station_ids)
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Apply the active type and station filters to the UI."""
        if not self._session:
            return

        filtered = self._session.filter_messages(
            self._active_types,
            self._active_stations,
            canonical=self._show_canonical_messages,
        )
        self._populate_message_table(filtered)
        self._map_widget.load_messages(filtered)
        self._reset_playback_render_caches()
        self._player.set_filtered_messages(filtered)
        self._refresh_problem_replay_indices(filtered)
        self._update_scene_for_message(filtered[0] if filtered else None, force=True)
        self._lbl_filter_hint.setText(f"{len(filtered)} von {len(self._session.messages)} Nachrichten sichtbar")
        self._statusbar.showMessage(f"Filter aktiv: {len(filtered)} / {len(self._session.messages)} Nachrichten")
        self._update_status_metrics(len(filtered))

    def _populate_station_list(self) -> None:
        """Populate the station filter list and select all entries."""
        self._station_list.blockSignals(True)
        self._station_list.clear()
        for station_id in sorted(self._all_station_ids):
            item = QListWidgetItem(station_id)
            self._station_list.addItem(item)
            item.setSelected(True)
        self._station_list.blockSignals(False)

    def _populate_message_table(self, messages: list[V2xMessage] | None = None) -> None:
        """Fill the message table with session data."""
        if messages is None and self._session:
            messages = self._session.messages
        elif messages is None:
            messages = []

        self._message_row_lookup = {}
        self._last_highlighted_row = None
        self._last_detail_key = None
        self._pending_detail_message = None
        self._set_table_updates_enabled(self._msg_table, False)
        try:
            self._msg_table.setRowCount(len(messages))
            for row, msg in enumerate(messages):
                timestamp_text = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
                self._message_row_lookup[(timestamp_text, msg.station_id)] = row
                self._msg_table.setItem(row, COL_TIMESTAMP, QTableWidgetItem(timestamp_text))
                self._msg_table.setItem(row, COL_STATION, QTableWidgetItem(msg.station_id))
                self._msg_table.setItem(row, COL_MSGTYPE, QTableWidgetItem(msg.msg_type.value))
                self._msg_table.setItem(
                    row,
                    COL_LATLON,
                    QTableWidgetItem(f"{msg.latitude:.6f}, {msg.longitude:.6f}"),
                )
                speed_str = f"{msg.speed:.1f} m/s" if msg.speed is not None else "-"
                heading_str = f"{msg.heading:.0f} deg" if msg.heading is not None else "-"
                self._msg_table.setItem(
                    row,
                    COL_SPEED_HEADING,
                    QTableWidgetItem(f"{speed_str} / {heading_str}"),
                )
                source_text = msg.source.display_name() if msg.source is not None else "-"
                merge_text = "-"
                if msg.merge_group_id:
                    merge_text = msg.merge_group_id
                    if msg.merge_confidence is not None:
                        merge_text += f" ({msg.merge_confidence:.2f})"
                self._msg_table.setItem(row, COL_SOURCE, QTableWidgetItem(source_text))
                self._msg_table.setItem(row, COL_MERGE, QTableWidgetItem(merge_text))
        finally:
            self._set_table_updates_enabled(self._msg_table, True)

    def _set_table_updates_enabled(self, table: QTableWidget, enabled: bool) -> None:
        """Toggle expensive table repaint/sort work if the backing widget supports it."""
        if hasattr(table, "setUpdatesEnabled"):
            table.setUpdatesEnabled(enabled)
        if hasattr(table, "setSortingEnabled"):
            table.setSortingEnabled(False)

    def _on_playback_tick(self, msg: V2xMessage | None) -> None:
        """Update map and details when the visible playback message changes."""
        if msg is None:
            return

        if self._should_render_full_map_slice(msg):
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

    def _should_render_full_map_slice(self, msg: V2xMessage) -> bool:
        """Throttle expensive map layer sync to avoid overloading QtWebEngine."""
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
        """Reset throttling/caches after loading, filtering, or clearing a session."""
        self._last_scene_update_monotonic = 0.0
        self._last_scene_cache_key = None
        self._last_scene_cache_snapshot = None
        self._last_map_slice_update_monotonic = 0.0
        self._last_map_slice_index = None
        self._last_map_messages_id = None

    def _highlight_table_row(self, msg: V2xMessage) -> None:
        """Select the matching row and only scroll when it leaves the viewport."""
        row = self._message_row_lookup.get(self._message_lookup_key(msg))
        if row is None or row == self._last_highlighted_row:
            return

        self._msg_table.selectRow(row)
        item = self._msg_table.item(row, COL_TIMESTAMP)
        if item is not None and not self._is_table_item_visible(item):
            self._msg_table.scrollToItem(
                item,
                QTableWidget.ScrollHint.PositionAtCenter,
            )
        self._last_highlighted_row = row

    def _message_lookup_key(self, msg: V2xMessage) -> tuple[str, str]:
        """Return the table lookup key for a playback message."""
        return (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)

    def _is_table_item_visible(self, item: QTableWidgetItem) -> bool:
        """Return whether the table item is already inside the visible viewport."""
        rect = self._msg_table.visualItemRect(item)
        if not rect.isValid():
            return False
        return self._msg_table.viewport().rect().intersects(rect)

    def _on_player_state_changed(self, state: str) -> None:
        """Update button states based on the player state."""
        self._btn_play.setEnabled(state != "playing" and self._session is not None)
        self._btn_pause.setEnabled(state == "playing")

    def _on_player_position_changed(self, index: int) -> None:
        """Update the position slider from the player index."""
        total = self._player.total_messages
        if total > 0:
            self._slider.blockSignals(True)
            self._slider.setValue(int((index / total) * 1000))
            self._slider.blockSignals(False)

    def _on_duration_changed(self, seconds: float) -> None:
        """Refresh the duration label."""
        self._lbl_time.setText(f"00:00.0 / {self._player.format_time(seconds)}")

    def _on_player_time_updated(self, seconds: float) -> None:
        """Refresh the time label without forcing a full map rerender."""
        total_time = self._session.duration_seconds if self._session else 0.0
        self._lbl_time.setText(f"{self._player.format_time(seconds)} / {self._player.format_time(total_time)}")

    def _on_context_tab_changed(self, index: int) -> None:
        """Refresh the detail table only when the user opens the details tab."""
        if index != 0 or self._pending_detail_message is None:
            return
        self._show_security_detail(
            self._pending_detail_message,
            auto_focus=False,
            force_refresh=True,
        )

    def _refresh_eta_analysis(self, messages: list[V2xMessage]) -> None:
        """Populate the ETA graph vehicle selector from the loaded session."""
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
        self._refresh_eta_dashboard()

    def _on_eta_station_changed(self, station_id: str) -> None:
        """Update the ETA graph when a single vehicle is selected."""
        self._eta_graph.set_selection(self._eta_station_combo.currentData())
        self._eta_summary.setText(self._eta_graph.summary_text())
        self._refresh_eta_dashboard()

    def _refresh_eta_dashboard(self) -> None:
        """Render ETA metrics and event rows for the selected request track."""
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
        """Synchronize playback, details, map and request focus from an ETA event row."""
        event = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(event, EtaDashboardEvent):
            return
        if event.message_type is not None and self._seek_eta_event_message(event):
            return
        self._focus_eta_event_request(event)

    def _seek_eta_event_message(self, event: EtaDashboardEvent) -> bool:
        """Seek to the concrete SREM/SSEM message represented by one event row."""
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
            f"Keine passende Nachricht fuer ETA-Ereignis {event.time_text} gefunden",
            4000,
        )
        return False

    def _message_matches_eta_event_selection(self, msg: V2xMessage, event: EtaDashboardEvent) -> bool:
        """Return whether msg belongs to the same request key as the dashboard event."""
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
        """Focus the map request geometry represented by the ETA dashboard row."""
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
        """Export current ETA dashboard metrics and events as CSV and JSON."""
        start_dir = self._memory.last_export_directory or self._memory.last_directory or str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "ETA-Dashboard-Exportverzeichnis waehlen",
            start_dir,
        )
        if not dir_path:
            return
        target_dir = Path(dir_path)
        data = self._eta_graph.dashboard_data()
        csv_path = target_dir / "eta_dashboard.csv"
        json_path = target_dir / "eta_dashboard.json"
        try:
            self._write_eta_dashboard_exports(data, csv_path, json_path)
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "ETA-Export fehlgeschlagen", str(exc))
            return
        self._memory.remember_export_directory(dir_path)
        self._memory.save()
        self._statusbar.showMessage(f"ETA-Dashboard exportiert nach {target_dir}", 5000)
        QMessageBox.information(
            self,
            "ETA exportiert",
            f"ETA-Dashboard wurde exportiert:\n{csv_path}\n{json_path}",
        )

    def _write_eta_dashboard_exports(self, data, csv_path: Path, json_path: Path) -> None:
        """Write ETA dashboard metrics and events to CSV and JSON files."""
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["Bereich", "Kennzahl/Zeit", "Typ", "Inhalt", "Details"])
            for metric, value in data.metrics:
                writer.writerow(["Kennzahl", metric, "", value, ""])
            for event in data.events:
                writer.writerow(
                    [
                        "Ereignis",
                        event.time_text,
                        event.kind,
                        event.content,
                        event.details,
                    ]
                )

        json_payload = {
            "metrics": [{"name": metric, "value": value} for metric, value in data.metrics],
            "events": [
                {
                    "time": event.time_text,
                    "kind": event.kind,
                    "content": event.content,
                    "details": event.details,
                    "timestamp": event.timestamp.isoformat(),
                    "message_type": event.message_type.value if event.message_type else None,
                    "selection_key": event.selection_key,
                }
                for event in data.events
            ],
        }
        json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _toggle_message_table_maximized(self, maximized: bool) -> None:
        """Expand the message table by collapsing the lower context tabs."""
        self._message_table_maximized = maximized
        self._context_tabs.setVisible(not maximized)
        if hasattr(self, "_right_splitter"):
            if maximized:
                self._right_splitter.setSizes([1, 0])
            else:
                self._right_splitter.setSizes([460, 280])
        self._btn_toggle_message_table.setText(
            "Tabellenbereich wiederherstellen" if maximized else "Tabelle maximieren"
        )

    def _on_speed_changed(self, index: int) -> None:
        """Handle speed selector changes."""
        if 0 <= index < len(SPEED_OPTIONS):
            self._player.set_speed(SPEED_OPTIONS[index])

    def _on_problem_replay_toggled(self, enabled: bool) -> None:
        """Enable or disable replay that jumps only between issue timestamps."""
        self._player.set_focus_replay_enabled(enabled)
        if enabled and not self._problem_replay_indices:
            self._statusbar.showMessage("Keine Problemstellen fuer den aktuellen Filter gefunden", 4000)
        elif enabled:
            self._statusbar.showMessage(
                f"Problemstellen-Replay aktiv: {len(self._problem_replay_indices)} Zeitpunkt(e)",
                4000,
            )
        else:
            self._statusbar.showMessage("Problemstellen-Replay deaktiviert", 3000)

    def _on_slider_moved(self, value: int) -> None:
        """Seek playback when the timeline slider is moved."""
        self._player.seek_to_position(value / 1000.0)

    def _refresh_problem_replay_indices(self, messages: list[V2xMessage]) -> None:
        """Precompute playback indices at which prioritization issues occur."""
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

    def _on_table_row_clicked(self, row: int, _: int) -> None:
        """Jump playback to the clicked row and show the message details."""
        ts_item = self._msg_table.item(row, COL_TIMESTAMP)
        station_item = self._msg_table.item(row, COL_STATION)
        if not ts_item or not station_item:
            return

        target_timestamp = ts_item.text()
        target_station = station_item.text()
        for index, msg in enumerate(self._player._messages):
            if msg.timestamp.strftime("%H:%M:%S.%f")[:-3] == target_timestamp and msg.station_id == target_station:
                self._player.seek_to_index(index)
                self._show_security_detail(msg, auto_focus=True, force_refresh=True)
                return

    def _show_security_detail(
        self,
        msg: V2xMessage,
        *,
        auto_focus: bool,
        force_refresh: bool = False,
    ) -> None:
        """Render message and PKI details for the selected message."""
        self._pending_detail_message = msg
        detail_key = self._message_lookup_key(msg)
        if not auto_focus and self._context_tabs.currentIndex() != 0:
            return
        if not force_refresh and detail_key == self._last_detail_key:
            return

        rows = list(msg.to_detail_rows())
        if msg.security_info is None:
            rows.append(
                (
                    "Sicherheitsheader",
                    "Kein Sicherheitsheader vorhanden oder nicht extrahierbar",
                )
            )
        else:
            rows.extend(msg.security_info.to_table_rows())
        self._detail_table.setRowCount(len(rows))
        for index, (field, value) in enumerate(rows):
            self._detail_table.setItem(index, 0, QTableWidgetItem(field))
            self._detail_table.setItem(index, 1, QTableWidgetItem(value))
        self._detail_table.show()
        self._last_detail_key = detail_key
        if auto_focus:
            self._context_tabs.setCurrentIndex(0)

        # Only toggle verify button when UI is fully initialized
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
        """Show a placeholder dialog for ECDSA signature verification.

        Real verification requires the certificate public key and the
        full signed payload.  This is deliberately deferred to a future
        opt-in build.
        """
        QMessageBox.information(
            self,
            "Signaturverifikation",
            (
                "ECDSA-Signaturverifikation ist noch nicht implementiert.\n\n"
                "Benötigt werden:\n"
                "  - Zertifikat der ausstellenden CA\n"
                "  - Öffentlicher Schlüssel des Absenders\n"
                "  - Vollständiger signierter Payload\n\n"
                "Wenn du diese Funktion benötigst, öffne bitte ein Issue "
                "oder kontaktiere das Entwicklerteam."
            ),
        )

    def _update_scene_for_message(self, msg: V2xMessage | None, *, force: bool = False) -> None:
        """Rebuild and display the current scene snapshot for one playback position."""
        if msg is None or not self._player._messages:
            self._clear_scene_panel()
            self._refresh_prioritization_issues([])
            self._last_scene_cache_key = None
            self._last_scene_cache_snapshot = None
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
        self._render_scene_snapshot(scene)
        self._refresh_prioritization_issues(build_prioritization_issues(scene))

    def _render_scene_snapshot(self, scene: SceneSnapshot) -> None:
        """Render a scene snapshot into the scene panel widgets."""
        intersections = sorted(scene.intersections.values(), key=lambda item: item.intersection_id)
        overdue_requests = find_overdue_requests(scene.active_requests, scene.timeline_position)
        clock_skew_warnings = get_clock_skew_warnings(scene)
        eta_accuracy_seconds = get_eta_accuracy_seconds(scene)
        forecast_groups = sum(len(forecast.segments_by_group) for forecast in scene.forecasts.values())
        revision_mismatch_count = sum(1 for state in intersections if state.revision_mismatch)
        msg_rate = self._estimate_visible_message_rate(scene.timeline_position)

        self._scene_summary.setText(
            "Zeitpunkt: "
            f"{scene.timeline_position.strftime('%H:%M:%S.%f')[:-3]} | "
            f"{len(intersections)} Kreuzung(en), "
            f"{len(scene.active_requests)} offene Anforderung(en), "
            f"{max(0, len(scene.request_states) - len(scene.active_requests))} kuerzlich beantwortet"
        )
        self._scene_metrics.setText(
            "Forecasts: "
            f"{forecast_groups} Signalgruppe(n) | "
            f"Overdue Requests: {len(overdue_requests)} | "
            f"Revisionen abweichend: {revision_mismatch_count} | "
            f"Clock Skew: {len(clock_skew_warnings)} | "
            f"ETA MAE: {self._format_eta_accuracy(eta_accuracy_seconds)} | "
            f"Msgs/s: {msg_rate:.1f}"
        )

        warnings: list[str] = []
        if not intersections:
            warnings.append("Noch keine MAP/SPAT-Szene fuer den aktuellen Zeitbereich erkannt.")
        if any(state.map_revision is None for state in intersections):
            warnings.append("Mindestens eine SPAT-Nachricht ohne passende MAP-Basis.")
        if any(state.revision_mismatch for state in intersections):
            warnings.append("MAP/SPAT-Revisionen weichen voneinander ab.")
        if overdue_requests:
            warnings.append(f"{len(overdue_requests)} Anforderung(en) ohne SSEM-Antwort ueber Timeout.")
        if clock_skew_warnings:
            warnings.append(
                "Uhrenversatz erkannt: "
                + ", ".join(f"Int {intersection_id} {skew:+.1f}s" for intersection_id, skew in clock_skew_warnings[:3])
            )
        inaccurate_eta = [item for item in scene.eta_verifications if not item.is_accurate]
        if inaccurate_eta:
            warnings.append(f"ETA-Abweichung > 2s bei {len(inaccurate_eta)} verifizierten Anfrage(n).")
        self._scene_warning_label.setVisible(bool(warnings))
        self._scene_warning_label.setText(" | ".join(warnings))

        self._scene_intersection_table.setRowCount(len(intersections))
        for row, intersection in enumerate(intersections):
            signal_groups = sorted(
                intersection.signal_groups.values(),
                key=lambda item: item.signal_group_id,
            )
            signal_group_summary = ", ".join(
                f"SG {group.signal_group_id}: {group.phase.value}" for group in signal_groups[:3]
            )
            if len(signal_groups) > 3:
                signal_group_summary += f" (+{len(signal_groups) - 3})"
            forecast = scene.forecasts.get(intersection.intersection_id)
            forecast_summary = self._format_forecast_summary(forecast)
            revision_text = self._format_revision_text(intersection)

            self._scene_intersection_table.setItem(row, 0, QTableWidgetItem(str(intersection.intersection_id)))
            self._scene_intersection_table.setItem(row, 1, QTableWidgetItem(revision_text))
            self._scene_intersection_table.setItem(
                row, 2, QTableWidgetItem(signal_group_summary or "Keine Signalgruppen")
            )
            self._scene_intersection_table.setItem(row, 3, QTableWidgetItem(forecast_summary))
            self._scene_intersection_table.setItem(row, 4, QTableWidgetItem(self._format_forecast_timeline(forecast)))

        request_visuals = [visual for visuals in scene.request_visuals_by_intersection.values() for visual in visuals]
        request_visuals.sort(
            key=lambda visual: (
                visual.display_rank,
                -(visual.importance_level or 0),
                -visual.requested_at.timestamp(),
            )
        )
        self._scene_requests_table.setRowCount(len(request_visuals))
        overdue_keys = {
            (request.intersection_id, request.request_id, request.sequence_number) for request in overdue_requests
        }
        for row, request_visual in enumerate(request_visuals):
            request_key = (
                request_visual.intersection_id,
                request_visual.request_id,
                request_visual.sequence_number,
            )
            status = request_visual.status.value
            if request_key in overdue_keys:
                status = "timeout"
            if request_visual.is_dominant:
                status = f"{status} / dominant"
            elif request_visual.display_rank > 0:
                status = f"{status} / sekundar"
            verification = self._find_eta_verification_by_key(
                scene,
                request_visual.intersection_id,
                request_visual.request_id,
                request_visual.sequence_number,
            )
            if verification is not None:
                status += f" / ETA {verification.delta_seconds:+.1f}s"
            lane_text = self._format_visual_lane_text(request_visual)
            request_text = (
                f"{request_visual.intersection_id}/{request_visual.request_id}/{request_visual.sequence_number}"
            )

            self._scene_requests_table.setItem(row, 0, QTableWidgetItem(request_text))
            self._scene_requests_table.setItem(row, 1, QTableWidgetItem(request_visual.station_id))
            self._scene_requests_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    str(request_visual.importance_level) if request_visual.importance_level is not None else "-"
                ),
            )
            self._scene_requests_table.setItem(row, 3, QTableWidgetItem(status))
            self._scene_requests_table.setItem(row, 4, QTableWidgetItem(lane_text))

    def _refresh_prioritization_issues(self, issues: list[PrioritizationIssue]) -> None:
        """Render prioritization issues in the map-side panel."""
        self._current_prioritization_issues = issues
        if not hasattr(self, "_issue_list"):
            return
        self._apply_issue_panel_policy(issues)
        self._issue_list.clear()
        self._refresh_issue_intersection_filter(issues)
        if not issues:
            self._issue_summary.setText("Keine priorisierungsrelevanten Fehler im aktuellen Zeitpunkt.")
            return

        filtered_issues = self._filter_prioritization_issues(issues)
        errors = sum(1 for issue in filtered_issues if issue.severity == "error")
        warnings = len(filtered_issues) - errors
        filter_suffix = "" if len(filtered_issues) == len(issues) else f" von {len(issues)}"
        self._issue_summary.setText(
            f"{errors} Fehler, {warnings} Warnung(en){filter_suffix}. Klick fokussiert Request."
        )
        if not filtered_issues:
            self._issue_summary.setText(f"Keine Fehler im aktuellen Filter ({len(issues)} insgesamt).")
            return

        for issue in filtered_issues:
            item = QListWidgetItem(self._format_issue_item(issue))
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue.message)
            self._issue_list.addItem(item)

    def _apply_issue_panel_policy(self, issues: list[PrioritizationIssue]) -> None:
        """Keep issue panel visible only when critical errors need attention."""
        if not hasattr(self, "_issue_panel"):
            return
        has_critical = any(issue.severity == "error" for issue in issues)
        should_collapse = not has_critical and self._is_compact_layout
        if has_critical:
            should_collapse = False
        if getattr(self, "_issue_panel_collapsed", False) != should_collapse:
            if hasattr(self, "_btn_toggle_issue_panel"):
                self._btn_toggle_issue_panel.blockSignals(True)
                self._btn_toggle_issue_panel.setChecked(should_collapse)
                self._btn_toggle_issue_panel.blockSignals(False)
            self._toggle_issue_panel_collapsed(should_collapse)

    def _toggle_issue_panel_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the prioritization issue panel without losing state."""
        self._issue_panel_collapsed = collapsed
        if hasattr(self, "_issue_content"):
            self._issue_content.setVisible(not collapsed)
        if hasattr(self, "_issue_panel"):
            self._issue_panel.setMinimumWidth(44 if collapsed else 260)
            self._issue_panel.setMaximumWidth(44 if collapsed else 320)
        if hasattr(self, "_issue_panel_title"):
            self._issue_panel_title.setText("!" if collapsed else "Priorisierungsfehler")
            self._issue_panel_title.setToolTip("Priorisierungsfehler" if collapsed else "")
        if hasattr(self, "_btn_toggle_issue_panel"):
            self._btn_toggle_issue_panel.setText(">" if collapsed else "Einklappen")
            self._btn_toggle_issue_panel.setToolTip(
                "Priorisierungsfehler-Panel ausklappen" if collapsed else "Priorisierungsfehler-Panel einklappen"
            )

    def _refresh_issue_intersection_filter(self, issues: list[PrioritizationIssue]) -> None:
        """Keep the intersection filter options aligned with the current issues."""
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

    def _filter_prioritization_issues(
        self,
        issues: list[PrioritizationIssue],
    ) -> list[PrioritizationIssue]:
        """Apply operator-selected issue-panel filters."""
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
        """Refresh the issue panel when an operator changes diagnostics filters."""
        if hasattr(self, "_issue_filter_combo"):
            self._issue_filter_mode = str(self._issue_filter_combo.currentData() or "all")
        if hasattr(self, "_issue_intersection_combo"):
            self._issue_filter_intersection = str(self._issue_intersection_combo.currentData() or "all")
        issues = list(getattr(self, "_current_prioritization_issues", []))
        if issues:
            self._refresh_prioritization_issues(issues)

    def _format_issue_item(self, issue: PrioritizationIssue) -> str:
        """Return compact issue card text."""
        lane_text = f"{issue.in_lane or '-'} -> {issue.out_lane or '-'}"
        delay_text = f"\nDelay: {issue.delay_seconds:.2f}s" if issue.delay_seconds is not None else ""
        return (
            f"{issue.issue_type}\n"
            f"I{issue.intersection_id} | Req {issue.request_id}/Seq {issue.sequence_number}\n"
            f"Lane {lane_text} | {issue.station_id}{delay_text}\n"
            f"{issue.source_summary}"
        )

    def _on_prioritization_issue_clicked(self, item: QListWidgetItem) -> None:
        """Synchronize map, ETA and details with a clicked prioritization issue."""
        issue = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(issue, PrioritizationIssue):
            return
        self._map_widget.highlight_request(issue.intersection_id, issue.request_id, issue.sequence_number)
        self._map_widget.focus_intersection(issue.intersection_id)
        self._select_eta_issue(issue)
        self._select_issue_message(issue)

    def _select_eta_issue(self, issue: PrioritizationIssue) -> None:
        """Select the matching ETA request track if present."""
        prefix = f"REQ:{issue.intersection_id}:{issue.request_id}:{issue.sequence_number}:{issue.station_id}:"
        for index in range(self._eta_station_combo.count()):
            key = self._eta_station_combo.itemData(index)
            if isinstance(key, str) and key.startswith(prefix):
                self._eta_station_combo.setCurrentIndex(index)
                return

    def _select_issue_message(self, issue: PrioritizationIssue) -> None:
        """Jump to a correlated SREM/SSEM message for the issue when possible."""
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
        """Small UI-local integer coercion for issue/message matching."""
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

    def _format_forecast_summary(self, forecast) -> str:
        """Build a compact one-line summary of a SPAT forecast."""
        if forecast is None or not forecast.segments_by_group:
            return "Keine Prognose"

        parts: list[str] = []
        for signal_group_id, segments in sorted(forecast.segments_by_group.items())[:3]:
            if not segments:
                continue
            next_segment = segments[0]
            duration = max(0.0, (next_segment.end - next_segment.start).total_seconds())
            parts.append(f"SG {signal_group_id}: {next_segment.phase.value} ({duration:.1f}s)")
        if len(forecast.segments_by_group) > 3:
            parts.append(f"+{len(forecast.segments_by_group) - 3} weitere")
        return " | ".join(parts) if parts else "Keine Prognose"

    def _format_forecast_timeline(self, forecast) -> str:
        """Render a compact ASCII timeline for the next 30 seconds."""
        if forecast is None or not forecast.segments_by_group:
            return "-" * FORECAST_TIMELINE_BUCKETS

        group_parts: list[str] = []
        for signal_group_id, segments in sorted(forecast.segments_by_group.items())[:2]:
            buckets = ["?"] * FORECAST_TIMELINE_BUCKETS
            if segments:
                horizon_start = segments[0].start
            else:
                horizon_start = None
            if horizon_start is None:
                continue
            bucket_width = forecast.horizon_seconds / FORECAST_TIMELINE_BUCKETS
            for bucket_index in range(FORECAST_TIMELINE_BUCKETS):
                bucket_midpoint = horizon_start.timestamp() + ((bucket_index + 0.5) * bucket_width)
                buckets[bucket_index] = self._phase_char_for_timestamp(
                    segments,
                    bucket_midpoint,
                )
            group_parts.append(f"SG{signal_group_id}:{''.join(buckets)}")

        if len(forecast.segments_by_group) > 2:
            group_parts.append(f"+{len(forecast.segments_by_group) - 2}")
        return " ".join(group_parts) if group_parts else "-" * FORECAST_TIMELINE_BUCKETS

    def _phase_char_for_timestamp(self, segments, bucket_midpoint: float) -> str:
        """Map one time bucket to a compact phase character."""
        for segment in segments:
            if segment.start.timestamp() <= bucket_midpoint <= segment.end.timestamp():
                phase = segment.phase.value
                if "Movement-Allowed" in phase:
                    return "G"
                if "clearance" in phase:
                    return "C"
                if "pre-Movement" in phase:
                    return "P"
                if "caution-Conflicting-Traffic" in phase:
                    return "!"
                if "stop" in phase or "Remain" in phase:
                    return "R"
                return "?"
        return "."

    def _estimate_visible_message_rate(self, timeline_position) -> float:
        """Estimate messages per second for the current filtered playback slice."""
        messages = self._player._messages
        if len(messages) < 2:
            return float(len(messages))

        window_seconds = 5.0
        start_time = timeline_position.timestamp() - window_seconds
        count = sum(1 for msg in messages if start_time <= msg.timestamp.timestamp() <= timeline_position.timestamp())
        return count / window_seconds

    def _format_revision_text(self, intersection) -> str:
        """Render MAP/SPAT revision state compactly."""
        map_rev = "-" if intersection.map_revision is None else str(intersection.map_revision)
        spat_rev = "-" if intersection.spat_revision is None else str(intersection.spat_revision)
        if intersection.revision_mismatch:
            return f"MAP {map_rev} / SPAT {spat_rev} (!)"
        return f"MAP {map_rev} / SPAT {spat_rev}"

    def _format_lane_text(self, request: ActiveRequest) -> str:
        """Render active request lane information."""
        in_lane = "-" if request.in_lane is None else str(request.in_lane)
        out_lane = "-" if request.out_lane is None else str(request.out_lane)
        return f"{in_lane} -> {out_lane}"

    def _format_visual_lane_text(self, request_visual) -> str:
        """Render lane information for a request visual state."""
        in_lane = "-" if request_visual.in_lane is None else str(request_visual.in_lane)
        out_lane = "-" if request_visual.out_lane is None else str(request_visual.out_lane)
        return f"{in_lane} -> {out_lane}"

    def _find_eta_verification(self, scene: SceneSnapshot, request: ActiveRequest):
        """Find ETA verification data for one active request."""
        for verification in scene.eta_verifications:
            if (
                verification.intersection_id == request.intersection_id
                and verification.request_id == request.request_id
                and verification.sequence_number == request.sequence_number
            ):
                return verification
        return None

    def _find_eta_verification_by_key(
        self,
        scene: SceneSnapshot,
        intersection_id: int,
        request_id: int,
        sequence_number: int,
    ):
        """Find ETA verification data by explicit request correlation key."""
        for verification in scene.eta_verifications:
            if (
                verification.intersection_id == intersection_id
                and verification.request_id == request_id
                and verification.sequence_number == sequence_number
            ):
                return verification
        return None

    def _format_eta_accuracy(self, value: float | None) -> str:
        """Format mean absolute ETA error."""
        if value is None:
            return "-"
        return f"{value:.1f}s"

    def _update_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable playback and export controls."""
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

    def _set_loading_state(
        self,
        loading: bool,
        minimum: int = 0,
        maximum: int = 0,
        status_message: str = "",
    ) -> None:
        """Show or hide the loading progress indicator."""
        self._progress.setVisible(loading)
        self._progress.setRange(minimum, maximum)
        self._progress.setValue(minimum)
        self._btn_load.setEnabled(not loading)
        self._btn_reload_last.setEnabled(not loading and bool(self._memory.existing_last_session_files()))
        self._btn_cancel_load.setEnabled(loading)
        if status_message:
            self._statusbar.showMessage(status_message)

    def _update_overview_for_session(self, paths: list[str], session: SessionData) -> None:
        """Refresh the overview cards after a successful load."""
        self._lbl_title.setText("Sitzung geladen")
        self._lbl_subtitle.setText(
            f"{Path(paths[0]).name}" if len(paths) == 1 else f"{len(paths)} PCAP-Dateien kombiniert"
        )
        msg_types = ", ".join(
            f"{msg_type.value}: {count}"
            for msg_type, count in sorted(session.msg_type_counts.items(), key=lambda item: item[0].value)
        )
        self._lbl_memory.setText(f"Nachrichtentypen: {msg_types}" if msg_types else "Keine Typverteilung verfuegbar")
        self._set_stat_card_value(self._stat_files, str(len(paths)))
        self._set_stat_card_value(self._stat_messages, str(len(session.messages)))
        self._set_stat_card_value(self._stat_stations, str(len(session.station_ids)))
        self._update_status_metrics(len(session.messages))
        self._update_compact_overview_text()

    def _refresh_memory_banner(self) -> None:
        """Show a startup banner based on persistent memory."""
        self._lbl_title.setText("PCAP2KML Player")
        self._lbl_subtitle.setText("Ziehe PCAP-Dateien ins Fenster oder lade die letzte Sitzung mit einem Klick.")
        last_files = self._memory.existing_last_session_files()
        if last_files:
            self._lbl_memory.setText(
                f"Letzte Sitzung: {len(last_files)} Datei(en), "
                f"{self._memory.last_session_message_count} Nachrichten, "
                f"{self._memory.last_session_station_count} Stationen"
            )
            self._set_stat_card_value(self._stat_files, str(len(last_files)))
            self._set_stat_card_value(self._stat_messages, str(self._memory.last_session_message_count))
            self._set_stat_card_value(self._stat_stations, str(self._memory.last_session_station_count))
            self._status_metrics.setText("Bereit fuer letzte Sitzung")
            self._update_compact_overview_text()
            return

        self._lbl_memory.setText("Noch keine persistente Sitzung gespeichert")
        self._set_stat_card_value(self._stat_files, "0")
        self._set_stat_card_value(self._stat_messages, "0")
        self._set_stat_card_value(self._stat_stations, "0")
        self._status_metrics.setText("Noch keine Sitzung geladen")
        self._update_compact_overview_text()

    def _update_status_metrics(self, visible_messages: int) -> None:
        """Update the compact status metrics label."""
        if not self._session:
            self._status_metrics.setText("Noch keine Sitzung geladen")
            return
        self._status_metrics.setText(
            f"Sichtbar: {visible_messages} | Stationen: {len(self._active_stations)} | "
            f"Dauer: {self._player.format_time(self._session.duration_seconds)}"
        )

    def _clear_session_views(self) -> None:
        """Reset map, tables, and playback to the empty state."""
        self._map_widget.clear()
        self._msg_table.setRowCount(0)
        self._message_row_lookup = {}
        self._last_highlighted_row = None
        self._last_detail_key = None
        self._pending_detail_message = None
        self._problem_replay_indices = []
        self._refresh_prioritization_issues([])
        self._detail_table.hide()
        self._clear_scene_panel()
        if hasattr(self, "_eta_station_combo"):
            self._eta_station_combo.blockSignals(True)
            self._eta_station_combo.clear()
            self._eta_station_combo.blockSignals(False)
        if hasattr(self, "_eta_graph"):
            self._eta_graph.set_messages([])
            self._eta_graph.set_station(None)
            self._eta_graph.set_current_time(None)
            self._refresh_eta_dashboard()
        if hasattr(self, "_eta_summary"):
            self._eta_summary.setText("Keine PCAP-Sitzung geladen.")
        if hasattr(self, "_context_tabs"):
            self._context_tabs.setCurrentIndex(1)
            self._context_tabs.setVisible(True)
        if hasattr(self, "_btn_toggle_message_table"):
            self._btn_toggle_message_table.blockSignals(True)
            self._btn_toggle_message_table.setChecked(False)
            self._btn_toggle_message_table.setText("Tabelle maximieren")
            self._btn_toggle_message_table.blockSignals(False)
        if hasattr(self, "_right_splitter"):
            self._right_splitter.setSizes([460, 280])
        self._message_table_maximized = False
        self._reset_playback_render_caches()
        self._issue_filter_mode = "all"
        self._issue_filter_intersection = "all"
        self._apply_issue_panel_policy([])
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

    def _clear_scene_panel(self) -> None:
        """Reset the scene panel to its empty state."""
        self._scene_summary.setText("Keine Szene verfuegbar. Lade eine PCAP-Datei und starte die Wiedergabe.")
        self._scene_metrics.setText("")
        self._scene_warning_label.clear()
        self._scene_warning_label.hide()
        self._scene_intersection_table.setRowCount(0)
        self._scene_requests_table.setRowCount(0)

    def _restore_window_state(self) -> None:
        """Restore persisted geometry and splitter layout."""
        geometry = self._settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.value("window/splitter")
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)
        right_splitter_state = self._settings.value("window/right_splitter")
        if right_splitter_state is not None and hasattr(self, "_right_splitter"):
            self._right_splitter.restoreState(right_splitter_state)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window state and app memory on close."""
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/splitter", self._splitter.saveState())
        if hasattr(self, "_right_splitter"):
            self._settings.setValue("window/right_splitter", self._right_splitter.saveState())
        self._memory.save()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept supported local PCAP files via drag and drop."""
        urls = event.mimeData().urls()
        if any(
            url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".pcap", ".pcapng", ".cap"} for url in urls
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Load supported dropped files."""
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
