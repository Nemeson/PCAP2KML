"""PyQt6 main window for PCAP2KML Player."""

from __future__ import annotations

import logging
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
from ..scene_model import (
    ActiveRequest,
    RequestOperationalStatus,
    SceneSnapshot,
    build_scene_snapshot,
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
NUM_COLUMNS = 5

TABLE_HEADERS = ["Timestamp", "Station ID", "Msg Type", "Lat / Lon", "Speed / Heading"]
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
        self._loader_thread: Optional[QThread] = None
        self._loader_worker: Optional[ParsingWorker] = None
        self._message_row_lookup: dict[tuple[str, str], int] = {}
        self._last_highlighted_row: Optional[int] = None

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
        self._splitter.addWidget(self._map_widget)
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
        filter_layout.addStretch()
        parent_layout.addWidget(filter_widget)

    def _setup_message_list(self) -> QWidget:
        """Create the message table plus a tabbed context area."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._msg_table = QTableWidget(0, NUM_COLUMNS)
        self._msg_table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self._msg_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._msg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._msg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._msg_table.setAlternatingRowColors(True)
        self._msg_table.verticalHeader().setVisible(False)
        layout.addWidget(self._msg_table, stretch=3)

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
        self._detail_table.hide()
        details_layout.addWidget(self._detail_table, stretch=1)
        self._context_tabs.addTab(details_tab, "Details")

        scene_tab = QWidget()
        scene_layout = QVBoxLayout(scene_tab)
        scene_layout.setContentsMargins(10, 10, 10, 10)
        scene_layout.setSpacing(6)
        self._setup_scene_panel(scene_layout)
        self._context_tabs.addTab(scene_tab, "Szene")

        layout.addWidget(self._context_tabs, stretch=2)

        return panel

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

    def _setup_playback_controls(self, parent_layout: QVBoxLayout) -> None:
        """Create the playback control bar."""
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(4, 2, 4, 2)

        self._btn_play = QPushButton("Play")
        self._btn_pause = QPushButton("Pause")
        self._btn_stop = QPushButton("Stop")
        self._btn_play.setFixedWidth(72)
        self._btn_pause.setFixedWidth(72)
        self._btn_stop.setFixedWidth(72)

        layout.addWidget(self._btn_play)
        layout.addWidget(self._btn_pause)
        layout.addWidget(self._btn_stop)

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
        self._btn_update_schemas.clicked.connect(self._on_update_schemas)

        self._btn_play.clicked.connect(self._player.play)
        self._btn_pause.clicked.connect(self._player.pause)
        self._btn_stop.clicked.connect(self._player.stop)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._station_list.itemSelectionChanged.connect(self._on_station_filter_changed)
        self._msg_table.cellClicked.connect(self._on_table_row_clicked)

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
        self._player.set_session(session)
        self._detail_table.hide()
        self._update_scene_for_message(session.messages[0])
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

        filtered = self._session.filter_messages(self._active_types, self._active_stations)
        self._populate_message_table(filtered)
        self._map_widget.load_messages(filtered)
        self._player.set_filtered_messages(filtered)
        self._update_scene_for_message(filtered[0] if filtered else None)
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
        self._msg_table.setRowCount(len(messages))
        for row, msg in enumerate(messages):
            timestamp_text = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
            self._message_row_lookup[(timestamp_text, msg.station_id)] = row
            self._msg_table.setItem(
                row,
                COL_TIMESTAMP,
                QTableWidgetItem(timestamp_text),
            )
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

    def _on_playback_tick(self, msg: Optional[V2xMessage]) -> None:
        """Update map and details when the visible playback message changes."""
        if msg is None:
            return

        self._map_widget.render_playback_slice(self._player._messages, self._player.current_index)
        self._map_widget.update_playback_position(msg)
        self._highlight_table_row(msg)
        self._show_security_detail(msg)
        self._update_scene_for_message(msg)

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

    def _on_speed_changed(self, index: int) -> None:
        """Handle speed selector changes."""
        if 0 <= index < len(SPEED_OPTIONS):
            self._player.set_speed(SPEED_OPTIONS[index])

    def _on_slider_moved(self, value: int) -> None:
        """Seek playback when the timeline slider is moved."""
        self._player.seek_to_position(value / 1000.0)

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
                self._show_security_detail(msg)
                return

    def _show_security_detail(self, msg: V2xMessage) -> None:
        """Render message and PKI details for the selected message."""
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
        self._context_tabs.setCurrentIndex(0)

    def _update_scene_for_message(self, msg: Optional[V2xMessage]) -> None:
        """Rebuild and display the current scene snapshot for one playback position."""
        if msg is None or not self._player._messages:
            self._clear_scene_panel()
            return

        scene = build_scene_snapshot(self._player._messages, msg.timestamp)
        self._render_scene_snapshot(scene)

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
        self._slider.setEnabled(enabled)
        self._speed_combo.setEnabled(enabled)
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
        self._detail_table.hide()
        self._clear_scene_panel()
        if hasattr(self, "_context_tabs"):
            self._context_tabs.setCurrentIndex(1)
        self._player.set_filtered_messages([])
        self._all_station_ids.clear()
        self._active_stations.clear()
        self._station_list.clear()
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

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window state and app memory on close."""
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/splitter", self._splitter.saveState())
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
