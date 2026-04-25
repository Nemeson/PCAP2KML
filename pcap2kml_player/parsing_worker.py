"""Background worker for parsing PCAP files without blocking the UI."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from .data_model import SessionData
from .pcap_parser import ParseCancelled, parse_pcap


class ParsingWorker(QObject):
    """Parse one or more PCAP files in a background thread."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object, list, list)
    cancelled = pyqtSignal()

    def __init__(self, paths: list[str]):
        super().__init__()
        self._paths = paths
        self._cancel_check_fn = lambda: False

    @pyqtSlot()
    def run(self) -> None:
        """Run the parsing pipeline."""
        session = SessionData()
        errors: list[str] = []
        total = max(len(self._paths), 1)

        try:
            for index, path in enumerate(self._paths):
                filename = Path(path).name

                def _progress(fraction: float, *, current=index, name=filename) -> None:
                    overall = int(
                        ((current + max(0.0, min(1.0, fraction))) / total) * 100
                    )
                    self.progress.emit(overall, name)

                try:
                    parse_pcap(
                        path,
                        session,
                        progress_callback=_progress,
                        cancel_check=self._cancel_check_fn,
                    )
                    self.progress.emit(int(((index + 1) / total) * 100), filename)
                except (FileNotFoundError, ValueError) as exc:
                    errors.append(f"{filename}: {exc}")
        except ParseCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            errors.append(str(exc))

        session.finalize()
        self.finished.emit(session, self._paths, errors)

    @pyqtSlot()
    def cancel(self) -> None:
        """Request cancellation atomically via closure replacement."""
        self._cancel_check_fn = lambda: True

        try:
            for index, path in enumerate(self._paths):
                filename = Path(path).name

                def _progress(fraction: float, *, current=index, name=filename) -> None:
                    overall = int(
                        ((current + max(0.0, min(1.0, fraction))) / total) * 100
                    )
                    self.progress.emit(overall, name)

                try:
                    parse_pcap(
                        path,
                        session,
                        progress_callback=_progress,
                        cancel_check=_cancel_check,
                    )
                    self.progress.emit(int(((index + 1) / total) * 100), filename)
                except (FileNotFoundError, ValueError) as exc:
                    errors.append(f"{filename}: {exc}")
        except ParseCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            errors.append(str(exc))

        session.finalize()
        if not _cancel_check():
            self.finished.emit(session, self._paths, errors)

    @pyqtSlot()
    def cancel(self) -> None:
        """Request cancellation."""
        self._cancel_mutex.lock()
        try:
            self._cancel_requested = True
        finally:
            self._cancel_mutex.unlock()
