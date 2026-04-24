from __future__ import annotations

from datetime import datetime, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.native_map_widget import _native_infrastructure_overlays


def test_native_infrastructure_overlays_include_lanes_stoplines_connections_and_requests():
    map_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        station_id="rsu-1",
        msg_type=MessageType.MAPEM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersections": [
                {
                    "id": {"id": 42},
                    "refPoint": {"lat": 52.0, "lon": 13.0},
                    "laneSet": [
                        {
                            "laneID": 17,
                            "laneRole": "inbound",
                            "connections": [{"signalGroup": 5, "targetLaneId": 18}],
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0001, "lon": 13.0002},
                                ]
                            },
                            "stopLine": {
                                "points": [
                                    {"lat": 52.0000, "lon": 13.0000},
                                    {"lat": 52.0000, "lon": 13.0001},
                                ]
                            },
                        },
                        {
                            "laneID": 18,
                            "laneRole": "outbound",
                            "nodeList": {
                                "nodes": [
                                    {"lat": 52.0002, "lon": 13.0003},
                                    {"lat": 52.0003, "lon": 13.0004},
                                ]
                            },
                        },
                    ],
                }
            ]
        },
    )
    srem_msg = V2xMessage(
        timestamp=datetime(2026, 4, 18, 12, 0, 1, tzinfo=timezone.utc),
        station_id="bus-1",
        msg_type=MessageType.SREM,
        latitude=52.0,
        longitude=13.0,
        decoded_data={
            "intersectionId": 42,
            "requestId": 7,
            "sequenceNumber": 1,
            "inLane": 17,
            "outLane": 18,
        },
    )

    overlays = _native_infrastructure_overlays([map_msg, srem_msg])

    popups = [str(overlay.get("popup", "")) for overlay in overlays]
    assert any("Lane 17" in popup and "inbound" in popup for popup in popups)
    assert any("Lane 18" in popup and "outbound" in popup for popup in popups)
    assert any("Stopline" in popup for popup in popups)
    assert any("Connection" in popup for popup in popups)
    assert any("Request 7/1" in popup for popup in popups)
