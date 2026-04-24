from __future__ import annotations

import os
from pathlib import Path

from pcap2kml_player.qt_runtime import (
    _prepend_env_path,
    configure_qt_runtime_environment,
    prefer_software_rendering,
)


def test_prefer_software_rendering_defaults_to_true(monkeypatch):
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.delenv("PCAP2KML_ENABLE_GPU", raising=False)

    assert prefer_software_rendering() is True


def test_prefer_software_rendering_can_opt_into_gpu(monkeypatch):
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.setenv("PCAP2KML_ENABLE_GPU", "1")

    assert prefer_software_rendering() is False


def test_configure_qt_runtime_adds_directcomposition_mitigation_and_software_default(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.delenv("PCAP2KML_ENABLE_GPU", raising=False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.delenv("QSG_RHI_PREFER_SOFTWARE_RENDERER", raising=False)
    monkeypatch.delenv("QT_OPENGL_DLL", raising=False)
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setattr(
        "pcap2kml_player.qt_runtime._find_pyqt_software_opengl_dll",
        lambda: Path(r"C:\PyQt6\Qt6\bin\opengl32sw.dll"),
    )

    configure_qt_runtime_environment()

    chromium_flags = set(os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())
    assert "--disable-direct-composition" in chromium_flags
    assert (
        "--disable-features=DirectComposition,DirectCompositionVideoOverlays,UseHDRTransferFunction"
        in chromium_flags
    )
    assert "--disable-accelerated-video-decode" in chromium_flags
    assert "--disable-gpu-memory-buffer-video-frames" in chromium_flags
    assert "--force-color-profile=srgb" in chromium_flags
    assert "--disable-gpu" in chromium_flags
    assert "--disable-gpu-compositing" in chromium_flags
    assert os.environ["QT_OPENGL"] == "software"
    assert os.environ["QSG_RHI_PREFER_SOFTWARE_RENDERER"] == "1"
    assert os.environ["QT_OPENGL_DLL"] == r"C:\PyQt6\Qt6\bin\opengl32sw.dll"
    assert os.environ["PATH"].split(os.pathsep)[0] == r"C:\PyQt6\Qt6\bin"


def test_configure_qt_runtime_can_force_software_rendering(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.delenv("QSG_RHI_PREFER_SOFTWARE_RENDERER", raising=False)
    monkeypatch.delenv("QT_OPENGL_DLL", raising=False)
    monkeypatch.delenv("PCAP2KML_ENABLE_GPU", raising=False)
    monkeypatch.setenv("PCAP2KML_DISABLE_GPU", "1")
    monkeypatch.setattr(
        "pcap2kml_player.qt_runtime._find_pyqt_software_opengl_dll",
        lambda: None,
    )

    configure_qt_runtime_environment()

    chromium_flags = set(os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())
    assert "--disable-gpu" in chromium_flags
    assert "--disable-gpu-compositing" in chromium_flags
    assert os.environ["QT_OPENGL"] == "software"
    assert os.environ["QSG_RHI_PREFER_SOFTWARE_RENDERER"] == "1"
    assert "QT_OPENGL_DLL" not in os.environ


def test_configure_qt_runtime_can_opt_into_gpu(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.delenv("QSG_RHI_PREFER_SOFTWARE_RENDERER", raising=False)
    monkeypatch.delenv("QT_OPENGL_DLL", raising=False)
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.setenv("PCAP2KML_ENABLE_GPU", "1")

    configure_qt_runtime_environment()

    chromium_flags = set(os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())
    assert "--disable-direct-composition" in chromium_flags
    assert "--disable-gpu" not in chromium_flags
    assert "QT_OPENGL" not in os.environ
    assert "QT_OPENGL_DLL" not in os.environ


def test_configure_qt_runtime_preserves_existing_flags(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--existing-flag")
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.delenv("PCAP2KML_ENABLE_GPU", raising=False)
    monkeypatch.setattr(
        "pcap2kml_player.qt_runtime._find_pyqt_software_opengl_dll",
        lambda: None,
    )

    configure_qt_runtime_environment()
    configure_qt_runtime_environment()

    flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split()
    assert flags.count("--existing-flag") == 1
    assert flags.count("--disable-direct-composition") == 1
    assert flags.count(
        "--disable-features=DirectComposition,DirectCompositionVideoOverlays,UseHDRTransferFunction"
    ) == 1


def test_configure_qt_runtime_does_not_duplicate_path_entry(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("PCAP2KML_DISABLE_GPU", raising=False)
    monkeypatch.delenv("PCAP2KML_ENABLE_GPU", raising=False)
    monkeypatch.setenv("PATH", r"C:\PyQt6\Qt6\bin" + os.pathsep + r"C:\Windows")
    monkeypatch.setattr(
        "pcap2kml_player.qt_runtime._find_pyqt_software_opengl_dll",
        lambda: Path(r"C:\PyQt6\Qt6\bin\opengl32sw.dll"),
    )

    configure_qt_runtime_environment()

    assert os.environ["PATH"].split(os.pathsep).count(r"C:\PyQt6\Qt6\bin") == 1


def test_prepend_env_path_prepends_once(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\Windows")

    _prepend_env_path("PATH", r"C:\PyQt6\Qt6\bin")
    _prepend_env_path("PATH", r"C:\PyQt6\Qt6\bin")

    assert os.environ["PATH"].split(os.pathsep) == [r"C:\PyQt6\Qt6\bin", r"C:\Windows"]
