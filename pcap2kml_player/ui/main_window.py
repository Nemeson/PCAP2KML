"""PyQt6 main window for PCAP2KML Player.

Contains the toolbar, splitter layout (map + message list),
playback controls, and filter widgets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, set as typing_set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from data_model import MessageType, SessionData, V2xMessage
from kml_exporter import export_kml
from map_widget import MapWidget
from pcap_parser import parse_pcap
from player_controller import SPEED_OPTIONS, PlayerController

logger = logging.getLogger(__name__)

# Column indices for the message table
COL_TIMESTAMP = 0
COL_STATION = 1
COL_MSGTYPE = 2
COL_LATLON = 3
COL_SPEED_HEADING = 4
NUM_COLUMNS = 5

TABLE_HEADERS = ["Timestamp", "Station ID", "Msg Type", "Lat / Lon", "Speed / Heading"]

# Highlight color for the currently playing message row
HIGHLIGHT_COLOR = "#ffe082"


class MainWindow(QMainWindow):
    """Main application window for PCAP2KML Player."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCAP2KML Player")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self._session: Optional[SessionData] = None
        self._active_types: set[MessageType] = set(MessageType)
        self._active_stations: set[str] = set()
        self._all_station_ids: set[str] = set()

        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        self._update_controls_enabled(False)

    # ─── UI Setup ─────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the complete UI layout."""
        # Toolbar
        self._setup_toolbar()

        # Central widget: splitter with map + message list
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Filter row above the splitter
        self._setup_filter_row(main_layout)

        # Splitter: map (left) + message list (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._map_widget = MapWidget()
        splitter.addWidget(self._map_widget)

        # Message list (right panel)
        right_panel = self._setup_message_list()
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 7)  # 70% map
        splitter.setStretchFactor(1, 3)  # 30% list

        main_layout.addWidget(splitter)

        # Playback controls below the splitter
        self._setup_playback_controls(main_layout)

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Bereit — PCAP-Datei laden zum Starten")

    def _setup_toolbar(self) -> None:
        """Create the toolbar with file operations."""
        toolbar = QToolBar("Hauptwerkzeugleiste")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._btn_load = QPushButton("PCAP laden")
        self._btn_load.setToolTip("Eine oder mehrere PCAP-Dateien öffnen")
        toolbar.addWidget(self._btn_load)

        toolbar.addSeparator()

        self._btn_export_kml = QPushButton("KML exportieren")
        self._btn_export_kml.setToolTip("KML-Dateien für alle gefilterten Entitäten exportieren")
        toolbar.addWidget(self._btn_export_kml)

        toolbar.addSeparator()

        self._btn_update_schemas = QPushButton("ASN.1 Schemas aktualisieren")
        self._btn_update_schemas.setToolTip("ASN.1-Schemadateien aus Git-Repo aktualisieren")
        toolbar.addWidget(self._btn_update_schemas)

    def _setup_filter_row(self, parent_layout: QVBoxLayout) -> None:
        """Create the filter row with message type checkboxes and station selector."""
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 4)

        # Message type filters
        filter_layout.addWidget(QLabel("Nachrichtentyp:"))
        self._type_checkboxes: dict[MessageType, QCheckBox] = {}
        for mt in MessageType:
            cb = QCheckBox(mt.value)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_filter_changed)
            self._type_checkboxes[mt] = cb
            filter_layout.addWidget(cb)

        filter_layout.addSpacing(20)

        # Station ID filter
        filter_layout.addWidget(QLabel("Station:"))
        self._station_list = QListWidget()
        self._station_list.setMaximumHeight(80)
        self._station_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._station_list.itemChanged.connect(self._on_station_filter_changed)
        filter_layout.addWidget(self._station_list)

        filter_layout.addStretch()
        parent_layout.addWidget(filter_widget)

    def _setup_message_list(self) -> QWidget:
        """Create the message table widget."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self._msg_table = QTableWidget(0, NUM_COLUMNS)
        self._msg_table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self._msg_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._msg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._msg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._msg_table.setAlternatingRowColors(True)
        self._msg_table.verticalHeader().setVisible(False)

        self._msg_table.cellClicked.connect(self._on_table_row_clicked)

        layout.addWidget(self._msg_table)
        return panel

    def _setup_playback_controls(self, parent_layout: QVBoxLayout) -> None:
        """Create the playback control bar."""
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(4, 2, 4, 2)

        # Play/Pause/Stop buttons
        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedWidth(36)
        self._btn_pause = QPushButton("⏸")
        self._btn_pause.setFixedWidth(36)
        self._btn_stop = QPushButton("⏹")
        self._btn_stop.setFixedWidth(36)

        layout.addWidget(self._btn_play)
        layout.addWidget(self._btn_pause)
        layout.addWidget(self._btn_stop)

        # Position slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        layout.addWidget(self._slider, stretch=1)

        # Speed selector
        layout.addWidget(QLabel("Geschw.:"))
        self._speed_combo = QComboBox()
        for spd in SPEED_OPTIONS:
            self._speed_combo.addItem(f"{spd}x")
        self._speed_combo.setCurrentIndex(2)  # 1.0x
        self._speed_combo.setFixedWidth(70)
        layout.addWidget(self._speed_combo)

        # Time display
        self._lbl_time = QLabel("00:00.0 / 00:00.0")
        self._lbl_time.setFixedWidth(140)
        layout.addWidget(self._lbl_time)

        parent_layout.addWidget(controls)

    # ─── Player Setup ─────────────────────────────────────────────

    def _setup_player(self) -> None:
        """Initialize the playback controller."""
        self._player = PlayerController(self)

    def _connect_signals(self) -> None:
        """Connect all UI signals to their handlers."""
        # Toolbar
        self._btn_load.clicked.connect(self._on_load_pcap)
        self._btn_export_kml.clicked.connect(self._on_export_kml)
        self._btn_update_schemas.clicked.connect(self._on_update_schemas)

        # Playback controls
        self._btn_play.clicked.connect(self._player.play)
        self._btn_pause.clicked.connect(self._player.pause)
        self._btn_stop.clicked.connect(self._player.stop)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self._slider.sliderMoved.connect(self._on_slider_moved)

        # Player signals
        self._player.tick.connect(self._on_playback_tick)
        self._player.state_changed.connect(self._on_player_state_changed)
        self._player.position_changed.connect(self._on_player_position_changed)
        self._player.duration_changed.connect(self._on_duration_changed)

    # ─── PCAP Loading ─────────────────────────────────────────────

    def _on_load_pcap(self) -> None:
        """Open file dialog and load PCAP file(s)."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "PCAP-Dateien öffnen",
            "",
            "PCAP-Dateien (*.pcap *.pcapng *.cap);;Alle Dateien (*)",
        )
        if not paths:
            return

        self._statusbar.showMessage("PCAP-Dateien werden geladen...")
        self._session = SessionData()

        for path in paths:
            try:
                parse_pcap(path, self._session)
            except FileNotFoundError:
                QMessageBox.warning(self, "Fehler", f"Datei nicht gefunden:\n{path}")
            except ValueError as e:
                QMessageBox.warning(self, "Fehler", str(e))
            except Exception as e:
                QMessageBox.critical(
                    self, "Fehler",
                    f"Fehler beim Parsen von {Path(path).name}:\n{e}"
                )

        if not self._session.messages:
            self._statusbar.showMessage("Keine V2X/NMEA-Nachrichten gefunden")
            QMessageBox.information(
                self, "Hinweis",
                "In den geladenen PCAP-Dateien wurden keine V2X- oder NMEA-Nachrichten gefunden."
            )
            return

        self._all_station_ids = set(self._session.station_ids)
        self._active_stations = set(self._session.station_ids)
        self._active_types = set(MessageType)

        self._populate_station_list()
        self._populate_message_table()
        self._map_widget.load_messages(self._session.messages)
        self._player.set_session(self._session)
        self._update_controls_enabled(True)

        self._statusbar.showMessage(
            f"{len(self._session.messages)} Nachrichten geladen — "
            f"{len(self._session.station_ids)} Stationen — "
            f"Dauer: {self._player.format_time(self._session.duration_seconds)}"
        )

    # ─── KML Export ────────────────────────────────────────────────

    def _on_export_kml(self) -> None:
        """Export KML files for all filtered entities."""
        if not self._session:
            return

        dir_path = QFileDialog.getExistingDirectory(
            self, "KML-Exportverzeichnis wählen", ""
        )
        if not dir_path:
            return

        try:
            created = export_kml(
                self._session,
                Path(dir_path),
                active_types=self._active_types if self._active_types != set(MessageType) else None,
                active_stations=self._active_stations if self._active_stations != self._all_station_ids else None,
            )
            self._statusbar.showMessage(f"{len(created)} KML-Dateien exportiert nach {dir_path}")
            QMessageBox.information(
                self, "Export erfolgreich",
                f"{len(created)} KML-Dateien wurden exportiert nach:\n{dir_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export-Fehler", str(e))

    # ─── ASN.1 Schema Update ──────────────────────────────────────

    def _on_update_schemas(self) -> None:
        """Update ASN.1 schemas from Git repository."""
        try:
            from asn1_schemas import update_from_git
            if update_from_git():
                self._statusbar.showMessage("ASN.1-Schemas erfolgreich aktualisiert")
                QMessageBox.information(self, "Erfolg", "ASN.1-Schemas wurden aktualisiert.")
            else:
                self._statusbar.showMessage("ASN.1-Schema-Update fehlgeschlagen")
                QMessageBox.warning(
                    self, "Fehler",
                    "ASN.1-Schemas konnten nicht aktualisiert werden.\n"
                    "Prüfen Sie Ihre Internetverbindung und Git-Installation."
                )
        except ImportError:
            QMessageBox.warning(self, "Hinweis", "asn1tools ist nicht installiert.")

    # ─── Filter Handling ──────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        """Handle message type checkbox changes."""
        self._active_types = {
            mt for mt, cb in self._type_checkboxes.items() if cb.isChecked()
        }
        self._apply_filters()

    def _on_station_filter_changed(self) -> None:
        """Handle station filter list changes."""
        self._active_stations = {
            item.text()
            for item in self._station_list.selectedItems()
        }
        # If nothing selected, show all
        if not self._active_stations:
            self._active_stations = set(self._all_station_ids)
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Apply current filters to map, table, and player."""
        if not self._session:
            return

        filtered = self._session.filter_messages(self._active_types, self._active_stations)

        self._populate_message_table(filtered)
        self._map_widget.load_messages(filtered)
        self._player.set_filtered_messages(filtered)

        self._statusbar.showMessage(
            f"Filter aktiv: {len(filtered)} / {len(self._session.messages)} Nachrichten"
        )

    def _populate_station_list(self) -> None:
        """Populate the station ID filter list."""
        self._station_list.blockSignals(True)
        self._station_list.clear()
        for sid in sorted(self._all_station_ids):
            item = QListWidgetItem(sid)
            item.setSelected(True)
            self._station_list.addItem(item)
        self._station_list.blockSignals(False)

    def _populate_message_table(self, messages: Optional[list[V2xMessage]] = None) -> None:
        """Fill the message table with data."""
        if messages is None and self._session:
            messages = self._session.messages
        elif messages is None:
            messages = []

        self._msg_table.setRowCount(len(messages))
        for row, msg in enumerate(messages):
            self._msg_table.setItem(row, COL_TIMESTAMP, QTableWidgetItem(
                msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
            ))
            self._msg_table.setItem(row, COL_STATION, QTableWidgetItem(msg.station_id))
            self._msg_table.setItem(row, COL_MSGTYPE, QTableWidgetItem(msg.msg_type.value))
            self._msg_table.setItem(row, COL_LATLON, QTableWidgetItem(
                f"{msg.latitude:.6f}, {msg.longitude:.6f}"
            ))
            speed_str = f"{msg.speed:.1f} m/s" if msg.speed is not None else "—"
            heading_str = f"{msg.heading:.0f}°" if msg.heading is not None else "—"
            self._msg_table.setItem(row, COL_SPEED_HEADING, QTableWidgetItem(
                f"{speed_str} / {heading_str}"
            ))

    # ─── Playback Event Handlers ──────────────────────────────────

    def _on_playback_tick(self, msg: Optional[V2xMessage]) -> None:
        """Handle a playback tick — update map and highlight table row."""
        if msg is None:
            return

        # Update map marker
        self._map_widget.update_playback_position(msg)

        # Highlight the current row in the table
        self._highlight_table_row(msg)

        # Update time display
        current_time = self._player.get_current_playback_time()
        total_time = self._session.duration_seconds if self._session else 0.0
        self._lbl_time.setText(
            f"{self._player.format_time(current_time)} / "
            f"{self._player.format_time(total_time)}"
        )

    def _highlight_table_row(self, msg: V2xMessage) -> None:
        """Highlight the table row corresponding to the current message."""
        # Find the row by matching timestamp and station
        for row in range(self._msg_table.rowCount()):
            ts_item = self._msg_table.item(row, COL_TIMESTAMP)
            st_item = self._msg_table.item(row, COL_STATION)
            if ts_item and st_item:
                msg_ts = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
                if ts_item.text() == msg_ts and st_item.text() == msg.station_id:
                    self._msg_table.selectRow(row)
                    self._msg_table.scrollToItem(
                        self._msg_table.item(row, 0),
                        QTableWidget.ScrollHint.EnsureVisible,
                    )
                    break

    def _on_player_state_changed(self, state: str) -> None:
        """Update button states based on player state."""
        self._btn_play.setEnabled(state != "playing")
        self._btn_pause.setEnabled(state == "playing")

    def _on_player_position_changed(self, index: int) -> None:
        """Update the slider position."""
        total = self._player.total_messages
        if total > 0:
            self._slider.blockSignals(True)
            self._slider.setValue(int((index / total) * 1000))
            self._slider.blockSignals(False)

    def _on_duration_changed(self, seconds: float) -> None:
        """Update the time display with new duration."""
        self._lbl_time.setText(
            f"00:00.0 / {self._player.format_time(seconds)}"
        )

    def _on_speed_changed(self, index: int) -> None:
        """Handle speed combo box change."""
        if 0 <= index < len(SPEED_OPTIONS):
            self._player.set_speed(SPEED_OPTIONS[index])

    def _on_slider_moved(self, value: int) -> None:
        """Handle slider scrubbing."""
        self._player.seek_to_position(value / 1000.0)

    def _on_table_row_clicked(self, row: int, col: int) -> None:
        """Handle table row click — jump to that message."""
        # Find the message index in the player's message list
        ts_item = self._msg_table.item(row, COL_TIMESTAMP)
        st_item = self._msg_table.item(row, COL_STATION)
        if ts_item and st_item:
            target_ts = ts_item.text()
            target_station = st_item.text()
            # Search in player messages
            for i, msg in enumerate(self._player._messages):
                if (msg.timestamp.strftime("%H:%M:%S.%f")[:-3] == target_ts
                        and msg.station_id == target_station):
                    self._player.seek_to_index(i)
                    break

    # ─── Utility ──────────────────────────────────────────────────

    def _update_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable playback and export controls."""
        self._btn_play.setEnabled(enabled)
        self._btn_pause.setEnabled(False)
        self._btn_stop.setEnabled(enabled)
        self._btn_export_kml.setEnabled(enabled)
        self._slider.setEnabled(enabled)
        self._speed_combo.setEnabled(enabled)