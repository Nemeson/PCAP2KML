"""ETA analysis graph for PCAP2KML Player."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..color_modes import MAP_COLOR_MODE_COLORBLIND, MAP_COLOR_MODE_NORMAL, normalize_color_mode
from ..data_model import MessageType, V2xMessage
from ..scene_model import build_scene_snapshot


@dataclass(frozen=True)
class EtaSelection:
    """One selectable ETA analysis track."""

    key: str
    label: str
    station_id: str
    intersection_id: int | None = None
    request_id: int | None = None
    sequence_number: int | None = None
    merge_group_id: str | None = None


@dataclass(frozen=True)
class EtaPoint:
    """One received ETA sample from an SREM/SRM message."""

    timestamp: datetime
    relative_seconds: float
    remaining_seconds: float
    error_seconds: float | None
    label: str


@dataclass(frozen=True)
class SpeedPoint:
    """One smoothed speed sample for the selected vehicle."""

    timestamp: datetime
    relative_seconds: float
    speed_mps: float


@dataclass(frozen=True)
class RequestEvent:
    """One SREM event marker in the ETA graph."""

    timestamp: datetime
    relative_seconds: float
    kind: str
    label: str
    color: QColor


@dataclass(frozen=True)
class StatusBand:
    """A colored SSEM status interval."""

    start: datetime
    end: datetime
    start_relative_seconds: float
    end_relative_seconds: float
    status: str
    label: str
    color: QColor


@dataclass(frozen=True)
class DiagnosticItem:
    """One automatically detected ETA/request anomaly."""

    timestamp: datetime
    relative_seconds: float
    label: str
    color: QColor


@dataclass(frozen=True)
class EtaDashboardData:
    """Operator-facing table data for the selected ETA track."""

    metrics: list[tuple[str, str]]
    events: list[EtaDashboardEvent]


@dataclass(frozen=True)
class EtaDashboardEvent:
    """One interactive row in the ETA dashboard event table."""

    time_text: str
    kind: str
    content: str
    details: str
    timestamp: datetime
    message_type: MessageType | None
    selection_key: str | None


class EtaGraphWidget(QWidget):
    """Paint a request-centric ETA, speed, SREM/SSEM, and diagnosis timeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[V2xMessage] = []
        self._selection_key: str | None = None
        self._selection: EtaSelection | None = None
        self._current_time: datetime | None = None
        self._start_time: datetime | None = None
        self._eta_points: list[EtaPoint] = []
        self._speed_points: list[SpeedPoint] = []
        self._events: list[RequestEvent] = []
        self._status_bands: list[StatusBand] = []
        self._diagnostics: list[DiagnosticItem] = []
        self._color_mode = MAP_COLOR_MODE_NORMAL
        self.setMinimumHeight(360)
        self.setStyleSheet("background: #ffffff; border: 1px solid #d7dde8; border-radius: 12px;")

    def set_color_mode(self, color_mode: str) -> None:
        """Set the graph palette used for color-vision accessibility."""
        normalized = normalize_color_mode(color_mode)
        if normalized == self._color_mode:
            return
        self._color_mode = normalized
        self._rebuild_series()

    def set_messages(self, messages: list[V2xMessage]) -> None:
        """Set the full message stream used for graph extraction."""
        self._messages = messages
        self._rebuild_series()

    def set_selection(self, selection_key: str | None) -> None:
        """Select the request/merge track to render."""
        self._selection_key = selection_key
        self._rebuild_series()

    def set_station(self, station_id: str | None) -> None:
        """Backward-compatible station fallback used by older callers/tests."""
        self.set_selection(f"STATION:{station_id}" if station_id else None)

    def set_current_time(self, timestamp: datetime | None) -> None:
        """Move the playback cursor."""
        self._current_time = timestamp
        self.update()

    def summary_text(self) -> str:
        """Return a short operator-facing summary for the selected request."""
        if self._selection is None:
            return "Keine ETA-Auswahl vorhanden."
        verification_count = sum(1 for point in self._eta_points if point.error_seconds is not None)
        worst_error = max(
            [abs(point.error_seconds) for point in self._eta_points if point.error_seconds is not None],
            default=None,
        )
        error_text = "keine verifizierte Ankunft"
        if worst_error is not None:
            error_text = f"max. ETA-Abweichung {worst_error:.1f}s"
        return (
            f"{self._selection.label}: {len(self._eta_points)} ETA-Sample(s), "
            f"{verification_count} verifiziert, {len(self._status_bands)} SSEM-Statusband/-baender, "
            f"{len(self._diagnostics)} Diagnosehinweis(e), {error_text}."
        )

    def dashboard_data(self) -> EtaDashboardData:
        """Return metrics and event rows for the selected request/vehicle track."""
        if self._selection is None:
            return EtaDashboardData(
                metrics=[("Status", "Keine ETA-Auswahl vorhanden")],
                events=[],
            )

        eta_errors = [abs(point.error_seconds) for point in self._eta_points if point.error_seconds is not None]
        speed_values = [point.speed_mps for point in self._speed_points]
        status_values = [band.status for band in self._status_bands]
        metrics = [
            ("Auswahl", self._selection.label),
            ("Station", self._selection.station_id),
            ("SREM-Samples", str(len(self._events))),
            ("SSEM-Updates", str(len(self._status_bands))),
            ("ETA-Samples", str(len(self._eta_points))),
            ("verifizierte ETA", str(len(eta_errors))),
            ("max. ETA-Abweichung", f"{max(eta_errors):.1f}s" if eta_errors else "-"),
            ("mittlere Geschwindigkeit", f"{sum(speed_values) / len(speed_values):.1f} m/s" if speed_values else "-"),
            ("letzter SSEM-Status", status_values[-1] if status_values else "-"),
            ("Diagnosehinweise", str(len(self._diagnostics))),
        ]

        rows: list[EtaDashboardEvent] = []
        for event in self._events:
            rows.append(
                EtaDashboardEvent(
                    time_text=_format_time(event.timestamp),
                    kind=event.kind,
                    content=event.label,
                    details="",
                    timestamp=event.timestamp,
                    message_type=MessageType.SREM,
                    selection_key=self._selection.key,
                )
            )
        for band in self._status_bands:
            rows.append(
                EtaDashboardEvent(
                    time_text=_format_time(band.start),
                    kind="SSEM",
                    content=band.status,
                    details=band.label,
                    timestamp=band.start,
                    message_type=MessageType.SSEM,
                    selection_key=self._selection.key,
                )
            )
        for diagnostic in self._diagnostics:
            rows.append(
                EtaDashboardEvent(
                    time_text=_format_time(diagnostic.timestamp),
                    kind="Diagnose",
                    content=diagnostic.label,
                    details="",
                    timestamp=diagnostic.timestamp,
                    message_type=None,
                    selection_key=self._selection.key,
                )
            )
        rows.sort(key=lambda row: row.timestamp)
        return EtaDashboardData(metrics=metrics, events=rows)

    def _rebuild_series(self) -> None:
        self._selection = _selection_for_key(self._selection_key, self._messages)
        self._start_time = None
        self._eta_points = []
        self._speed_points = []
        self._events = []
        self._status_bands = []
        self._diagnostics = []

        if not self._messages or self._selection is None:
            self.update()
            return

        srem_messages = [msg for msg in self._messages if _matches_selection(msg, self._selection)]
        if not srem_messages:
            self.update()
            return

        self._start_time = min(msg.timestamp for msg in srem_messages)
        end_time = self._messages[-1].timestamp
        scene = build_scene_snapshot(self._messages, end_time)
        verifications = {
            (item.intersection_id, item.request_id, item.sequence_number, item.station_id): item
            for item in scene.eta_verifications
        }

        for msg in srem_messages:
            request_id = _coerce_int(msg.decoded_data.get("requestId"))
            sequence_number = _coerce_int(msg.decoded_data.get("sequenceNumber"))
            intersection_id = _coerce_int(msg.decoded_data.get("intersectionId"))
            verification = verifications.get((intersection_id, request_id, sequence_number, msg.station_id))
            eta = _coerce_eta_datetime(msg.decoded_data.get("eta"), msg.timestamp)
            if eta is None and verification is not None:
                eta = verification.predicted_eta
            remaining_seconds = max(0.0, (eta - msg.timestamp).total_seconds()) if eta else 0.0
            # Validate: reject physically implausible ETA values (> 30 min or negative)
            if eta is not None and remaining_seconds > 1800.0:
                eta = None
                remaining_seconds = 0.0
            error_seconds = verification.delta_seconds if verification is not None else None
            relative_seconds = _relative_seconds(msg.timestamp, self._start_time)
            label = _request_label("SREM", request_id, sequence_number)
            self._events.append(
                RequestEvent(
                    timestamp=msg.timestamp,
                    relative_seconds=relative_seconds,
                    kind="SREM",
                    label=f"{label} | ETA {remaining_seconds:.1f}s" if eta else label,
                    color=_graph_color("eta", self._color_mode),
                )
            )
            if eta is not None:
                self._eta_points.append(
                    EtaPoint(
                        timestamp=msg.timestamp,
                        relative_seconds=relative_seconds,
                        remaining_seconds=remaining_seconds,
                        error_seconds=error_seconds,
                        label=label,
                    )
                )

        # Build speed curve from CAM messages that overlap with the request window
        # Include messages before start_time to warm up the moving average
        speed_messages = [
            msg
            for msg in self._messages
            if msg.station_id == self._selection.station_id
            and msg.speed is not None
            and msg.timestamp >= self._start_time - timedelta(seconds=5)
        ]
        self._speed_points = _smooth_speed_points(speed_messages, self._start_time)
        # Filter speed points to only those within the actual request window
        self._speed_points = [
            point for point in self._speed_points
            if point.timestamp >= self._start_time
        ]

        ssem_events = [msg for msg in self._messages if _matches_ssem(msg, self._selection)]
        self._status_bands = _build_status_bands(ssem_events, self._start_time, end_time, self._color_mode)
        self._diagnostics = _detect_diagnostics(
            eta_points=self._eta_points,
            srem_messages=srem_messages,
            ssem_events=ssem_events,
            status_bands=self._status_bands,
            scene=scene,
            selection=self._selection,
            start_time=self._start_time,
            color_mode=self._color_mode,
        )

        self._eta_points.sort(key=lambda point: point.timestamp)
        self._speed_points.sort(key=lambda point: point.timestamp)
        self._events.sort(key=lambda event: event.timestamp)
        self._status_bands.sort(key=lambda band: band.start)
        self._diagnostics.sort(key=lambda item: item.timestamp)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#ffffff"))

        if not self._messages:
            self._draw_empty_state(painter, "Keine PCAP-Sitzung geladen.")
            return
        if self._selection is None:
            self._draw_empty_state(painter, "Bitte eine Request-/Merge-Spur fuer die ETA-Analyse auswaehlen.")
            return
        if self._start_time is None:
            self._draw_empty_state(painter, "Fuer diese Auswahl wurden keine SREM-ETA-Daten gefunden.")
            return

        end_time = max([self._messages[-1].timestamp] + [band.end for band in self._status_bands])
        duration = max(1.0, (end_time - self._start_time).total_seconds())
        plot = QRectF(64, 42, max(160, self.width() - 142), max(140, self.height() - 132))
        status_rect = QRectF(plot.left(), plot.bottom() + 8, plot.width(), 28.0)
        diagnosis_y = status_rect.bottom() + 20
        eta_max = max([point.remaining_seconds for point in self._eta_points] + [1.0])
        speed_max = max([point.speed_mps for point in self._speed_points] + [1.0])

        self._draw_grid(painter, plot, duration, eta_max, speed_max)
        self._draw_status_bands(painter, status_rect, duration)
        self._draw_srem_events(painter, plot, status_rect, duration)
        self._draw_eta_series(painter, plot, duration, eta_max)
        self._draw_speed_series(painter, plot, duration, speed_max)
        self._draw_diagnostics(painter, plot, diagnosis_y, duration)
        self._draw_current_cursor(painter, plot, status_rect, duration)
        self._draw_legend(painter, plot)

    def _draw_empty_state(self, painter: QPainter, text: str) -> None:
        painter.setPen(QPen(QColor("#667891")))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_grid(self, painter: QPainter, plot: QRectF, duration: float, eta_max: float, speed_max: float) -> None:
        painter.setPen(QPen(QColor("#d7dde8"), 1))
        painter.drawRect(plot)
        painter.setFont(QFont("Segoe UI", 8))
        for index in range(1, 5):
            y = plot.top() + (plot.height() * index / 5)
            painter.setPen(QPen(QColor("#edf2f7"), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(QPen(QColor("#7b8ca4")))
        for index in range(6):
            x = plot.left() + (plot.width() * index / 5)
            y = plot.bottom() + 16
            painter.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 4))
            painter.drawText(QPointF(x - 14, y), f"+{duration * index / 5:.0f}s")
        painter.drawText(QPointF(plot.left() - 58, plot.top() + 10), f"{eta_max:.0f}s Rest")
        painter.drawText(QPointF(plot.right() + 8, plot.top() + 10), f"{speed_max:.1f} m/s")
        painter.drawText(QPointF(plot.left() - 44, plot.bottom()), "0")
        painter.drawText(QPointF(plot.right() + 8, plot.bottom()), "0")

    def _draw_status_bands(self, painter: QPainter, status_rect: QRectF, duration: float) -> None:
        painter.setPen(QPen(QColor("#d7dde8"), 1))
        painter.drawRect(status_rect)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(QPointF(status_rect.left() - 58, status_rect.center().y() + 4), "SSEM")
        for band in self._status_bands:
            start_x = _x_for_relative(band.start_relative_seconds, duration, status_rect)
            end_x = _x_for_relative(band.end_relative_seconds, duration, status_rect)
            width = max(3.0, end_x - start_x)
            band_rect = QRectF(start_x, status_rect.top() + 3, width, status_rect.height() - 6)
            painter.fillRect(band_rect, band.color.lighter(165))
            painter.setPen(QPen(band.color, 1.5))
            painter.drawRect(band_rect)
            painter.setPen(QPen(QColor("#233044")))
            painter.drawText(QPointF(start_x + 4, status_rect.center().y() + 4), band.status[:18])

    def _draw_srem_events(self, painter: QPainter, plot: QRectF, status_rect: QRectF, duration: float) -> None:
        for request_event in self._events:
            x = _x_for_relative(request_event.relative_seconds, duration, plot)
            painter.setPen(QPen(request_event.color, 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, status_rect.bottom()))
            painter.setPen(QPen(request_event.color, 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            painter.drawText(QPointF(x + 4, plot.top() + 14), request_event.kind)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QPointF(x + 4, plot.bottom() - 8), request_event.label[:32])

    def _draw_eta_series(self, painter: QPainter, plot: QRectF, duration: float, eta_max: float) -> None:
        if not self._eta_points:
            return
        # Draw filled area under the ETA curve
        eta_color = _graph_color("eta", self._color_mode)
        fill_color = _graph_color("eta", self._color_mode)
        fill_color.setAlpha(30)
        points = [
            QPointF(
                _x_for_relative(point.relative_seconds, duration, plot),
                _y_for_value(point.remaining_seconds, eta_max, plot),
            )
            for point in self._eta_points
        ]
        # Build closed path for fill
        if len(points) >= 2:
            path = QPainterPath()
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            path.lineTo(QPointF(points[-1].x(), plot.bottom()))
            path.lineTo(QPointF(points[0].x(), plot.bottom()))
            path.closeSubpath()
            painter.fillPath(path, fill_color)
        # Draw polyline
        self._draw_polyline_or_points(painter, points, eta_color, 2.8)
        # Draw error indicators with severity-based colors
        painter.setFont(QFont("Segoe UI", 8))
        for eta_point, draw_point in zip(self._eta_points, points):
            if eta_point.error_seconds is None:
                continue
            abs_error = abs(eta_point.error_seconds)
            if abs_error <= 1.0:
                color = _quality_color("excellent", self._color_mode)
            elif abs_error <= 2.0:
                color = _quality_color("good", self._color_mode)
            elif abs_error <= 5.0:
                color = _quality_color("fair", self._color_mode)
            else:
                color = _quality_color("poor", self._color_mode)
            # Draw error bar circle
            painter.setPen(QPen(color, 1))
            painter.setBrush(color)
            painter.drawEllipse(draw_point, 4.0, 4.0)
            painter.setPen(QPen(color))
            painter.drawText(QPointF(draw_point.x() + 6, draw_point.y() - 6), f"{eta_point.error_seconds:+.1f}s")

    def _draw_speed_series(self, painter: QPainter, plot: QRectF, duration: float, speed_max: float) -> None:
        if not self._speed_points:
            return
        speed_color = _graph_color("speed", self._color_mode)
        fill_color = _graph_color("speed", self._color_mode)
        fill_color.setAlpha(20)
        points = [
            QPointF(
                _x_for_relative(point.relative_seconds, duration, plot), _y_for_value(point.speed_mps, speed_max, plot)
            )
            for point in self._speed_points
        ]
        # Build closed path for fill
        if len(points) >= 2:
            path = QPainterPath()
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            path.lineTo(QPointF(points[-1].x(), plot.bottom()))
            path.lineTo(QPointF(points[0].x(), plot.bottom()))
            path.closeSubpath()
            painter.fillPath(path, fill_color)
        self._draw_polyline_or_points(painter, points, speed_color, 2.0)

    def _draw_diagnostics(self, painter: QPainter, plot: QRectF, diagnosis_y: float, duration: float) -> None:
        if not self._diagnostics:
            return
        # Group diagnostics by type for better visual scanning
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.setPen(QPen(_graph_color("diagnostic", self._color_mode)))
        painter.drawText(QPointF(plot.left() - 58, diagnosis_y + 4), "Checks")
        for index, item in enumerate(self._diagnostics[:12]):
            x = _x_for_relative(item.relative_seconds, duration, plot)
            # Severity-based color: use item color but derive severity from label keywords
            severity_color = _diagnostic_severity_color(item.label, self._color_mode)
            # Draw semi-transparent vertical span line
            span_pen = QPen(severity_color)
            span_pen.setWidth(1)
            span_color = QColor(severity_color)
            span_color.setAlpha(40)
            painter.setPen(span_pen)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            # Stagger labels vertically to reduce overlap
            label_y = diagnosis_y + ((index % 3) * 14)
            painter.setBrush(severity_color)
            painter.drawEllipse(QPointF(x, label_y), 4.0, 4.0)
            painter.setPen(QPen(severity_color))
            painter.drawText(QPointF(x + 6, label_y + 4), item.label[:28])

    def _draw_polyline_or_points(self, painter: QPainter, points: list[QPointF], color: QColor, width: float) -> None:
        if not points:
            return
        painter.setPen(QPen(color, width))
        for index in range(1, len(points)):
            painter.drawLine(points[index - 1], points[index])
        painter.setBrush(color)
        for point in points:
            painter.drawEllipse(point, 3.2, 3.2)

    def _draw_current_cursor(self, painter: QPainter, plot: QRectF, status_rect: QRectF, duration: float) -> None:
        if self._current_time is None or self._start_time is None:
            return
        x = _x_for_relative(_relative_seconds(self._current_time, self._start_time), duration, plot)
        painter.setPen(QPen(QColor("#10233f"), 2))
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, status_rect.bottom()))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(QPointF(x + 5, plot.bottom() - 6), "Jetzt")

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        entries = [
            ("Restzeit bis Stopline", _graph_color("eta", self._color_mode)),
            ("Speed geglaettet", _graph_color("speed", self._color_mode)),
            ("SREM Event", _graph_color("eta", self._color_mode)),
            ("SSEM Statusband", _graph_color("status", self._color_mode)),
            ("Diagnose", _graph_color("diagnostic", self._color_mode)),
        ]
        x = plot.left()
        y = 22
        painter.setFont(QFont("Segoe UI", 8))
        for label, color in entries:
            painter.setPen(QPen(color, 3))
            painter.drawLine(QPointF(x, y - 4), QPointF(x + 18, y - 4))
            painter.setPen(QPen(QColor("#42546b")))
            painter.drawText(QPointF(x + 24, y), label)
            x += 142


