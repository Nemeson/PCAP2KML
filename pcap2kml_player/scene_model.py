"""Scene aggregation model for PCAP2KML Player.

Aggregates the flat V2xMessage stream into an interpretable scene:
MAP+SPaT per intersection, phase forecasts, and tracked SREM/SSEM requests.

References:
    ETSI TS 103 301, SAE J2735, ISO/TS 19091, ETSI TS 102 894-2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from .data_model import MessageType, V2xMessage

class MovementPhaseState(Enum):
    """SAE J2735 MovementPhaseState."""
    UNAVAILABLE = "unavailable"
    DARK = "dark"
    STOP_THEN_PROCEED = "stop-Then-Proceed"
    STOP_AND_REMAIN = "stop-And-Remain"
    PRE_MOVEMENT = "pre-Movement"
    PERMISSIVE_MOVEMENT_ALLOWED = "permissive-Movement-Allowed"
    PROTECTED_MOVEMENT_ALLOWED = "protected-Movement-Allowed"
    PERMISSIVE_CLEARANCE = "permissive-clearance"
    PROTECTED_CLEARANCE = "protected-clearance"
    CAUTION_CONFLICTING_TRAFFIC = "caution-Conflicting-Traffic"


class ForecastConfidence(Enum):
    """Mapped from ETSI TS 103 301 timeConfidence."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SignalGroupState:
    """Current state of one signal group within an intersection."""
    signal_group_id: int
    phase: MovementPhaseState
    min_end_time: Optional[datetime] = None
    max_end_time: Optional[datetime] = None
    likely_time: Optional[datetime] = None
    time_confidence: Optional[ForecastConfidence] = None


@dataclass
class PhaseSegment:
    """One contiguous forecast segment for a signal group."""
    phase: MovementPhaseState
    start: datetime
    end: datetime
    confidence: ForecastConfidence


@dataclass
class SpatForecast:
    """Phase segments for the next ~30 s per signal group."""
    intersection_id: int
    horizon_seconds: float
    segments_by_group: dict[int, list[PhaseSegment]] = field(default_factory=dict)


@dataclass
class IntersectionState:
    """MAP + latest SPaT for one intersection."""
    intersection_id: int
    map_revision: Optional[int] = None
    spat_revision: Optional[int] = None
    last_map_time: Optional[datetime] = None
    last_spat_time: Optional[datetime] = None
    map_reference_point: Optional[tuple[float, float]] = None
    clock_skew_seconds: Optional[float] = None
    signal_groups: dict[int, SignalGroupState] = field(default_factory=dict)

    @property
    def revision_mismatch(self) -> bool:
        """True when MAP and SPaT reference different revisions."""
        if self.map_revision is None or self.spat_revision is None:
            return False
        return self.map_revision != self.spat_revision


@dataclass
class ActiveRequest:
    """A tracked SREM, optionally correlated with its SSEM response."""
    request_id: int
    sequence_number: int
    intersection_id: int
    station_id: str
    importance_level: Optional[int] = None
    requestor_role: Optional[str] = None
    in_lane: Optional[int] = None
    out_lane: Optional[int] = None
    eta: Optional[datetime] = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    responded_at: Optional[datetime] = None
    ssem_status: Optional[str] = None

    @property
    def is_pending(self) -> bool:
        return self.responded_at is None


@dataclass
class SceneSnapshot:
    """Everything the visualization assistant needs at one timeline position."""
    timeline_position: datetime
    intersections: dict[int, IntersectionState] = field(default_factory=dict)
    forecasts: dict[int, SpatForecast] = field(default_factory=dict)
    active_requests: list[ActiveRequest] = field(default_factory=list)
    eta_verifications: list["EtaVerification"] = field(default_factory=list)


@dataclass
class EtaVerification:
    """Predicted-vs-actual arrival timing for one SREM request."""
    request_id: int
    sequence_number: int
    intersection_id: int
    station_id: str
    predicted_eta: datetime
    actual_arrival: datetime
    delta_seconds: float

    @property
    def is_accurate(self) -> bool:
        """Whether the ETA error stays within a 2-second operator tolerance."""
        return abs(self.delta_seconds) <= 2.0


