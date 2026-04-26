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

import hashlib
import logging
import pickle
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

try:
    import asn1tools
except ImportError:
    asn1tools = None

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).parent / "assets" / "asn1"
SCHEMA_CACHE_DIR = Path(__file__).parent / "assets" / "cache"

# Structured decoding error statistics (Phase 1.2).
# Counter is reset per process; surface via `get_decoding_error_stats()`.
_decoding_errors: Counter[str] = Counter()

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
    "CAM": "CAM",
    "DENM": "DENM",
    "MAPEM": "MAPEM",
    "SPATEM": "SPATEM",
    "SREM": "SREM",
    "SSEM": "SSEM",
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
    SCHEMA_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file, streamed."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_schema_integrity() -> dict[str, str]:
    """Return a SHA-256 digest for every .asn file in the schema directory.

    Used as an integrity fingerprint: if the dict is stable across runs,
    schemas have not been tampered with.
    """
    if not SCHEMAS_DIR.exists():
        return {}
    return {p.name: _file_sha256(p) for p in sorted(SCHEMAS_DIR.glob("*.asn"))}


def get_schema_versions() -> dict[str, str]:
    """Extract schema version strings from .asn file headers.

    Scans up to the first 40 lines of each file for ETSI-style version
    markers ("V1.4.1", "V2.2.1" ...). Used for KML provenance (Phase 2.2).
    """
    import re

    version_re = re.compile(r"V\d+\.\d+\.\d+")
    versions: dict[str, str] = {}
    if not SCHEMAS_DIR.exists():
        return versions
    for path in sorted(SCHEMAS_DIR.glob("*.asn")):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for _ in range(40):
                    line = fh.readline()
                    if not line:
                        break
                    match = version_re.search(line)
                    if match:
                        versions[path.stem] = match.group(0)
                        break
        except OSError as exc:
            logger.debug("Could not read %s for version: %s", path, exc)
    return versions


def get_decoding_error_stats() -> dict[str, int]:
    """Return counts of ASN.1 decoding errors grouped by (msg_type, reason).

    Phase 1.2: structured visibility over decoding failures instead of
    only a stream of debug logs.
    """
    return dict(_decoding_errors)


def reset_decoding_error_stats() -> None:
    """Clear the decoding-error counter (e.g. between sessions)."""
    _decoding_errors.clear()


def _cache_key(msg_type: str, schema_files: list[Path]) -> str:
    """Build a cache key that changes when any input schema file changes."""
    hasher = hashlib.sha256()
    hasher.update(msg_type.encode("utf-8"))
    for path in schema_files:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(_file_sha256(path).encode("ascii"))
    return hasher.hexdigest()[:16]


def _load_compiled_from_disk(cache_path: Path):
    """Load a pickled compiled schema, or return None on any failure."""
    try:
        with cache_path.open("rb") as fh:
            return pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError) as exc:
        logger.debug("Compiled-schema cache miss (%s): %s", cache_path.name, exc)
        return None


