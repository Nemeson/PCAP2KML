"""PCAP2KML Player — Entry point.

A PyQt6 desktop application for visualizing V2X messages from PCAP files
on an interactive map with synchronized playback and KML export.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

# Add the project root to Python path for imports
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.main_window import MainWindow


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


def main() -> int:
    """Application entry point."""
    setup_logging()
    logger = logging.getLogger("pcap2kml")
    logger.info("Starting PCAP2KML Player")

    app = QApplication(sys.argv)
    app.setApplicationName("PCAP2KML Player")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())