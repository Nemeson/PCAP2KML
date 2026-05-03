from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pcap2kml_player.theme_manager import (
    THEME_DARK,
    THEME_LIGHT,
    ThemeManager,
    _read_stylesheet,
)


class TestReadStylesheet:
    def test_reads_valid_file(self, tmp_path: Path):
        qss = tmp_path / "test.qss"
        qss.write_text("QWidget { color: red; }", encoding="utf-8")
        assert _read_stylesheet(qss) == "QWidget { color: red; }"

    def test_returns_empty_string_for_missing_file(self):
        result = _read_stylesheet(Path("/nonexistent/path.qss"))
        assert result == ""

    def test_returns_empty_string_for_unreadable_file(self, tmp_path: Path):
        bad = tmp_path / "unreadable.qss"
        bad.write_text("content", encoding="utf-8")
        with patch("pathlib.Path.read_text", side_effect=OSError):
            result = _read_stylesheet(bad)
            assert result == ""


class TestThemeManager:
    @pytest.fixture
    def mock_app(self):
        return MagicMock()

    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock()
        settings.value.return_value = THEME_LIGHT
        return settings

    def test_default_theme_is_light(self, mock_app, mock_settings):
        with patch(
            "pcap2kml_player.theme_manager.create_settings", return_value=mock_settings
        ):
            mgr = ThemeManager(mock_app)
            assert mgr.current == THEME_LIGHT

    def test_apply_dark_theme(self, mock_app, mock_settings):
        with patch(
            "pcap2kml_player.theme_manager.create_settings", return_value=mock_settings
        ):
            mgr = ThemeManager(mock_app)
            with patch.object(mock_app, "setStyleSheet"):
                mgr.apply(THEME_DARK)
            assert mgr.current == THEME_DARK

    def test_toggle_switches_theme(self, mock_app, mock_settings):
        with patch(
            "pcap2kml_player.theme_manager.create_settings", return_value=mock_settings
        ), patch.object(mock_app, "setStyleSheet"):
            mgr = ThemeManager(mock_app)
            assert mgr.current == THEME_LIGHT
            new = mgr.toggle()
            assert new == THEME_DARK
            assert mgr.current == THEME_DARK

    def test_toggle_twice_returns_to_original(self, mock_app, mock_settings):
        with patch(
            "pcap2kml_player.theme_manager.create_settings", return_value=mock_settings
        ), patch.object(mock_app, "setStyleSheet"):
            mgr = ThemeManager(mock_app)
            mgr.toggle()
            result = mgr.toggle()
            assert result == THEME_LIGHT
            assert mgr.current == THEME_LIGHT