def build_eta_selection_options(messages: list[V2xMessage]) -> list[EtaSelection]:
    """Build request/merge-first selection options for the ETA analysis combo."""
    selections: dict[str, EtaSelection] = {}
    for msg in messages:
        if msg.msg_type != MessageType.SREM:
            continue
        request_id = _coerce_int(msg.decoded_data.get("requestId"))
        sequence_number = _coerce_int(msg.decoded_data.get("sequenceNumber"))
        intersection_id = _coerce_int(msg.decoded_data.get("intersectionId"))
        if request_id is None or sequence_number is None or intersection_id is None:
            continue
        key = _request_selection_key(intersection_id, request_id, sequence_number, msg.station_id, msg.merge_group_id)
        merge_text = f" | Merge {msg.merge_group_id}" if msg.merge_group_id else ""
        label = f"I{intersection_id} R{request_id}/S{sequence_number} | {msg.station_id}{merge_text}"
        selections.setdefault(
            key,
            EtaSelection(key, label, msg.station_id, intersection_id, request_id, sequence_number, msg.merge_group_id),
        )
    if selections:
        return sorted(
            selections.values(),
            key=lambda item: (
                item.intersection_id or 0,
                item.request_id or 0,
                item.sequence_number or 0,
                item.station_id,
            ),
        )
    station_ids = sorted(
        {
            msg.station_id
            for msg in messages
            if msg.msg_type in {MessageType.CAM, MessageType.NMEA} or msg.speed is not None
        }
    )
    return [
        EtaSelection(key=f"STATION:{station_id}", label=f"Station {station_id}", station_id=station_id)
        for station_id in station_ids
    ]