# -----------------------------------------------------------------------------
# Business-logic decisions left for the user (Learning Mode)
# -----------------------------------------------------------------------------

# Phase-Klassifikation nach SAE J2735 MovementPhaseState.
# "Movement allowed" = Fahrzeug darf fahren (inkl. permissive = Gegenverkehr moeglich).
_MOVEMENT_ALLOWED_PHASES = frozenset({
    MovementPhaseState.PERMISSIVE_MOVEMENT_ALLOWED,
    MovementPhaseState.PROTECTED_MOVEMENT_ALLOWED,
})

# Priorisierter Timeout nach ETSI TS 103 301 importanceLevel (0..14).
# Hintergrund: Rettungs-/OEPV-Prioritaeten (>=10) sind zeitkritisch, deshalb striktere Frist.
_TIMEOUT_HIGH_PRIORITY_S = 0.5
_TIMEOUT_DEFAULT_S = 1.0
_HIGH_PRIORITY_THRESHOLD = 10
_FALLBACK_INTERSECTION_RADIUS_M = 250.0


def find_overdue_requests(
    requests: list[ActiveRequest],
    now: datetime,
) -> list[ActiveRequest]:
    """Return all pending requests whose SSEM response is overdue.

    Priority-tiered: importanceLevel >= 10 gets 500 ms, others 1000 ms.
    """
    overdue = []
    for req in requests:
        if not req.is_pending:
            continue
        threshold = (
            _TIMEOUT_HIGH_PRIORITY_S
            if req.importance_level is not None
            and req.importance_level >= _HIGH_PRIORITY_THRESHOLD
            else _TIMEOUT_DEFAULT_S
        )
        if (now - req.requested_at).total_seconds() > threshold:
            overdue.append(req)
    return overdue


def is_flow_allowed(
    scene: SceneSnapshot,
    intersection_id: int,
    ingress_lane: int,
    egress_lane: int,
    ingress_signal_group: int,
) -> tuple[bool, Optional[datetime], Optional[ForecastConfidence]]:
    """Check whether the ingress-to-egress flow is currently allowed.

    Returns (is_allowed_now, estimated_release_time, confidence).
    The MAPEM-derived ingress_signal_group must be supplied by the caller;
    scene_model deliberately stays free of MAP lane-connectivity logic.
    """
    isec = scene.intersections.get(intersection_id)
    if isec is None:
        return (False, None, None)

    sg = isec.signal_groups.get(ingress_signal_group)
    if sg is None:
        return (False, None, None)

    if sg.phase in _MOVEMENT_ALLOWED_PHASES:
        return (True, None, sg.time_confidence)

    forecast = scene.forecasts.get(intersection_id)
    if forecast is None:
        return (False, None, None)

    for seg in forecast.segments_by_group.get(ingress_signal_group, []):
        if seg.phase in _MOVEMENT_ALLOWED_PHASES and seg.start >= scene.timeline_position:
            return (False, seg.start, seg.confidence)

    return (False, None, None)


