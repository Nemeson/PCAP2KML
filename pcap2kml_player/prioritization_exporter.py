"""CSV/JSON export for SREM/SSEM prioritization diagnostics."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .data_model import V2xMessage
from .scene_model import PrioritizationIssue, collect_prioritization_issue_history

ISSUE_EXPORT_FIELDS = [
    "timestamp",
    "issue_type",
    "severity",
    "intersection_id",
    "request_id",
    "sequence_number",
    "station_id",
    "in_lane",
    "out_lane",
    "status",
    "delay_seconds",
    "message",
    "source_summary",
    "source_roles",
    "source_files",
    "merge_group_id",
    "merge_confidence",
]

ISSUE_EXPORT_HEADERS = {
    "timestamp": "Zeitstempel",
    "issue_type": "Fehlertyp",
    "severity": "Schweregrad",
    "intersection_id": "Kreuzung",
    "request_id": "Request-ID",
    "sequence_number": "Sequenznummer",
    "station_id": "Station",
    "in_lane": "Einfahrts-Lane",
    "out_lane": "Ausfahrts-Lane",
    "status": "SSEM-Status",
    "delay_seconds": "Verzoegerung [s]",
    "message": "Beschreibung",
    "source_summary": "Quelle",
    "source_roles": "Quellrollen",
    "source_files": "Quelldateien",
    "merge_group_id": "Merge-Gruppe",
    "merge_confidence": "Merge-Konfidenz",
}


def export_prioritization_issues(
    messages: list[V2xMessage],
    output_dir: Path,
    *,
    basename: str = "prioritization_issues",
) -> list[Path]:
    """Export prioritization issue history as CSV and JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    issues = collect_prioritization_issue_history(messages)
    rows = [_issue_to_row(issue) for issue in issues]

    csv_path = output_dir / f"{basename}.csv"
    json_path = output_dir / f"{basename}.json"
    report_path = output_dir / f"{basename.replace('issues', 'report')}.json"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=ISSUE_EXPORT_FIELDS,
            restval="",
        )
        writer.writerow(ISSUE_EXPORT_HEADERS)
        writer.writerows(rows)

    machine_csv_path = output_dir / f"{basename}_machine.csv"
    with machine_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ISSUE_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)

    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(_build_report(issues), handle, ensure_ascii=False, indent=2)

    return [csv_path, machine_csv_path, json_path, report_path]


def _issue_to_row(issue: PrioritizationIssue) -> dict[str, object]:
    """Convert one issue to stable export columns."""
    return {
        "timestamp": issue.timestamp.isoformat(),
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "intersection_id": issue.intersection_id,
        "request_id": issue.request_id,
        "sequence_number": issue.sequence_number,
        "station_id": issue.station_id,
        "in_lane": "" if issue.in_lane is None else issue.in_lane,
        "out_lane": "" if issue.out_lane is None else issue.out_lane,
        "status": "" if issue.status is None else issue.status,
        "delay_seconds": "" if issue.delay_seconds is None else f"{issue.delay_seconds:.3f}",
        "message": issue.message,
        "source_summary": issue.source_summary,
        "source_roles": ", ".join(issue.source_roles),
        "source_files": ", ".join(issue.source_files),
        "merge_group_id": issue.merge_group_id or "",
        "merge_confidence": (
            "" if issue.merge_confidence is None else f"{issue.merge_confidence:.3f}"
        ),
    }


def _build_report(issues: list[PrioritizationIssue]) -> dict[str, object]:
    """Build a compact machine-readable prioritization diagnostics report."""
    by_intersection: dict[str, Counter[str]] = defaultdict(Counter)
    source_roles: Counter[str] = Counter()
    issue_types: Counter[str] = Counter()
    severities: Counter[str] = Counter()
    grant_delays: list[float] = []

    for issue in issues:
        issue_types[issue.issue_type] += 1
        severities[issue.severity] += 1
        by_intersection[str(issue.intersection_id)][issue.issue_type] += 1
        for role in issue.source_roles:
            source_roles[role] += 1
        if issue.issue_type == "LATE_GRANTED" and issue.delay_seconds is not None:
            grant_delays.append(issue.delay_seconds)

    mean_late_grant_delay = (
        sum(grant_delays) / len(grant_delays)
        if grant_delays
        else None
    )
    return {
        "total_issues": len(issues),
        "issues_by_type": dict(sorted(issue_types.items())),
        "issues_by_severity": dict(sorted(severities.items())),
        "issues_by_intersection": {
            intersection_id: dict(sorted(counter.items()))
            for intersection_id, counter in sorted(by_intersection.items())
        },
        "source_roles": dict(sorted(source_roles.items())),
        "mean_late_grant_delay_seconds": mean_late_grant_delay,
    }
