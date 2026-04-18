"""ASN.1 schema management for ETSI ITS V2X message decoding.

Provides hybrid schema loading: locally embedded ASN.1 files with
optional update from the official ETSI Forge GitLab repositories.

ETSI Standards Referenced:
  - CAM:   ETSI EN 302 637-2 V1.4.1 (Oct 2019)
  - DENM:  ETSI EN 302 637-3 V1.3.1 (Apr 2019)
  - MAPEM:  ETSI TS 103 301 V2.2.1 (Aug 2024)
  - SPATEM: ETSI TS 103 301 V2.2.1 (Aug 2024)
  - SREM:  ETSI TS 103 301 V2.2.1 (Aug 2024)
  - SSEM:  ETSI TS 103 301 V2.2.1 (Aug 2024)
  - CDD:   ETSI TS 102 894-2 V2.2.1 (Common Data Dictionary)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

try:
    import asn1tools
except ImportError:
    asn1tools = None

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).parent / "assets" / "asn1"

# Official ETSI Forge GitLab repositories (BSD 3-Clause license)
ETSI_FORGE_BASE = "https://forge.etsi.org/rep/ITS/asn1"
ETSI_FORGE_REPOS = {
    "CAM": f"{ETSI_FORGE_BASE}/cam_en302637_2",
    "DENM": f"{ETSI_FORGE_BASE}/denm_en302637_3",
    "IS": f"{ETSI_FORGE_BASE}/is_ts103301",
    "CDD": f"{ETSI_FORGE_BASE}/cdd_ts102894_2",
}

# Mapping of message types to their ASN.1 PDU module filenames
# These are the official ETSI ASN.1 module names per standard
MSG_TYPE_MODULES = {
    "CAM": "CAM-PDU-Descriptions.asn",
    "DENM": "DENM-PDU-Descriptions.asn",
    "MAPEM": "MAPEM-PDU-Descriptions.asn",
    "SPATEM": "SPATEM-PDU-Descriptions.asn",
    "SREM": "SREM-PDU-Descriptions.asn",
    "SSEM": "SSEM-PDU-Descriptions.asn",
}

# ITS ASN.1 type names used as top-level decode targets
MSG_TYPE_ASN1_NAMES = {
    "CAM": "CamPdu",
    "DENM": "DenmPdu",
    "MAPEM": "MapemPdu",
    "SPATEM": "SpatemPdu",
    "SREM": "SremPdu",
    "SSEM": "SsemPdu",
}

# Common Data Dictionary (CDD) — required dependency for all ITS messages
# Formerly known as ITS-Container; renamed to ETSI-ITS-CDD in Sep 2022
CDD_FILE = "ETSI-ITS-CDD.asn"

# ISO TS 19091 DSRC module — required by IS message types (MAPEM, SPATEM, SREM, SSEM)
# Contains MapData, SPAT, SignalRequestMessage, SignalStatusMessage
DSRC_FILE = "DSRC.asn"

# Stub for ISO 24534 Electronic Registration Identification (used by DSRC module)
ERI_FILE = "ElectronicRegistrationIdentificationVehicleDataModule.asn"

# IS message types that additionally require the DSRC module
IS_MSG_TYPES = {"MAPEM", "SPATEM", "SREM", "SSEM"}

# Compiled schema cache: msg_type -> compiled ASN.1 schema
_compiled_schemas: dict[str, object] = {}


def _ensure_schema_dir() -> None:
    """Create the ASN.1 schema directory if it doesn't exist."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)


def _schema_files_available() -> bool:
    """Check if at least one ASN.1 schema file exists locally."""
    return any(SCHEMAS_DIR.glob("*.asn"))


def _get_schema_files(msg_type: str) -> list[Path]:
    """Get the list of .asn files needed to compile a message type.

    All ITS message types require the CDD (Common Data Dictionary)
    as a dependency since they import types from it.

    IS message types (MAPEM, SPATEM, SREM, SSEM) additionally require
    the DSRC module from ISO TS 19091 for MapData, SPAT, etc.
    """
    cdd_path = SCHEMAS_DIR / CDD_FILE
    module_path = SCHEMAS_DIR / MSG_TYPE_MODULES[msg_type]

    files = []
    if cdd_path.exists():
        files.append(cdd_path)
    else:
        logger.warning("CDD file not found: %s", cdd_path)

    # IS message types need the DSRC module from ISO TS 19091
    if msg_type in IS_MSG_TYPES:
        # ERI stub must come before DSRC (DSRC imports from it)
        eri_path = SCHEMAS_DIR / ERI_FILE
        if eri_path.exists():
            files.append(eri_path)
        else:
            logger.warning("ERI stub file not found: %s", eri_path)

        dsrc_path = SCHEMAS_DIR / DSRC_FILE
        if dsrc_path.exists():
            files.append(dsrc_path)
        else:
            logger.warning("DSRC file not found: %s", dsrc_path)

    if module_path.exists():
        files.append(module_path)
    else:
        logger.warning("Schema file not found: %s", module_path)

    return files


