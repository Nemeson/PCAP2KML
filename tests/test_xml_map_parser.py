from pathlib import Path

import pytest

from pcap2kml_player.data_model import MessageType, SessionData
from pcap2kml_player.xml_map_parser import parse_map_xml


def test_parse_map_xml_adds_synthetic_mapem_message(tmp_path: Path) -> None:
    xml_path = tmp_path / "intersection.xml"
    xml_path.write_text(
        """
        <MapData>
          <IntersectionGeometry>
            <id><id>42</id></id>
            <refPoint><lat>488950000</lat><long>92080000</long></refPoint>
            <laneSet>
              <GenericLane>
                <laneID>17</laneID>
                <ingressApproach>1</ingressApproach>
                <nodeList>
                  <NodeXY><lat>48.8950</lat><lon>9.2080</lon></NodeXY>
                  <NodeXY><lat>48.8951</lat><lon>9.2082</lon></NodeXY>
                </nodeList>
              </GenericLane>
            </laneSet>
          </IntersectionGeometry>
        </MapData>
        """,
        encoding="utf-8",
    )
    session = SessionData()

    parsed = parse_map_xml(str(xml_path), session)

    assert parsed == 1
    assert len(session.messages) == 1
    msg = session.messages[0]
    assert msg.msg_type == MessageType.MAPEM
    assert msg.latitude == pytest.approx(48.895)
    assert msg.longitude == pytest.approx(9.208)
    assert msg.decoded_data["intersectionCount"] == 1
    assert msg.decoded_data["laneCount"] == 1
    assert msg.source is not None
    assert msg.source.parser_backend == "xml-map"


def test_parse_map_xml_rejects_empty_file(tmp_path: Path) -> None:
    xml_path = tmp_path / "empty.xml"
    xml_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="leer"):
        parse_map_xml(str(xml_path), SessionData())


def test_parse_map_xml_creates_one_station_per_intersection(tmp_path: Path) -> None:
    xml_path = tmp_path / "multi.xml"
    xml_path.write_text(
        """
        <MapData>
          <IntersectionGeometry>
            <id><id>10</id></id>
            <refPoint><lat>488950000</lat><long>92080000</long></refPoint>
            <laneSet><GenericLane><laneID>1</laneID></GenericLane></laneSet>
          </IntersectionGeometry>
          <IntersectionGeometry>
            <id><id>11</id></id>
            <refPoint><lat>488960000</lat><long>92090000</long></refPoint>
            <laneSet><GenericLane><laneID>2</laneID></GenericLane></laneSet>
          </IntersectionGeometry>
        </MapData>
        """,
        encoding="utf-8",
    )
    session = SessionData()

    parsed = parse_map_xml(str(xml_path), session)

    assert parsed == 2
    assert len(session.messages) == 2
    assert {msg.station_id for msg in session.messages} == {"xml-map-multi-I10", "xml-map-multi-I11"}
    assert all(msg.decoded_data["intersectionCount"] == 1 for msg in session.messages)
    assert all(msg.decoded_data["xmlIntersectionTotal"] == 2 for msg in session.messages)
