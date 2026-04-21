"""Qt/QtWebEngine runtime setup for Windows compatibility."""

from __future__ import annotations

import os


DEFAULT_CHROMIUM_FLAGS = (
    "--disable-direct-composition",
    "--force-color-profile=srgb",
)
SOFTWARE_RENDERING_FLAGS = (
    "--disable-gpu",
    "--disable-gpu-compositing",
)


def configure_qt_runtime_environment() -> None:
    """Configure QtWebEngine before any PyQt imports happen.

    Some Windows machines emit noisy Chromium/QtWebEngine D3D11/HDR errors such
    as QueryVideoProcessorCustomExtForHDR. The default flags avoid the most
    fragile DirectComposition/HDR path while keeping GPU rendering available.

    Set PCAP2KML_DISABLE_GPU=1 to force software rendering on problematic
    remote desktops, old GPUs, or broken drivers.
    """
    flags = list(DEFAULT_CHROMIUM_FLAGS)
    if os.environ.get("PCAP2KML_DISABLE_GPU", "").strip().lower() in {"1", "true", "yes"}:
        flags.extend(SOFTWARE_RENDERING_FLAGS)
        os.environ.setdefault("QT_OPENGL", "software")

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
