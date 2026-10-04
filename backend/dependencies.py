from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from database import SessionLocal
from models.user import User, UserRole
from services.auth_service import decode_token
from services.host_service import (
    AmbiguousHostError,
    HostNotFoundError,
    NoHostRegisteredError,
    open_client,
    resolve_host,
)
from services.lxd_client import LXDClient, LXDClientError
from services.lxd_client_mock import MockLXDClient

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DBDep = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBDep,
) -> User:
    """Validate the JWT access token and return the corresponding User.

    Raises HTTP 401 on any token problem, HTTP 403 if the account is inactive.
    Stack traces are never included in the response detail.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
    except JWTError:
        # Don't leak JWT decode errors to the client.
        raise credentials_exc from None

    token_type: str = payload.get("type", "")
    if token_type != "access":
        raise credentials_exc

    subject: str | None = payload.get("sub")
    if subject is None:
        raise credentials_exc

    user: User | None = db.query(User).filter(User.username == subject).first()
    if user is None:
        raise credentials_exc

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> User:
    """Reject non-admin callers with HTTP 403.

    Used by sensitive endpoints like the cluster bootstrap. Phase 4 (RBAC)
    will generalise this into a proper role/permission dependency tree.
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this operation.",
        )
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]


# ---------------------------------------------------------------------------
# LXD client
# ---------------------------------------------------------------------------


async def get_lxd_client(
    db: DBDep,
    current_user: CurrentUser,
    host_id: Annotated[int | None, Query(description="LXD host ID")] = None,
) -> LXDClient | MockLXDClient:
    """Return a connected LXDClient (or MockLXDClient when LXD_MOCK=true).

    ``host_id`` is optional: with a single registered host the request is
    served by it, which keeps a single-host deployment free of a query
    parameter everywhere. As soon as a second host exists the caller must name
    the one it means.

    Host resolution runs before the LXD_MOCK short-circuit on purpose —
    development mode must hit the same registry gate as production, otherwise
    "no host registered" only ever surfaces in production.

    Raises HTTP 409 when no host is registered, HTTP 422 when the choice is
    ambiguous, HTTP 404 when ``host_id`` is unknown, and HTTP 502 when the
    connection to LXD fails.
    """
    try:
        host = resolve_host(db, host_id)
    except NoHostRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except AmbiguousHostError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HostNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    try:
        return await open_client(host)
    except LXDClientError as exc:
        logger.warning("lxd.connect_failed", host_id=host.id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to the LXD host.",
        ) from exc


LXDDep = Annotated[LXDClient | MockLXDClient, Depends(get_lxd_client)]
