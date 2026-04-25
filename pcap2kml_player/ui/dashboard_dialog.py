"""Standalone statistics dashboard dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..statistics import (
    SessionOverview,
    compute_message_rate,
    compute_session_overview,
    compute_station_speed_heading,
)
from ..data_model import SessionData


class StatisticsDashboard(QDialog):
    """Modal dialog showing session statistics."""

    def __init__(self, session: SessionData, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Statistik-Dashboard")
        self.setMinimumSize(600, 400)
        self._session = session

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Overview tab
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        overview = compute_session_overview(session)
        overview_layout.addWidget(QLabel(f"Gesamtnachrichten: {overview.total_messages}"))
        overview_layout.addWidget(QLabel(f"Stationen: {overview.station_count}"))
        overview_layout.addWidget(QLabel(f"Nachrichtentypen: {overview.unique_types}"))
        overview_layout.addWidget(QLabel(f"Dauer: {overview.duration_seconds:.1f} s"))
        overview_layout.addWidget(QLabel(f"Nachrichten/s: {overview.messages_per_second:.2f}"))
        tabs.addTab(overview_tab, "Überblick")

        # Message rate tab
        rate_tab = QWidget()
        rate_layout = QVBoxLayout(rate_tab)
        rate_table = QTableWidget()
        rate_table.setColumnCount(3)
        rate_table.setHorizontalHeaderLabels(["Start", "Ende", "Rate (Msgs/s)"])
        rates = compute_message_rate(session, bucket_seconds=1.0)
        rate_table.setRowCount(len(rates))
        for i, entry in enumerate(rates):
            rate_table.setItem(i, 0, QTableWidgetItem(entry.start_time.strftime("%H:%M:%S")))
            rate_table.setItem(i, 1, QTableWidgetItem(entry.end_time.strftime("%H:%M:%S")))
            rate_table.setItem(i, 2, QTableWidgetItem(f"{entry.rate:.2f}"))
        rate_layout.addWidget(rate_table)
        tabs.addTab(rate_tab, "Nachrichtenraten")

        # Speed/Heading tab
        speed_tab = QWidget()
        speed_layout = QVBoxLayout(speed_tab)
        speed_table = QTableWidget()
        speed_table.setColumnCount(4)
        speed_table.setHorizontalHeaderLabels(["Station", "Ø Speed", "Ø Heading", "Varianz"])
        stats = compute_station_speed_heading(session)
        speed_table.setRowCount(len(stats))
        for i, (station_id, sh) in enumerate(stats.items()):
            speed_table.setItem(i, 0, QTableWidgetItem(station_id))
            speed_table.setItem(i, 1, QTableWidgetItem(f"{sh.avg_speed:.1f}"))
            speed_table.setItem(i, 2, QTableWidgetItem(f"{sh.avg_heading:.1f}"))
            speed_table.setItem(i, 3, QTableWidgetItem(f"{sh.speed_variance:.1f}"))
        speed_layout.addWidget(speed_table)
        tabs.addTab(speed_tab, "Speed / Heading")

        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
