"""Qt/QtWebEngine runtime setup for Windows compatibility."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


DEFAULT_CHROMIUM_FLAGS = (
    "--disable-direct-composition",
    "--disable-features=DirectComposition,DirectCompositionVideoOverlays,UseHDRTransferFunction",
    "--disable-accelerated-video-decode",
    "--disable-gpu-memory-buffer-video-frames",
    "--force-color-profile=srgb",
)
SOFTWARE_RENDERING_FLAGS = (
    # Keep GPU rasterization off to reduce GPU memory use, but do NOT disable
    # the GPU process or the display compositor — Chromium handles kFatalFailure
    # GPU channel errors gracefully when the browser process itself has a working
    # OpenGL context (provided here via QT_OPENGL=software / opengl32sw.dll).
    # Adding --disable-gpu or --disable-gpu-compositing breaks this recovery path
    # and leaves the WebEngine surface permanently blank.
    "--disable-gpu-rasterization",
    "--disable-oop-rasterization",
)


def prefer_software_rendering() -> bool:
    """Return whether the app should prefer software rendering for QtWebEngine."""
    enable_gpu = os.environ.get("PCAP2KML_ENABLE_GPU", "").strip().lower() in {"1", "true", "yes"}
    disable_gpu = os.environ.get("PCAP2KML_DISABLE_GPU", "").strip().lower() in {"1", "true", "yes"}
    return disable_gpu or not enable_gpu


def configure_qt_runtime_environment() -> None:
    """Configure QtWebEngine before any PyQt imports happen.

    Some Windows machines emit Chromium/QtWebEngine D3D11/HDR errors such as
    QueryVideoProcessorCustomExtForHDR or show a gray WebEngine surface. The
    default favors stability and forces software rendering for the embedded map.

    Set PCAP2KML_ENABLE_GPU=1 to opt back into GPU rendering for testing on
    machines where QtWebEngine is known to be stable.
    """
    flags = list(DEFAULT_CHROMIUM_FLAGS)
    if prefer_software_rendering():
        flags.extend(SOFTWARE_RENDERING_FLAGS)
        os.environ.setdefault("QT_OPENGL", "software")
        os.environ.setdefault("QSG_RHI_PREFER_SOFTWARE_RENDERER", "1")
        software_gl_dll = _find_pyqt_software_opengl_dll()
        if software_gl_dll is not None:
            os.environ.setdefault("QT_OPENGL_DLL", str(software_gl_dll))
            _prepend_env_path("PATH", str(software_gl_dll.parent))

    _append_env_flags("QTWEBENGINE_CHROMIUM_FLAGS", flags)
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def _append_env_flags(env_name: str, flags: list[str]) -> None:
    """Append flags to an environment variable without duplicating entries."""
    existing = os.environ.get(env_name, "").split()
    merged = list(existing)
    for flag in flags:
        if flag not in merged:
            merged.append(flag)
    os.environ[env_name] = " ".join(merged).strip()


def _prepend_env_path(env_name: str, value: str) -> None:
    """Prepend one path segment to an env var without duplication."""
    existing = [item for item in os.environ.get(env_name, "").split(os.pathsep) if item]
    if value in existing:
        return
    os.environ[env_name] = os.pathsep.join([value, *existing]) if existing else value


def _find_pyqt_software_opengl_dll() -> Path | None:
    """Locate the `opengl32sw.dll` shipped with PyQt6, if present."""
    spec = importlib.util.find_spec("PyQt6")
    origin = getattr(spec, "origin", None)
    if not origin:
        return None
    pyqt_root = Path(origin).resolve().parent
    candidates = [
        pyqt_root / "Qt6" / "bin" / "opengl32sw.dll",
        pyqt_root / "Qt" / "bin" / "opengl32sw.dll",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
