from __future__ import annotations

from pcap2kml_player.map_backend import (
    MAP_BACKEND_NATIVE,
    MAP_BACKEND_WEBENGINE,
    create_map_widget,
    prefer_native_map_backend,
    selected_map_backend_name,
)


def test_map_backend_auto_keeps_webengine_when_software_opengl_dll_is_active(monkeypatch):
    monkeypatch.delenv("PCAP2KML_MAP_BACKEND", raising=False)
    monkeypatch.setenv("QT_OPENGL_DLL", r"C:\PyQt6\Qt6\bin\opengl32sw.dll")

    assert prefer_native_map_backend() is False
    assert selected_map_backend_name() == MAP_BACKEND_WEBENGINE


def test_map_backend_auto_uses_webengine_without_software_opengl_dll(monkeypatch):
    monkeypatch.delenv("PCAP2KML_MAP_BACKEND", raising=False)
    monkeypatch.delenv("QT_OPENGL_DLL", raising=False)

    assert prefer_native_map_backend() is False
    assert selected_map_backend_name() == MAP_BACKEND_WEBENGINE


def test_map_backend_can_force_webengine(monkeypatch):
    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "webengine")
    monkeypatch.setenv("QT_OPENGL_DLL", r"C:\PyQt6\Qt6\bin\opengl32sw.dll")

    assert prefer_native_map_backend() is False
    assert selected_map_backend_name() == MAP_BACKEND_WEBENGINE


def test_map_backend_can_force_native(monkeypatch):
    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "native")
    monkeypatch.delenv("QT_OPENGL_DLL", raising=False)

    assert prefer_native_map_backend() is True
    assert selected_map_backend_name() == MAP_BACKEND_NATIVE


def test_create_map_widget_explicit_webengine(monkeypatch):
    """create_map_widget with explicit backend falls through to WebEngine path."""
    import sys
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock_mod = MagicMock()
    mock_mod.MapWidget.return_value = mock
    monkeypatch.setitem(sys.modules, "pcap2kml_player.map_widget", mock_mod)

    result = create_map_widget(parent=None, backend="webengine")
    assert result is mock
    mock_mod.MapWidget.assert_called_once_with(None)


def test_create_map_widget_selected_native(monkeypatch):
    """create_map_widget follows selected backend when backend arg is None."""
    import sys
    from unittest.mock import MagicMock

    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "native")
    mock = MagicMock()
    mock_mod = MagicMock()
    mock_mod.NativeMapWidget.return_value = mock
    monkeypatch.setitem(sys.modules, "pcap2kml_player.native_map_widget", mock_mod)

    result = create_map_widget(parent=None, backend=None)
    assert result is mock
    mock_mod.NativeMapWidget.assert_called_once_with(None)


def test_map_backend_env_uppercase(monkeypatch):
    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "NATIVE")
    assert prefer_native_map_backend() is True


def test_map_backend_env_whitespace(monkeypatch):
    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "  native  ")
    assert prefer_native_map_backend() is True


def test_map_backend_env_invalid(monkeypatch):
    monkeypatch.setenv("PCAP2KML_MAP_BACKEND", "foobar")
    assert prefer_native_map_backend() is False
