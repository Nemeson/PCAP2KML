"""Theme management for PCAP2KML Player.

Supports light and dark QSS stylesheets with runtime switching
and persistence via QSettings.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .map_backend import create_settings

_STYLES_DIR = Path(__file__).resolve().parent / "ui" / "styles"
_LIGHT_PATH = _STYLES_DIR / "light.qss"
_DARK_PATH = _STYLES_DIR / "dark.qss"

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = {THEME_LIGHT, THEME_DARK}


def _read_stylesheet(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


class ThemeManager:
    """Manages application theme (light/dark) and persists preference."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._settings = create_settings()
        self._current = self._settings.value("theme", THEME_LIGHT)

    @property
    def current(self) -> str:
        return self._current

    def apply(self, theme: str | None = None) -> None:
        """Apply a theme. If no theme given, re-applies the current one."""
        if theme is not None:
            self._current = theme

        path = _DARK_PATH if self._current == THEME_DARK else _LIGHT_PATH
        stylesheet = _read_stylesheet(path)
        self._app.setStyleSheet(stylesheet)
        self._settings.setValue("theme", self._current)

    def toggle(self) -> str:
        """Switch between light and dark, return the new theme ID."""
        new_theme = THEME_DARK if self._current == THEME_LIGHT else THEME_LIGHT
        self.apply(new_theme)
        return new_theme
