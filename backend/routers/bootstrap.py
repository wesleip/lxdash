"""Router for first-node LXD cluster bootstrap.

Endpoints (admin-only):

* ``GET  /bootstrap/status`` — report whether the local LXD daemon has been
  initialized yet. Used by the wizard to decide what to show.
* ``POST /bootstrap/cluster`` — drive ``POST /1.0/cluster`` with a preseed
  body. On success, create the first ``hosts`` record so the rest of the
  app is immediately usable.

The endpoint is one-shot: a second call returns HTTP 409 Conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from dependencies import AdminUser, DBDep
from models.host import ConnectionType, Host
from schemas.bootstrap import (
    BootstrapRequest,
    BootstrapResult,
    BootstrapStatus,
)
from services.audit_service import record_and_notify
from services.lxd_bootstrap import LXDBootstrap, LXDBootstrapError

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /bootstrap/status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=BootstrapStatus,
    summary="Detect local LXD daemon bootstrap state",
)
async def bootstrap_status(_admin: AdminUser) -> BootstrapStatus:
    """Return whether the local LXD daemon is uninitialized, untrusted, or ready.

    The wizard uses this to decide which step to render.
    """
    bootstrap = LXDBootstrap.instance()
    try:
        info = await bootstrap.check_status()
    except LXDBootstrapError as exc:
        return BootstrapStatus(
            state="uninitialized",
            socket=bootstrap.socket_path,
            message=str(exc),
        )

    return BootstrapStatus(
        state=info.state,
        api_version=info.api_version,
        server=info.server,
        socket=bootstrap.socket_path,
    )


# ---------------------------------------------------------------------------
# POST /bootstrap/cluster
# ---------------------------------------------------------------------------


@router.post(
    "/cluster",
    response_model=BootstrapResult,
    status_code=status.HTTP_201_CREATED,
    summary="Bootstrap the first node of an LXD cluster",
)
async def bootstrap_cluster(
    body: BootstrapRequest,
    db: DBDep,
    admin: AdminUser,
) -> BootstrapResult:
    """Drive LXD's ``POST /1.0/cluster`` and register the resulting host.

    Refuses with HTTP 409 if the daemon is already initialized, or with
    HTTP 502 if LXD is unreachable. The cluster join for additional nodes
    remains operator-driven (``lxd cluster add``) until Phase 3.
    """
    bootstrap = LXDBootstrap.instance()

    try:
        info = await bootstrap.check_status()
    except LXDBootstrapError as exc:
        logger.error("bootstrap.status_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cannot reach LXD daemon: {exc}",
        ) from exc

    if info.state == "initialized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LXD daemon is already initialized. "
            "To register an existing host, use POST /hosts (Phase 3).",
        )
    if info.state == "untrusted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LXD cluster exists but our client certificate is not trusted. "
            "Run 'lxc config trust add' on the host to trust this client.",
        )

    # State is "uninitialized" — drive the bootstrap.
    try:
        await bootstrap.bootstrap(
            server_name=body.cluster.server_name,
            cluster_password=body.cluster.cluster_password,
        )
    except LXDBootstrapError as exc:
        await record_and_notify(
            db,
            user=admin,
            action="host.bootstrap",
            resource_type="host",
            resource_name=body.host_name,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LXD refused the bootstrap preseed: {exc}",
        ) from exc

    # Register the freshly-bootstrapped host so the rest of the app can use it.
    host = Host(
        name=body.host_name,
        address=bootstrap.socket_path,
        connection_type=ConnectionType.socket,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db.add(host)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        await record_and_notify(
            db,
            user=admin,
            action="host.bootstrap",
            resource_type="host",
            resource_name=body.host_name,
            status="failure",
            detail=f"host name conflict: {exc.orig}",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A host named '{body.host_name}' already exists.",
        ) from exc

    db.refresh(host)

    await record_and_notify(
        db,
        user=admin,
        action="host.bootstrap",
        resource_type="host",
        resource_name=host.name,
        host_id=host.id,
        status="success",
        detail={
            "server_name": body.cluster.server_name,
            "address": host.address,
        },
    )

    logger.info(
        "host.bootstrap.success",
        host_id=host.id,
        host_name=host.name,
        actor=admin.username,
    )

    return BootstrapResult(
        state="initialized",
        host_id=host.id,
        host_name=host.name,
        address=host.address,
        connection_type=host.connection_type,
        is_active=host.is_active,
        created_at=host.created_at,
    )
