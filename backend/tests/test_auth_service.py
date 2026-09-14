"""Tests for services.auth_service: password hashing and JWT helpers."""

from __future__ import annotations

import time
from datetime import UTC

import pytest
from jose import JWTError


def test_hash_password_is_not_plaintext():
    from services.auth_service import hash_password

    plain = "correct horse battery staple"
    hashed = hash_password(plain)
    assert hashed != plain
    assert hashed.startswith("$2")  # bcrypt marker


def test_verify_password_accepts_correct_plain():
    from services.auth_service import hash_password, verify_password

    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_password_rejects_wrong_plain():
    from services.auth_service import hash_password, verify_password

    hashed = hash_password("hunter2")
    assert verify_password("hunter3", hashed) is False


def test_access_token_roundtrip():
    from services.auth_service import create_access_token, decode_token

    token = create_access_token("alice")
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    from services.auth_service import create_refresh_token, decode_token

    token = create_refresh_token("alice")
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_token_rejects_garbage():
    from services.auth_service import decode_token

    with pytest.raises(JWTError):
        decode_token("not-a-real-jwt")


def test_decode_token_rejects_tampered_signature():
    from services.auth_service import create_access_token, decode_token

    token = create_access_token("alice")
    # Flip the last char of the signature segment
    head, mid, sig = token.split(".")
    tampered = f"{head}.{mid}.{sig[:-1]}A" if sig else token
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_decode_token_rejects_expired():
    """Force expiry by using a token issued in the far past."""
    from datetime import datetime, timedelta

    from jose import jwt

    from config import get_settings

    settings = get_settings()
    past = datetime.now(UTC) - timedelta(days=1)
    payload = {"sub": "alice", "type": "access", "iat": past, "exp": past + timedelta(seconds=10)}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    from services.auth_service import decode_token

    with pytest.raises(JWTError):
        decode_token(token)


def test_access_token_has_reasonable_expiry_window():
    """Sanity check: tokens don't expire instantly and don't last forever."""
    from services.auth_service import create_access_token, decode_token

    issued_at = time.time()
    token = create_access_token("alice")
    payload = decode_token(token)
    exp = payload["exp"]
    # Default ACCESS_TOKEN_EXPIRE_MINUTES is 15 -> 900s
    assert 60 <= (exp - issued_at) <= 60 * 60