def build_scene_snapshot(
    messages: list[V2xMessage],
    timeline_position: datetime,
    horizon_seconds: float = 30.0,
) -> SceneSnapshot:
    """Aggregate messages up to one timeline position into a scene snapshot."""
    intersections: dict[int, IntersectionState] = {}
    forecasts: dict[int, SpatForecast] = {}
    requests: dict[tuple[int, int, int], ActiveRequest] = {}
    eta_verifications: list[EtaVerification] = []
    cam_history: dict[str, list[V2xMessage]] = {}

    for msg in messages:
        if msg.timestamp > timeline_position:
            break

        if msg.msg_type == MessageType.CAM:
            cam_history.setdefault(msg.station_id, []).append(msg)
        elif msg.msg_type == MessageType.MAPEM:
            raw_intersections = _iter_map_intersections(msg)
            if not raw_intersections:
                raw_intersections = [_fallback_intersection_from_message(msg)]
            for intersection in raw_intersections:
                intersection_id = _ensure_intersection_id(intersections, intersection, msg)
                state = intersections.setdefault(
                    intersection_id,
                    IntersectionState(intersection_id=intersection_id),
                )
                state.map_revision = _coerce_int(intersection.get("revision"))
                state.last_map_time = msg.timestamp
                state.map_reference_point = _extract_map_reference_point(intersection)
        elif msg.msg_type == MessageType.SPATEM:
            raw_intersections = _iter_spat_intersections(msg)
            if not raw_intersections:
                raw_intersections = [_fallback_intersection_from_message(msg)]
            for intersection in raw_intersections:
                intersection_id = _ensure_intersection_id(intersections, intersection, msg)
                state = intersections.setdefault(
                    intersection_id,
                    IntersectionState(intersection_id=intersection_id),
                )
                state.spat_revision = _coerce_int(intersection.get("revision"))
                state.last_spat_time = msg.timestamp
                state.clock_skew_seconds = _estimate_spat_clock_skew_seconds(
                    packet_timestamp=msg.timestamp,
                    intersection=intersection,
                )
                state.signal_groups = _build_signal_group_states(
                    intersection,
                    base_time=msg.timestamp,
                    horizon_seconds=horizon_seconds,
                )
                forecast = _build_spat_forecast(
                    intersection_id=intersection_id,
                    intersection=intersection,
                    base_time=msg.timestamp,
                    horizon_seconds=horizon_seconds,
                )
                if forecast.segments_by_group:
                    forecasts[intersection_id] = forecast
        elif msg.msg_type == MessageType.SREM:
            request = _build_active_request(msg)
            if request is None:
                continue
            requests[(request.intersection_id, request.request_id, request.sequence_number)] = request

        elif msg.msg_type == MessageType.SSEM:
            response = _extract_ssem_response(msg)
            if response is None:
                continue
            request = requests.get(
                (response["intersection_id"], response["request_id"], response["sequence_number"])
            )
            if request is None:
                continue
            request.responded_at = msg.timestamp
            request.ssem_status = response["status"]

    for request in requests.values():
        verification = _verify_eta_against_cam(
            request=request,
            intersection=intersections.get(request.intersection_id),
            cam_history=cam_history.get(request.station_id, []),
        )
        if verification is not None:
            eta_verifications.append(verification)

    active_requests = [request for request in requests.values() if request.is_pending]
    active_requests.sort(key=lambda request: request.requested_at)
    return SceneSnapshot(
        timeline_position=timeline_position,
        intersections=intersections,
        forecasts=forecasts,
        active_requests=active_requests,
        eta_verifications=eta_verifications,
    )


def _iter_map_intersections(msg: V2xMessage) -> list[dict]:
    """Return normalized MAPEM intersections from decoded_data."""
    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list):
        return [entry for entry in intersections if isinstance(entry, dict)]
    return []


def _iter_spat_intersections(msg: V2xMessage) -> list[dict]:
    """Return normalized SPATEM intersections from decoded_data."""
    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list):
        return [entry for entry in intersections if isinstance(entry, dict)]
    return []


def _extract_intersection_id(intersection: dict) -> Optional[int]:
    """Extract the numeric intersection id from a MAPEM/SPATEM entry."""
    return _coerce_int(intersection.get("intersectionId", intersection.get("id")))


def _fallback_intersection_from_message(msg: V2xMessage) -> dict:
    """Create a minimal intersection structure from raw MAP/SPAT message position."""
    return {
        "referencePosition": {
            "latitude": int(msg.latitude * 1e7),
            "longitude": int(msg.longitude * 1e7),
        },
        "_fallback_station_id": msg.station_id,
    }


def _build_signal_group_states(
    intersection: dict,
    *,
    base_time: datetime,
    horizon_seconds: float,
) -> dict[int, SignalGroupState]:
    """Convert a SPAT intersection payload into current signal group states."""
    states: dict[int, SignalGroupState] = {}
    for signal_group in _iter_signal_group_entries(intersection):
        signal_group_id = _coerce_int(signal_group.get("signalGroup"))
        if signal_group_id is None:
            continue
        phases = _extract_phase_segments(
            signal_group,
            base_time=base_time,
            horizon_seconds=horizon_seconds,
        )
        if not phases:
            continue
        current = phases[0]
        states[signal_group_id] = SignalGroupState(
            signal_group_id=signal_group_id,
            phase=current.phase,
            min_end_time=current.end,
            max_end_time=current.end,
            likely_time=current.end,
            time_confidence=current.confidence,
        )
    return states