def _save_compiled_to_disk(cache_path: Path, compiled) -> None:
    """Best-effort persist of a compiled schema to disk."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as fh:
            pickle.dump(compiled, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except (OSError, pickle.PicklingError, TypeError) as exc:
        # Not all asn1tools versions pickle cleanly; treat as non-fatal.
        logger.debug("Could not persist compiled schema %s: %s", cache_path.name, exc)


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


def _required_schema_files() -> set[str]:
    """Return the set of required ASN.1 schema filenames."""
    return {CDD_FILE, DSRC_FILE, ERI_FILE, *MSG_TYPE_MODULES.values()}


def update_from_git() -> bool:
    """Clone or pull ETSI ITS ASN.1 schemas from official ETSI Forge repos.

    Clones each ETSI Forge GitLab repository (CAM, DENM, IS, CDD) with
    --depth 1 and copies relevant ASN.1 files into the local schema dir.

    Returns True if all CDD + all required PDU modules are present after update.
    """
    _ensure_schema_dir()

    # In-place update if schema dir is already a git checkout
    git_dir = SCHEMAS_DIR / ".git"
    if git_dir.exists():
        try:
            subprocess.run(
                ["git", "-C", str(SCHEMAS_DIR), "pull"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            _invalidate_schema_caches()
            logger.info("Updated ASN.1 schemas in-place")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to update ASN.1 schemas in-place: %s", e)
            return False

    try:
        with tempfile.TemporaryDirectory(prefix="pcap2kml_asn1_") as temp_dir:
            temp_path = Path(temp_dir)
            total_copied = 0
            for name, repo_url in ETSI_FORGE_REPOS.items():
                checkout_dir = temp_path / name.lower()
                try:
                    subprocess.run(
                        ["git", "clone", "--depth", "1", repo_url, str(checkout_dir)],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=True,
                    )
                    copied = _copy_schema_payloads_from_checkout(checkout_dir, SCHEMAS_DIR)
                    total_copied += copied
                    logger.debug("Copied %d schema files from %s repo", copied, name)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    logger.warning("Failed to clone %s: %s", repo_url, e)

            _invalidate_schema_caches()

            # Verify required files are present
            required = _required_schema_files()
            missing = [f for f in required if not (SCHEMAS_DIR / f).exists()]
            if missing:
                logger.warning("Missing required ASN.1 schema files after update: %s", missing)
                return False

            logger.info("Refreshed ASN.1 schema files from ETSI Forge repos")
            return True
    except OSError as e:
        logger.warning("Failed to refresh ASN.1 schemas: %s", e)
        return False


def _copy_schema_payloads_from_checkout(source_dir: Path, target_dir: Path) -> int:
    """Copy relevant ASN.1 files from a git checkout into the schema dir.

    Tries the standard file names first, then falls back to searching
    in asn1/external/ and case-insensitive matching.
    """
    # Prefer the asn1/external directory in the checkout (ika-rwth-aachen repo structure)
    external_dir = source_dir / "asn1" / "external"
    if external_dir.exists():
        source_dir = external_dir

    # Map target names to a list of possible source names (case-insensitive fallback)
    _candidates = {
        CDD_FILE: [CDD_FILE, "cdd.asn", "ETSI_ITS_CDD.asn", "etsi_its_cdd.asn"],
        DSRC_FILE: [DSRC_FILE, "dsrc.asn", "DSRC.asn"],
        ERI_FILE: [ERI_FILE, "eri.asn", "ERI.asn"],
    }
    for msg_type, module_file in MSG_TYPE_MODULES.items():
        # Try lower-case variants and underscore variants
        candidates = [module_file]
        # Common naming convention in the ika-rwth repo: cam-pdu-descriptions | etsi_its_cam_ts
        msg_prefix = msg_type.lower().replace("em", "_ts")  # e.g. mapem -> map_ts
        candidates.append(module_file.lower())
        candidates.append(f"{msg_type.lower()}.asn")
        candidates.append(f"etsi_its_{msg_type.lower()}.asn")
        candidates.append(f"etsi_its_{msg_type.lower()}_ts.asn")
        _candidates[module_file] = list(dict.fromkeys(candidates))

    copied = 0
    needed_files = {CDD_FILE, DSRC_FILE, ERI_FILE, *MSG_TYPE_MODULES.values()}

    # Flat case-insensitive index of all files under source_dir
    file_index_lower: dict[str, list[Path]] = {}
    for candidate in source_dir.rglob("*.asn"):
        key = candidate.name.lower()
        file_index_lower.setdefault(key, []).append(candidate)

    for target_name in sorted(needed_files):
        target_path = target_dir / target_name

        # 1) Exact match
        exact = list(source_dir.rglob(target_name))
        if exact:
            shutil.copy2(exact[0], target_path)
            copied += 1
            continue

        # 2) Case-insensitive match via index
        source_name = next(
            (
                name
                for name in (file_index_lower.get(k) for k in _candidates.get(target_name, [target_name]) if k)
                if name
            ),
            None,
        )
        if source_name:
            shutil.copy2(source_name[0], target_path)
            copied += 1
            continue

        logger.debug("Schema file %s not found in checkout", target_name)

    return copied


def _invalidate_schema_caches() -> None:
    """Drop in-memory and on-disk compiled schema caches after schema updates."""
    _compiled_schemas.clear()
    if not SCHEMA_CACHE_DIR.exists():
        return
    for cache_path in SCHEMA_CACHE_DIR.glob("*.pkl"):
        try:
            cache_path.unlink()
        except OSError as exc:
            logger.debug("Could not remove schema cache %s: %s", cache_path.name, exc)


def get_compiled_schema(msg_type: str) -> object | None:
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

    cache_key = _cache_key(msg_type, schema_files)
    cache_path = SCHEMA_CACHE_DIR / f"{msg_type}_{cache_key}.pkl"
    if cache_path.exists():
        cached = _load_compiled_from_disk(cache_path)
        if cached is not None:
            _compiled_schemas[msg_type] = cached
            logger.debug("Loaded cached ASN.1 schema for %s from %s", msg_type, cache_path.name)
            return cached

    try:
        file_paths = [str(f) for f in schema_files]
        compiled = asn1tools.compile_files(file_paths, "uper")
        _compiled_schemas[msg_type] = compiled
        _save_compiled_to_disk(cache_path, compiled)
        logger.info("Compiled ASN.1 schema for %s from %d files", msg_type, len(file_paths))
        return compiled
    except Exception as e:
        _decoding_errors[f"compile:{msg_type}:{type(e).__name__}"] += 1
        logger.error("Failed to compile ASN.1 schema for %s: %s", msg_type, e)
        return None


def decode_its_message(msg_type: str, payload: bytes) -> dict | None:
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
        _decoding_errors[f"decode:{msg_type}:{type(e).__name__}"] += 1
        logger.debug("ASN.1 decode failed for %s (%s): %s", msg_type, asn1_type_name, e)
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