def _selection_for_key(selection_key: str | None, messages: list[V2xMessage]) -> EtaSelection | None:
    if selection_key is None:
        options = build_eta_selection_options(messages)
        return options[0] if options else None
    for option in build_eta_selection_options(messages):
        if option.key == selection_key:
            return option
    if selection_key.startswith("STATION:"):
        station_id = selection_key.split(":", 1)[1]
        return EtaSelection(key=selection_key, label=f"Station {station_id}", station_id=station_id)
    return None


def _matches_selection(msg: V2xMessage, selection: EtaSelection) -> bool:
    if msg.msg_type != MessageType.SREM:
        return False
    if selection.intersection_id is None:
        return msg.station_id == selection.station_id
    return (
        msg.station_id == selection.station_id
        and _coerce_int(msg.decoded_data.get("intersectionId")) == selection.intersection_id
        and _coerce_int(msg.decoded_data.get("requestId")) == selection.request_id
        and _coerce_int(msg.decoded_data.get("sequenceNumber")) == selection.sequence_number
        and (selection.merge_group_id is None or msg.merge_group_id == selection.merge_group_id)
    )


def _matches_ssem(msg: V2xMessage, selection: EtaSelection) -> bool:
    if msg.msg_type != MessageType.SSEM or selection.intersection_id is None:
        return False
    return (
        _coerce_int(msg.decoded_data.get("intersectionId")) == selection.intersection_id
        and _coerce_int(msg.decoded_data.get("requestId")) == selection.request_id
        and _coerce_int(msg.decoded_data.get("sequenceNumber")) == selection.sequence_number
    )