def _build_spat_forecast(
    *,
    intersection_id: int,
    intersection: dict,
    base_time: datetime,
    horizon_seconds: float,
) -> SpatForecast:
    """Convert a SPAT intersection payload into a forecast object."""
    segments_by_group: dict[int, list[PhaseSegment]] = {}
    for signal_group in _iter_signal_group_entries(intersection):
        signal_group_id = _coerce_int(signal_group.get("signalGroup"))
        if signal_group_id is None:
            continue
        segments = _extract_phase_segments(
            signal_group,
            base_time=base_time,
            horizon_seconds=horizon_seconds,
        )
        if segments:
            segments_by_group[signal_group_id] = segments
    return SpatForecast(
        intersection_id=intersection_id,
        horizon_seconds=horizon_seconds,
        segments_by_group=segments_by_group,
    )


def _iter_signal_group_entries(intersection: dict) -> list[dict]:
    """Return SPAT signal group state entries in a tolerant way."""
    states = intersection.get("states")
    if isinstance(states, list):
        return [entry for entry in states if isinstance(entry, dict)]
    signal_groups = intersection.get("signalGroups")
    if isinstance(signal_groups, list):
        return [entry for entry in signal_groups if isinstance(entry, dict)]
    return []


def _extract_phase_segments(
    signal_group: dict,
    *,
    base_time: datetime,
    horizon_seconds: float,
) -> list[PhaseSegment]:
    """Build forecast segments from a signal group's movement events."""
    segments: list[PhaseSegment] = []
    cursor = base_time
    events = signal_group.get("stateTimeSpeed") or signal_group.get("state-time-speed") or []
    if not isinstance(events, list):
        return []

    for event in events:
        if not isinstance(event, dict):
            continue
        phase = _parse_phase(event.get("eventState"))
        if phase is None:
            continue
        timing = event.get("timing") if isinstance(event.get("timing"), dict) else {}
        end_seconds = _first_number(
            timing.get("likelyTime"),
            timing.get("minEndTime"),
            timing.get("maxEndTime"),
        )
        if end_seconds is None:
            end = cursor
        else:
            end = base_time + timedelta(seconds=end_seconds / 10.0)

        horizon_end = base_time + timedelta(seconds=horizon_seconds)
        if end > horizon_end:
            end = horizon_end
        if end < cursor:
            end = cursor

        confidence = _map_time_confidence(timing.get("timeConfidence"))
        segments.append(PhaseSegment(phase=phase, start=cursor, end=end, confidence=confidence))
        cursor = end
        if cursor >= horizon_end:
            break

    return segments


def _build_active_request(msg: V2xMessage) -> Optional[ActiveRequest]:
    """Create an ActiveRequest from an SREM message."""
    request_id = _coerce_int(msg.decoded_data.get("requestId"))
    sequence_number = _coerce_int(msg.decoded_data.get("sequenceNumber"))
    intersection_id = _coerce_int(msg.decoded_data.get("intersectionId"))
    if request_id is None or sequence_number is None or intersection_id is None:
        return None

    return ActiveRequest(
        request_id=request_id,
        sequence_number=sequence_number,
        intersection_id=intersection_id,
        station_id=msg.station_id,
        importance_level=_coerce_int(msg.decoded_data.get("importanceLevel")),
        requestor_role=_coerce_str(msg.decoded_data.get("requestorType")),
        in_lane=_coerce_int(msg.decoded_data.get("inLane")),
        out_lane=_coerce_int(msg.decoded_data.get("outLane")),
        eta=_coerce_datetime(msg.decoded_data.get("eta"), reference_time=msg.timestamp),
        requested_at=msg.timestamp,
    )


