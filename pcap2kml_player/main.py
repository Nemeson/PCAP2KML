"""PCAP2KML Player — Entry point.

A PyQt6 desktop application for visualizing V2X messages from PCAP files
on an interactive map with synchronized playback and KML export.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

# Add the parent directory to Python path so pcap2kml_player is importable
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pcap2kml_player.qt_runtime import configure_qt_runtime_environment, prefer_software_rendering

configure_qt_runtime_environment()

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from pcap2kml_player.ui.main_window import MainWindow


def setup_logging() -> None:
    """Configure application-wide logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy libraries
    logging.getLogger("PyQt6").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def check_runtime_dependencies() -> list[str]:
    """Return a list of missing optional and required runtime dependencies."""
    missing: list[str] = []
    dependency_map = {
        "scapy": "PCAP-Parsing",
        "simplekml": "KML-Export",
    }

    for module_name, purpose in dependency_map.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(f"{module_name} ({purpose})")

    return missing


def install_global_exception_handler(app: QApplication) -> None:
    """Show unhandled exceptions in a user-visible dialog and log them."""

    def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger = logging.getLogger("pcap2kml")
        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(
            None,
            "Unerwarteter Fehler",
            "Die Anwendung hat einen unbehandelten Fehler erkannt.\n"
            "Details stehen im Log. Die aktuelle Aktion wurde abgebrochen.\n\n"
            f"{exc_value}",
            QMessageBox.StandardButton.Ok,
        )
        logger.debug("Unhandled exception details:\n%s", details)

    sys.excepthook = _handle_exception


def main() -> int:
    """Application entry point."""
    setup_logging()
    logger = logging.getLogger("pcap2kml")
    logger.info("Starting PCAP2KML Player")
    logger.info(
        "Qt runtime: software=%s | QT_OPENGL=%s | QT_OPENGL_DLL=%s | QSG_RHI_PREFER_SOFTWARE_RENDERER=%s | flags=%s",
        prefer_software_rendering(),
        os.environ.get("QT_OPENGL", ""),
        os.environ.get("QT_OPENGL_DLL", ""),
        os.environ.get("QSG_RHI_PREFER_SOFTWARE_RENDERER", ""),
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
    )

    if prefer_software_rendering():
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)

    app = QApplication(sys.argv)
    app.setApplicationName("PCAP2KML Player")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PCAP2KML")
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QMainWindow, QWidget {
            background: #f5f7fb;
            color: #10233f;
            font-size: 13px;
        }
        QToolBar {
            background: #ffffff;
            border: none;
            spacing: 8px;
            padding: 8px;
        }
        QPushButton {
            background: #ffffff;
            border: 1px solid #d7dde8;
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #fff2f3;
            border-color: #b2192b;
        }
        QPushButton:disabled {
            color: #92a0b5;
            background: #eef1f6;
        }
        QPushButton:pressed {
            background: #b2192b;
            color: #ffffff;
        }
        QTableWidget, QListWidget, QComboBox {
            background: #ffffff;
            border: 1px solid #d7dde8;
            border-radius: 10px;
            padding: 4px;
        }
        QHeaderView::section {
            background: #10233f;
            color: #ffffff;
            border: none;
            border-bottom: 1px solid #d7dde8;
            padding: 8px;
            font-weight: 700;
        }
        QStatusBar {
            background: #ffffff;
            border-top: 1px solid #d7dde8;
        }
        QSlider::groove:horizontal {
            height: 8px;
            background: #dce3ee;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            width: 16px;
            margin: -5px 0;
            border-radius: 8px;
            background: #b2192b;
        }
        """
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)
    install_global_exception_handler(app)

    missing_dependencies = check_runtime_dependencies()
    if missing_dependencies:
        QMessageBox.warning(
            None,
            "Fehlende Abhaengigkeiten",
            "Einige Funktionen sind eventuell nicht verfuegbar:\n\n"
            + "\n".join(f"- {entry}" for entry in missing_dependencies),
        )

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
