"""MAPEM/SPATEM sanity checks aligned with the C-Roads handbook profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .data_model import MessageType, V2xMessage


@dataclass(frozen=True)
class MapValidationIssue:
    """One MAPEM/SPATEM validation finding."""

    severity: str
    code: str
    message: str
    station_id: str
    intersection_id: int | None = None
    lane_id: int | None = None
    source_summary: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {key: value for key, value in asdict(self).items() if value is not None}


def validate_mapem_spatem(messages: Iterable[V2xMessage]) -> list[MapValidationIssue]:
    """Validate loaded MAPEM/SPATEM data with conservative C-Roads-inspired checks."""
    issues: list[MapValidationIssue] = []
    map_revisions: dict[int, int | None] = {}
    spat_revisions: dict[int, int | None] = {}
    map_signal_groups: dict[int, set[int]] = {}
    spat_signal_groups: dict[int, set[int]] = {}

    for msg in messages:
        if msg.msg_type == MessageType.MAPEM:
            intersections = _iter_intersections(msg)
            if not intersections:
                issues.append(
                    _issue("error", "MAPEM_NO_INTERSECTION", "MAPEM enthaelt keine IntersectionGeometry.", msg)
                )
                continue
            for intersection in intersections:
                iid = _intersection_id(intersection, msg)
                revision = _coerce_int(intersection.get("revision", msg.decoded_data.get("revision")))
                if iid is not None:
                    map_revisions[iid] = revision
                issues.extend(_validate_map_intersection(msg, intersection, iid))
                if iid is not None:
                    map_signal_groups.setdefault(iid, set()).update(_map_signal_groups(intersection))
        elif msg.msg_type == MessageType.SPATEM:
            intersections = _iter_intersections(msg)
            if not intersections:
                issues.append(
                    _issue("error", "SPATEM_NO_INTERSECTION", "SPATEM enthaelt keine IntersectionState.", msg)
                )
                continue
            for intersection in intersections:
                iid = _intersection_id(intersection, msg)
                revision = _coerce_int(intersection.get("revision", msg.decoded_data.get("revision")))
                if iid is not None:
                    spat_revisions[iid] = revision
                issues.extend(_validate_spat_intersection(msg, intersection, iid))
                if iid is not None:
                    spat_signal_groups.setdefault(iid, set()).update(_spat_signal_groups(intersection))

    for iid, map_revision in sorted(map_revisions.items()):
        spat_revision = spat_revisions.get(iid)
        if spat_revision is None:
            issues.append(
                _issue(
                    "info",
                    "SPATEM_MISSING_FOR_MAP",
                    "Keine passende SPATEM in der Sitzung; fuer reine MAP-Pruefung zulaessig.",
                    None,
                    intersection_id=iid,
                )
            )
        elif map_revision is not None and spat_revision != map_revision:
            issues.append(
                _issue(
                    "error",
                    "MAP_SPAT_REVISION_MISMATCH",
                    f"MAPEM/SPATEM Revisionen stimmen nicht ueberein ({map_revision} != {spat_revision}).",
                    None,
                    intersection_id=iid,
                )
            )
    for iid in sorted(set(spat_revisions) - set(map_revisions)):
        issues.append(
            _issue(
                "warning",
                "MAPEM_MISSING_FOR_SPAT",
                "SPATEM verweist auf eine Kreuzung ohne MAPEM in der Sitzung.",
                None,
                intersection_id=iid,
            )
        )
    for iid, signal_groups in sorted(map_signal_groups.items()):
        if iid not in spat_signal_groups or not spat_signal_groups[iid]:
            continue
        missing = sorted(signal_groups - spat_signal_groups[iid])
        if missing:
            issues.append(
                _issue(
                    "warning",
                    "MAP_SIGNALGROUP_NOT_IN_SPAT",
                    "MAPEM nutzt Signalgruppen ohne Entsprechung in SPATEM: " + ", ".join(map(str, missing[:8])),
                    None,
                    intersection_id=iid,
                )
            )

    # SPATEM signal groups not present in MAPEM
    for iid, spat_groups in sorted(spat_signal_groups.items()):
        if iid not in map_signal_groups:
            continue
        missing = sorted(spat_groups - map_signal_groups[iid])
        if missing:
            issues.append(
                _issue(
                    "warning",
                    "SPAT_SIGNALGROUP_NOT_IN_MAP",
                    "SPATEM nutzt Signalgruppen ohne Entsprechung in MAPEM: " + ", ".join(map(str, missing[:8])),
                    None,
                    intersection_id=iid,
                )
            )

    # Additional linking and topology checks
    _check_crosswalk_linking(messages, issues)
    _check_bicycle_lane_linking(messages, issues)
    _check_roundabout_topology(messages, issues)

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(issues, key=lambda item: (severity_rank.get(item.severity, 9), item.code, item.intersection_id or 0))


def validation_summary(issues: Iterable[MapValidationIssue]) -> dict[str, int]:
    """Count validation findings by severity."""
    summary = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        if issue.severity in summary:
            summary[issue.severity] += 1
    return summary


def _validate_map_intersection(
    msg: V2xMessage,
    intersection: dict,
    intersection_id: int | None,
) -> list[MapValidationIssue]:
    issues: list[MapValidationIssue] = []
    if intersection_id is None:
        issues.append(
            _issue("error", "MAP_INTERSECTION_ID_MISSING", "IntersectionGeometry hat keine numerische id.", msg)
        )
    if _coerce_int(intersection.get("revision", msg.decoded_data.get("revision"))) is None:
        issues.append(
            _issue(
                "warning",
                "MAP_REVISION_MISSING",
                "MAPEM IntersectionGeometry hat keine Revision.",
                msg,
                intersection_id,
            )
        )
    if not _valid_ref_point(intersection.get("refPoint"), msg):
        issues.append(
            _issue(
                "error",
                "MAP_REFPOINT_INVALID",
                "IntersectionGeometry hat keinen gueltigen refPoint.",
                msg,
                intersection_id,
            )
        )

    lanes = _lane_set(intersection)
    if not lanes:
        issues.append(
            _issue("error", "MAP_LANESET_EMPTY", "IntersectionGeometry enthaelt kein laneSet.", msg, intersection_id)
        )
        return issues

    # Intersection-level checks
    lane_width = _coerce_int(intersection.get("laneWidth"))
    if lane_width is None:
        issues.append(
            _issue("info", "MAP_LANEWIDTH_MISSING", "IntersectionGeometry hat keine laneWidth.", msg, intersection_id)
        )
    elif lane_width <= 0 or lane_width > 10000:
        issues.append(
            _issue(
                "warning",
                "MAP_LANEWIDTH_UNUSUAL",
                f"laneWidth {lane_width} cm ist ausserhalb des ueblichen Bereichs (10-10000 cm).",
                msg,
                intersection_id,
            )
        )

    # Track which lanes are ingress vs egress for connection validation
    ingress_lanes: set[int] = set()
    egress_lanes: set[int] = set()
    signalized_lanes: set[int] = set()

    seen_lane_ids: set[int] = set()
    for lane in lanes:
        lane_id = _lane_id(lane)
        if lane_id is None:
            issues.append(
                _issue("error", "MAP_LANE_ID_MISSING", "GenericLane hat keine numerische laneID.", msg, intersection_id)
            )
            continue
        if lane_id in seen_lane_ids:
            issues.append(
                _issue(
                    "error",
                    "MAP_LANE_ID_DUPLICATE",
                    f"laneID {lane_id} ist innerhalb der Kreuzung doppelt.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )
        seen_lane_ids.add(lane_id)

        # Lane role detection
        is_ingress = _value(lane, "ingressApproach", "ingressapproach") is not None
        is_egress = _value(lane, "egressApproach", "egressapproach") is not None
        approach_id = _value(lane, "approachID", "approachId")
        if is_ingress:
            ingress_lanes.add(lane_id)
        if is_egress:
            egress_lanes.add(lane_id)
        if approach_id is not None and not (is_ingress or is_egress):
            issues.append(
                _issue(
                    "warning",
                    "MAP_APPROACH_WITHOUT_DIRECTION",
                    f"laneID {lane_id} hat approachID aber weder ingress noch egress Approach.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )

        # NodeList validation
        nodes = _lane_nodes(lane)
        if len(nodes) < 2:
            issues.append(
                _issue(
                    "warning",
                    "MAP_LANE_NODELIST_SHORT",
                    "GenericLane hat weniger als zwei NodeList-Punkte.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )
        elif len(nodes) > 500:
            issues.append(
                _issue(
                    "warning",
                    "MAP_LANE_NODELIST_EXTREMELY_LONG",
                    f"GenericLane hat {len(nodes)} NodeList-Punkte (>500 ist ungewoehnlich).",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )

        # Lane attributes
        lane_attrs = _value(lane, "laneAttributes")
        if lane_attrs is not None:
            _validate_lane_attributes(issues, lane_attrs, lane_id, msg, intersection_id)

        # Maneuvers validation
        maneuvers = _value(lane, "maneuvers", "maneuver")
        if maneuvers is None:
            issues.append(
                _issue(
                    "warning",
                    "MAP_MANEUVERS_MISSING",
                    "GenericLane hat keine maneuvers.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )
        elif not _has_valid_maneuver(maneuvers):
            issues.append(
                _issue(
                    "warning",
                    "MAP_MANEUVERS_INVALID",
                    "GenericLane maneuvers enthalten keine gueltige Bewegungsrichtung.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )

        # Connections and signal groups
        connections = _connections(lane)
        has_signal_group = False
        for connection in connections:
            signal_group = _coerce_int(_value(connection, "signalGroup", "signalgroup"))
            if signal_group is not None:
                has_signal_group = True
                break
        if has_signal_group:
            signalized_lanes.add(lane_id)

        # Stop line check for signalized ingress lanes
        if has_signal_group and is_ingress:
            stop_line = _value(lane, "stopLine")
            if stop_line is None:
                issues.append(
                    _issue(
                        "info",
                        "MAP_STOPLINE_RECOMMENDED",
                        f"Signalisierte ingress lane {lane_id} sollte eine stopLine haben.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )

    lane_ids = {lane_id for lane_id in (_lane_id(lane) for lane in lanes) if lane_id is not None}
    for lane in lanes:
        lane_id = _lane_id(lane)
        connections = _connections(lane)
        for connection in connections:
            target = _connection_lane_id(connection)
            if target is not None and target not in lane_ids:
                issues.append(
                    _issue(
                        "warning",
                        "MAP_CONNECTION_TARGET_UNKNOWN",
                        f"connectsTo verweist auf unbekannte laneID {target}.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
            if _coerce_int(_value(connection, "signalGroup", "signalgroup")) is None:
                issues.append(
                    _issue(
                        "warning",
                        "MAP_CONNECTION_SIGNALGROUP_MISSING",
                        "connectsTo hat keine signalGroup.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
            # Check egress lanes shouldn't have signal groups
            if lane_id is not None and lane_id in egress_lanes:
                if _coerce_int(_value(connection, "signalGroup", "signalgroup")) is not None:
                    issues.append(
                        _issue(
                            "info",
                            "MAP_EGRESS_WITH_SIGNAL_GROUP",
                            f"Egress lane {lane_id} hat signalGroup in connectsTo — typisch nur fuer ingress lanes.",
                            msg,
                            intersection_id,
                            lane_id,
                        )
                    )
    return issues


def _validate_lane_attributes(
    issues: list[MapValidationIssue],
    lane_attrs: dict,
    lane_id: int,
    msg: V2xMessage,
    intersection_id: int | None,
) -> None:
    """Validate laneAttributes per C-Roads handbook section 3.3.2."""
    directional_use = _value(lane_attrs, "directionalUse", "directionaluse")
    if directional_use is None:
        issues.append(
            _issue(
                "warning",
                "MAP_LANE_ATTR_DIRECTIONALUSE_MISSING",
                f"laneAttributes fuer laneID {lane_id} hat keine directionalUse.",
                msg,
                intersection_id,
                lane_id,
            )
        )
    elif isinstance(directional_use, str):
        # Accept both bitstring format ("10", "01", "11") and textual ("forward", "reverse", "both")
        valid_textual = {"forward", "reverse", "both"}
        valid_bitstrings = {"01", "10", "11"}
        if (
            directional_use not in valid_textual
            and directional_use not in valid_bitstrings
            and not _is_valid_directional_bitstring(directional_use)
        ):
            issues.append(
                _issue(
                    "warning",
                    "MAP_LANE_ATTR_DIRECTIONALUSE_INVALID",
                    f"laneAttributes.directionalUse='{directional_use}' ist weder gueltiger Bitstring noch erwarteter Textwert.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )
    elif isinstance(directional_use, int):
        # Integer bitstring: bit1=ingress, bit0=egress. Valid: 1(01), 2(10), 3(11)
        if directional_use not in (1, 2, 3, 10, 5, 6, 7, 11, 12, 13, 14):
            # Accept any 2-bit value or common extended values
            if directional_use > 3:
                issues.append(
                    _issue(
                        "info",
                        "MAP_LANE_ATTR_DIRECTIONALUSE_EXTENDED",
                        f"laneAttributes.directionalUse={directional_use} (erweiterte Bitkodierung).",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
            else:
                issues.append(
                    _issue(
                        "warning",
                        "MAP_LANE_ATTR_DIRECTIONALUSE_INVALID",
                        f"laneAttributes.directionalUse={directional_use} unerwartet (erwartet: 1=egress, 2=ingress, 3=both).",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )

    lane_type = _value(lane_attrs, "laneType", "lanetype")
    if lane_type is None:
        issues.append(
            _issue(
                "warning",
                "MAP_LANE_ATTR_LANETYPE_MISSING",
                f"laneAttributes fuer laneID {lane_id} hat keinen laneType.",
                msg,
                intersection_id,
                lane_id,
            )
        )
    elif isinstance(lane_type, str):
        valid_lane_types = {
            "vehicle",
            "crosswalk",
            "bikeLane",
            "bikeway",
            "hikingTrail",
            "median",
            "striping",
            "trackedVehicle",
            "parking",
            "sidewalk",
            "shoulder",
        }
        if lane_type not in valid_lane_types:
            issues.append(
                _issue(
                    "info",
                    "MAP_LANE_ATTR_LANETYPE_UNUSUAL",
                    f"laneAttributes.laneType='{lane_type}' ist kein ueblicher Wert.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )
    elif isinstance(lane_type, dict):
        # ASN.1 CHOICE as dict, e.g. {"bikeLane": 0}, {"vehicle": "00000000"}
        keys = list(lane_type.keys())
        if len(keys) == 1:
            lane_type_name = keys[0]
            valid_lane_type_names = {
                "vehicle",
                "crosswalk",
                "crosswalkLane",
                "bikeLane",
                "bikeway",
                "hikingTrail",
                "median",
                "medianLane",
                "striping",
                "stripingLane",
                "trackedVehicle",
                "parking",
                "parkingLane",
                "sidewalk",
                "shoulder",
            }
            if lane_type_name not in valid_lane_type_names:
                issues.append(
                    _issue(
                        "info",
                        "MAP_LANE_ATTR_LANETYPE_UNUSUAL",
                        f"laneAttributes.laneType hat unerwartete CHOICE '{lane_type_name}'.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
        else:
            issues.append(
                _issue(
                    "warning",
                    "MAP_LANE_ATTR_LANETYPE_INVALID",
                    f"laneAttributes.laneType hat ungueltige Struktur.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )

    shared_with = _value(lane_attrs, "sharedWith", "sharedwith")
    if shared_with is not None:
        if isinstance(shared_with, str):
            if len(shared_with) > 10:
                issues.append(
                    _issue(
                        "info",
                        "MAP_LANE_ATTR_SHAREDWITH_LONG",
                        f"laneAttributes.sharedWith='{shared_with}' ist ein langer Bitstring.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
        elif isinstance(shared_with, int):
            if shared_with < 0 or shared_with > 1023:
                issues.append(
                    _issue(
                        "warning",
                        "MAP_LANE_ATTR_SHAREDWITH_INVALID",
                        f"laneAttributes.sharedWith={shared_with} unerwartet.",
                        msg,
                        intersection_id,
                        lane_id,
                    )
                )
        else:
            issues.append(
                _issue(
                    "info",
                    "MAP_LANE_ATTR_SHAREDWITH_INVALID_TYPE",
                    f"laneAttributes.sharedWith hat unerwarteten Typ.",
                    msg,
                    intersection_id,
                    lane_id,
                )
            )


def _has_valid_maneuver(maneuvers: object) -> bool:
    """Check if maneuvers contains at least one valid movement."""
    if maneuvers is None:
        return False
    valid = {
        "maneuverStraightAllowed",
        "maneuverLeftAllowed",
        "maneuverRightAllowed",
        "maneuverUTurnAllowed",
        "maneuverLeftTurnOnRedAllowed",
    }
    if isinstance(maneuvers, dict):
        for key in valid:
            if maneuvers.get(key) is True:
                return True
    elif isinstance(maneuvers, str):
        for val in valid:
            if val in maneuvers or val.replace("Allowed", "").replace("maneuver", "") in maneuvers:
                return True
        # Check for bitstring "100000000000" style
        if maneuvers == "100000000000" or maneuvers == "001000000000":
            return True
    elif isinstance(maneuvers, (list, tuple)):
        for m in maneuvers:
            if isinstance(m, str):
                for val in valid:
                    if val in m or val.replace("Allowed", "").replace("maneuver", "") in m:
                        return True
                if m in ("100000000000", "001000000000"):
                    return True
            elif isinstance(m, dict):
                for key in valid:
                    if m.get(key) is True:
                        return True
    return False


def _is_valid_directional_bitstring(value: str) -> bool:
    """Check if directionalUse is a valid 2-bit string per ASN.1."""
    return len(value) == 2 and all(c in "01" for c in value)


def _validate_spat_intersection(
    msg: V2xMessage,
    intersection: dict,
    intersection_id: int | None,
) -> list[MapValidationIssue]:
    issues: list[MapValidationIssue] = []
    if intersection_id is None:
        issues.append(
            _issue("error", "SPAT_INTERSECTION_ID_MISSING", "IntersectionState hat keine numerische id.", msg)
        )
    if _coerce_int(intersection.get("revision", msg.decoded_data.get("revision"))) is None:
        issues.append(
            _issue(
                "warning", "SPAT_REVISION_MISSING", "SPATEM IntersectionState hat keine Revision.", msg, intersection_id
            )
        )
    groups = _spat_state_entries(intersection)
    if not groups:
        issues.append(
            _issue("error", "SPAT_STATES_EMPTY", "SPATEM enthaelt keine Signalgruppen-States.", msg, intersection_id)
        )
    for group in groups:
        signal_group = _coerce_int(_value(group, "signalGroup", "signalgroup"))
        if signal_group is None:
            issues.append(
                _issue("error", "SPAT_SIGNALGROUP_MISSING", "SPATEM State hat keine signalGroup.", msg, intersection_id)
            )
        events = _as_list(_value(group, "stateTimeSpeed", "events", "eventState", "states"))
        if not events:
            issues.append(
                _issue(
                    "warning",
                    "SPAT_EVENTSTATE_MISSING",
                    "SPATEM State hat keine auswertbare eventState/stateTimeSpeed.",
                    msg,
                    intersection_id,
                )
            )
            continue
        for event in events:
            if isinstance(event, dict):
                _validate_spat_timing(issues, event, signal_group, msg, intersection_id)
    return issues


def _validate_spat_timing(
    issues: list[MapValidationIssue],
    event: dict,
    signal_group: int | None,
    msg: V2xMessage,
    intersection_id: int | None,
) -> None:
    """Validate timing fields per C-Roads Handbook §5.7.4."""
    timing = _value(event, "timing")
    if timing is None:
        issues.append(
            _issue(
                "info",
                "SPAT_TIMING_MISSING",
                f"SPATEM event fuer signalGroup {signal_group} hat kein timing-Element.",
                msg,
                intersection_id,
            )
        )
        return
    if not isinstance(timing, dict):
        return

    min_end = _coerce_int(_value(timing, "minEndTime"))
    max_end = _coerce_int(_value(timing, "maxEndTime"))
    likely = _coerce_int(_value(timing, "likelyTime"))
    next_time = _coerce_int(_value(timing, "nextTime"))
    confidence = _coerce_int(_value(timing, "confidence"))
    start_time = _coerce_int(_value(timing, "startTime"))

    # Range checks (ETSI DSecond / TimeMark: 0-36000 seconds typical)
    if start_time is not None and (start_time < 0 or start_time > 36000):
        issues.append(
            _issue(
                "warning",
                "SPAT_STARTTIME_UNUSUAL",
                f"SPATEM startTime={start_time} ausserhalb typischer Range.",
                msg,
                intersection_id,
            )
        )
    if min_end is not None and (min_end < 0 or min_end > 36000):
        issues.append(
            _issue(
                "warning",
                "SPAT_MINENDTIME_UNUSUAL",
                f"SPATEM minEndTime={min_end} ausserhalb typischer Range.",
                msg,
                intersection_id,
            )
        )
    if max_end is not None and (max_end < 0 or max_end > 36000):
        issues.append(
            _issue(
                "warning",
                "SPAT_MAXENDTIME_UNUSUAL",
                f"SPATEM maxEndTime={max_end} ausserhalb typischer Range.",
                msg,
                intersection_id,
            )
        )
    if likely is not None and (likely < 0 or likely > 36000):
        issues.append(
            _issue(
                "warning",
                "SPAT_LIKELYTIME_UNUSUAL",
                f"SPATEM likelyTime={likely} ausserhalb typischer Range.",
                msg,
                intersection_id,
            )
        )
    if next_time is not None and (next_time < 0 or next_time > 36000):
        issues.append(
            _issue(
                "warning",
                "SPAT_NEXTTIME_UNUSUAL",
                f"SPATEM nextTime={next_time} ausserhalb typischer Range.",
                msg,
                intersection_id,
            )
        )

    # Consistency checks
    if min_end is not None and max_end is not None and min_end > max_end:
        issues.append(
            _issue(
                "error",
                "SPAT_MINENDTIME_AFTER_MAX",
                f"SPATEM minEndTime({min_end}) > maxEndTime({max_end}).",
                msg,
                intersection_id,
            )
        )
    if max_end is not None and min_end is None:
        issues.append(
            _issue(
                "warning",
                "SPAT_MAXEND_WITHOUT_MINEND",
                "SPATEM hat maxEndTime ohne minEndTime.",
                msg,
                intersection_id,
            )
        )
    if likely is not None and min_end is not None and likely < min_end:
        issues.append(
            _issue(
                "warning",
                "SPAT_LIKELYTIME_BEFORE_MINEND",
                f"SPATEM likelyTime={likely} < minEndTime={min_end}.",
                msg,
                intersection_id,
            )
        )
    if next_time is not None and max_end is not None and next_time < max_end:
        issues.append(
            _issue(
                "warning",
                "SPAT_NEXTTIME_BEFORE_MAXEND",
                f"SPATEM nextTime={next_time} < maxEndTime={max_end}.",
                msg,
                intersection_id,
            )
        )

    # Confidence
    if confidence is None:
        issues.append(
            _issue(
                "info",
                "SPAT_CONFIDENCE_MISSING",
                f"SPATEM timing fuer signalGroup {signal_group} hat keine confidence.",
                msg,
                intersection_id,
            )
        )
    elif confidence < 0 or confidence > 7:
        issues.append(
            _issue(
                "warning",
                "SPAT_CONFIDENCE_INVALID",
                f"SPATEM confidence={confidence} (gueltig: 0-7).",
                msg,
                intersection_id,
            )
        )
    elif confidence == 0:
        issues.append(
            _issue(
                "info",
                "SPAT_CONFIDENCE_UNAVAILABLE",
                f"SPATEM confidence=0 (unavailable) fuer signalGroup {signal_group}.",
                msg,
                intersection_id,
            )
        )
    elif confidence < 3:
        issues.append(
            _issue(
                "info",
                "SPAT_CONFIDENCE_LOW",
                f"SPATEM confidence={confidence} fuer signalGroup {signal_group} niedrig.",
                msg,
                intersection_id,
            )
        )


def _issue(
    severity: str,
    code: str,
    message: str,
    msg: V2xMessage | None,
    intersection_id: int | None = None,
    lane_id: int | None = None,
) -> MapValidationIssue:
    source_summary = None
    station_id = "session"
    if msg is not None:
        station_id = msg.station_id
        source_summary = msg.source.display_name() if msg.source is not None else msg.timestamp.isoformat()
    return MapValidationIssue(severity, code, message, station_id, intersection_id, lane_id, source_summary)


def _iter_intersections(msg: V2xMessage) -> list[dict]:
    intersections = msg.decoded_data.get("intersections")
    if isinstance(intersections, list):
        return [entry for entry in intersections if isinstance(entry, dict)]
    return []


def _intersection_id(intersection: dict, msg: V2xMessage) -> int | None:
    return _coerce_int(
        intersection.get("intersectionId", intersection.get("id", msg.decoded_data.get("intersectionId")))
    )


def _lane_set(intersection: dict) -> list[dict]:
    lanes = _value(intersection, "laneSet", "lanes")
    return [lane for lane in _as_list(lanes) if isinstance(lane, dict)]


def _lane_id(lane: dict) -> int | None:
    return _coerce_int(_value(lane, "laneID", "laneId", "id"))


def _lane_nodes(lane: dict) -> list[object]:
    node_list = _value(lane, "nodeList", "node-list")
    if isinstance(node_list, dict):
        return _as_list(_value(node_list, "nodes", "nodeSetXY", "nodeSet"))
    return _as_list(node_list)


def _has_lane_role(lane: dict) -> bool:
    keys = {
        "ingressApproach",
        "egressApproach",
        "approachID",
        "approachId",
        "laneAttributes",
        "directionalUse",
        "maneuvers",
    }
    return any(_value(lane, key) not in (None, "", [], {}) for key in keys)


def _connections(lane: dict) -> list[dict]:
    connects_to = _value(lane, "connectsTo", "connectsto", "connections")
    if isinstance(connects_to, dict):
        connects_to = _value(connects_to, "connections", "connectsTo", "connectsto")
    return [connection for connection in _as_list(connects_to) if isinstance(connection, dict)]


def _connection_lane_id(connection: dict) -> int | None:
    connecting_lane = _value(connection, "connectingLane", "lane", "laneID", "laneId")
    if isinstance(connecting_lane, dict):
        return _coerce_int(_value(connecting_lane, "lane", "laneID", "laneId", "id"))
    return _coerce_int(connecting_lane)


def _map_signal_groups(intersection: dict) -> set[int]:
    signal_groups: set[int] = set()
    for lane in _lane_set(intersection):
        for connection in _connections(lane):
            signal_group = _coerce_int(_value(connection, "signalGroup", "signalgroup"))
            if signal_group is not None:
                signal_groups.add(signal_group)
    return signal_groups


def _spat_signal_groups(intersection: dict) -> set[int]:
    signal_groups: set[int] = set()
    for group in _spat_state_entries(intersection):
        signal_group = _coerce_int(_value(group, "signalGroup", "signalgroup"))
        if signal_group is not None:
            signal_groups.add(signal_group)
    return signal_groups


def _spat_state_entries(intersection: dict) -> list[dict]:
    states = _value(intersection, "states", "signalGroups", "state")
    if isinstance(states, dict):
        states = _value(states, "states", "signalGroups", "state")
    return [entry for entry in _as_list(states) if isinstance(entry, dict)]


def _valid_ref_point(point: object, msg: V2xMessage) -> bool:
    if isinstance(point, dict) and _valid_lat_lon(
        _value(point, "lat", "latitude"), _value(point, "lon", "long", "longitude")
    ):
        return True
    return False


def _valid_lat_lon(lat: object, lon: object) -> bool:
    try:
        lat_num = float(lat)
        lon_num = float(lon)
    except (TypeError, ValueError):
        return False
    if abs(lat_num) > 90 or abs(lon_num) > 180:
        lat_num /= 1e7
        lon_num /= 1e7
    return -90 <= lat_num <= 90 and -180 <= lon_num <= 180


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _value(mapping: object, *keys: str) -> object:
    if not isinstance(mapping, dict):
        return None
    lowered = {str(key).replace("_", "").replace("-", "").lower(): value for key, value in mapping.items()}
    for key in keys:
        token = key.replace("_", "").replace("-", "").lower()
        if token in lowered:
            return lowered[token]
    return None


def _coerce_int(value: object) -> int | None:
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
        for key in ("id", "value", "lane", "signalGroup", "intersectionId"):
            nested = _coerce_int(value.get(key))
            if nested is not None:
                return nested
    return None


def _check_crosswalk_linking(
    messages: Iterable[V2xMessage],
    issues: list[MapValidationIssue],
) -> None:
    """Per C-Roads Handbook §4.6: Crosswalks should connect to ingress/egress vehicle lanes."""
    for msg in messages:
        if msg.msg_type != MessageType.MAPEM:
            continue
        for intersection in _iter_intersections(msg):
            iid = _intersection_id(intersection, msg)
            lanes = _lane_set(intersection)
            lane_ids = {}
            for lane in lanes:
                lid = _lane_id(lane)
                if lid is not None:
                    attrs = _value(lane, "laneAttributes")
                    ltype = _value(attrs, "laneType", "lanetype") if isinstance(attrs, dict) else None
                    lane_ids[lid] = ltype

            for lane in lanes:
                lid = _lane_id(lane)
                if lid is None:
                    continue
                attrs = _value(lane, "laneAttributes")
                ltype = _value(attrs, "laneType", "lanetype") if isinstance(attrs, dict) else None
                if ltype not in ("crosswalk", "crosswalkLane"):
                    continue
                connections = _connections(lane)
                if not connections:
                    issues.append(
                        _issue(
                            "warning",
                            "CROSSWALK_NO_CONNECTION",
                            f"Crosswalk lane {lid} hat keine connectsTo-Verbindung.",
                            msg,
                            intersection_id=iid,
                            lane_id=lid,
                        )
                    )
                    continue
                for connection in connections:
                    target = _connection_lane_id(connection)
                    if target is not None and target in lane_ids:
                        target_type = lane_ids[target]
                        if target_type in ("crosswalk", "crosswalkLane"):
                            issues.append(
                                _issue(
                                    "info",
                                    "CROSSWALK_CONNECTS_TO_CROSSWALK",
                                    f"Crosswalk lane {lid} verbindet mit crosswalk {target} — pruefen ob korrekt.",
                                    msg,
                                    intersection_id=iid,
                                    lane_id=lid,
                                )
                            )


def _check_bicycle_lane_linking(
    messages: Iterable[V2xMessage],
    issues: list[MapValidationIssue],
) -> None:
    """Per C-Roads Handbook §4.8: Bicycle lanes should connect to vehicle lanes."""
    for msg in messages:
        if msg.msg_type != MessageType.MAPEM:
            continue
        for intersection in _iter_intersections(msg):
            iid = _intersection_id(intersection, msg)
            lanes = _lane_set(intersection)
            lane_ids = {}
            for lane in lanes:
                lid = _lane_id(lane)
                if lid is not None:
                    attrs = _value(lane, "laneAttributes")
                    ltype = _value(attrs, "laneType", "lanetype") if isinstance(attrs, dict) else None
                    lane_ids[lid] = ltype

            for lane in lanes:
                lid = _lane_id(lane)
                if lid is None:
                    continue
                attrs = _value(lane, "laneAttributes")
                ltype = _value(attrs, "laneType", "lanetype") if isinstance(attrs, dict) else None
                if ltype not in ("bikeLane", "bikeway", "bicycle"):
                    continue
                connections = _connections(lane)
                if not connections:
                    issues.append(
                        _issue(
                            "warning",
                            "BIKE_NO_CONNECTION",
                            f"Bicycle/Bike lane {lid} hat keine connectsTo-Verbindung.",
                            msg,
                            intersection_id=iid,
                            lane_id=lid,
                        )
                    )
                    continue
                has_vehicle_connection = False
                for connection in connections:
                    target = _connection_lane_id(connection)
                    if target is not None:
                        target_type = lane_ids.get(target)
                        if target_type == "vehicle":
                            has_vehicle_connection = True
                            break
                if not has_vehicle_connection:
                    issues.append(
                        _issue(
                            "warning",
                            "BIKE_NO_VEHICLE_CONNECTION",
                            f"Bicycle/Bike lane {lid} hat keine Verbindung zu einer vehicle lane.",
                            msg,
                            intersection_id=iid,
                            lane_id=lid,
                        )
                    )


def _check_roundabout_topology(
    messages: Iterable[V2xMessage],
    issues: list[MapValidationIssue],
) -> None:
    """Per C-Roads Handbook §4.10: Roundabout detection and validation."""
    for msg in messages:
        if msg.msg_type != MessageType.MAPEM:
            continue
        for intersection in _iter_intersections(msg):
            iid = _intersection_id(intersection, msg)
            lanes = _lane_set(intersection)
            if not lanes:
                continue
            # Heuristic: Roundabout has circular connections (ingress connects back to egress)
            lane_ids = set()
            for lane in lanes:
                lid = _lane_id(lane)
                if lid is not None:
                    lane_ids.add(lid)

            ingress_count = 0
            egress_count = 0
            for lane in lanes:
                if _value(lane, "ingressApproach", "ingressapproach") is not None:
                    ingress_count += 1
                if _value(lane, "egressApproach", "egressapproach") is not None:
                    egress_count += 1

            # If all lanes have no ingress/egress distinction, might be roundabout
            if ingress_count == 0 and egress_count == 0:
                if any(_has_lane_role(lane) for lane in lanes):
                    continue
                if _has_circular_connections(lanes):
                    issues.append(
                        _issue(
                            "info",
                            "ROUNDABOUT_CIRCULAR_TOPOLOGY",
                            "Erkannt: moeglicher Kreisverkehr (roundabout) mit zirkulaeren Verbindungen. Pruefen ob id und name korrekt sind.",
                            msg,
                            intersection_id=iid,
                        )
                    )
                else:
                    issues.append(
                        _issue(
                            "warning",
                            "LANES_NO_DIRECTION",
                            "Keine ingress/egress-Zuordnung bei lanes erkannt.",
                            msg,
                            intersection_id=iid,
                        )
                    )


def _has_circular_connections(lanes: list[dict]) -> bool:
    """Check if lanes form a circular connection pattern typical of roundabouts."""
    for lane in lanes:
        connections = _connections(lane)
        for connection in connections:
            target = _connection_lane_id(connection)
            if target is not None:
                for other in lanes:
                    if _lane_id(other) == target:
                        other_connections = _connections(other)
                        for oc in other_connections:
                            if _connection_lane_id(oc) == _lane_id(lane):
                                return True
    return False