def _extract_ssem_response(msg: V2xMessage) -> Optional[dict[str, int | str]]:
    """Extract SSEM correlation data."""
    request_id = _coerce_int(msg.decoded_data.get("requestId"))
    sequence_number = _coerce_int(msg.decoded_data.get("sequenceNumber"))
    intersection_id = _coerce_int(msg.decoded_data.get("intersectionId"))
    status = _coerce_str(msg.decoded_data.get("requestState"))
    if (
        request_id is None
        or sequence_number is None
        or intersection_id is None
        or status is None
    ):
        return None
    return {
        "request_id": request_id,
        "sequence_number": sequence_number,
        "intersection_id": intersection_id,
        "status": status,
    }


def _parse_phase(value: object) -> Optional[MovementPhaseState]:
    """Parse a raw SPAT eventState into the enum used by the app."""
    if isinstance(value, MovementPhaseState):
        return value
    if not isinstance(value, str):
        return None
    for phase in MovementPhaseState:
        if phase.value == value:
            return phase
    return None


def _map_time_confidence(value: object) -> ForecastConfidence:
    """Map ETSI/SPAT time confidence to the app's coarse confidence levels."""
    numeric = _coerce_int(value)
    if numeric is not None:
        if numeric <= 10:
            return ForecastConfidence.HIGH
        if numeric <= 40:
            return ForecastConfidence.MEDIUM
        return ForecastConfidence.LOW

    if isinstance(value, str):
        token = value.lower()
        if "low" in token:
            return ForecastConfidence.LOW
        if "medium" in token:
            return ForecastConfidence.MEDIUM
        if "high" in token:
            return ForecastConfidence.HIGH
    return ForecastConfidence.MEDIUM


def _first_number(*values: object) -> Optional[float]:
    """Return the first value that can be interpreted as a number."""
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def get_clock_skew_warnings(
    scene: SceneSnapshot,
    threshold_seconds: float = 2.0,
) -> list[tuple[int, float]]:
    """Return intersections whose SPAT clock skew exceeds the threshold."""
    warnings: list[tuple[int, float]] = []
    for intersection in scene.intersections.values():
        if intersection.clock_skew_seconds is None:
            continue
        if abs(intersection.clock_skew_seconds) >= threshold_seconds:
            warnings.append((intersection.intersection_id, intersection.clock_skew_seconds))
    return warnings


def get_eta_accuracy_seconds(scene: SceneSnapshot) -> Optional[float]:
    """Return mean absolute ETA error across all verified requests."""
    if not scene.eta_verifications:
        return None
    return sum(abs(item.delta_seconds) for item in scene.eta_verifications) / len(scene.eta_verifications)


def _estimate_spat_clock_skew_seconds(
    *,
    packet_timestamp: datetime,
    intersection: dict,
) -> Optional[float]:
    """Compare DSRC/SPAT time-of-year against the PCAP timestamp."""
    moy = _coerce_int(intersection.get("moy"))
    timestamp_ms = _coerce_int(intersection.get("timeStamp"))
    if moy is None or timestamp_ms is None:
        return None

    packet_utc = packet_timestamp.astimezone(timezone.utc)
    seconds_of_year = (
        (packet_utc.timetuple().tm_yday - 1) * 86400
        + packet_utc.hour * 3600
        + packet_utc.minute * 60
        + packet_utc.second
        + packet_utc.microsecond / 1_000_000.0
    )
    dsrc_seconds_of_year = (moy * 60.0) + (timestamp_ms / 1000.0)
    year_seconds = 366 * 86400 if _is_leap_year(packet_utc.year) else 365 * 86400
    diff = dsrc_seconds_of_year - seconds_of_year
    if diff > year_seconds / 2:
        diff -= year_seconds
    elif diff < -(year_seconds / 2):
        diff += year_seconds
    return diff


def _extract_map_reference_point(intersection: dict) -> Optional[tuple[float, float]]:
    """Extract a normalized MAP reference point in decimal degrees."""
    for key in ("refPoint", "referencePoint", "refPos", "referencePosition"):
        value = intersection.get(key)
        point = _coerce_lat_lon(value)
        if point is not None:
            return point
    return None


