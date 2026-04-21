"""Windows-friendly launcher for PCAP2KML Player.

This module intentionally avoids importing PyQt before dependency checks run.
It can be executed directly with Python or packaged as a small .exe wrapper.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
REQUIREMENTS_FILE = PROJECT_ROOT / "pcap2kml_player" / "requirements.txt"


@dataclass(frozen=True)
class RequirementCheck:
    """Result of checking one requirement line."""

    requirement: str
    package_name: str
    import_name: str
    installed: bool


PACKAGE_IMPORTS = {
    "PyQt6-WebEngine": "PyQt6.QtWebEngineWidgets",
    "PyQt6": "PyQt6",
    "scapy": "scapy",
    "pyshark": "pyshark",
    "asn1tools": "asn1tools",
    "simplekml": "simplekml",
}


def load_requirements(path: Path = REQUIREMENTS_FILE) -> list[str]:
    """Return non-comment requirement lines."""
    if not path.exists():
        return []
    requirements: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            requirements.append(stripped)
    return requirements


def requirement_package_name(requirement: str) -> str:
    """Extract the distribution name from a simple PEP 508 requirement line."""
    if "[" in requirement:
        requirement = requirement.split("[", 1)[0].strip()
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
        if separator in requirement:
            return requirement.split(separator, 1)[0].strip()
    return requirement.strip()


def check_requirements(requirements: list[str]) -> list[RequirementCheck]:
    """Check whether each runtime requirement is importable/installed."""
    checks: list[RequirementCheck] = []
    for requirement in requirements:
        package_name = requirement_package_name(requirement)
        import_name = PACKAGE_IMPORTS.get(package_name, package_name.replace("-", "_"))
        installed = _is_requirement_available(package_name, import_name)
        checks.append(
            RequirementCheck(
                requirement=requirement,
                package_name=package_name,
                import_name=import_name,
                installed=installed,
            )
        )
    return checks


def missing_requirements(requirements: list[str]) -> list[str]:
    """Return requirement lines that are not currently available."""
    return [check.requirement for check in check_requirements(requirements) if not check.installed]


def install_requirements(requirements: list[str]) -> int:
    """Install missing requirements via the active Python interpreter."""
    if not requirements:
        return 0
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        *requirements,
    ]
    return subprocess.call(command, cwd=str(PROJECT_ROOT))


def prompt_install(missing: list[str]) -> bool:
    """Ask the operator whether missing packages should be installed."""
    print("Fehlende Python-Abhaengigkeiten erkannt:")
    for requirement in missing:
        print(f"  - {requirement}")
    print()
    answer = input("Jetzt automatisch mit pip nachinstallieren? [j/N] ").strip().lower()
    return answer in {"j", "ja", "y", "yes"}


def launch_app() -> int:
    """Import and start the real PyQt application."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from pcap2kml_player.main import main

    return main()


def main() -> int:
    """Check dependencies, optionally install missing ones, then launch the app."""
    requirements = load_requirements()
    missing = missing_requirements(requirements)
    if missing:
        if not prompt_install(missing):
            print("Start abgebrochen. Bitte Requirements installieren und erneut starten.")
            return 2
        install_code = install_requirements(missing)
        if install_code != 0:
            print(f"Installation fehlgeschlagen (Exit-Code {install_code}).")
            return install_code

        still_missing = missing_requirements(requirements)
        if still_missing:
            print("Einige Requirements fehlen weiterhin:")
            for requirement in still_missing:
                print(f"  - {requirement}")
            return 3

    return launch_app()


def _is_requirement_available(package_name: str, import_name: str) -> bool:
    """Return True if a requirement appears installed and importable."""
    try:
        importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return importlib.util.find_spec(import_name) is not None

    root_import = import_name.split(".", 1)[0]
    return importlib.util.find_spec(root_import) is not None


if __name__ == "__main__":
    raise SystemExit(main())
