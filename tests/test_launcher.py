from __future__ import annotations

from pathlib import Path

import pcap2kml_launcher as launcher


def test_load_requirements_ignores_empty_lines_and_comments(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n# comment\nPyQt6>=6.6.0\n\nsimplekml>=1.3.0\n",
        encoding="utf-8",
    )

    assert launcher.load_requirements(requirements) == [
        "PyQt6>=6.6.0",
        "simplekml>=1.3.0",
    ]


def test_requirement_package_name_handles_common_specifiers():
    assert launcher.requirement_package_name("PyQt6-WebEngine>=6.6.0") == "PyQt6-WebEngine"
    assert launcher.requirement_package_name("simplekml==1.3.6") == "simplekml"
    assert launcher.requirement_package_name("example[extra]>=1") == "example"


def test_missing_requirements_returns_unavailable_requirement(monkeypatch):
    def fake_available(package_name: str, import_name: str) -> bool:
        return package_name == "installed-package" and import_name == "installed_package"

    monkeypatch.setattr(launcher, "_is_requirement_available", fake_available)

    assert launcher.missing_requirements(
        ["installed-package>=1", "missing-package>=2"]
    ) == ["missing-package>=2"]
