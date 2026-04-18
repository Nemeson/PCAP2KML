"""NMEA sentence parser for GPS data embedded in PCAP files.

Parses GPGGA and GPRMC sentences to extract position, speed, and heading.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from .data_model import MessageType, V2xMessage

# Regex patterns for NMEA sentences
_GPGGA_RE = re.compile(
    r"^\$GPGGA,"
    r"(\d{6})(\.\d+)?,"   # time: HHMMSS.ss
    r"(\d{2}\d{2}\.\d+),"  # latitude: DDMM.MMMMM
    r"([NS]),"
    r"(\d{3}\d{2}\.\d+),"  # longitude: DDDMM.MMMMM
    r"([EW]),"
    r"(\d),"               # fix quality
    r"(\d+)?,"             # number of satellites
    r"([\d.]*)?,"          # HDOP
    r"([\d.]*)?,"          # altitude
    r"M?,"
    r"([\d.]*)?,"          # geoidal separation
)

_GPRMC_RE = re.compile(
    r"^\$GPRMC,"
    r"(\d{6})(\.\d+)?,"   # time: HHMMSS.ss
    r"([AV]),"              # status: A=valid, V=invalid
    r"(\d{2}\d{2}\.\d+),"  # latitude: DDMM.MMMMM
    r"([NS]),"
    r"(\d{3}\d{2}\.\d+),"  # longitude: DDDMM.MMMMM
    r"([EW]),"
    r"([\d.]+)?,"           # speed in knots
    r"([\d.]+)?,"           # track angle (heading)
    r"(\d{2}\d{2}\d{2})?"  # date: DDMMYY
)


def _nmea_to_decimal(value: str, direction: str) -> float:
    """Convert NMEA coordinate (DDMM.MMMMM) to decimal degrees."""
    if not value:
        return 0.0
    # Find the split point: 2 digits for lat, 3 for lon
    if direction in "NS":
        deg = int(value[:2])
        minutes = float(value[2:])
    else:
        deg = int(value[:3])
        minutes = float(value[3:])
    decimal = deg + minutes / 60.0
    if direction in "SW":
        decimal = -decimal
    return decimal


def _parse_nmea_time(time_str: str, frac: str = "", date_str: str = "") -> datetime:
    """Parse NMEA time string into a datetime object.

    NMEA timestamps lack date info in the time field; if date_str
    (DDMMYY) is available from GPRMC, it is combined. Otherwise,
    today's date is used as a fallback.
    """
    hour = int(time_str[0:2])
    minute = int(time_str[2:4])
    second = int(time_str[4:6])
    microsecond = int(float(f"0.{frac.lstrip('.')}") * 1_000_000) if frac else 0

    if date_str and len(date_str) >= 6:
        day = int(date_str[0:2])
        month = int(date_str[2:4])
        year = 2000 + int(date_str[4:6])
        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc)

    # Fallback: use today's date
    now = datetime.now(tz=timezone.utc)
    return datetime(now.year, now.month, now.day, hour, minute, second, microsecond, tzinfo=timezone.utc)


def parse_gpgga(sentence: str, default_station_id: str = "GPS") -> Optional[V2xMessage]:
    """Parse a $GPGGA sentence into a V2xMessage."""
    match = _GPGGA_RE.match(sentence.strip())
    if not match:
        return None

    time_str, time_frac, lat, ns, lon, ew, fix, sats, hdop, alt, _ = match.groups()

    if fix == "0":
        return None  # No fix

    try:
        return V2xMessage(
            timestamp=_parse_nmea_time(time_str, time_frac),
            station_id=default_station_id,
            msg_type=MessageType.NMEA,
            latitude=_nmea_to_decimal(lat, ns),
            longitude=_nmea_to_decimal(lon, ew),
            altitude=float(alt) if alt else None,
            speed=None,
            heading=None,
        )
    except (ValueError, IndexError):
        return None


def parse_gprmc(sentence: str, default_station_id: str = "GPS") -> Optional[V2xMessage]:
    """Parse a $GPRMC sentence into a V2xMessage."""
    match = _GPRMC_RE.match(sentence.strip())
    if not match:
        return None

    time_str, time_frac, status, lat, ns, lon, ew, speed_knots, heading, date_str = match.groups()

    if status == "V":
        return None  # Invalid data

    try:
        speed_ms = float(speed_knots) * 0.514444 if speed_knots else None
        heading_val = float(heading) if heading else None

        return V2xMessage(
            timestamp=_parse_nmea_time(time_str, time_frac, date_str or ""),
            station_id=default_station_id,
            msg_type=MessageType.NMEA,
            latitude=_nmea_to_decimal(lat, ns),
            longitude=_nmea_to_decimal(lon, ew),
            altitude=None,
            speed=speed_ms,
            heading=heading_val,
        )
    except (ValueError, IndexError):
        return None


def parse_nmea_sentence(data: bytes, default_station_id: str = "GPS") -> Optional[V2xMessage]:
    """Try to parse bytes as an NMEA sentence.

    Checks for GPGGA first, then GPRMC. Returns None if the data
    is not a recognized NMEA sentence.
    """
    try:
        text = data.decode("ascii", errors="ignore").strip()
    except Exception:
        return None

    if text.startswith("$GPGGA"):
        return parse_gpgga(text, default_station_id)
    elif text.startswith("$GPRMC"):
        return parse_gprmc(text, default_station_id)
    return None