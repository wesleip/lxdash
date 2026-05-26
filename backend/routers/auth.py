from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from dependencies import get_db
from models.user import User
from schemas.user import AccessToken, LoginRequest, Token, TokenRefresh, TokenUser
from services.auth_service import (
    access_token_expires_in_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=Token,
    summary="Obtain access + refresh tokens",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """Authenticate with username + password and receive JWT tokens.

    The form body must be ``application/x-www-form-urlencoded`` with fields
    ``username`` and ``password`` (OAuth2 password flow).
    """
    user: User | None = db.query(User).filter(User.username == form_data.username).first()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        logger.warning("auth.login_failed", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    extra = {"role": user.role.value, "uid": user.id}
    access = create_access_token(subject=user.username, extra=extra)
    refresh = create_refresh_token(subject=user.username)

    logger.info("auth.login_success", username=user.username, user_id=user.id)

    return Token(
        access_token=access,
        refresh_token=refresh,
        expires_in=access_token_expires_in_seconds(),
        user=TokenUser(username=user.username, role=user.role.value),
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=AccessToken,
    summary="Exchange a refresh token for a new access token",
)
async def refresh_token(
    body: TokenRefresh,
    db: Session = Depends(get_db),
) -> AccessToken:
    """Validate the provided refresh token and issue a fresh access token."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise credentials_exc

    if payload.get("type") != "refresh":
        raise credentials_exc

    subject: str | None = payload.get("sub")
    if not subject:
        raise credentials_exc

    user: User | None = db.query(User).filter(User.username == subject).first()
    if user is None or not user.is_active:
        raise credentials_exc

    extra = {"role": user.role.value, "uid": user.id}
    access = create_access_token(subject=user.username, extra=extra)

    return AccessToken(
        access_token=access,
        expires_in=access_token_expires_in_seconds(),
    )