def _request_selection_key(
    intersection_id: int, request_id: int, sequence_number: int, station_id: str, merge_group_id: str | None
) -> str:
    merge_token = merge_group_id or "raw"
    return f"REQ:{intersection_id}:{request_id}:{sequence_number}:{station_id}:{merge_token}"


def _smooth_speed_points(messages: list[V2xMessage], start_time: datetime, window: int = 3) -> list[SpeedPoint]:
    """Return a small moving-average speed curve to reduce PCAP jitter."""
    result: list[SpeedPoint] = []
    speeds: list[float] = []
    for msg in sorted(messages, key=lambda item: item.timestamp):
        if msg.speed is None:
            continue
        speeds.append(float(msg.speed))
        sample = speeds[-window:]
        result.append(
            SpeedPoint(msg.timestamp, _relative_seconds(msg.timestamp, start_time), sum(sample) / len(sample))
        )
    return result


def _build_status_bands(
    messages: list[V2xMessage],
    start_time: datetime,
    end_time: datetime,
    color_mode: str = MAP_COLOR_MODE_NORMAL,
) -> list[StatusBand]:
    bands: list[StatusBand] = []
    ordered = sorted(messages, key=lambda item: item.timestamp)
    for index, msg in enumerate(ordered):
        status = str(msg.decoded_data.get("requestState") or "acknowledged")
        next_time = ordered[index + 1].timestamp if index + 1 < len(ordered) else end_time
        if next_time <= msg.timestamp:
            next_time = msg.timestamp + timedelta(milliseconds=250)
        bands.append(
            StatusBand(
                msg.timestamp,
                next_time,
                _relative_seconds(msg.timestamp, start_time),
                _relative_seconds(next_time, start_time),
                status,
                f"SSEM {status}",
                _status_color(status, color_mode),
            )
        )
    return bands


