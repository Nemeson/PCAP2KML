"""T1.1 — Stutter-Profiling-Harness.

Misst pro simuliertem Tick die CPU-Zeit von `_compute_render_payload`
sowie Payload-Groesse, Station-Count und Trail-Laenge.
Schreibt CSV pro PCAP + Markdown-Zusammenfassung.

Kein WebEngine, kein QApplication — pure-CPU-Profil.
JS-Bridge-Latenz wird in einem separaten Schritt (Live-App) gemessen.

Usage:
    python -m scripts.profiling.profile_replay <pcap-path> [<pcap-path> ...]
    python -m scripts.profiling.profile_replay --all   # alle testfiles/*.pcap
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pcap2kml_player.map_widget import _compute_render_payload  # noqa: E402
from pcap2kml_player.pcap_parser import parse_pcap  # noqa: E402
from pcap2kml_player.player_controller import TICK_INTERVAL_MS  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "profiling"
TESTFILES = REPO_ROOT / "testfiles"

PERFORMANCE_MODES = ("normal",)
SHORT_TRAILS = False
FIT_VIEW = False


@dataclass(frozen=True)
class TickSample:
    tick_index: int
    sim_time_s: float
    msg_index: int
    payload_compute_ms: float
    payload_size_bytes: int
    station_count: int
    marker_count: int
    gc_pauses_ms: float


def _build_station_color_map(messages) -> dict[str, str]:
    palette = [
        "#3388ff", "#ff5733", "#33c1ff", "#ffd133", "#33ff8d",
        "#a833ff", "#ff33d1", "#33ff33", "#ff8033", "#3333ff",
    ]
    seen: dict[str, str] = {}
    for msg in messages:
        sid = getattr(msg, "station_id", None)
        if sid and sid not in seen:
            seen[sid] = palette[len(seen) % len(palette)]
    return seen


def _attach_gc_logger() -> list[float]:
    pauses: list[float] = []
    state = {"start": 0.0}

    def cb(phase: str, info: dict) -> None:  # noqa: ARG001
        if phase == "start":
            state["start"] = time.perf_counter()
        else:
            pauses.append((time.perf_counter() - state["start"]) * 1000.0)

    gc.callbacks.append(cb)
    return pauses


def profile_pcap(
    pcap_path: Path,
    performance_mode: str = "normal",
    window_seconds: float | None = None,
) -> dict:
    print(f"[profile] parsing {pcap_path.name} ...", flush=True)
    parse_start = time.perf_counter()
    session = parse_pcap(str(pcap_path))
    parse_seconds = time.perf_counter() - parse_start
    messages = list(session.messages)
    if not messages:
        print(f"[profile]   no messages in {pcap_path.name} — skipping")
        return {}

    color_map = _build_station_color_map(messages)
    t0 = messages[0].timestamp
    t_end = messages[-1].timestamp
    duration_s = (t_end - t0).total_seconds()
    print(f"[profile]   {len(messages)} msgs, duration {duration_s:.1f}s, parse {parse_seconds:.2f}s")

    samples: list[TickSample] = []
    gc_pauses = _attach_gc_logger()
    tick_dt = TICK_INTERVAL_MS / 1000.0

    sim_time = 0.0
    msg_index = 0
    tick_index = 0
    t0_epoch = t0.timestamp()

    while sim_time <= duration_s:
        while msg_index + 1 < len(messages):
            next_offset = (messages[msg_index + 1].timestamp - t0).total_seconds()
            if next_offset > sim_time:
                break
            msg_index += 1

        if window_seconds is not None and window_seconds > 0:
            window_start = t0_epoch + sim_time - window_seconds
        else:
            window_start = None

        gc_pauses.clear()
        compute_start = time.perf_counter()
        payload = _compute_render_payload(
            messages,
            max_index=msg_index,
            window_start_timestamp=window_start,
            fit_view=FIT_VIEW,
            short_trails=SHORT_TRAILS,
            clear_first=False,
            performance_mode=performance_mode,
            station_color_map=color_map,
        )
        compute_ms = (time.perf_counter() - compute_start) * 1000.0
        payload_json = json.dumps(payload)

        markers = payload.get("markers") or payload.get("station_markers") or []
        if isinstance(markers, dict):
            marker_count = len(markers)
        else:
            marker_count = len(markers) if hasattr(markers, "__len__") else 0
        station_coords = payload.get("station_coords") or payload.get("trails") or {}
        station_count = len(station_coords) if hasattr(station_coords, "__len__") else 0

        samples.append(
            TickSample(
                tick_index=tick_index,
                sim_time_s=sim_time,
                msg_index=msg_index,
                payload_compute_ms=compute_ms,
                payload_size_bytes=len(payload_json.encode("utf-8")),
                station_count=station_count,
                marker_count=marker_count,
                gc_pauses_ms=sum(gc_pauses),
            )
        )

        sim_time += tick_dt
        tick_index += 1

    suffix = f"{performance_mode}"
    if window_seconds is not None and window_seconds > 0:
        suffix += f"_w{int(window_seconds)}s"
    csv_path = OUT_DIR / f"{pcap_path.stem.replace(' ', '_')}_{suffix}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow([
            "tick", "sim_time_s", "msg_index",
            "compute_ms", "payload_bytes",
            "stations", "markers", "gc_pauses_ms",
        ])
        for s in samples:
            writer.writerow([
                s.tick_index, f"{s.sim_time_s:.3f}", s.msg_index,
                f"{s.payload_compute_ms:.3f}", s.payload_size_bytes,
                s.station_count, s.marker_count,
                f"{s.gc_pauses_ms:.3f}",
            ])

    compute_times = [s.payload_compute_ms for s in samples]
    payload_sizes = [s.payload_size_bytes for s in samples]
    summary = {
        "pcap": pcap_path.name,
        "size_bytes": pcap_path.stat().st_size,
        "messages": len(messages),
        "duration_s": duration_s,
        "parse_seconds": parse_seconds,
        "ticks": len(samples),
        "compute_ms_p50": statistics.median(compute_times) if compute_times else 0.0,
        "compute_ms_p95": _pct(compute_times, 95),
        "compute_ms_p99": _pct(compute_times, 99),
        "compute_ms_max": max(compute_times) if compute_times else 0.0,
        "compute_ms_first10pct": (
            statistics.mean(compute_times[: max(1, len(compute_times) // 10)])
            if compute_times else 0.0
        ),
        "compute_ms_last10pct": (
            statistics.mean(compute_times[-max(1, len(compute_times) // 10):])
            if compute_times else 0.0
        ),
        "payload_kb_p95": _pct(payload_sizes, 95) / 1024.0,
        "payload_kb_max": (max(payload_sizes) / 1024.0) if payload_sizes else 0.0,
        "csv": str(csv_path.relative_to(REPO_ROOT)),
    }
    return summary


def _pct(values, percentile: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((percentile / 100.0) * (len(s) - 1)))))
    return s[k]


def write_report(summaries: list[dict]) -> Path:
    md = OUT_DIR / "stutter_profile.md"
    lines = [
        "# T1.1 — Stutter-Profiling-Bericht",
        "",
        f"Generiert: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Pure-CPU-Profil von `_compute_render_payload` ueber simulierte Tick-Schleife.",
        "Tick-Intervall: 50 ms (= TICK_INTERVAL_MS in player_controller).",
        "",
        "## Zusammenfassung",
        "",
        "| PCAP | Msgs | Dauer s | Ticks | compute p50 | p95 | p99 | max | first10% mean | last10% mean | payload p95 KB |",
        "|------|------|---------|-------|-------------|-----|-----|-----|----------------|---------------|-----------------|",
    ]
    for s in summaries:
        if not s:
            continue
        lines.append(
            "| {pcap} | {msgs} | {dur:.1f} | {ticks} | {p50:.2f} | {p95:.2f} | {p99:.2f} | {mx:.2f} | {fst:.2f} | {lst:.2f} | {pl:.1f} |".format(
                pcap=s["pcap"],
                msgs=s["messages"],
                dur=s["duration_s"],
                ticks=s["ticks"],
                p50=s["compute_ms_p50"],
                p95=s["compute_ms_p95"],
                p99=s["compute_ms_p99"],
                mx=s["compute_ms_max"],
                fst=s["compute_ms_first10pct"],
                lst=s["compute_ms_last10pct"],
                pl=s["payload_kb_p95"],
            )
        )
    lines.append("")
    lines.append("**Frametime-Gate v1.8:** p95 < 18 ms, p99 < 25 ms.")
    lines.append("")
    lines.append("## Befund-Hypothesen")
    lines.append("")
    lines.append(
        "Wenn `last10%-mean` deutlich groesser als `first10%-mean` ist, bestaetigt sich der "
        "**O(N) Vollscan in `_compute_render_payload`**: die Funktion iteriert pro Tick alle "
        "Messages von Index 0 bis `max_index+1`, ohne Index-Cut. Mit fortschreitender Playback-"
        "Position waechst die Render-Arbeit linear → progressiver Stutter."
    )
    lines.append("")
    lines.append("Pro PCAP: rohe Tick-Daten in den verlinkten CSV-Dateien.")
    lines.append("")
    lines.append("## Rohdaten")
    lines.append("")
    for s in summaries:
        if not s:
            continue
        lines.append(f"- `{s['csv']}` — {s['pcap']} ({s['ticks']} Ticks)")
    lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def main() -> int:
    ap = argparse.ArgumentParser(description="T1.1 Stutter-Profiling-Harness")
    ap.add_argument("paths", nargs="*", help="PCAP-Pfade")
    ap.add_argument("--all", action="store_true", help="alle testfiles/*.pcap")
    ap.add_argument("--mode", default="normal", help="performance_mode")
    ap.add_argument("--window", type=float, default=None,
                    help="Trail-Window in Sekunden (Production-Default normal=120)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    if args.all:
        paths = sorted(TESTFILES.glob("*.pcap"))
    else:
        paths = [Path(p) for p in args.paths]

    if not paths:
        ap.error("keine PCAPs angegeben")

    summaries = []
    for path in paths:
        try:
            summaries.append(profile_pcap(path, args.mode, args.window))
        except Exception as exc:  # noqa: BLE001
            print(f"[profile] FAILED {path.name}: {exc}")
            summaries.append({"pcap": path.name, "error": str(exc)})

    md = write_report(summaries)
    print(f"[profile] report -> {md.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
