"""Router for the LXD host registry.

Endpoints:

* ``GET    /hosts``              — list registered hosts (any authenticated user)
* ``POST   /hosts``              — register a host after proving we can reach it (admin)
* ``DELETE /hosts/{id}``         — forget a host (admin)
* ``GET    /hosts/{id}/health``  — probe the daemon through the LXD REST API

Registering a host is deliberately the only way to give the app access to a
daemon: nothing about LXD's state is replicated into our database, so the row
holds connection details only (address, transport, TLS material).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Response, status

from dependencies import AdminUser, CurrentUser, DBDep
from models.host import Host
from schemas.host import HostCreate, HostHealth, HostMetrics, HostResponse
from services.audit_service import record_and_notify
from services.host_service import (
    HostConflictError,
    probe_host,
    register_host,
)
from services.lxd_probe import LXDProbeError, fetch_resources, fetch_server_info

router = APIRouter(prefix="/hosts", tags=["hosts"])
logger = structlog.get_logger(__name__)


def _get_host_or_404(db, host_id: int) -> Host:
    host: Host | None = db.query(Host).filter(Host.id == host_id).first()
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found.",
        )
    return host


# ---------------------------------------------------------------------------
# GET /hosts
# ---------------------------------------------------------------------------


@router.get("", response_model=list[HostResponse], summary="List registered LXD hosts")
async def list_hosts(db: DBDep, current_user: CurrentUser) -> list[Host]:
    """Return every registered host, active or not, ordered by ID."""
    return db.query(Host).order_by(Host.id).all()


# ---------------------------------------------------------------------------
# POST /hosts
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=HostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an LXD host",
)
async def create_host(body: HostCreate, db: DBDep, admin: AdminUser) -> Host:
    """Register a host, rejecting it when the LXD API cannot be reached.

    The connectivity probe is what makes a stored ``hosts`` row trustworthy:
    without it a typo in the address would only surface later as a 502 on
    every container listing.
    """
    if not body.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A host must be registered active; deactivate it instead of "
            "registering it inactive.",
        )

    try:
        info = await fetch_server_info(
            body.address,
            body.connection_type.value,
            cert_pem=body.tls_cert,
            key_pem=body.tls_key,
            server_cert_pem=body.tls_server_cert,
        )
    except LXDProbeError as exc:
        await record_and_notify(
            db,
            user=admin,
            action="host.create",
            resource_type="host",
            resource_name=body.name,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cannot reach the LXD API at {body.address}: {exc}",
        ) from exc

    try:
        host = register_host(
            db,
            name=body.name,
            address=body.address,
            connection_type=body.connection_type,
            tls_cert=body.tls_cert,
            tls_key=body.tls_key,
            tls_server_cert=body.tls_server_cert,
            is_active=body.is_active,
        )
    except HostConflictError as exc:
        await record_and_notify(
            db,
            user=admin,
            action="host.create",
            resource_type="host",
            resource_name=body.name,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await record_and_notify(
        db,
        user=admin,
        action="host.create",
        resource_type="host",
        resource_name=host.name,
        host_id=host.id,
        detail={
            "address": host.address,
            "connection_type": host.connection_type.value,
            "api_version": info.api_version,
            "clustered": info.clustered,
        },
    )
    return host


# ---------------------------------------------------------------------------
# DELETE /hosts/{host_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{host_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a host from the registry",
)
async def delete_host(host_id: int, db: DBDep, admin: AdminUser) -> Response:
    """Forget a host. Containers, images and pools it holds are untouched — they live in LXD."""
    host = _get_host_or_404(db, host_id)
    name = host.name
    db.delete(host)
    db.commit()
    await record_and_notify(
        db,
        user=admin,
        action="host.delete",
        resource_type="host",
        resource_name=name,
        detail={"host_id": host_id},
    )
    logger.info("host.deleted", host_id=host_id, host_name=name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /hosts/{host_id}/health
# ---------------------------------------------------------------------------


@router.get(
    "/{host_id}/health",
    response_model=HostHealth,
    summary="Probe a host through the LXD REST API",
)
async def host_health(host_id: int, db: DBDep, current_user: CurrentUser) -> HostHealth:
    """Report what the daemon says about itself.

    Answers 200 with ``reachable: false`` when the daemon is down, so a panel
    can render a mixed fleet instead of failing the whole request. Only an
    unknown ``host_id`` is an error.
    """
    host = _get_host_or_404(db, host_id)

    base = {
        "host_id": host.id,
        "host_name": host.name,
        "address": host.address,
        "connection_type": host.connection_type,
    }

    try:
        described = await probe_and_describe(host)
    except LXDProbeError as exc:
        logger.warning("host.health_failed", host_id=host.id, error=str(exc))
        return HostHealth(**base, reachable=False, message=str(exc))

    return HostHealth(**base, **described)


async def probe_and_describe(host: Host) -> dict:
    """Probe *host* and flatten the answer into ``HostHealth`` fields.

    ``GET /1.0/resources`` is best-effort: daemons that do not expose it (or
    clients whose certificate lacks the permission) still get a full answer
    from ``/1.0`` and ``/1.0/cluster``.
    """
    info = await probe_host(host)

    described: dict = {
        "reachable": True,
        "api_version": info.api_version,
        "api_extensions_count": len(info.api_extensions),
        "server": info.server,
        "public": info.public,
        "auth": info.auth,
        "auth_user_method": info.auth_user_method,
        "clustered": info.clustered,
        "server_name": info.server_name,
        "certificate_fingerprint": info.certificate_fingerprint,
    }

    try:
        resources = await fetch_resources(
            host.address,
            host.connection_type.value,
            cert_pem=host.tls_cert,
            key_pem=host.tls_key,
            server_cert_pem=host.tls_server_cert,
        )
    except LXDProbeError as exc:
        logger.debug("host.resources_unavailable", host_id=host.id, error=str(exc))
        return described

    return described | {
        "architecture": resources.architecture,
        "os_name": resources.os_name,
        "os_version": resources.os_version,
        "hostname": resources.hostname,
        "cpu_total": resources.cpu_total,
        "memory_total": resources.memory_total,
    }


# ---------------------------------------------------------------------------
# GET /hosts/{host_id}/metrics
# ---------------------------------------------------------------------------


@router.get(
    "/{host_id}/metrics",
    response_model=HostMetrics,
    summary="Get real-time host metrics",
)
async def host_metrics(host_id: int, db: DBDep, current_user: CurrentUser) -> HostMetrics:
    """Return real-time metrics for the host.

    Sources data from the LXD API (``GET /1.0/resources``) and returns
    CPU, memory, disk, and network usage. Answers 200 with ``reachable: false``
    when the daemon is down.
    """
    host = _get_host_or_404(db, host_id)

    base = {
        "host_id": host.id,
        "host_name": host.name,
    }

    try:
        resources = await fetch_resources(
            host.address,
            host.connection_type.value,
            cert_pem=host.tls_cert,
            key_pem=host.tls_key,
            server_cert_pem=host.tls_server_cert,
        )
    except LXDProbeError as exc:
        logger.warning("host.metrics_failed", host_id=host.id, error=str(exc))
        return HostMetrics(**base, reachable=False, message=str(exc))

    cpu = resources.cpu_total
    memory = resources.memory_total

    return HostMetrics(
        **base,
        reachable=True,
        cpu_usage=None,
        cpu_total=cpu,
        memory_used=None,
        memory_total=memory,
        disk_used=None,
        disk_total=None,
        network_bytes_received=None,
        network_bytes_sent=None,
    )
