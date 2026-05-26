from __future__ import annotations

from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from dependencies import CurrentUser, DBDep, LXDDep, get_lxd_client
from schemas.container import (
    ContainerActionRequest,
    ContainerCreate,
    ContainerResponse,
    ContainerStats,
    ContainerCpuUsage,
    ContainerMemoryUsage,
    ContainerNetworkAddress,
    ContainerNetworkInterface,
)
from services.audit_service import log_action
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/containers", tags=["containers"])
logger = structlog.get_logger(__name__)


def _container_to_response(c) -> ContainerResponse:  # noqa: ANN001
    """Map a pylxd Container object to ContainerResponse."""
    return ContainerResponse(
        name=c.name,
        status=c.status,
        status_code=c.status_code,
        type=getattr(c, "type", "container"),
        profiles=list(c.profiles),
        config=dict(c.config),
        architecture=getattr(c, "architecture", ""),
        created_at=getattr(c, "created_at", None),
        last_used_at=getattr(c, "last_used_at", None),
        location=getattr(c, "location", ""),
    )


# ---------------------------------------------------------------------------
# GET /containers
# ---------------------------------------------------------------------------

@router.get("", response_model=List[ContainerResponse])
async def list_containers(
    lxd: LXDDep,
    current_user: CurrentUser,
) -> List[ContainerResponse]:
    """Return all containers on the specified LXD host."""
    try:
        containers = await lxd.list_containers()
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [_container_to_response(c) for c in containers]


# ---------------------------------------------------------------------------
# GET /containers/{name}
# ---------------------------------------------------------------------------

@router.get("/{name}", response_model=ContainerResponse)
async def get_container(
    name: str,
    lxd: LXDDep,
    current_user: CurrentUser,
    with_stats: bool = Query(default=False, alias="stats"),
) -> ContainerResponse:
    """Return details for a single container, optionally including live stats."""
    try:
        container = await lxd.get_container(name)
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    response = _container_to_response(container)

    if with_stats:
        try:
            state = await lxd.get_container_state(name)
            cpu = ContainerCpuUsage(usage=state.cpu.get("usage", 0))
            mem_data = state.memory
            memory = ContainerMemoryUsage(
                usage=mem_data.get("usage", 0),
                usage_peak=mem_data.get("usage_peak", 0),
                swap_usage=mem_data.get("swap_usage", 0),
                swap_usage_peak=mem_data.get("swap_usage_peak", 0),
            )
            net_ifaces: dict = {}
            for iface_name, iface_data in (state.network or {}).items():
                addresses = [
                    ContainerNetworkAddress(**addr)
                    for addr in iface_data.get("addresses", [])
                ]
                net_ifaces[iface_name] = ContainerNetworkInterface(
                    name=iface_name,
                    addresses=addresses,
                    mac_address=iface_data.get("hwaddr", ""),
                    mtu=iface_data.get("mtu", 1500),
                    state=iface_data.get("state", ""),
                )
            response.stats = ContainerStats(cpu=cpu, memory=memory, network=net_ifaces)
        except LXDClientError:
            # Stats are best-effort; don't fail the whole request.
            pass

    return response


# ---------------------------------------------------------------------------
# POST /containers
# ---------------------------------------------------------------------------

@router.post("", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def create_container(
    body: ContainerCreate,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> ContainerResponse:
    """Create a new container on the specified LXD host."""
    lxd_config = {
        "name": body.name,
        "source": {
            "type": "image",
            "alias": body.image,
        },
        "profiles": body.profiles,
        "config": body.config,
        "devices": body.devices,
        "ephemeral": body.ephemeral,
    }

    try:
        container = await lxd.create_container(lxd_config)
        if body.start_after_create:
            await lxd.start_container(body.name)
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="container.create",
            resource_type="container",
            resource_name=body.name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db,
        user_id=current_user.id,
        action="container.create",
        resource_type="container",
        resource_name=body.name,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()

    return _container_to_response(container)


# ---------------------------------------------------------------------------
# DELETE /containers/{name}
# ---------------------------------------------------------------------------

@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_container(
    name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> None:
    """Stop (if running) and delete a container."""
    try:
        container = await lxd.get_container(name)
        if container.status == "Running":
            await lxd.stop_container(name, force=True)
        await lxd.delete_container(name)
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="container.delete",
            resource_type="container",
            resource_name=name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db,
        user_id=current_user.id,
        action="container.delete",
        resource_type="container",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()


# ---------------------------------------------------------------------------
# POST /containers/{name}/start
# ---------------------------------------------------------------------------

@router.post("/{name}/start", response_model=ContainerResponse)
async def start_container(
    name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
    body: ContainerActionRequest = ContainerActionRequest(),
) -> ContainerResponse:
    try:
        await lxd.start_container(name, timeout=body.timeout, force=body.force)
        container = await lxd.get_container(name)
    except LXDClientError as exc:
        log_action(
            db, user_id=current_user.id, action="container.start",
            resource_type="container", resource_name=name,
            host_id=lxd.host_id, status="failure", detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db, user_id=current_user.id, action="container.start",
        resource_type="container", resource_name=name,
        host_id=lxd.host_id, status="success",
    )
    db.commit()
    return _container_to_response(container)


# ---------------------------------------------------------------------------
# POST /containers/{name}/stop
# ---------------------------------------------------------------------------

@router.post("/{name}/stop", response_model=ContainerResponse)
async def stop_container(
    name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
    body: ContainerActionRequest = ContainerActionRequest(),
) -> ContainerResponse:
    try:
        await lxd.stop_container(name, timeout=body.timeout, force=body.force)
        container = await lxd.get_container(name)
    except LXDClientError as exc:
        log_action(
            db, user_id=current_user.id, action="container.stop",
            resource_type="container", resource_name=name,
            host_id=lxd.host_id, status="failure", detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db, user_id=current_user.id, action="container.stop",
        resource_type="container", resource_name=name,
        host_id=lxd.host_id, status="success",
    )
    db.commit()
    return _container_to_response(container)


# ---------------------------------------------------------------------------
# POST /containers/{name}/restart
# ---------------------------------------------------------------------------

@router.post("/{name}/restart", response_model=ContainerResponse)
async def restart_container(
    name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
    body: ContainerActionRequest = ContainerActionRequest(),
) -> ContainerResponse:
    try:
        await lxd.restart_container(name, timeout=body.timeout, force=body.force)
        container = await lxd.get_container(name)
    except LXDClientError as exc:
        log_action(
            db, user_id=current_user.id, action="container.restart",
            resource_type="container", resource_name=name,
            host_id=lxd.host_id, status="failure", detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db, user_id=current_user.id, action="container.restart",
        resource_type="container", resource_name=name,
        host_id=lxd.host_id, status="success",
    )
    db.commit()
    return _container_to_response(container)
