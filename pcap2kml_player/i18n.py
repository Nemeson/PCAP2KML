"""Lightweight internationalization for PCAP2KML Player.

Provides a central translation register with German (default) and English
support. Uses a simple dict-based lookup — no gettext compilation step
required.
"""

from __future__ import annotations

# ── Translation register ──────────────────────────────────────────────
# Keys are the canonical English message IDs; values are German translations.
_translations: dict[str, str] = {
    # ── General ──
    "PCAP2KML Player": "PCAP2KML Player",
    "Starting PCAP2KML Player": "Starte PCAP2KML Player",
    "Unexpected Error": "Unerwarteter Fehler",
    "The application encountered an unhandled error.\n"
    "Details are in the log. The current action was cancelled.": (
        "Die Anwendung hat einen unbehandelten Fehler erkannt.\n"
        "Details stehen im Log. Die aktuelle Aktion wurde abgebrochen."
    ),
    # ── Dependencies ──
    "Missing Dependencies": "Fehlende Abhängigkeiten",
    "Some features may be unavailable:": (
        "Einige Funktionen sind eventuell nicht verfügbar:"
    ),
    "PCAP Parsing": "PCAP-Parsing",
    "KML Export": "KML-Export",
    # ── File ──
    "Open PCAP File": "PCAP-Datei öffnen",
    "PCAP Files": "PCAP-Dateien",
    "All Files": "Alle Dateien",
    "No file loaded": "Keine Datei geladen",
    "File loaded successfully": "Datei erfolgreich geladen",
    "Failed to load file": "Fehler beim Laden der Datei",
    # ── Player ──
    "Play": "Abspielen",
    "Pause": "Pause",
    "Stop": "Stopp",
    "Speed": "Geschwindigkeit",
    "No messages to display": "Keine Nachrichten zum Anzeigen",
    "Export KML": "KML exportieren",
    "KML Files": "KML-Dateien",
    # ── Export ──
    "Export successful": "Export erfolgreich",
    "Export failed": "Export fehlgeschlagen",
    # ── Map ──
    "Map loading...": "Karte lädt...",
    "Map ready": "Karte bereit",
    "Map error": "Kartenfehler",
}


def tr(message_id: str, *args: object) -> str:
    """Return the German translation for *message_id*.

    Falls back to the message_id itself if no translation is registered.
    Format-style placeholders (``{}``) are supported via *args*.

    Usage::

        tr("File loaded successfully")
        tr("{} messages processed", count)
    """
    text = _translations.get(message_id, message_id)
    if args:
        text = text.format(*args)
    return text
