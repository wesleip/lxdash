"""Router for LXD host onboarding.

Endpoints (admin-only):

* ``GET  /bootstrap/status``   — report whether the local LXD daemon is
  uninitialized, untrusted, or already initialized, and whether it is already
  registered as a host.
* ``POST /bootstrap/register`` — adopt the **existing** local daemon: verify it
  answers on the LXD REST API and store a ``hosts`` row. This is the path for
  the common case of a host that already runs containers.
* ``POST /bootstrap/cluster``  — drive ``POST /1.0/cluster`` with a preseed
  body to create the *first* node of a new cluster, then register it.

Both registering endpoints are idempotent in spirit: registering a daemon that
is already registered returns the existing host instead of a duplicate row.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Response, status

from dependencies import AdminUser, DBDep
from models.host import ConnectionType, Host
from schemas.bootstrap import BootstrapRequest, BootstrapResult, BootstrapStatus
from schemas.host import HostRegisterRequest
from services.audit_service import record_and_notify
from services.host_service import (
    HostConflictError,
    default_host_name,
    register_host,
)
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
async def bootstrap_status(db: DBDep, _admin: AdminUser) -> BootstrapStatus:
    """Return whether the local LXD daemon is uninitialized, untrusted, or ready.

    ``host_id`` is set when the daemon is already registered, which lets the
    wizard send the operator straight to the panel instead of asking them to
    bootstrap a daemon that is already running.
    """
    bootstrap = LXDBootstrap.instance()
    try:
        info = await bootstrap.check_status()
    except LXDBootstrapError as exc:
        logger.warning("bootstrap.unreachable", socket=bootstrap.socket_path, error=str(exc))
        return BootstrapStatus(
            state="unreachable",
            socket=bootstrap.socket_path,
            message=str(exc),
        )

    existing: Host | None = db.query(Host).filter(Host.address == bootstrap.socket_path).first()

    return BootstrapStatus(
        state=info.state,
        api_version=info.api_version,
        server=info.server,
        clustered=info.clustered,
        server_name=info.server_name,
        socket=bootstrap.socket_path,
        host_id=existing.id if existing else None,
        host_name=existing.name if existing else None,
    )


# ---------------------------------------------------------------------------
# POST /bootstrap/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=BootstrapResult,
    status_code=status.HTTP_201_CREATED,
    summary="Register the already-initialized local LXD daemon",
)
async def bootstrap_register(
    body: HostRegisterRequest,
    db: DBDep,
    admin: AdminUser,
    response: Response,
) -> BootstrapResult:
    """Adopt the local daemon without touching its configuration.

    Refuses with HTTP 502 when the daemon cannot be reached at all, and with
    HTTP 409 when there is nothing to adopt yet — an uninitialized daemon
    belongs to ``POST /bootstrap/cluster``, and an untrusted cluster needs
    ``lxc config trust add`` on the host.

    The operation is idempotent: registering a daemon that already has a
    ``hosts`` row answers 200 with that row instead of failing, so the operator
    (or the startup hook) can retry freely.
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

    if info.state == "uninitialized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The LXD daemon has not been initialized yet, so there is "
            "nothing to register. Use POST /bootstrap/cluster to create the "
            "first node of a new cluster.",
        )
    if info.state == "untrusted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LXD cluster exists but our client certificate is not trusted. "
            "Run 'lxc config trust add' on the host to trust this client.",
        )

    existing: Host | None = db.query(Host).filter(Host.address == bootstrap.socket_path).first()
    if existing is not None:
        logger.info("host.register.noop", host_id=existing.id, host_name=existing.name)
        response.status_code = status.HTTP_200_OK
        return BootstrapResult(
            state="initialized",
            host_id=existing.id,
            host_name=existing.name,
            address=existing.address,
            connection_type=existing.connection_type,
            is_active=existing.is_active,
            created_at=existing.created_at,
        )

    host_name = body.host_name or default_host_name(info.server_name)
    try:
        host = register_host(
            db,
            name=host_name,
            address=bootstrap.socket_path,
            connection_type=ConnectionType.socket,
        )
    except HostConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc} Pick a different name in the request body.",
        ) from exc

    await record_and_notify(
        db,
        user=admin,
        action="host.register",
        resource_type="host",
        resource_name=host.name,
        host_id=host.id,
        detail={
            "address": host.address,
            "api_version": info.api_version,
            "clustered": info.clustered,
        },
    )

    logger.info(
        "host.register.success",
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

    Only valid on a daemon that has never been initialized: ``/1.0/cluster``
    creates the cluster, it does not adopt one. Refuses with HTTP 409 when the
    daemon is already initialized (use ``POST /bootstrap/register``) or when a
    cluster exists but our client certificate is not trusted. The cluster join
    for additional nodes remains operator-driven (``lxc cluster add``) until
    Phase 3.
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
            detail="LXD daemon is already initialized, so there is no cluster to "
            "bootstrap. Register the existing host with POST /bootstrap/register, "
            "or add a remote host with POST /hosts.",
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
    try:
        host = register_host(
            db,
            name=body.host_name,
            address=bootstrap.socket_path,
            connection_type=ConnectionType.socket,
        )
    except HostConflictError as exc:
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
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc} Pick a different host_name in the request body.",
        ) from exc

    await record_and_notify(
        db,
        user=admin,
        action="host.bootstrap",
        resource_type="host",
        resource_name=host.name,
        host_id=host.id,
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
