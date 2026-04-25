"""Data model for PCAP2KML Player.

Defines the core data structures shared across all modules:
V2xMessage, MessageType, SessionData.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class MessageType(Enum):
    """Supported V2X and GNSS message types."""

    CAM = "CAM"
    DENM = "DENM"
    SREM = "SREM"
    SSEM = "SSEM"
    MAPEM = "MAPEM"
    SPATEM = "SPATEM"
    NMEA = "NMEA"


class CaptureRole(Enum):
    """Best-effort role of a loaded capture file."""

    TXA = "txa"
    RXA = "rxa"
    UNKNOWN = "unknown"


@dataclass
class CaptureSource:
    """Metadata for one loaded PCAP/capture file."""

    path: str
    source_index: int
    role: CaptureRole = CaptureRole.UNKNOWN
    message_count: int = 0

    @property
    def filename(self) -> str:
        """Return the display filename for this capture source."""
        return Path(self.path).name


@dataclass
class MessageSource:
    """Provenance for one decoded V2X/NMEA message."""

    path: str
    filename: str
    source_index: int
    role: CaptureRole = CaptureRole.UNKNOWN
    parser_backend: Optional[str] = None
    packet_index: Optional[int] = None

    def display_name(self) -> str:
        """Return compact source text for tables, details, and exports."""
        role = self.role.value.upper()
        return f"{self.filename} ({role})"


@dataclass
class MergedObservation:
    """A soft-merged group of observations that likely describe one event."""

    merge_id: str
    canonical_key: tuple[str, str, str]
    confidence: float
    reason: str
    observation_keys: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class V2xMessage:
    """A single decoded V2X or NMEA message with position data."""

    timestamp: datetime
    station_id: str
    msg_type: MessageType
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    raw_payload: Optional[bytes] = None
    details: dict[str, str] = field(default_factory=dict)
    security_info: Optional[SecurityInfo] = None
    decoded_data: dict = field(default_factory=dict)
    source: Optional[MessageSource] = None
    merge_group_id: Optional[str] = None
    merge_confidence: Optional[float] = None
    merge_reason: Optional[str] = None
    """Structured fields extracted from the ASN.1-decoded ITS PDU.

    Message-type-specific keys (Phase 2.1 — ETSI TS 103 301 / EN 302 637):
      CAM:    vehicleWidth, vehicleLength, driveDirection, lightBarStatus, ...
      DENM:   causeCode, subCauseCode, severity, validityDuration, ...
      MAPEM:  intersectionId, revision, lanes[...], speedLimits, ...
      SPATEM: intersectionId, signalGroups[...], moy, timeStamp, ...
      SREM:   requestId, sequenceNumber, importanceLevel, requestorRole,
              inLane, outLane, eta, ...
      SSEM:   requestId, sequenceNumber, status, ...
    """

    def to_kml_description(self) -> str:
        """Generate an HTML description string for KML Placemark."""
        parts = [
            f"<b>Type:</b> {self.msg_type.value}",
            f"<b>Station:</b> {self.station_id}",
            f"<b>Time:</b> {self.timestamp.isoformat()}",
            f"<b>Lat/Lon:</b> {self.latitude:.6f}, {self.longitude:.6f}",
        ]
        if self.source is not None:
            parts.append(f"<b>Source:</b> {self.source.display_name()}")
        if self.merge_group_id:
            parts.append(
                f"<b>Merge:</b> {self.merge_group_id}"
                + (
                    f" ({self.merge_confidence:.2f})"
                    if self.merge_confidence is not None
                    else ""
                )
            )
        if self.altitude is not None:
            parts.append(f"<b>Altitude:</b> {self.altitude:.1f} m")
        if self.speed is not None:
            parts.append(f"<b>Speed:</b> {self.speed:.1f} m/s")
        if self.heading is not None:
            parts.append(f"<b>Heading:</b> {self.heading:.1f}°")
        return "<br>".join(parts)

    def to_detail_rows(self) -> list[tuple[str, str]]:
        """Convert the message into human-readable detail rows."""
        rows = [
            ("Nachrichtentyp", self.msg_type.value),
            ("Station", self.station_id),
            ("Zeit", self.timestamp.isoformat()),
            ("Position", f"{self.latitude:.6f}, {self.longitude:.6f}"),
        ]
        if self.source is not None:
            rows.append(("Capture-Datei", self.source.filename))
            rows.append(("Capture-Rolle", self.source.role.value.upper()))
            if self.source.parser_backend:
                rows.append(("Parser", self.source.parser_backend))
        if self.merge_group_id:
            merge_text = self.merge_group_id
            if self.merge_confidence is not None:
                merge_text += f" ({self.merge_confidence:.2f})"
            if self.merge_reason:
                merge_text += f" - {self.merge_reason}"
            rows.append(("Merge-Gruppe", merge_text))
        identity_hint = self.details.get("Identitaets-Hinweis")
        if identity_hint:
            rows.append(("Identitaets-Hinweis", identity_hint))
        if self.altitude is not None:
            rows.append(("Hoehe", f"{self.altitude:.1f} m"))
        if self.speed is not None:
            rows.append(("Geschwindigkeit", f"{self.speed:.1f} m/s"))
        if self.heading is not None:
            rows.append(("Heading", f"{self.heading:.1f} deg"))
        for key, value in self.details.items():
            if key == "Identitaets-Hinweis":
                continue
            rows.append((key, value))
        return rows


@dataclass
class SecurityInfo:
    """Security header data extracted from ETSI TS 103 097 signed messages.

    ETSI ITS G5 messages carry a security envelope (IEEE 1609.2 / ETSI TS 103 097)
    that wraps the actual ITS PDU. This dataclass holds the extracted fields.

    Reference: ETSI TS 103 097 V2.2.1 (Security header and certificate formats)
    """

    # Security envelope
    protocol_version: Optional[int] = None
    """ITS Security protocol version (2 = current)."""
    security_profile: Optional[str] = None
    """Security profile: 'unsecured', 'signed', 'signed_encrypted', 'signed_encrypted_auth'."""

    # Signer information
    signer_type: Optional[str] = None
    """How the signer is identified: 'self', 'digest', 'certificate_chain'."""
    signer_digest: Optional[str] = None
    """SHA-256 digest of the signing certificate (hex string)."""
    certificate_issuer: Optional[str] = None
    """Issuer of the signing certificate."""
    certificate_subject_type: Optional[str] = None
    """Subject type: 'CA', 'subscriber', 'enrollment_CA'."""

    # Certificate validity
    validity_start: Optional[str] = None
    """Certificate validity start (ISO 8601 or 'Not available')."""
    validity_end: Optional[str] = None
    """Certificate validity end (ISO 8601 or 'Not available')."""

    # Signature
    signature_algorithm: Optional[str] = None
    """ECDSA curve: 'NIST P-256' or 'BrainpoolP256r1'."""
    signature_r: Optional[str] = None
    """Signature R value (hex, first 16 bytes)."""
    signature_s: Optional[str] = None
    """Signature S value (hex, first 16 bytes)."""

    # Subject attributes
    assurance_level: Optional[int] = None
    """Assurance level (0-7) per ETSI TS 102 941."""
    station_type: Optional[str] = None
    """Station type from certificate (e.g. 'passengerCar', 'roadSideUnit')."""
    its_aid_list: Optional[list[int]] = None
    """ITS Application Identifiers the certificate is authorized for."""
    ssp_permissions: Optional[str] = None
    """Service Specific Permissions (hex or human-readable)."""

    # Geographic scope
    region_type: Optional[str] = None
    """Geographic validity: 'none', 'circular', 'rectangular', 'polygonal', 'country'."""
    region_detail: Optional[str] = None
    """Region description (e.g. 'Germany (DE)' or lat/lon coordinates)."""

    def to_table_rows(self) -> list[tuple[str, str]]:
        """Convert to list of (field, value) pairs for table display."""
        rows = [
            (
                "Protokollversion",
                str(self.protocol_version)
                if self.protocol_version is not None
                else "—",
            ),
            ("Sicherheitsprofil", self.security_profile or "—"),
            ("Signer-Typ", self.signer_type or "—"),
            ("Signer-Digest", self.signer_digest or "—"),
            ("Zertifikat-Aussteller", self.certificate_issuer or "—"),
            ("Subjekt-Typ", self.certificate_subject_type or "—"),
            ("Gültig von", self.validity_start or "—"),
            ("Gültig bis", self.validity_end or "—"),
            ("Signaturalgorithmus", self.signature_algorithm or "—"),
            ("Signatur R (gekürzt)", self.signature_r or "—"),
            ("Signatur S (gekürzt)", self.signature_s or "—"),
            (
                "Assurance-Level",
                str(self.assurance_level) if self.assurance_level is not None else "—",
            ),
            ("Stations-Typ", self.station_type or "—"),
            (
                "ITS-AIDs",
                ", ".join(str(a) for a in self.its_aid_list)
                if self.its_aid_list
                else "—",
            ),
            ("SSP-Berechtigungen", self.ssp_permissions or "—"),
            ("Regionstyp", self.region_type or "—"),
            ("Region", self.region_detail or "—"),
        ]
        return rows


@dataclass
class SessionData:
    """Container for all messages parsed from one or more PCAP files."""

    messages: list[V2xMessage] = field(default_factory=list)
    station_ids: set[str] = field(default_factory=set)
    msg_type_counts: dict[MessageType, int] = field(default_factory=dict)
    sources: list[CaptureSource] = field(default_factory=list)
    merge_groups: dict[str, MergedObservation] = field(default_factory=dict)
    _canonical_cache: list[V2xMessage] = field(default_factory=list, repr=False)
    _canonical_cache_valid: bool = field(default=False, repr=False)

    @property
    def time_range(self) -> tuple[datetime, datetime]:
        """First and last timestamp in the session."""
        if not self.messages:
            raise ValueError("Session has no messages")
        return self.messages[0].timestamp, self.messages[-1].timestamp

    @property
    def duration_seconds(self) -> float:
        """Duration of the session in seconds."""
        if not self.messages:
            return 0.0
        start, end = self.time_range
        return (end - start).total_seconds()

    def add_message(self, msg: V2xMessage) -> None:
        """Add a message and update indices."""
        self.messages.append(msg)
        self.station_ids.add(msg.station_id)
        self.msg_type_counts[msg.msg_type] = (
            self.msg_type_counts.get(msg.msg_type, 0) + 1
        )

    def register_source(
        self, path: str, role: CaptureRole, message_count: int
    ) -> CaptureSource:
        """Register or update metadata for one capture source."""
        normalized = str(Path(path).resolve())
        for source in self.sources:
            if source.path == normalized:
                source.role = role
                source.message_count = message_count
                return source
        source = CaptureSource(
            path=normalized,
            source_index=len(self.sources),
            role=role,
            message_count=message_count,
        )
        self.sources.append(source)
        return source

    def finalize(self, *, build_merge_groups: bool = True) -> None:
        """Sort messages by timestamp after all parsing is complete."""
        self.messages.sort(key=lambda m: m.timestamp)
        self._canonical_cache_valid = False
        if build_merge_groups:
            self.rebuild_merge_groups()

    def rebuild_merge_groups(self) -> None:
        """Recalculate soft-merge groups for the current message stream."""
        from .merge_model import build_merge_groups

        self.merge_groups = build_merge_groups(self.messages)
        self._canonical_cache_valid = False

    def canonical_messages(self) -> list[V2xMessage]:
        """Return one canonical message per merge group plus unmerged messages."""
        canonical_keys_by_merge = {
            merge_id: group.canonical_key
            for merge_id, group in self.merge_groups.items()
            if len(group.observation_keys) > 1
        }
        seen_merge_ids: set[str] = set()
        result: list[V2xMessage] = []
        for msg in self.messages:
            key = message_identity_key(msg)
            if msg.merge_group_id and msg.merge_group_id in self.merge_groups:
                if msg.merge_group_id in seen_merge_ids:
                    continue
                if key == canonical_keys_by_merge.get(msg.merge_group_id):
                    result.append(msg)
                    seen_merge_ids.add(msg.merge_group_id)
                continue
            result.append(msg)
        return result

    def filter_messages(
        self,
        active_types: set[MessageType],
        active_stations: set[str],
        *,
        canonical: bool = False,
    ) -> list[V2xMessage]:
        """Return messages matching the given type and station filters."""
        messages = self.canonical_messages() if canonical else self.messages
        return [
            m
            for m in messages
            if m.msg_type in active_types and m.station_id in active_stations
        ]


def infer_capture_role(path: str) -> CaptureRole:
    """Infer TXA/RXA capture role from the filename using conservative tokens."""
    name = Path(path).name.lower()
    if any(token in name for token in ("txa", "_tx", "-tx", "transmit", "send")):
        return CaptureRole.TXA
    if any(token in name for token in ("rxa", "_rx", "-rx", "receive", "recv")):
        return CaptureRole.RXA
    return CaptureRole.UNKNOWN


def message_identity_key(msg: V2xMessage) -> tuple[str, str, str]:
    """Return a stable in-session key for one message."""
    return (msg.timestamp.isoformat(), msg.station_id, msg.msg_type.value)
