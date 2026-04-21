from __future__ import annotations

import os

from pcap2kml_player.qt_runtime import configure_qt_runtime_environment


def test_configure_qt_runtime_adds_directcomposition_mitigation(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)

    configure_qt_runtime_environment()

    chromium_flags = set(os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())
    assert "--disable-direct-composition" in chromium_flags
    assert "--force-color-profile=srgb" in chromium_flags
    assert "--disable-gpu" not in chromium_flags


def test_configure_qt_runtime_can_force_software_rendering(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.setenv("PCAP2KML_DISABLE_GPU", "1")

    configure_qt_runtime_environment()

    chromium_flags = set(os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())
    assert "--disable-gpu" in chromium_flags
    assert "--disable-gpu-compositing" in chromium_flags
    assert os.environ["QT_OPENGL"] == "software"


def test_configure_qt_runtime_preserves_existing_flags(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--existing-flag")
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)

    configure_qt_runtime_environment()
    configure_qt_runtime_environment()

    flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split()
    assert flags.count("--existing-flag") == 1
    assert flags.count("--disable-direct-composition") == 1
