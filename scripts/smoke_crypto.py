"""Quick smoke test: sign + verify round-trip across all three parties."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.shared.crypto import canonicalize, content_hash, decode_unverified, sign, verify


def main() -> None:
    obj = {"hello": "world", "n": 42, "list": [3, 1, 2]}
    print("JCS:", canonicalize(obj))
    print("hash:", content_hash(obj))

    for party in ("user", "merchant", "psp"):
        tok = sign(party, {"foo": "bar", "p": party})  # type: ignore[arg-type]
        payload = verify(tok, party)  # type: ignore[arg-type]
        print(f"  {party}: round-trip OK, payload={payload}")
        print(f"           header={decode_unverified(tok)['header']}")

    # Negative case: wrong issuer
    tok = sign("user", {"x": 1})
    try:
        verify(tok, "merchant")
        print("  ERROR: should have rejected wrong issuer")
    except ValueError as e:
        print(f"  rejected wrong issuer as expected: {e}")


if __name__ == "__main__":
    main()
