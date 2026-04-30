from __future__ import annotations

from PyQt6.QtCore import QSettings

from pcap2kml_player.map_backend import (
    MAP_PERFORMANCE_DIAGNOSTIC,
    MAP_PERFORMANCE_MODES,
    MAP_PERFORMANCE_NORMAL,
    MAP_PERFORMANCE_SAVER,
    METERS_PER_DEGREE_LATITUDE,
    create_settings,
)


def test_performance_mode_constants_are_distinct():
    assert MAP_PERFORMANCE_NORMAL != MAP_PERFORMANCE_SAVER
    assert MAP_PERFORMANCE_SAVER != MAP_PERFORMANCE_DIAGNOSTIC
    assert MAP_PERFORMANCE_NORMAL != MAP_PERFORMANCE_DIAGNOSTIC


def test_performance_modes_set_contains_all_constants():
    assert {
        MAP_PERFORMANCE_NORMAL,
        MAP_PERFORMANCE_SAVER,
        MAP_PERFORMANCE_DIAGNOSTIC,
    } == MAP_PERFORMANCE_MODES


def test_meters_per_degree_latitude_is_positive():
    assert METERS_PER_DEGREE_LATITUDE > 0


def test_create_settings_returns_qsettings():
    s = create_settings()
    assert isinstance(s, QSettings)
    assert s.organizationName() == "PCAP2KML"
    assert s.applicationName() == "Player"
