"""Dashboard/statistics computation for PCAP2KML Player.

Aggregates session data for visualization in a standalone dialog.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import NamedTuple

from .data_model import MessageType, SessionData, V2xMessage


class SessionOverview(NamedTuple):
    """High-level session metrics."""

    total_messages: int
    station_count: int
    unique_types: int
    duration_seconds: float
    messages_per_second: float


class RateEntry(NamedTuple):
    """One bucket in a message-rate timeline."""

    start_time: datetime
    end_time: datetime
    rate: float  # messages per second


class SpeedHeadingEntry(NamedTuple):
    """Speed and heading for a single message."""

    speed: float | None
    heading: float | None


class StationSpeedHeading(NamedTuple):
    """Aggregated speed/heading stats for one station."""

    speeds: list[float]
    headings: list[float]
    avg_speed: float
    avg_heading: float
    speed_variance: float


def compute_session_overview(session: SessionData) -> SessionOverview:
    """Return basic session statistics."""
    total = len(session.messages)
    stations = len(session.station_ids)
    types = len(session.msg_type_counts)
    duration = session.duration_seconds
    mps = total / max(duration, 1.0)
    return SessionOverview(
        total_messages=total,
        station_count=stations,
        unique_types=types,
        duration_seconds=duration,
        messages_per_second=mps,
    )


def compute_message_rate(
    session: SessionData,
    bucket_seconds: float = 1.0,
) -> list[RateEntry]:
    """Build a message-rate timeline (messages per second).

    Args:
        session: SessionData with messages.
        bucket_seconds: Width of each time bucket in seconds.

    Returns:
        List of RateEntry, sorted ascending by start_time.
    """
    if not session.messages:
        return []

    messages = session.messages
    start = messages[0].timestamp
    end = messages[-1].timestamp
    total_seconds = (end - start).total_seconds() or 1.0
    num_buckets = max(1, int(total_seconds // bucket_seconds) + 1)

    buckets = [0] * num_buckets
    for msg in messages:
        offset = (msg.timestamp - start).total_seconds()
        idx = int(offset // bucket_seconds)
        if 0 <= idx < num_buckets:
            buckets[idx] += 1

    result: list[RateEntry] = []
    for idx, count in enumerate(buckets):
        if count == 0:
            continue
        bucket_start = start + timedelta(seconds=idx * bucket_seconds)
        bucket_end = bucket_start + timedelta(seconds=bucket_seconds)
        result.append(
            RateEntry(
                start_time=bucket_start,
                end_time=bucket_end,
                rate=count / bucket_seconds,
            )
        )
    return result


def compute_station_speed_heading(
    session: SessionData,
) -> dict[str, StationSpeedHeading]:
    """Compute speed and heading distributions per station.

    Returns:
        Mapping station_id -> StationSpeedHeading.
    """
    by_station: dict[str, list[SpeedHeadingEntry]] = defaultdict(list)
    for msg in session.messages:
        by_station[msg.station_id].append(SpeedHeadingEntry(speed=msg.speed, heading=msg.heading))

    result: dict[str, StationSpeedHeading] = {}
    for station_id, entries in by_station.items():
        speeds = [e.speed for e in entries if e.speed is not None]
        headings = [e.heading for e in entries if e.heading is not None]
        if not speeds:
            continue
        avg_speed = sum(speeds) / len(speeds)
        avg_heading = sum(headings) / len(headings) if headings else 0.0
        var = sum((s - avg_speed) ** 2 for s in speeds) / len(speeds)
        result[station_id] = StationSpeedHeading(
            speeds=speeds,
            headings=headings,
            avg_speed=avg_speed,
            avg_heading=avg_heading,
            speed_variance=var,
        )
    return result
