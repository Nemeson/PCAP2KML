"""Tests for NMEA parsing (GPGGA / GPRMC)."""

import pytest

from pcap2kml_player.data_model import MessageType
from pcap2kml_player.nmea_parser import (
    _nmea_to_decimal,
    _validate_nmea_checksum,
    parse_gpgga,
    parse_gprmc,
    parse_nmea_sentence,
)


# ---------- coordinate conversion ----------

def test_nmea_to_decimal_north():
    # 48 deg 07.038 min N  -> 48 + 7.038/60
    assert _nmea_to_decimal("4807.038", "N") == pytest.approx(48.1173, rel=1e-4)


def test_nmea_to_decimal_south_is_negative():
    result = _nmea_to_decimal("4807.038", "S")
    assert result < 0
    assert result == pytest.approx(-48.1173, rel=1e-4)


def test_nmea_to_decimal_west_is_negative():
    result = _nmea_to_decimal("01131.000", "W")
    assert result < 0
    assert result == pytest.approx(-11.5166, rel=1e-3)


def test_nmea_to_decimal_empty_returns_zero():
    assert _nmea_to_decimal("", "N") == 0.0


# ---------- GPGGA ----------

def test_parse_gpgga_valid_fix():
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    msg = parse_gpgga(sentence)
    assert msg is not None
    assert msg.msg_type == MessageType.NMEA
    assert msg.latitude == pytest.approx(48.1173, rel=1e-4)
    assert msg.longitude == pytest.approx(11.5166, rel=1e-3)
    assert msg.altitude == pytest.approx(545.4)


def test_parse_gpgga_no_fix_returns_none():
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,0,00,99.9,,M,,M,,*47"
    assert parse_gpgga(sentence) is None


def test_parse_gpgga_malformed_returns_none():
    assert parse_gpgga("$GPGGA,this,is,garbage") is None


def test_parse_gpgga_uses_default_station_id():
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    msg = parse_gpgga(sentence, default_station_id="TEST_GPS")
    assert msg.station_id == "TEST_GPS"


def test_parse_gpgga_invalid_checksum_returns_none_and_logs_warning(caplog):
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*48"
    with caplog.at_level("WARNING"):
        msg = parse_gpgga(sentence)
    assert msg is None
    assert "invalid checksum" in caplog.text


def test_parse_gpgga_missing_checksum_is_accepted():
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
    msg = parse_gpgga(sentence)
    assert msg is not None


# ---------- GPRMC ----------

def test_parse_gprmc_valid_active():
    sentence = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    msg = parse_gprmc(sentence)
    assert msg is not None
    assert msg.latitude == pytest.approx(48.1173, rel=1e-4)
    assert msg.longitude == pytest.approx(11.5166, rel=1e-3)
    # 22.4 knots -> 11.52 m/s
    assert msg.speed == pytest.approx(22.4 * 0.514444, rel=1e-3)
    assert msg.heading == pytest.approx(84.4)


def test_parse_gprmc_invalid_status_returns_none():
    sentence = "$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    assert parse_gprmc(sentence) is None


def test_parse_gprmc_date_propagated_to_timestamp():
    sentence = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    msg = parse_gprmc(sentence)
    assert msg.timestamp.year == 2094  # "94" -> 2094 given the 2000+YY convention
    assert msg.timestamp.month == 3
    assert msg.timestamp.day == 23


def test_parse_gprmc_invalid_checksum_returns_none_and_logs_warning(caplog):
    sentence = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*00"
    with caplog.at_level("WARNING"):
        msg = parse_gprmc(sentence)
    assert msg is None
    assert "invalid checksum" in caplog.text


def test_validate_nmea_checksum_handles_empty_string():
    assert _validate_nmea_checksum("") is True


# ---------- parse_nmea_sentence dispatcher ----------

def test_parse_nmea_sentence_dispatches_gpgga():
    raw = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    msg = parse_nmea_sentence(raw)
    assert msg is not None
    assert msg.altitude == pytest.approx(545.4)


def test_parse_nmea_sentence_dispatches_gprmc():
    raw = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    msg = parse_nmea_sentence(raw)
    assert msg is not None
    assert msg.heading == pytest.approx(84.4)


def test_parse_nmea_sentence_unknown_returns_none():
    assert parse_nmea_sentence(b"$GPGSV,3,1,11,...") is None


def test_parse_nmea_sentence_non_nmea_bytes_returns_none():
    assert parse_nmea_sentence(b"\x00\x01\x02random binary") is None
