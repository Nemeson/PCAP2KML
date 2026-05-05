"""Automated UI documentation generator.

Starts the app with a fixture PCAP, cycles through workspaces,
captures screenshots, and verifies HTML references.

Usage:
    python scripts/generate_ui_docs.py [fixture_pcap_path] [output_dir]

Returns exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

# Allow importing from project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pcap2kml_player.ui.main_window import MainWindow
from pcap2kml_player.parsing_worker import ParsingWorker


# ── Configuration ──────────────────────────────────────────────────

WORKSPACE_IDS = ["map", "eta", "issues", "raw"]
SCREENSHOT_DELAY_MS = 500  # Wait for render settle
POST_CLICK_DELAY_MS = 300

# Default fixture: use the Landau XML as a reliable multi-message fixture
DEFAULT_FIXTURE = PROJECT_ROOT / "testfiles" / "Landau_2009886_V06_R1.xml"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "screenshots"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>PCAP2KML Player – UI Screenshots</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #0d1b2a; }}
  h1 {{ font-size: 20px; margin-bottom: 16px; }}
  .screenshot {{ margin: 16px 0; }}
  .screenshot img {{ max-width: 100%; border: 1px solid #d7dde8; border-radius: 4px; }}
  .label {{ font-size: 13px; color: #5a6b81; margin-bottom: 4px; }}
  .generated {{ font-size: 11px; color: #667891; margin-top: 24px; }}
</style>
</head>
<body>
<h1>PCAP2KML Player – UI Screenshots (automatisch generiert)</h1>
{images}
<div class="generated">Generiert: {timestamp}</div>
</body>
</html>
"""


def _capture_widget(widget, path: Path) -> bool:
    """Save a QWidget screenshot to path."""
    pixmap = widget.grab()
    if pixmap.isNull():
        print(f"  [WARN] Screenshot empty for {path.name}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = pixmap.save(str(path), "PNG")
    if ok:
        print(f"  [OK] {path.name} ({pixmap.width()}x{pixmap.height()})")
    else:
        print(f"  [FAIL] Could not save {path}")
    return ok


def _build_html_report(output_dir: Path, screenshots: list[Path]) -> Path:
    """Build an HTML page referencing all screenshots."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    image_blocks = []
    for shot in screenshots:
        rel = shot.relative_to(output_dir)
        label = shot.stem.replace("_", " ").title()
        image_blocks.append(
            f'<div class="screenshot"><div class="label">{label}</div><img src="{rel}" alt="{label}"></div>'
        )
    html = HTML_TEMPLATE.format(images="\n".join(image_blocks), timestamp=timestamp)
    report_path = output_dir / "index.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML report: {report_path}")
    return report_path


def _verify_html_references(output_dir: Path, screenshots: set[str]) -> list[str]:
    """Return missing screenshot references in any HTML file under output_dir."""
    errors: list[str] = []
    for html_file in output_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for shot in screenshots:
            # Check common reference patterns
            if shot not in content and Path(shot).stem not in content:
                errors.append(f"{html_file.name}: missing reference to {shot}")
    return errors


def generate_ui_docs(fixture_path: Path, output_dir: Path) -> int:
    """Run the full screenshot pipeline. Returns exit code."""
    print(f"[INFO] Fixture: {fixture_path}")
    print(f"[INFO] Output:  {output_dir}")

    if not fixture_path.exists():
        print(f"[ERROR] Fixture not found: {fixture_path}")
        return 1

    app = QApplication.instance() or QApplication(sys.argv)

    # Parse fixture
    print("[INFO] Parsing fixture...")
    session = ParsingWorker([str(fixture_path)]).run_sync()
    if not session.messages:
        print("[ERROR] Fixture produced no messages")
        return 1
    print(f"[INFO] Loaded {len(session.messages)} messages, {len(session.station_ids)} stations")

    # Create main window
    print("[INFO] Starting MainWindow...")
    window = MainWindow()
    window.show()
    window._on_load_finished(session, [str(fixture_path)], [])
    app.processEvents()

    screenshots: list[Path] = []
    expected_names: set[str] = set()

    # 1. Full window screenshot
    shot_path = output_dir / "01_full_window.png"
    _capture_widget(window, shot_path)
    screenshots.append(shot_path)
    expected_names.add(shot_path.name)
    time.sleep(SCREENSHOT_DELAY_MS / 1000)

    # 2. Cycle through workspaces
    for ws_id in WORKSPACE_IDS:
        print(f"[INFO] Switching to workspace: {ws_id}")
        window._switch_workspace(ws_id)
        app.processEvents()
        time.sleep(POST_CLICK_DELAY_MS / 1000)

        # Screenshot the central content area (workspace stack)
        shot_path = output_dir / f"02_workspace_{ws_id}.png"
        content_widget = window._workspace_stack
        _capture_widget(content_widget, shot_path)
        screenshots.append(shot_path)
        expected_names.add(shot_path.name)
        time.sleep(SCREENSHOT_DELAY_MS / 1000)

    # 3. Filter interaction screenshot
    print("[INFO] Capturing filter row...")
    # Find the filter row widget (it's a child of the main layout)
    # The filter row is the second widget in the main vertical layout after toolbar
    filter_widget = None
    main_layout = window.centralWidget().layout()
    if main_layout:
        for i in range(main_layout.count()):
            widget = main_layout.itemAt(i).widget()
            if widget and hasattr(widget, "objectName") and "filter" in str(widget.objectName()).lower():
                filter_widget = widget
                break
            # Fallback: look for widget with checkboxes
            if widget:
                children = widget.findChildren(type(window._type_checkboxes.get(MessageType.CAM)))
                if children:
                    filter_widget = widget
                    break
    if filter_widget:
        shot_path = output_dir / "03_filter_row.png"
        _capture_widget(filter_widget, shot_path)
        screenshots.append(shot_path)
        expected_names.add(shot_path.name)

    # 4. Message table screenshot
    print("[INFO] Capturing message table...")
    shot_path = output_dir / "04_message_table.png"
    _capture_widget(window._msg_table, shot_path)
    screenshots.append(shot_path)
    expected_names.add(shot_path.name)

    # 5. Detail inspector screenshot
    print("[INFO] Capturing detail inspector...")
    if hasattr(window, "_detail_table"):
        shot_path = output_dir / "05_detail_inspector.png"
        _capture_widget(window._detail_table, shot_path)
        screenshots.append(shot_path)
        expected_names.add(shot_path.name)

    # Close window
    window.close()
    app.processEvents()

    # Build HTML report
    print("[INFO] Building HTML report...")
    _build_html_report(output_dir, screenshots)

    # Verify references
    print("[INFO] Verifying HTML references...")
    errors = _verify_html_references(output_dir, expected_names)
    if errors:
        print("[WARN] Reference issues found:")
        for err in errors:
            print(f"  - {err}")
    else:
        print("[OK] All HTML references verified")

    ok_count = sum(1 for s in screenshots if s.exists())
    print(f"\n[SUMMARY] {ok_count}/{len(screenshots)} screenshots generated")
    return 0 if ok_count == len(screenshots) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UI screenshots for documentation")
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    return generate_ui_docs(args.fixture, args.output)


if __name__ == "__main__":
    sys.exit(main())
