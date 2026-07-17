"""API-key primitives (§6 api_keys, Phase 5).

Keys look like `wk_<43 urlsafe chars>` — the `wk_` prefix lets the auth
dependency route them away from JWT decoding, and makes accidental
leakage greppable. Only the SHA-256 of the full key is stored (same
rationale as refresh tokens: a DB leak yields nothing usable); the raw
key is returned exactly once, at creation.
"""

import hashlib
import secrets

API_KEY_PREFIX = "wk_"
# Stored display prefix: "wk_" + first 8 chars of the random part.
DISPLAY_PREFIX_CHARS = 8


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, sha256_hex, display_prefix)."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw), raw[: len(API_KEY_PREFIX) + DISPLAY_PREFIX_CHARS]


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def looks_like_api_key(credential: str) -> bool:
    return credential.startswith(API_KEY_PREFIX)
