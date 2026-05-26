from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _make_token(
    data: Dict[str, Any],
    expires_delta: timedelta,
    token_type: str,
) -> str:
    payload = data.copy()
    now = datetime.now(timezone.utc)
    payload.update(
        {
            "iat": now,
            "exp": now + expires_delta,
            "type": token_type,
        }
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, extra: Optional[Dict[str, Any]] = None) -> str:
    """Create a short-lived JWT access token for *subject* (username or user id)."""
    data: Dict[str, Any] = {"sub": subject}
    if extra:
        data.update(extra)
    return _make_token(
        data,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(subject: str) -> str:
    """Create a long-lived JWT refresh token for *subject*."""
    return _make_token(
        {"sub": subject},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT.

    Raises jose.JWTError (or a subclass) on any validation failure — callers
    are responsible for catching and translating to HTTPException.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def access_token_expires_in_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