def _detect_diagnostics(
    *,
    eta_points: list[EtaPoint],
    srem_messages: list[V2xMessage],
    ssem_events: list[V2xMessage],
    status_bands: list[StatusBand],
    scene,
    selection: EtaSelection,
    start_time: datetime,
    color_mode: str = MAP_COLOR_MODE_NORMAL,
) -> list[DiagnosticItem]:
    diagnostics: list[DiagnosticItem] = []
    ordered_eta = sorted(eta_points, key=lambda point: point.timestamp)
    for previous, current in zip(ordered_eta, ordered_eta[1:]):
        jump = current.remaining_seconds - previous.remaining_seconds
        if abs(jump) > 5.0:
            diagnostics.append(_diagnostic(current.timestamp, start_time, f"ETA-Sprung {jump:+.1f}s", color_mode))
        if current.remaining_seconds > previous.remaining_seconds + 1.0:
            diagnostics.append(_diagnostic(current.timestamp, start_time, "ETA steigt trotz Annaherung", color_mode))
    if srem_messages and not ssem_events:
        diagnostics.append(_diagnostic(srem_messages[-1].timestamp, start_time, "SREM ohne SSEM-Antwort", color_mode))
    granted_bands = [band for band in status_bands if _is_granted_status(band.status)]
    if srem_messages and not granted_bands:
        diagnostics.append(_diagnostic(srem_messages[-1].timestamp, start_time, "kein granted fuer Request", color_mode))
    elif srem_messages and granted_bands:
        delay = (granted_bands[0].start - srem_messages[0].timestamp).total_seconds()
        if delay > 1.0:
            diagnostics.append(_diagnostic(granted_bands[0].start, start_time, f"granted spaet ({delay:.1f}s)", color_mode))
    for verification in scene.eta_verifications:
        if not _verification_matches(verification, selection):
            continue
        if not verification.is_accurate:
            diagnostics.append(
                _diagnostic(
                    verification.actual_arrival,
                    start_time,
                    f"ETA-Fehler {verification.delta_seconds:+.1f}s",
                    color_mode,
                )
            )
        if not any(
            band.start <= verification.actual_arrival and _is_granted_status(band.status) for band in granted_bands
        ):
            diagnostics.append(_diagnostic(verification.actual_arrival, start_time, "Stopline ohne granted passiert", color_mode))
    if not eta_points and srem_messages:
        diagnostics.append(_diagnostic(srem_messages[0].timestamp, start_time, "SREM ohne verwertbare ETA", color_mode))
    return diagnostics


