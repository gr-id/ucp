"""Stub signature helper for the 2nd PoC.

The 2nd PoC abstracts away the cryptographic signing ceremony — we assume the
user (and the merchant) already possess signing devices and the resulting
signature is available as an opaque value. Real production would replace this
with Passkey/WebAuthn, OS keystore, or HSM-backed JWS as proven in the 1st PoC.

This module produces a `StubSignature` carrying a content hash so that downstream
consumers can at least observe "what was signed" without performing real
verification.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from services.shared.mandates import StubSignature


def _content_hash(payload: Any) -> str:
    if payload is None:
        body = ""
    elif isinstance(payload, (dict, list)):
        body = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    elif hasattr(payload, "model_dump"):
        body = json.dumps(payload.model_dump(), sort_keys=True, default=str, ensure_ascii=False)
    else:
        body = str(payload)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def stub_sign(signer: str, payload: Any = None) -> StubSignature:
    """Produce a stub signature for the given signer over the given payload."""
    return StubSignature(
        signer=signer,
        signed_at=int(time.time()),
        payload_hash=_content_hash(payload),
    )
