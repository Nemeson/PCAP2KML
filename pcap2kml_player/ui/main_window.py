"""PyQt6 main window for PCAP2KML Player."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings, QThread, Qt
from PyQt6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..app_memory import AppMemory
from ..data_model import MessageType, SessionData, V2xMessage
from ..kml_exporter import export_kml
from ..map_widget import MapWidget
from ..parsing_worker import ParsingWorker
from ..player_controller import SPEED_OPTIONS, PlayerController
from ..prioritization_exporter import export_prioritization_issues
from .eta_graph_widget import EtaGraphWidget, build_eta_selection_options
from ..scene_model import (
    ActiveRequest,
    PrioritizationIssue,
    RequestOperationalStatus,
    SceneSnapshot,
    build_prioritization_issues,
    build_scene_snapshot,
    collect_prioritization_issue_occurrences,
    get_request_operational_status,
    find_overdue_requests,
    get_clock_skew_warnings,
    get_eta_accuracy_seconds,
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
SCENE_INTERSECTION_HEADERS = ["Intersection", "Revision", "Signalgruppen", "Prognose", "30s Timeline"]
SCENE_REQUEST_HEADERS = ["Request", "Station", "Prio", "Status", "Lanes"]
FORECAST_TIMELINE_BUCKETS = 15


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

        self._session: Optional[SessionData] = None
        self._active_types: set[MessageType] = set(MessageType)
        self._active_stations: set[str] = set()
        self._all_station_ids: set[str] = set()
        self._show_canonical_messages = False
        self._loader_thread: Optional[QThread] = None
        self._loader_worker: Optional[ParsingWorker] = None
        self._message_row_lookup: dict[tuple[str, str], int] = {}
        self._last_highlighted_row: Optional[int] = None
        self._last_detail_key: Optional[tuple[str, str]] = None
        self._pending_detail_message: Optional[V2xMessage] = None
        self._current_prioritization_issues: list[PrioritizationIssue] = []
        self._issue_filter_mode = "all"
        self._issue_filter_intersection = "all"
        self._issue_panel_collapsed = False
        self._problem_replay_indices: list[int] = []
        self._message_table_maximized = False
        self._last_scene_update_monotonic = 0.0
        self._last_scene_cache_key: Optional[tuple[int, str]] = None
        self._last_scene_cache_snapshot: Optional[SceneSnapshot] = None
        self._last_map_slice_update_monotonic = 0.0
        self._last_map_slice_index: Optional[int] = None
        self._last_map_messages_id: Optional[int] = None

        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        self._restore_window_state()
        self._refresh_memory_banner()
        self._update_controls_enabled(False)

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
        self._map_widget = MapWidget()
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._map_widget, stretch=1)

        issue_panel = QFrame()
        self._issue_panel = issue_panel
        issue_panel.setObjectName("PrioritizationIssuePanel")
        issue_panel.setMinimumWidth(260)
        issue_panel.setMaximumWidth(320)
        issue_panel.setStyleSheet(
            "QFrame#PrioritizationIssuePanel {"
            "background: #f8fbff; border: 1px solid #d7dde8; border-radius: 10px;"
            "}"
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
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { margin: 3px 0; padding: 7px; border-radius: 7px; }"
            "QListWidget::item:selected { background: #dbeafe; color: #111827; }"
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
        self._btn_export_issues.setToolTip("Priorisierungsfehler als CSV und JSON exportieren")
        toolbar.addWidget(self._btn_export_issues)

        toolbar.addSeparator()

        self._btn_update_schemas = QPushButton("ASN.1-Schemas aktualisieren")
        self._btn_update_schemas.setToolTip("ASN.1-Schemadateien aus dem Git-Repo aktualisieren")
        toolbar.addWidget(self._btn_update_schemas)

    def _setup_overview_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the SWARCO-inspired overview header."""
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #d7dde8; border-radius: 16px; }"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        self._lbl_title = QLabel("PCAP2KML Player")
        self._lbl_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #10233f;")
        self._lbl_subtitle = QLabel(
            "Datenorientierte V2X-Analyse in einer klaren, operativen SWARCO-ITS-Anmutung."
        )
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
        parent_layout.addWidget(panel)

    def _create_stat_card(self, title: str, value: str) -> QFrame:
        """Create a compact summary card."""
        card = QFrame()
        card.setMinimumWidth(130)
        card.setStyleSheet(
            "QFrame { background: #f5f7fb; border: 1px solid #d7dde8; border-radius: 14px; }"
        )
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
        self._merge_view_checkbox.setToolTip(
            "TXA/RXA-Mehrfachbeobachtungen nur einmal kanonisch anzeigen"
        )
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
        self._detail_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._detail_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._apply_table_readability_style(self._detail_table)
        self._detail_table.hide()
        details_layout.addWidget(self._detail_table, stretch=1)
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

        self._scene_summary = QLabel(
            "Keine Szene verfuegbar. Lade eine PCAP-Datei und starte die Wiedergabe."
        )
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
        self._scene_intersection_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
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
        self._scene_requests_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
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
        controls.addStretch()
        parent_layout.addLayout(controls)

        self._eta_summary = QLabel("Keine PCAP-Sitzung geladen.")
        self._eta_summary.setWordWrap(True)
        self._eta_summary.setStyleSheet("color: #42546b;")
        parent_layout.addWidget(self._eta_summary)

        self._eta_graph = EtaGraphWidget()
        parent_layout.addWidget(self._eta_graph, stretch=1)

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
        self._btn_update_schemas.clicked.connect(self._on_update_schemas)

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
        if self._loader_thread is not None:
            self._loader_thread.quit()
            self._loader_thread.wait()
            self._loader_thread.deleteLater()
            self._loader_thread = None
        if self._loader_worker is not None:
            self._loader_worker.deleteLater()
            self._loader_worker = None

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
                active_stations=(
                    self._active_stations
                    if self._active_stations != self._all_station_ids
                    else None
                ),
                canonical=self._show_canonical_messages,
            )
        except Exception as exc:  # pragma: no cover
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
            "Priorisierungsfehler wurden exportiert:\n"
            + "\n".join(str(path) for path in created),
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

    def _on_filter_changed(self) -> None:
        """Handle message type filter changes."""
        self._active_types = {
            msg_type for msg_type, checkbox in self._type_checkboxes.items() if checkbox.isChecked()
        }
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
        self._lbl_filter_hint.setText(
            f"{len(filtered)} von {len(self._session.messages)} Nachrichten sichtbar"
        )
        self._statusbar.showMessage(
            f"Filter aktiv: {len(filtered)} / {len(self._session.messages)} Nachrichten"
        )
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

    def _populate_message_table(self, messages: Optional[list[V2xMessage]] = None) -> None:
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

    def _on_playback_tick(self, msg: Optional[V2xMessage]) -> None:
        """Update map and details when the visible playback message changes."""
        if msg is None:
            return

        if self._should_render_full_map_slice(msg):
            self._map_widget.render_playback_slice(self._player._messages, self._player.current_index)
        self._map_widget.update_playback_position(msg)
        self._highlight_table_row(msg)
        self._show_security_detail(msg, auto_focus=False)
        self._update_scene_for_message(msg)
        self._eta_graph.set_current_time(msg.timestamp)

    def _should_render_full_map_slice(self, msg: V2xMessage) -> bool:
        """Throttle expensive map layer sync while keeping critical states immediate."""
        messages_id = id(self._player._messages)
        index = self._player.current_index
        now = time.perf_counter()
        if self._last_map_messages_id != messages_id:
            should_render = True
        elif self._last_map_slice_index is None or index < self._last_map_slice_index:
            should_render = True
        elif msg.msg_type in {MessageType.MAPEM, MessageType.SPATEM, MessageType.SREM, MessageType.SSEM}:
            should_render = True
        elif now - self._last_map_slice_update_monotonic >= 0.25:
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
        self._lbl_time.setText(
            f"{self._player.format_time(seconds)} / {self._player.format_time(total_time)}"
        )

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

    def _on_eta_station_changed(self, station_id: str) -> None:
        """Update the ETA graph when a single vehicle is selected."""
        self._eta_graph.set_selection(self._eta_station_combo.currentData())
        self._eta_summary.setText(self._eta_graph.summary_text())

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
            "Tabellenbereich wiederherstellen"
            if maximized
            else "Tabelle maximieren"
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
        indices = [
            occurrence.message_index
            for occurrence in collect_prioritization_issue_occurrences(messages)
        ]

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
            if (
                msg.timestamp.strftime("%H:%M:%S.%f")[:-3] == target_timestamp
                and msg.station_id == target_station
            ):
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
                ("Sicherheitsheader", "Kein Sicherheitsheader vorhanden oder nicht extrahierbar")
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

    def _update_scene_for_message(self, msg: Optional[V2xMessage], *, force: bool = False) -> None:
        """Rebuild and display the current scene snapshot for one playback position."""
        if msg is None or not self._player._messages:
            self._clear_scene_panel()
            self._refresh_prioritization_issues([])
            self._last_scene_cache_key = None
            self._last_scene_cache_snapshot = None
            return

        now = time.perf_counter()
        if (
            not force
            and self._player.state == "playing"
            and now - self._last_scene_update_monotonic < 0.25
        ):
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
        forecast_groups = sum(
            len(forecast.segments_by_group) for forecast in scene.forecasts.values()
        )
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
            warnings.append(
                f"{len(overdue_requests)} Anforderung(en) ohne SSEM-Antwort ueber Timeout."
            )
        if clock_skew_warnings:
            warnings.append(
                "Uhrenversatz erkannt: "
                + ", ".join(
                    f"Int {intersection_id} {skew:+.1f}s"
                    for intersection_id, skew in clock_skew_warnings[:3]
                )
            )
        inaccurate_eta = [item for item in scene.eta_verifications if not item.is_accurate]
        if inaccurate_eta:
            warnings.append(
                f"ETA-Abweichung > 2s bei {len(inaccurate_eta)} verifizierten Anfrage(n)."
            )
        self._scene_warning_label.setVisible(bool(warnings))
        self._scene_warning_label.setText(" | ".join(warnings))

        self._scene_intersection_table.setRowCount(len(intersections))
        for row, intersection in enumerate(intersections):
            signal_groups = sorted(intersection.signal_groups.values(), key=lambda item: item.signal_group_id)
            signal_group_summary = ", ".join(
                f"SG {group.signal_group_id}: {group.phase.value}"
                for group in signal_groups[:3]
            )
            if len(signal_groups) > 3:
                signal_group_summary += f" (+{len(signal_groups) - 3})"
            forecast = scene.forecasts.get(intersection.intersection_id)
            forecast_summary = self._format_forecast_summary(forecast)
            revision_text = self._format_revision_text(intersection)

            self._scene_intersection_table.setItem(
                row, 0, QTableWidgetItem(str(intersection.intersection_id))
            )
            self._scene_intersection_table.setItem(row, 1, QTableWidgetItem(revision_text))
            self._scene_intersection_table.setItem(
                row, 2, QTableWidgetItem(signal_group_summary or "Keine Signalgruppen")
            )
            self._scene_intersection_table.setItem(
                row, 3, QTableWidgetItem(forecast_summary)
            )
            self._scene_intersection_table.setItem(
                row, 4, QTableWidgetItem(self._format_forecast_timeline(forecast))
            )

        request_visuals = [
            visual
            for visuals in scene.request_visuals_by_intersection.values()
            for visual in visuals
        ]
        request_visuals.sort(
            key=lambda visual: (
                visual.display_rank,
                -(visual.importance_level or 0),
                -visual.requested_at.timestamp(),
            )
        )
        self._scene_requests_table.setRowCount(len(request_visuals))
        overdue_keys = {
            (request.intersection_id, request.request_id, request.sequence_number)
            for request in overdue_requests
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
                    str(request_visual.importance_level)
                    if request_visual.importance_level is not None
                    else "-"
                ),
            )
            self._scene_requests_table.setItem(row, 3, QTableWidgetItem(status))
            self._scene_requests_table.setItem(row, 4, QTableWidgetItem(lane_text))

    def _refresh_prioritization_issues(self, issues: list[PrioritizationIssue]) -> None:
        """Render prioritization issues in the map-side panel."""
        self._current_prioritization_issues = issues
        if not hasattr(self, "_issue_list"):
            return
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
            self._issue_summary.setText(
                f"Keine Fehler im aktuellen Filter ({len(issues)} insgesamt)."
            )
            return

        for issue in filtered_issues:
            item = QListWidgetItem(self._format_issue_item(issue))
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue.message)
            item.setForeground(Qt.GlobalColor.darkRed if issue.severity == "error" else Qt.GlobalColor.darkYellow)
            self._issue_list.addItem(item)

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
            self._issue_panel_title.setToolTip(
                "Priorisierungsfehler" if collapsed else ""
            )
        if hasattr(self, "_btn_toggle_issue_panel"):
            self._btn_toggle_issue_panel.setText(">" if collapsed else "Einklappen")
            self._btn_toggle_issue_panel.setToolTip(
                "Priorisierungsfehler-Panel ausklappen"
                if collapsed
                else "Priorisierungsfehler-Panel einklappen"
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
            self._issue_filter_intersection = str(
                self._issue_intersection_combo.currentData() or "all"
            )
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

    def _coerce_detail_int(self, value: object) -> Optional[int]:
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
            parts.append(
                f"SG {signal_group_id}: {next_segment.phase.value} ({duration:.1f}s)"
            )
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
        count = sum(
            1
            for msg in messages
            if start_time <= msg.timestamp.timestamp() <= timeline_position.timestamp()
        )
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

    def _format_eta_accuracy(self, value: Optional[float]) -> str:
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
        self._lbl_memory.setText(
            f"Nachrichtentypen: {msg_types}" if msg_types else "Keine Typverteilung verfuegbar"
        )
        self._set_stat_card_value(self._stat_files, str(len(paths)))
        self._set_stat_card_value(self._stat_messages, str(len(session.messages)))
        self._set_stat_card_value(self._stat_stations, str(len(session.station_ids)))
        self._update_status_metrics(len(session.messages))

    def _refresh_memory_banner(self) -> None:
        """Show a startup banner based on persistent memory."""
        self._lbl_title.setText("PCAP2KML Player")
        self._lbl_subtitle.setText(
            "Ziehe PCAP-Dateien ins Fenster oder lade die letzte Sitzung mit einem Klick."
        )
        last_files = self._memory.existing_last_session_files()
        if last_files:
            self._lbl_memory.setText(
                f"Letzte Sitzung: {len(last_files)} Datei(en), "
                f"{self._memory.last_session_message_count} Nachrichten, "
                f"{self._memory.last_session_station_count} Stationen"
            )
            self._set_stat_card_value(self._stat_files, str(len(last_files)))
            self._set_stat_card_value(
                self._stat_messages, str(self._memory.last_session_message_count)
            )
            self._set_stat_card_value(
                self._stat_stations, str(self._memory.last_session_station_count)
            )
            self._status_metrics.setText("Bereit fuer letzte Sitzung")
            return

        self._lbl_memory.setText("Noch keine persistente Sitzung gespeichert")
        self._set_stat_card_value(self._stat_files, "0")
        self._set_stat_card_value(self._stat_messages, "0")
        self._set_stat_card_value(self._stat_stations, "0")
        self._status_metrics.setText("Noch keine Sitzung geladen")

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
        self._last_scene_update_monotonic = 0.0
        self._last_scene_cache_key = None
        self._last_scene_cache_snapshot = None
        self._last_map_slice_update_monotonic = 0.0
        self._last_map_slice_index = None
        self._last_map_messages_id = None
        self._issue_filter_mode = "all"
        self._issue_filter_intersection = "all"
        self._issue_panel_collapsed = False
        if hasattr(self, "_btn_toggle_issue_panel"):
            self._btn_toggle_issue_panel.blockSignals(True)
            self._btn_toggle_issue_panel.setChecked(False)
            self._btn_toggle_issue_panel.blockSignals(False)
            self._toggle_issue_panel_collapsed(False)
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
        self._scene_summary.setText(
            "Keine Szene verfuegbar. Lade eine PCAP-Datei und starte die Wiedergabe."
        )
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
            url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".pcap", ".pcapng", ".cap"}
            for url in urls
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
