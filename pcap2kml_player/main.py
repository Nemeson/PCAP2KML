"""PCAP2KML Player — Entry point.

A PyQt6 desktop application for visualizing V2X messages from PCAP files
on an interactive map with synchronized playback and KML export.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Add the parent directory to Python path so pcap2kml_player is importable
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pcap2kml_player.qt_runtime import configure_qt_runtime_environment, prefer_software_rendering

configure_qt_runtime_environment()

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from pcap2kml_player.i18n import tr
from pcap2kml_player.theme_manager import ThemeManager
from pcap2kml_player.ui.main_window import MainWindow

try:
    __version__ = importlib.metadata.version("pcap2kml-player")
except importlib.metadata.PackageNotFoundError:
    __version__ = "1.7.0"


def setup_logging() -> None:
    """Configure application-wide logging with console and file output."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_format, datefmt="%H:%M:%S"))
    root_logger.addHandler(console)

    # File handler with rotation (persists across sessions for debugging)
    log_dir = Path(os.environ.get("PCAP2KML_LOG_DIR", Path.home() / ".pcap2kml" / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "pcap2kml.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(file_handler)

    # Suppress noisy libraries
    logging.getLogger("PyQt6").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def check_runtime_dependencies() -> list[str]:
    """Return a list of missing optional and required runtime dependencies."""
    missing: list[str] = []
    dependency_map = {
        "scapy": tr("PCAP Parsing"),
        "pyshark": tr("PCAP Parsing (pyshark)"),
        "simplekml": tr("KML Export"),
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
        # Avoid QMessageBox when headless (CI/tests) to prevent hangs/deadlocks.
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                tr("Unexpected Error"),
                tr(
                    "The application encountered an unhandled error.\n"
                    "Details are in the log. The current action was cancelled."
                )
                + f"\n\n{exc_value}",
                QMessageBox.StandardButton.Ok,
            )
        except Exception:
            logger.error("Failed to show QMessageBox: %s", exc_value)
        logger.debug("Unhandled exception details:\n%s", details)

    sys.excepthook = _handle_exception


def main() -> int:
    """Application entry point."""
    setup_logging()
    logger = logging.getLogger("pcap2kml")
    logger.info("Starting PCAP2KML Player")
    logger.info(
        "Qt runtime: software=%s | map_backend=webengine | QT_OPENGL=%s | QT_OPENGL_DLL=%s | QSG_RHI_PREFER_SOFTWARE_RENDERER=%s | flags=%s",
        prefer_software_rendering(),
        os.environ.get("QT_OPENGL", ""),
        os.environ.get("QT_OPENGL_DLL", ""),
        os.environ.get("QSG_RHI_PREFER_SOFTWARE_RENDERER", ""),
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
    )

    if prefer_software_rendering():
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("PCAP2KML Player")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PCAP2KML")
    app.setStyle("Fusion")
    theme = ThemeManager(app)
    theme.apply()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)
    install_global_exception_handler(app)

    missing_dependencies = check_runtime_dependencies()
    if missing_dependencies:
        QMessageBox.warning(
            None,
            tr("Missing Dependencies"),
            tr("Some features may be unavailable:") + "\n\n" + "\n".join(f"- {entry}" for entry in missing_dependencies),
        )

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
