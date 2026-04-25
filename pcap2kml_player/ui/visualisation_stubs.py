"""Visualisation and UI enhancements for Phase D.

Stubs / placeholders for features not yet implemented in full:
  - Heatmap/Cluster overlay (offline MapLibre)
  - Screenshot export
  - Dense timeline + loop mode + frame navigation
  - Coordinate + scale display

These will be integrated into the main window when the underlying
map backend supports the required primitives.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget


def show_heatmap_cluster_stub(parent: QWidget) -> None:
    """Placeholder: Heatmap and cluster overlay.

    Requires MapLibre GL JS integration with vector tile support.
    """
    QMessageBox.information(
        parent,
        "Heatmap / Cluster",
        (
            "Heatmap- und Cluster-Overlay sind geplant, benötigen aber "
            "die MapLibre-Integration mit Vector-Tiles.\n\n"
            "Warte auf Offline-Karten-Unterstützung (MBTiles / PMTiles)."
        ),
    )


def show_screenshot_stub(parent: QWidget) -> None:
    """Placeholder: Map screenshot export.

    Requires QWebEnginePage::captureToImage or map screenshot API.
    """
    QMessageBox.information(
        parent,
        "Screenshot",
        (
            "Screenshot-Export der Karte ist noch nicht implementiert.\n\n"
            "Verwende stattdessen: GeoJSON / CSV / GPX / KML Export "
            "für externe Visualisierung."
        ),
    )


def show_loop_mode_stub(parent: QWidget) -> None:
    """Placeholder: Loop mode and frame-by-frame navigation.

    Requires playback controller integration.
    """
    QMessageBox.information(
        parent,
        "Loop-Modus / Frame-Navigation",
        (
            "Loop-Modus und Frame-für-Frame-Navigation sind geplant.\n\n"
            "Lesezeichen in der Zeitleiste und Dichte-Timeline folgen "
            "nach der MapLibre-Integration."
        ),
    )
