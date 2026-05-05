"""Best-effort parser for XML files containing MAP geometry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from .data_model import CaptureRole, MessageSource, MessageType, SessionData, V2xMessage


_INTERSECTION_TAGS = {"intersectiongeometry", "intersection"}
_LANE_TAGS = {"genericlane", "lane", "roadlane"}
_NODE_TAGS = {"nodexy", "node", "node-xy"}
_REF_POINT_TAGS = {"refpoint", "referencepoint", "refpos", "referenceposition", "position"}


def parse_map_xml(path: str, session: SessionData) -> int:
    """Parse one MAP XML file and append one synthetic MAPEM message per intersection."""
    source_path = Path(path)
    if source_path.stat().st_size == 0:
        raise ValueError("XML-Datei ist leer")

    root = ET.parse(source_path).getroot()
    intersections = _extract_intersections(root)
    if not intersections:
        raise ValueError("Keine MAP-Kreuzungsgeometrie in XML gefunden")

    base_station_id = _station_id_from_xml(root, source_path)
    source = session.register_source(str(source_path), CaptureRole.UNKNOWN, len(intersections))
    timestamp_base = datetime.fromtimestamp(source_path.stat().st_mtime, tz=UTC)
    parsed = 0
    skipped = 0
    for index, intersection in enumerate(intersections):
        point = _normalize_geo_point(intersection.get("refPoint"))
        if point is None:
            skipped += 1
            continue
        intersection_id = _coerce_int(intersection.get("intersectionId", intersection.get("id")))
        lane_set = intersection.get("laneSet")
        lane_count = len(lane_set) if isinstance(lane_set, list) else 0
        station_id = _intersection_station_id(base_station_id, intersection_id, index)
        message = V2xMessage(
            timestamp=timestamp_base + timedelta(microseconds=index),
            station_id=station_id,
            msg_type=MessageType.MAPEM,
            latitude=point["lat"],
            longitude=point["lon"],
            decoded_data={
                "source": "xml",
                "intersectionCount": 1,
                "xmlIntersectionIndex": index + 1,
                "xmlIntersectionTotal": len(intersections),
                "intersectionId": intersection_id,
                "laneCount": lane_count,
                "intersections": [intersection],
            },
            details={
                "Quelle": "MAP-XML",
                "Datei": source_path.name,
                "Kreuzung": str(intersection_id if intersection_id is not None else index + 1),
                "Kreuzungen in Datei": str(len(intersections)),
                "Fahrstreifen": str(lane_count),
            },
            source=MessageSource(
                path=source.path,
                filename=source.filename,
                source_index=source.source_index,
                role=source.role,
                parser_backend="xml-map",
                packet_index=index + 1,
            ),
        )
        session.add_message(message)
        parsed += 1
    if parsed == 0:
        if skipped:
            raise ValueError(
                f"MAP-XML enthält {len(intersections)} Kreuzung(en), aber keine hat einen gültigen refPoint ({skipped} übersprungen)"
            )
        raise ValueError("MAP-XML enthält keine gültige Referenzposition")
    source.message_count = parsed
    return parsed


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _key(tag: str) -> str:
    return _local_name(tag).replace("_", "").replace("-", "").lower()


def _coerce_scalar(text: str | None) -> object:
    value = (text or "").strip()
    if not value:
        return ""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


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
        for key in ("id", "value", "lane", "signalGroup"):
            nested = _coerce_int(value.get(key))
            if nested is not None:
                return nested
    return None


def _normalize_geo_point(point: object) -> dict[str, float] | None:
    if not isinstance(point, dict):
        return None
    lat = point.get("lat", point.get("latitude"))
    lon = point.get("lon", point.get("longitude", point.get("long")))
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
    if not (-90 <= lat_num <= 90 and -180 <= lon_num <= 180):
        return None
    return {"lat": lat_num, "lon": lon_num}


def _normalize_map_intersection(intersection: dict) -> dict:
    normalized = dict(intersection)
    point = _normalize_geo_point(normalized.get("refPoint"))
    if point is not None:
        normalized["refPoint"] = point
    lane_set = normalized.get("laneSet")
    if isinstance(lane_set, list):
        normalized_lanes = []
        for lane in lane_set:
            if not isinstance(lane, dict):
                continue
            normalized_lane = dict(lane)
            lane_id = _coerce_int(
                normalized_lane.get("laneID", normalized_lane.get("laneId", normalized_lane.get("id")))
            )
            if lane_id is not None:
                normalized_lane["laneID"] = lane_id
                normalized_lane["laneId"] = lane_id
            normalized_lanes.append(normalized_lane)
        normalized["laneSet"] = normalized_lanes
    return normalized


def _element_to_dict(element: ET.Element) -> dict[str, object]:
    data: dict[str, object] = {str(key): _coerce_scalar(value) for key, value in element.attrib.items()}
    children = list(element)
    if not children:
        text = _coerce_scalar(element.text)
        if text != "":
            data["value"] = text
        return data

    for child in children:
        name = _local_name(child.tag)
        value = _element_to_value(child)
        if name in data:
            existing = data[name]
            if not isinstance(existing, list):
                data[name] = [existing]
            data[name].append(value)
        else:
            data[name] = value
    return data


def _element_to_value(element: ET.Element) -> object:
    children = list(element)
    if not children and not element.attrib:
        return _coerce_scalar(element.text)
    return _element_to_dict(element)


def _find_descendants(element: ET.Element, keys: set[str]) -> list[ET.Element]:
    return [candidate for candidate in element.iter() if _key(candidate.tag) in keys]


def _extract_intersections(root: ET.Element) -> list[dict]:
    candidates = [element for element in root.iter() if _key(element.tag) in _INTERSECTION_TAGS and list(element)]
    if not candidates and _key(root.tag) in {"mapem", "mapdata", "map"}:
        candidates = [root]

    intersections: list[dict] = []
    for candidate in candidates:
        intersection = _normalize_map_intersection(_intersection_from_element(candidate))
        intersections.append(intersection)
    return intersections


def _intersection_from_element(element: ET.Element) -> dict:
    data = _element_to_dict(element)
    ref_point = _find_ref_point(element)
    if ref_point is not None:
        data["refPoint"] = ref_point

    lane_set = [_lane_from_element(lane) for lane in _find_descendants(element, _LANE_TAGS)]
    lane_set = [lane for lane in lane_set if lane]
    if lane_set:
        data["laneSet"] = lane_set

    iid = _coerce_int(data.get("intersectionId", data.get("id")))
    if iid is not None:
        data["intersectionId"] = iid
        data["id"] = {"id": iid}
    return data


def _find_ref_point(element: ET.Element) -> dict[str, float] | None:
    for candidate in _find_descendants(element, _REF_POINT_TAGS):
        point = _point_from_element(candidate)
        if point is not None:
            return point
    return _point_from_element(element)


def _point_from_element(element: ET.Element) -> dict[str, float] | None:
    data = _element_to_dict(element)
    point = _normalize_geo_point(data)
    if point is not None:
        return point
    flattened = _flatten_values(element)
    return _normalize_geo_point(flattened)


def _flatten_values(element: ET.Element) -> dict[str, object]:
    values: dict[str, object] = {}
    for candidate in element.iter():
        if list(candidate):
            continue
        name = _local_name(candidate.tag)
        text = _coerce_scalar(candidate.text)
        if text != "":
            values[name] = text
    return values


def _lane_from_element(element: ET.Element) -> dict:
    lane = _element_to_dict(element)
    lane_id = _coerce_int(lane.get("laneID", lane.get("laneId", lane.get("id"))))
    if lane_id is not None:
        lane["laneID"] = lane_id
        lane["laneId"] = lane_id

    nodes = [_node_from_element(node) for node in _find_descendants(element, _NODE_TAGS)]
    nodes = [node for node in nodes if node]
    if nodes:
        lane["nodeList"] = {"nodes": nodes}
    return lane


def _node_from_element(element: ET.Element) -> dict:
    point = _point_from_element(element)
    if point is not None:
        return point
    flattened = _flatten_values(element)
    x = _coerce_int(flattened.get("x", flattened.get("deltaX", flattened.get("nodeX"))))
    y = _coerce_int(flattened.get("y", flattened.get("deltaY", flattened.get("nodeY"))))
    if x is not None or y is not None:
        return {"delta": {"x": x or 0, "y": y or 0}}
    return {}


def _first_ref_point(intersections: list[dict]) -> dict[str, float] | None:
    for intersection in intersections:
        point = _normalize_geo_point(intersection.get("refPoint"))
        if point is not None:
            return point
    return None


def _station_id_from_xml(root: ET.Element, path: Path) -> str:
    for candidate in root.iter():
        name = _key(candidate.tag)
        if name in {"stationid", "station", "mapid", "intersectionid"}:
            value = _coerce_scalar(candidate.text)
            if value != "":
                return f"xml-map-{value}"
    return f"xml-map-{path.stem}"


def _intersection_station_id(base_station_id: str, intersection_id: int | None, index: int) -> str:
    suffix = intersection_id if intersection_id is not None else index + 1
    return f"{base_station_id}-I{suffix}"