def update_from_git() -> bool:
    """Pull or clone ETSI ITS ASN.1 schemas from official ETSI Forge.

    Uses the ika-rwth-aachen/etsi_its_messages GitHub repository which
    aggregates all ETSI ITS ASN.1 definitions in one place.

    Returns True if update succeeded, False otherwise.
    """
    aggregate_repo = "https://github.com/ika-rwth-aachen/etsi_its_messages.git"

    if not SCHEMAS_DIR.exists() or not list(SCHEMAS_DIR.glob(".git")):
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", aggregate_repo,
                 str(SCHEMAS_DIR)],
                capture_output=True, text=True, timeout=120,
                check=True,
            )
            logger.info("Cloned ASN.1 schemas from %s", aggregate_repo)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired) as e:
            logger.warning("Failed to clone ASN.1 schemas: %s", e)
            return False
    else:
        try:
            subprocess.run(
                ["git", "-C", str(SCHEMAS_DIR), "pull"],
                capture_output=True, text=True, timeout=30,
                check=True,
            )
            logger.info("Updated ASN.1 schemas from %s", aggregate_repo)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired) as e:
            logger.warning("Failed to update ASN.1 schemas: %s", e)
            return False


def get_compiled_schema(msg_type: str) -> Optional[object]:
    """Get a compiled ASN.1 schema for the given message type.

    Compiles the message-specific PDU module together with the
    CDD (Common Data Dictionary) dependency. Uses cached compilation
    if available.

    Returns None if asn1tools is not installed or schema files are missing.
    """
    if asn1tools is None:
        logger.warning("asn1tools not installed — cannot decode ASN.1")
        return None

    if msg_type in _compiled_schemas:
        return _compiled_schemas[msg_type]

    if msg_type not in MSG_TYPE_MODULES:
        logger.warning("No ASN.1 module mapping for %s", msg_type)
        return None

    schema_files = _get_schema_files(msg_type)
    if len(schema_files) < 2:
        logger.warning(
            "Insufficient schema files for %s (need CDD + PDU module)",
            msg_type,
        )
        return None

    try:
        file_paths = [str(f) for f in schema_files]
        compiled = asn1tools.compile_files(file_paths, "uper")
        _compiled_schemas[msg_type] = compiled
        logger.info("Compiled ASN.1 schema for %s from %d files",
                     msg_type, len(file_paths))
        return compiled
    except Exception as e:
        logger.error("Failed to compile ASN.1 schema for %s: %s",
                      msg_type, e)
        return None


def decode_its_message(msg_type: str, payload: bytes) -> Optional[dict]:
    """Decode a V2X ITS message payload using ASN.1 schemas.

    Args:
        msg_type: One of CAM, DENM, MAPEM, SPATEM, SREM, SSEM.
        payload: Raw ASN.1 UPER-encoded bytes.

    Returns:
        Decoded dict with message fields, or None on failure.
    """
    schema = get_compiled_schema(msg_type)
    if schema is None:
        return None

    asn1_type_name = MSG_TYPE_ASN1_NAMES.get(msg_type)
    if not asn1_type_name:
        logger.warning("No ASN.1 type name for %s", msg_type)
        return None

    try:
        decoded = schema.decode(asn1_type_name, payload)
        return decoded
    except Exception as e:
        logger.debug("ASN.1 decode failed for %s (%s): %s",
                      msg_type, asn1_type_name, e)
        return None


def init_schemas() -> dict[str, bool]:
    """Initialize ASN.1 schemas at startup.

    Returns a dict mapping msg_type -> True/False indicating whether
    the schema compiled successfully.
    """
    _ensure_schema_dir()
    results = {}
    for msg_type in MSG_TYPE_MODULES:
        schema = get_compiled_schema(msg_type)
        results[msg_type] = schema is not None
    return results