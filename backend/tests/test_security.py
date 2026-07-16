"""Security-primitive unit tests: Argon2id hashing and JWT lifecycle."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from app.config import get_settings
from app.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-passphrase")
    assert h.startswith("$argon2id$")  # §9 mandates Argon2id specifically
    assert verify_password(h, "s3cret-passphrase")
    assert not verify_password(h, "wrong")


def test_password_hash_unique_salts() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_garbage_hash_returns_false() -> None:
    assert not verify_password("not-a-hash", "anything")
    assert not verify_password("", "anything")


def test_access_token_roundtrip() -> None:
    uid = uuid.uuid4()
    token = create_access_token(uid, "admin")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == str(uid)
    assert payload["role"] == "admin"


def test_expired_token_rejected() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "type": "access",
        },
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_wrong_signature_rejected() -> None:
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5), "type": "access"},
        "another-secret-that-is-long-enough-0123456789",
        algorithm=JWT_ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_alg_none_rejected() -> None:
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5), "type": "access"},
        key=None,
        algorithm="none",
    )
    assert decode_access_token(token) is None


def test_non_access_type_rejected() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(days=7),
            "type": "refresh",
        },
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_missing_claims_rejected() -> None:
    settings = get_settings()
    token = pyjwt.encode({"foo": "bar"}, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    assert decode_access_token(token) is None


def test_refresh_token_hash_matches() -> None:
    raw, digest = generate_refresh_token()
    assert hash_refresh_token(raw) == digest
    assert len(digest) == 64
    raw2, digest2 = generate_refresh_token()
    assert raw != raw2 and digest != digest2
