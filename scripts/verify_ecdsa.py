"""Standalone ECDSA signature verifier for ETSI TS 103 097 V2X messages.

Optional — requires the `cryptography` package:

    pip install cryptography

Usage:
    python scripts/verify_ecdsa.py --help

References:
    - ETSI TS 103 097 V2.2.1
    - IEEE 1609.2
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature
except ImportError as exc:  # pragma: no cover
    print(
        "Fehler: 'cryptography' ist nicht installiert.\nInstalliere es mit: pip install cryptography",
        file=sys.stderr,
    )
    sys.exit(1)

from pcap2kml_player.pcap_parser import parse_pcap
from pcap2kml_player.data_model import SessionData

logger = logging.getLogger(__name__)

# ECDSA curve mapping per ETSI TS 103 097
CURVE_NIST_P256 = 0
CURVE_BRAINPOOL_P256 = 1

_CURVES = {
    CURVE_NIST_P256: ec.SECP256R1(),
    CURVE_BRAINPOOL_P256: ec.BrainpoolP256r1(),
}


def verify_signature(
    payload: bytes,
    signer_cert_pem: str,
    signature_algorithm: int = CURVE_NIST_P256,
) -> bool:
    """Verify an ECDSA P-256 / BrainpoolP256r1 signature.

    Args:
        payload: Raw signed payload (including security header).
        signer_cert_pem: Signer certificate in PEM format.
        signature_algorithm: 0=NIST P-256, 1=BrainpoolP256r1.

    Returns:
        True if the signature is valid.

    Raises:
        ValueError: If the certificate or signature format is invalid.
        InvalidSignature: If the signature does not match.
    """
    # Parse certificate to extract public key
    public_key = serialization.load_pem_public_key(signer_cert_pem.encode())

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("Certificate does not contain an ECDSA public key")

    # Determine curve
    curve = _CURVES.get(signature_algorithm)
    if curve is None:
        raise ValueError(f"Unsupported signature algorithm: {signature_algorithm}")

    if public_key.curve.name != curve.name:
        raise ValueError(
            f"Certificate curve {public_key.curve.name} does not match signature algorithm curve {curve.name}"
        )

    # Find signature in payload (last 64 bytes for P-256 after algorithm byte)
    if len(payload) < 65:
        raise ValueError("Payload too short to contain a signature")

    # Signature format: [algorithm byte (1)][R (32 bytes)][S (32 bytes)]
    # Or: [R length (1)][R (32 bytes)][S length (1)][S (32 bytes)]
    algo_byte = payload[-65]
    if algo_byte != signature_algorithm:
        logger.warning(
            "Algorithm byte mismatch: expected %d, got %d",
            signature_algorithm,
            algo_byte,
        )

    r_bytes = payload[-64:-32]
    s_bytes = payload[-32:]

    # Construct DER signature (r, s concatenated = raw) → ECDSA signature
    signature = r_bytes + s_bytes

    # The 'to-be-signed' data is everything before the signature
    tbs_data = payload[:-65]

    try:
        public_key.verify(signature, tbs_data, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify ECDSA signatures in V2X PCAP files.")
    parser.add_argument("pcap", type=Path, help="Path to the PCAP file")
    parser.add_argument("--cert", type=Path, required=True, help="Signer certificate (PEM)")
    parser.add_argument(
        "--curve",
        choices=["nist-p256", "brainpool-p256"],
        default="nist-p256",
        help="ECDSA curve (default: nist-p256)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = _build_argparser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if not args.pcap.exists():
        parser.error(f"PCAP file not found: {args.pcap}")
    if not args.cert.exists():
        parser.error(f"Certificate file not found: {args.cert}")

    cert_pem = args.cert.read_text(encoding="utf-8")
    session = SessionData()
    parse_pcap(str(args.pcap), session)

    if not session.messages:
        print("Keine Nachrichten gefunden.", file=sys.stderr)
        return 1

    curve_code = CURVE_BRAINPOOL_P256 if args.curve == "brainpool-p256" else CURVE_NIST_P256

    verified = 0
    failed = 0
    for msg in session.messages:
        if not msg.raw_payload or len(msg.raw_payload) < 65:
            continue
        try:
            ok = verify_signature(msg.raw_payload, cert_pem, curve_code)
            if ok:
                verified += 1
            else:
                failed += 1
        except Exception as exc:
            logger.debug("Verification error for %s: %s", msg.station_id, exc)
            failed += 1

    print(f"Ergebnis: {verified} OK, {failed} fehlgeschlagen")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