def _diagnostic_severity_color(label: str, color_mode: str = MAP_COLOR_MODE_NORMAL) -> QColor:
    """Map diagnostic label keywords to a severity QColor.

    Returns one of four severity colors:
    - excellent  (#16a34a)  – nominal / granted / good
    - good       (#84cc16)  – acceptable / ack / minor
    - fair       (#f59e0b)  – warning / late / delay / degraded
    - poor       (#dc2626)  – error / reject / timeout / critical / fail
    """
    token = label.lower()
    if any(keyword in token for keyword in ("ok", "good", "granted", "nominal", "valid")):
        return _quality_color("excellent", color_mode)
    if any(keyword in token for keyword in ("acceptable", "ack", "tolerant", "minor", "soft")):
        return _quality_color("good", color_mode)
    if any(keyword in token for keyword in ("warning", "late", "slow", "delay", "degraded", "caution")):
        return _quality_color("fair", color_mode)
    if any(keyword in token for keyword in ("error", "critical", "reject", "deny", "timeout", "expired", "missed", "fail", "fatal")):
        return _quality_color("poor", color_mode)
    return _quality_color("poor", color_mode)


def _diagnostic(
    timestamp: datetime,
    start_time: datetime,
    label: str,
    color_mode: str = MAP_COLOR_MODE_NORMAL,
) -> DiagnosticItem:
    return DiagnosticItem(timestamp, _relative_seconds(timestamp, start_time), label, _graph_color("diagnostic", color_mode))