def _ensure_intersection_id(
    intersections: dict[int, IntersectionState],
    intersection: dict,
    msg: V2xMessage,
) -> int:
    """Resolve or synthesize an intersection id for decoded or raw infrastructure messages."""
    decoded_id = _extract_intersection_id(intersection)
    if decoded_id is not None:
        return decoded_id

    reference_point = _extract_map_reference_point(intersection)
    if reference_point is None:
        reference_point = (msg.latitude, msg.longitude)

    for existing_id, existing_state in intersections.items():
        if existing_state.map_reference_point is None:
            continue
        distance = _haversine_meters(
            reference_point[0],
            reference_point[1],
            existing_state.map_reference_point[0],
            existing_state.map_reference_point[1],
        )
        if distance <= _FALLBACK_INTERSECTION_RADIUS_M:
            return existing_id

    rounded_lat = int(round(reference_point[0] * 1000))
    rounded_lon = int(round(reference_point[1] * 1000))
    synthetic_id = -((abs(rounded_lat) * 100000) + abs(rounded_lon))
    while synthetic_id in intersections:
        synthetic_id -= 1
    return synthetic_id


def _verify_eta_against_cam(
    *,
    request: ActiveRequest,
    intersection: Optional[IntersectionState],
    cam_history: list[V2xMessage],
) -> Optional[EtaVerification]:
    """Compare the requested ETA with the first CAM arrival at the intersection."""
    if request.eta is None or intersection is None or intersection.map_reference_point is None:
        return None
    if not cam_history:
        return None

    target_lat, target_lon = intersection.map_reference_point
    arrival: Optional[datetime] = None
    for cam_msg in cam_history:
        if cam_msg.timestamp < request.requested_at:
            continue
        distance_m = _haversine_meters(
            cam_msg.latitude,
            cam_msg.longitude,
            target_lat,
            target_lon,
        )
        if distance_m <= 40.0:
            arrival = cam_msg.timestamp
            break
    if arrival is None:
        return None

    return EtaVerification(
        request_id=request.request_id,
        sequence_number=request.sequence_number,
        intersection_id=request.intersection_id,
        station_id=request.station_id,
        predicted_eta=request.eta,
        actual_arrival=arrival,
        delta_seconds=(arrival - request.eta).total_seconds(),
    )


def _coerce_lat_lon(value: object) -> Optional[tuple[float, float]]:
    """Normalize reference-point structures to decimal degrees."""
    if not isinstance(value, dict):
        return None
    lat = value.get("lat", value.get("latitude"))
    lon = value.get("lon", value.get("longitude"))
    if lat is None or lon is None:
        return None
    try:
        lat_num = float(lat)
        lon_num = float(lon)
    except (TypeError, ValueError):
        return None
    if abs(lat_num) > 90 or abs(lon_num) > 180:
        lat_num /= 1e7
        lon_num /= 1e7
    return (lat_num, lon_num)


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the great-circle distance between two coordinates."""
    from math import asin, cos, radians, sin, sqrt

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    start_lat = radians(lat1)
    end_lat = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(start_lat) * cos(end_lat) * sin(d_lon / 2) ** 2
    c = 2 * asin(min(1.0, sqrt(a)))
    return 6371000.0 * c


def _is_leap_year(year: int) -> bool:
    """Return whether a year is a leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _coerce_int(value: object) -> Optional[int]:
    """Best-effort integer normalization for nested decoded fields."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("id", "lane", "value", "timeStamp"):
            coerced = _coerce_int(value.get(key))
            if coerced is not None:
                return coerced
    return None


def _coerce_str(value: object) -> Optional[str]:
    """Normalize a value to string if it is meaningfully present."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for candidate in value.values():
            coerced = _coerce_str(candidate)
            if coerced:
                return coerced
        return None
    return str(value)


def _coerce_datetime(value: object, *, reference_time: Optional[datetime] = None) -> Optional[datetime]:
    """Normalize ETA-like structures into UTC datetimes when possible."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        if reference_time is not None:
            second_of_minute = _first_number(
                value.get("second"),
                value.get("timeStamp"),
                value.get("millisecond"),
            )
            if second_of_minute is not None:
                if second_of_minute > 60:
                    second_of_minute /= 1000.0
                base = reference_time.astimezone(timezone.utc).replace(second=0, microsecond=0)
                candidate = base + timedelta(seconds=second_of_minute)
                if candidate < reference_time - timedelta(seconds=30):
                    candidate += timedelta(minutes=1)
                return candidate
    return None
