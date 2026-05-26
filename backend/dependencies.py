from __future__ import annotations

from typing import Annotated, Generator, Optional

import structlog
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from config import get_settings
from database import SessionLocal
from models.host import Host
from models.user import User
from services.auth_service import decode_token
from services.lxd_client import LXDClient, LXDClientError
from services.lxd_client_mock import MockLXDClient

settings = get_settings()
logger = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


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
        raise credentials_exc

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


# ---------------------------------------------------------------------------
# LXD client
# ---------------------------------------------------------------------------

async def get_lxd_client(
    db: DBDep,
    current_user: CurrentUser,
    host_id: Annotated[Optional[int], Query(description="LXD host ID")] = None,
) -> LXDClient | MockLXDClient:
    """Return a connected LXDClient (or MockLXDClient when LXD_MOCK=true).

    Raises HTTP 404 if the host does not exist or is inactive,
    HTTP 502 if the connection to LXD fails.
    """
    if settings.LXD_MOCK:
        return MockLXDClient()

    if host_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query parameter 'host_id' is required.",
        )

    host: Host | None = (
        db.query(Host).filter(Host.id == host_id, Host.is_active.is_(True)).first()
    )
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found.",
        )

    try:
        if host.connection_type.value == "socket":
            return await LXDClient.connect_socket(host.address, host_id=host.id)
        else:
            if not host.tls_cert or not host.tls_key:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Host {host_id} is configured for TLS but has no certificate.",
                )
            return await LXDClient.connect_tls(
                endpoint=host.address,
                cert_pem=host.tls_cert,
                key_pem=host.tls_key,
                server_cert_pem=host.tls_server_cert,
                host_id=host.id,
            )
    except LXDClientError as exc:
        logger.warning("lxd.connect_failed", host_id=host_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to the LXD host.",
        )


LXDDep = Annotated[LXDClient | MockLXDClient, Depends(get_lxd_client)]