def _verification_matches(verification, selection: EtaSelection) -> bool:
    if selection.intersection_id is None:
        return verification.station_id == selection.station_id
    return (
        verification.station_id == selection.station_id
        and verification.intersection_id == selection.intersection_id
        and verification.request_id == selection.request_id
        and verification.sequence_number == selection.sequence_number
    )


def _x_for_relative(relative_seconds: float, duration: float, plot: QRectF) -> float:
    offset = max(0.0, min(duration, relative_seconds))
    return plot.left() + (plot.width() * offset / duration)


def _y_for_value(value: float, maximum: float, plot: QRectF) -> float:
    normalized = max(0.0, min(1.0, value / max(1.0, maximum)))
    return plot.bottom() - (plot.height() * normalized)


def _relative_seconds(timestamp: datetime, start_time: datetime) -> float:
    return max(0.0, (timestamp - start_time).total_seconds())


def _format_time(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M:%S.%f")[:-3]


def _request_label(kind: str, request_id: int | None, sequence_number: int | None) -> str:
    if request_id is None or sequence_number is None:
        return kind
    return f"{kind} {request_id}/{sequence_number}"


def _coerce_int(value: object) -> int | None:
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
        return _coerce_int(value[1])
    if isinstance(value, dict):
        for key in ("id", "value", "requestId", "requestID", "sequenceNumber", "lane"):
            coerced = _coerce_int(value.get(key))
            if coerced is not None:
                return coerced
    return None


def _coerce_eta_datetime(value: object, reference_time: datetime) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, dict):
        return None
    second_of_minute = _first_number(value.get("second"), value.get("timeStamp"), value.get("millisecond"))
    if second_of_minute is None:
        return None
    if second_of_minute > 60:
        second_of_minute /= 1000.0
    base = reference_time.astimezone(UTC).replace(second=0, microsecond=0)
    candidate = base + timedelta(seconds=second_of_minute)
    if candidate < reference_time - timedelta(seconds=30):
        candidate += timedelta(minutes=1)
    return candidate


