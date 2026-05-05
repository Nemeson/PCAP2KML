"""Dialog for displaying MAP/SPATEM validation results with HTML export."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..mapem_spatem_validator import MapValidationIssue, validation_summary


# C-Roads Handbook 3.2.0 Rule ID mapping
_RULE_ID_MAP: dict[str, str | None] = {
    # MAP structure
    "MAP_INTERSECTION_ID_MISSING": "3.2.2",
    "MAP_REVISION_MISSING": "3.2.3",
    "MAP_REFPOINT_INVALID": "3.2.4",
    "MAP_LANEWIDTH_MISSING": "3.2.5",
    "MAP_LANEWIDTH_UNUSUAL": "3.2.5",
    "MAP_LANESET_EMPTY": "3.3",
    # Lane checks
    "MAP_LANE_ID_MISSING": "3.3",
    "MAP_LANE_ID_DUPLICATE": "3.3",
    "MAP_LANE_NODELIST_SHORT": "3.3.4",
    "MAP_LANE_NODELIST_EXTREMELY_LONG": "3.3.4",
    "MAP_LANE_ROLE_MISSING": "3.3.1",
    "MAP_APPROACH_WITHOUT_DIRECTION": "3.3.1",
    # Lane attributes
    "MAP_LANE_ATTR_DIRECTIONALUSE_MISSING": "3.3.2.3",
    "MAP_LANE_ATTR_DIRECTIONALUSE_INVALID": "3.3.2.3",
    "MAP_LANE_ATTR_DIRECTIONALUSE_EXTENDED": "3.3.2.3",
    "MAP_LANE_ATTR_LANETYPE_MISSING": "3.3.2.1",
    "MAP_LANE_ATTR_LANETYPE_INVALID": "3.3.2.1",
    "MAP_LANE_ATTR_LANETYPE_UNUSUAL": "3.3.2.1",
    "MAP_LANE_ATTR_SHAREDWITH_INVALID_TYPE": "3.3.2.2",
    "MAP_LANE_ATTR_SHAREDWITH_INVALID": "3.3.2.2",
    "MAP_LANE_ATTR_SHAREDWITH_LONG": "3.3.2.2",
    # Maneuvers
    "MAP_MANEUVERS_MISSING": "3.3.3",
    "MAP_MANEUVERS_INVALID": "3.3.3",
    # Connections
    "MAP_CONNECTION_TARGET_UNKNOWN": "3.3.5",
    "MAP_CONNECTION_SIGNALGROUP_MISSING": "3.3.5",
    "MAP_EGRESS_WITH_SIGNAL_GROUP": "3.3.5",
    # Stop line
    "MAP_STOPLINE_RECOMMENDED": "4.11",
    # Crosswalk
    "CROSSWALK_NO_CONNECTION": "4.6",
    "CROSSWALK_CONNECTS_TO_CROSSWALK": "4.6",
    # Bicycle
    "BIKE_NO_CONNECTION": "4.8",
    "BIKE_NO_VEHICLE_CONNECTION": "4.8",
    # Roundabout
    "ROUNDABOUT_CIRCULAR_TOPOLOGY": "4.10",
    "LANES_NO_DIRECTION": "4.10",
    # SPATEM
    "SPAT_INTERSECTION_ID_MISSING": "5.2",
    "SPAT_REVISION_MISSING": "5.3",
    "SPAT_STATES_EMPTY": "5.7",
    "SPAT_SIGNALGROUP_MISSING": "5.7.1",
    "SPAT_EVENTSTATE_MISSING": "5.7.2",
    # Timing
    "SPAT_TIMING_MISSING": "5.7.4",
    "SPAT_STARTTIME_UNUSUAL": "5.7.4.1",
    "SPAT_MINENDTIME_UNUSUAL": "5.7.4.2",
    "SPAT_MAXENDTIME_UNUSUAL": "5.7.4.2",
    "SPAT_MINENDTIME_AFTER_MAX": "5.7.4.2",
    "SPAT_MAXEND_WITHOUT_MINEND": "5.7.4.2",
    "SPAT_LIKELYTIME_UNUSUAL": "5.7.4.3",
    "SPAT_LIKELYTIME_BEFORE_MINEND": "5.7.4.3",
    "SPAT_NEXTTIME_UNUSUAL": "5.7.4.3",
    "SPAT_NEXTTIME_BEFORE_MAXEND": "5.7.4.3",
    "SPAT_CONFIDENCE_MISSING": "5.7.4.4",
    "SPAT_CONFIDENCE_INVALID": "5.7.4.4",
    "SPAT_CONFIDENCE_UNAVAILABLE": "5.7.4.4",
    "SPAT_CONFIDENCE_LOW": "5.7.4.4",
    # Linking
    "SPATEM_MISSING_FOR_MAP": "6.1",
    "MAPEM_MISSING_FOR_SPAT": "6.1",
    "MAP_SPAT_REVISION_MISMATCH": "6.1",
    "MAP_SIGNALGROUP_NOT_IN_SPAT": "6.2",
    "SPAT_SIGNALGROUP_NOT_IN_MAP": "6.2",
}


class MapValidationDialog(QDialog):
    """Modal dialog showing C-Roads MAPEM/SPATEM validation findings."""

    def __init__(
        self,
        issues: Iterable[MapValidationIssue],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("C-Roads MAP/SPAT pruefen")
        self.setMinimumSize(720, 480)
        self._issues = list(issues)
        self._summary = validation_summary(self._issues)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Summary header
        summary_text = (
            f"Fehler: {self._summary['error']}   |   "
            f"Warnungen: {self._summary['warning']}   |   "
            f"Hinweise: {self._summary['info']}"
        )
        self._summary_label = QLabel(summary_text)
        self._summary_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(self._summary_label)

        if not self._issues:
            layout.addWidget(QLabel("Keine Auffaelligkeiten in MAPEM/SPATEM gefunden."))
        else:
            self._table = QTableWidget(0, 6)
            self._table.setHorizontalHeaderLabels(["Severity", "Code", "Rule", "Intersection", "Lane", "Beschreibung"])
            self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self._table.setAlternatingRowColors(True)
            self._table.verticalHeader().setVisible(False)
            self._populate_table()
            layout.addWidget(self._table)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        if self._issues:
            self._btn_export_json = QPushButton("Als JSON speichern...")
            self._btn_export_json.clicked.connect(self._export_json)
            button_row.addWidget(self._btn_export_json)

            self._btn_export_html = QPushButton("Als HTML speichern...")
            self._btn_export_html.clicked.connect(self._export_html)
            button_row.addWidget(self._btn_export_html)

        self._btn_close = QPushButton("Schliessen")
        self._btn_close.clicked.connect(self.close)
        button_row.addWidget(self._btn_close)

        layout.addLayout(button_row)

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._issues))
        for i, issue in enumerate(self._issues):
            rule_id = _rule_id(issue.code)
            self._table.setItem(i, 0, QTableWidgetItem(issue.severity.upper()))
            self._table.setItem(i, 1, QTableWidgetItem(issue.code))
            self._table.setItem(i, 2, QTableWidgetItem(rule_id or "-"))
            self._table.setItem(
                i, 3, QTableWidgetItem(str(issue.intersection_id) if issue.intersection_id is not None else "-")
            )
            self._table.setItem(i, 4, QTableWidgetItem(str(issue.lane_id) if issue.lane_id is not None else "-"))
            self._table.setItem(i, 5, QTableWidgetItem(issue.message))

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "JSON-Report speichern", "map-spat-report.json", "JSON (*.json)")
        if not path:
            return
        json_content = _build_json_report(self._issues, self._summary)
        Path(path).write_text(json_content, encoding="utf-8")
        self._summary_label.setText(self._summary_label.text() + f"   (JSON: {Path(path).name})")

    def _export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "HTML-Report speichern", "map-spat-report.html", "HTML (*.html)")
        if not path:
            return
        html_content = _build_html_report(self._issues, self._summary)
        Path(path).write_text(html_content, encoding="utf-8")
        self._summary_label.setText(self._summary_label.text() + f"   (HTML: {Path(path).name})")


def _build_html_report(
    issues: list[MapValidationIssue],
    summary: dict[str, int],
) -> str:
    rows = ""
    for issue in issues:
        severity_class = f"severity-{html.escape(issue.severity)}"
        rule_id = _rule_id(issue.code) or "-"
        rows += (
            f"<tr class='{severity_class}'>"
            f"<td>{html.escape(issue.severity.upper())}</td>"
            f"<td>{html.escape(issue.code)}</td>"
            f"<td><span class='rule-id'>{rule_id}</span></td>"
            f"<td>{issue.intersection_id if issue.intersection_id is not None else '-'}</td>"
            f"<td>{issue.lane_id if issue.lane_id is not None else '-'}</td>"
            f"<td>{html.escape(issue.message)}</td>"
            f"<td>{html.escape(issue.station_id)}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>C-Roads MAPEM/SPATEM Prüfbericht</title>
<style>
  body {{ font-family: Segoe UI, Roboto, sans-serif; margin: 24px; color: #0d1b2a; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  .summary {{ font-size: 14px; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #dde1e7; padding: 8px 10px; text-align: left; }}
  th {{ background: #f5f7fb; font-weight: 600; }}
  tr:nth-child(even) {{ background: #fafbfc; }}
  .severity-error {{ background: #fef2f2; color: #991b1b; }}
  .severity-warning {{ background: #fffbeb; color: #92400e; }}
  .severity-info {{ background: #eff6ff; color: #1e40af; }}
  .rule-id {{ font-size: 11px; color: #64748b; }}
  .handbook-ref {{ font-size: 11px; color: #64748b; margin-top: 16px; }}
</style>
</head>
<body>
<h1>C-Roads MAPEM/SPATEM Prüfbericht</h1>
<div class="summary">
  Fehler: <b>{summary["error"]}</b> &nbsp;|&nbsp;
  Warnungen: <b>{summary["warning"]}</b> &nbsp;|&nbsp;
  Hinweise: <b>{summary["info"]}</b>
</div>
<table>
  <thead>
    <tr><th>Severity</th><th>Code</th><th>Rule</th><th>Intersection</th><th>Lane</th><th>Beschreibung</th><th>Station</th></tr>
  </thead>
  <tbody>
{rows}  </tbody>
</table>
<p class="handbook-ref">Rule-IDs beziehen sich auf das C-Roads MAPEM/SPATEM Handbook v3.2.0</p>
</body>
</html>"""


def _rule_id(code: str) -> str | None:
    """Return the C-Roads Handbook v3.2.0 rule ID for a validation code."""
    return _RULE_ID_MAP.get(code)


def _build_json_report(
    issues: list[MapValidationIssue],
    summary: dict[str, int],
) -> str:
    """Build a machine-readable JSON report with rule IDs."""
    import json
    from datetime import UTC, datetime

    report = {
        "reportType": "C-Roads MAPEM/SPATEM Conformance Check",
        "handbookVersion": "3.2.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": summary,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "ruleId": _rule_id(issue.code),
                "message": issue.message,
                "stationId": issue.station_id,
                "intersectionId": issue.intersection_id,
                "laneId": issue.lane_id,
                "sourceSummary": issue.source_summary,
            }
            for issue in issues
        ],
    }
    return json.dumps(report, indent=2, ensure_ascii=False)
