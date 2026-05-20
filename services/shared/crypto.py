"""ES256 JWS signing/verification and RFC 8785 JSON canonicalization.

The full AP2 spec uses JWS Detached Content for merchant authorization and
SD-JWT+kb for the checkout mandate. For demo clarity we use plain compact JWS
everywhere; see README for the spec-level differences.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jws
from joserfc.jwk import ECKey

KEYS_DIR = Path(__file__).resolve().parent.parent.parent / "keys"

Party = Literal["user", "merchant", "psp"]


def _load_private(party: Party) -> ECKey:
    pem = (KEYS_DIR / f"{party}.priv.pem").read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    return ECKey.import_key(pem)


def _load_public(party: Party) -> ECKey:
    pem = (KEYS_DIR / f"{party}.pub.pem").read_bytes()
    return ECKey.import_key(pem)


_PRIVATE_CACHE: dict[Party, ECKey] = {}
_PUBLIC_CACHE: dict[Party, ECKey] = {}


def private_key(party: Party) -> ECKey:
    if party not in _PRIVATE_CACHE:
        _PRIVATE_CACHE[party] = _load_private(party)
    return _PRIVATE_CACHE[party]


def public_key(party: Party) -> ECKey:
    if party not in _PUBLIC_CACHE:
        _PUBLIC_CACHE[party] = _load_public(party)
    return _PUBLIC_CACHE[party]


def canonicalize(obj: Any) -> bytes:
    """RFC 8785 JSON Canonicalization (JCS) — required by UCP AP2 extension."""
    return rfc8785.dumps(obj)


def content_hash(obj: Any) -> str:
    """base64url(sha256(JCS(obj))) — used to bind a JWS to a payload."""
    digest = hashlib.sha256(canonicalize(obj)).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(party: Party, payload: dict[str, Any]) -> str:
    """Sign `payload` as an ES256 compact JWS with `iss=party` and `kid=party`."""
    payload = {**payload, "iss": party}
    header = {"alg": "ES256", "typ": "JWT", "kid": party}
    return jws.serialize_compact(header, json.dumps(payload).encode(), private_key(party))


def verify(token: str, expected_issuer: Party) -> dict[str, Any]:
    """Verify ES256 JWS and return the decoded payload.

    Raises ValueError if the signature is invalid or the issuer mismatches.
    """
    try:
        obj = jws.deserialize_compact(token, public_key(expected_issuer))
    except Exception as exc:
        raise ValueError(f"JWS verification failed for {expected_issuer}: {exc}") from exc
    payload = json.loads(obj.payload)
    if payload.get("iss") != expected_issuer:
        raise ValueError(
            f"Issuer mismatch: expected {expected_issuer!r}, got {payload.get('iss')!r}"
        )
    return payload


def decode_unverified(token: str) -> dict[str, Any]:
    """Decode JWS without verifying signature — for UI inspection only."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a compact JWS")
    header_b64, payload_b64, _sig = parts
    pad = lambda s: s + "=" * (-len(s) % 4)
    return {
        "header": json.loads(base64.urlsafe_b64decode(pad(header_b64))),
        "payload": json.loads(base64.urlsafe_b64decode(pad(payload_b64))),
    }