def _first_number(*values: object) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _graph_color(role: str, color_mode: str = MAP_COLOR_MODE_NORMAL) -> QColor:
    if normalize_color_mode(color_mode) == MAP_COLOR_MODE_COLORBLIND:
        colors = {
            "eta": "#0072b2",
            "speed": "#e69f00",
            "status": "#56b4e9",
            "diagnostic": "#d55e00",
        }
    else:
        colors = {
            "eta": "#2563eb",
            "speed": "#16a34a",
            "status": "#f59e0b",
            "diagnostic": "#dc2626",
        }
    return QColor(colors.get(role, "#42546b"))


def _quality_color(level: str, color_mode: str = MAP_COLOR_MODE_NORMAL) -> QColor:
    if normalize_color_mode(color_mode) == MAP_COLOR_MODE_COLORBLIND:
        colors = {
            "excellent": "#0072b2",
            "good": "#56b4e9",
            "fair": "#e69f00",
            "poor": "#d55e00",
        }
    else:
        colors = {
            "excellent": "#16a34a",
            "good": "#84cc16",
            "fair": "#f59e0b",
            "poor": "#dc2626",
        }
    return QColor(colors.get(level, colors["poor"]))


def _status_color(status: str, color_mode: str = MAP_COLOR_MODE_NORMAL) -> QColor:
    token = status.lower()
    if _is_granted_status(status):
        return _quality_color("excellent", color_mode)
    if any(keyword in token for keyword in ("reject", "deny", "cancel", "terminated")):
        return _quality_color("poor", color_mode)
    if any(keyword in token for keyword in ("ack", "process", "receive", "watch", "accept")):
        return _quality_color("good", color_mode)
    return _quality_color("fair", color_mode)


def _is_granted_status(status: str) -> bool:
    token = status.lower()
    return any(keyword in token for keyword in ("grant", "green", "allow", "served"))
