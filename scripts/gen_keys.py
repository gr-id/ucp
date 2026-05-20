"""Generate ES256 (P-256) keypairs for user, merchant, and PSP.

Run once before starting the demo. Keys are written to ./keys/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"
PARTIES = ("user", "merchant", "psp")


def generate_one(name: str, force: bool) -> None:
    priv_path = KEYS_DIR / f"{name}.priv.pem"
    pub_path = KEYS_DIR / f"{name}.pub.pem"
    if priv_path.exists() and not force:
        print(f"  [skip] {name} keys already exist")
        return
    key = ec.generate_private_key(ec.SECP256R1())
    priv_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"  [ok]   {name} -> {priv_path.name}, {pub_path.name}")


def main() -> None:
    force = "--force" in sys.argv
    KEYS_DIR.mkdir(exist_ok=True)
    print(f"Writing ES256 keypairs to {KEYS_DIR}")
    for party in PARTIES:
        generate_one(party, force)
    print("Done.")


if __name__ == "__main__":
    main()
