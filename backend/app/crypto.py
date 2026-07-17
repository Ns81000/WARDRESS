"""Encryption-at-rest for stored credentials (master prompt §6/§9).

Notification-channel configs, SMTP passwords, bot tokens, and LLM API
keys are Fernet-encrypted before they touch the database. The Fernet key
is derived (SHA-256 -> urlsafe base64) from CREDENTIALS_ENCRYPTION_KEY,
which install.ps1 generates as a random string — deriving means any
sufficiently-random string works as the env value, with no base64
formatting requirement leaking into the installer.

A missing key fails loudly at first use (rule: secrets never fall back
to something guessable). A wrong key surfaces as DecryptionError, which
callers treat as "credential unavailable" — never a crash mid-scan.
"""

import base64
import hashlib
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class DecryptionError(Exception):
    """Stored ciphertext could not be decrypted (wrong/rotated key or
    corrupt value). Callers must degrade, not crash."""


@lru_cache
def _fernet() -> Fernet:
    raw = get_settings().credentials_encryption_key
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise DecryptionError("stored credential could not be decrypted") from exc


def encrypt_json(value: dict) -> str:
    return encrypt_text(json.dumps(value, separators=(",", ":")))


def decrypt_json(ciphertext: str) -> dict:
    try:
        parsed = json.loads(decrypt_text(ciphertext))
    except DecryptionError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DecryptionError("stored credential is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise DecryptionError("stored credential is not a JSON object")
    return parsed
