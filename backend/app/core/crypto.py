"""Fernet encryption for stored cloud credentials. Never log plaintext or ciphertext."""
import json
from typing import Any

from cryptography.fernet import Fernet


def _fernet(key: str) -> Fernet:
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt_credentials(key: str, credentials: dict[str, Any]) -> bytes:
    return _fernet(key).encrypt(json.dumps(credentials).encode())


def decrypt_credentials(key: str, token: bytes | None) -> dict[str, Any]:
    if token is None:
        return {}
    return json.loads(_fernet(key).decrypt(bytes(token)))
