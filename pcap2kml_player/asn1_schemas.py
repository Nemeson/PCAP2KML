"""ASN.1 schema management for ETSI ITS V2X message decoding.

Provides hybrid schema loading: locally embedded ASN.1 files with
optional update from a remote Git repository.
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
ETSI_GIT_URL = "https://github.com/nickvdp/ETSI-ITS-ASN1.git"

# Mapping of message types to their ASN.1 module filenames
MSG_TYPE_MODULES = {
    "CAM": "CAM.asn",
    "DENM": "DENM.asn",
    "MAPEM": "MAPEM.asn",
    "SPATEM": "SPATEM.asn",
    "SREM": "SREM.asn",
    "SSEM": "SSEM.asn",
}

# Compiled schema cache: msg_type -> compiled ASN.1 schema
_compiled_schemas: dict[str, object] = {}


def _ensure_schema_dir() -> None:
    """Create the ASN.1 schema directory if it doesn't exist."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)


def _schema_files_available() -> bool:
    """Check if at least one ASN.1 schema file exists locally."""
    return any(SCHEMAS_DIR.glob("*.asn"))


def update_from_git() -> bool:
    """Pull or clone ETSI ITS ASN.1 schemas from Git repository.

    Returns True if update succeeded, False otherwise.
    """
    if not SCHEMAS_DIR.exists() or not list(SCHEMAS_DIR.glob(".git")):
        # Fresh clone
        try:
            subprocess.run(
                ["git", "clone", ETSI_GIT_URL, str(SCHEMAS_DIR)],
                capture_output=True, text=True, timeout=60,
                check=True,
            )
            logger.info("Cloned ASN.1 schemas from %s", ETSI_GIT_URL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to clone ASN.1 schemas: %s", e)
            return False
    else:
        # Pull update
        try:
            subprocess.run(
                ["git", "-C", str(SCHEMAS_DIR), "pull"],
                capture_output=True, text=True, timeout=30,
                check=True,
            )
            logger.info("Updated ASN.1 schemas from %s", ETSI_GIT_URL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to update ASN.1 schemas: %s", e)
            return False


def get_compiled_schema(msg_type: str) -> Optional[object]:
    """Get a compiled ASN.1 schema for the given message type.

    Uses cached compilation if available. Returns None if asn1tools
    is not installed or schema files are missing.
    """
    if asn1tools is None:
        logger.warning("asn1tools not installed — cannot decode ASN.1")
        return None

    if msg_type in _compiled_schemas:
        return _compiled_schemas[msg_type]

    module_file = MSG_TYPE_MODULES.get(msg_type)
    if not module_file:
        logger.warning("No ASN.1 module mapping for %s", msg_type)
        return None

    schema_path = SCHEMAS_DIR / module_file
    if not schema_path.exists():
        logger.warning("ASN.1 schema file not found: %s", schema_path)
        return None

    try:
        compiled = asn1tools.compile_files([str(schema_path)], "uper")
        _compiled_schemas[msg_type] = compiled
        return compiled
    except Exception as e:
        logger.error("Failed to compile ASN.1 schema for %s: %s", msg_type, e)
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

    try:
        # The ASN.1 type name matches the message type
        decoded = schema.decode(msg_type, payload)
        return decoded
    except Exception as e:
        logger.debug("ASN.1 decode failed for %s: %s", msg_type, e)
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