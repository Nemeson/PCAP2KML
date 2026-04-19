from __future__ import annotations

from datetime import datetime, timezone

from pcap2kml_player.data_model import MessageType, V2xMessage
from pcap2kml_player.ui.main_window import COL_TIMESTAMP, MainWindow


def _message(second: int, station_id: str = "car-1") -> V2xMessage:
    return V2xMessage(
        timestamp=datetime(2026, 4, 19, 12, 0, second, tzinfo=timezone.utc),
        station_id=station_id,
        msg_type=MessageType.CAM,
        latitude=52.0,
        longitude=13.0,
    )


class _Rect:
    def __init__(self, visible: bool):
        self._visible = visible

    def isValid(self) -> bool:
        return True

    def intersects(self, _other) -> bool:
        return self._visible


class _Viewport:
    def rect(self) -> _Rect:
        return _Rect(True)


class _FakeTable:
    def __init__(self, visible_rows: set[int] | None = None):
        self.visible_rows = visible_rows or set()
        self.selected_rows: list[int] = []
        self.scrolled_rows: list[int] = []
        self._items: dict[tuple[int, int], object] = {}

    def setRowCount(self, _count: int) -> None:
        return None

    def setItem(self, row: int, column: int, item: object) -> None:
        self._items[(row, column)] = item

    def item(self, row: int, column: int) -> object | None:
        return self._items.get((row, column))

    def selectRow(self, row: int) -> None:
        self.selected_rows.append(row)

    def scrollToItem(self, item: object, _hint: object) -> None:
        for (row, _column), candidate in self._items.items():
            if candidate is item:
                self.scrolled_rows.append(row)
                return

    def visualItemRect(self, item: object) -> _Rect:
        for (row, _column), candidate in self._items.items():
            if candidate is item:
                return _Rect(row in self.visible_rows)
        return _Rect(False)

    def viewport(self) -> _Viewport:
        return _Viewport()


def test_populate_message_table_builds_lookup_without_full_window_init():
    window = MainWindow.__new__(MainWindow)
    window._session = None
    window._message_row_lookup = {}
    window._last_highlighted_row = None
    window._msg_table = _FakeTable()

    first = _message(0, "car-1")
    second = _message(1, "car-2")

    window._populate_message_table([first, second])

    assert window._message_row_lookup[window._message_lookup_key(first)] == 0
    assert window._message_row_lookup[window._message_lookup_key(second)] == 1


def test_highlight_table_row_skips_scroll_when_row_is_already_visible():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    key = (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)
    table = _FakeTable(visible_rows={2})
    timestamp_item = object()
    table.setItem(2, COL_TIMESTAMP, timestamp_item)

    window._msg_table = table
    window._message_row_lookup = {key: 2}
    window._last_highlighted_row = None

    window._highlight_table_row(msg)

    assert table.selected_rows == [2]
    assert table.scrolled_rows == []
    assert window._last_highlighted_row == 2


def test_highlight_table_row_avoids_repeat_selection_for_same_row():
    window = MainWindow.__new__(MainWindow)
    msg = _message(0, "car-1")
    key = (msg.timestamp.strftime("%H:%M:%S.%f")[:-3], msg.station_id)
    table = _FakeTable()
    timestamp_item = object()
    table.setItem(3, COL_TIMESTAMP, timestamp_item)

    window._msg_table = table
    window._message_row_lookup = {key: 3}
    window._last_highlighted_row = 3

    window._highlight_table_row(msg)

    assert table.selected_rows == []
    assert table.scrolled_rows == []
