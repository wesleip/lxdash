from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from dependencies import CurrentUser, DBDep, LXDDep
from schemas.container import (
    ContainerActionRequest,
    ContainerCpuUsage,
    ContainerCreate,
    ContainerMemoryUsage,
    ContainerNetworkAddress,
    ContainerNetworkInterface,
    ContainerResponse,
    ContainerStateAddress,
    ContainerStateCounters,
    ContainerStateCpu,
    ContainerStateDisk,
    ContainerStateInterface,
    ContainerStateResponse,
    ContainerStats,
    ContainerSummary,
    SnapshotCreateRequest,
    SnapshotResponse,
)
from services.audit_service import record_and_notify
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/containers", tags=["containers"])
logger = structlog.get_logger(__name__)


def _container_to_response(c) -> ContainerResponse:
    """Map a pylxd Container object to ContainerResponse.

    Optional fields are normalised with ``or`` because pylxd exposes
    ``None`` for them on non-clustered daemons — its own
    ``Instance.__setattr__`` forces ``location = None`` when
    ``client.server_clustered`` is false. A pydantic field default
    (``= ""``) does not save us: it only applies when the key is
    absent, and the mapper passes the value explicitly.
    """
    return ContainerResponse(
        name=c.name,
        status=c.status,
        status_code=c.status_code,
        type=getattr(c, "type", None) or "container",
        profiles=list(c.profiles),
        config=dict(c.config),
        architecture=getattr(c, "architecture", None) or "",
        created_at=getattr(c, "created_at", None),
        last_used_at=getattr(c, "last_used_at", None),
        location=getattr(c, "location", None) or "",
    )


def _extract_image(c) -> str:
    """Best-effort human-readable image label from the instance config.

    LXD writes ``image.description`` (``"Ubuntu 22.04 LTS"``) at create time
    when the source is an image. ``image.os`` is a coarser fallback (e.g.
    ``"ubuntu"``). ``expanded_config`` is the resolved config — pylxd exposes
    it on every instance regardless of project — and ``config`` is the raw
    override map. We prefer ``expanded_config`` because the operator may
    unset image keys in ``config`` without losing the source label.
    """
    config = getattr(c, "expanded_config", None) or getattr(c, "config", None) or {}
    if not isinstance(config, dict):
        return ""
    return config.get("image.description") or config.get("image.os") or ""


def _extract_ips(state) -> tuple[str | None, str | None]:
    """First global-scoped inet/inet6 address from the instance state.

    ``state.network`` is the dict returned by LXD's
    ``GET /1.0/instances/{name}/state``. Each interface lists addresses that
    carry a ``scope`` (``global``/``link``/``local``) and ``family``
    (``inet``/``inet6``). Link-local ``fe80::`` addresses are useless for the
    panel so we only collect global-scoped entries, picking the first one
    found for each family.
    """
    ipv4: str | None = None
    ipv6: str | None = None
    if state is None:
        return ipv4, ipv6
    network = getattr(state, "network", None) or {}
    if not isinstance(network, dict):
        return ipv4, ipv6
    for info in network.values():
        if not isinstance(info, dict):
            continue
        for addr in info.get("addresses", []) or []:
            if not isinstance(addr, dict):
                continue
            if addr.get("scope") != "global":
                continue
            family = addr.get("family")
            address = addr.get("address")
            if not address:
                continue
            if family == "inet" and ipv4 is None:
                ipv4 = address
            elif family == "inet6" and ipv6 is None:
                ipv6 = address
        if ipv4 is not None and ipv6 is not None:
            break
    return ipv4, ipv6


def _container_to_summary(c, state=None) -> ContainerSummary:
    """Lightweight projection used by ``GET /containers``.

    ``state`` is the live state fetched alongside the list so we can fill
    in the IPv4/IPv6 columns without making the panel issue a second
    request per row.
    """
    ipv4, ipv6 = _extract_ips(state)
    return ContainerSummary(
        name=c.name,
        status=c.status,
        type=getattr(c, "type", None) or "container",
        image=_extract_image(c),
        ipv4=ipv4,
        ipv6=ipv6,
        created_at=getattr(c, "created_at", None),
        last_used_at=getattr(c, "last_used_at", None),
    )


def _state_to_response(container, state) -> ContainerStateResponse:
    """Map a pylxd state object to ContainerStateResponse.

    Every field is read defensively: LXD omits keys (disk on some instance
    types, network while stopped) and pylxd's AttributeDict raises
    AttributeError instead of returning None for a missing key.
    """
    cpu = getattr(state, "cpu", None) or {}
    memory = getattr(state, "memory", None) or {}

    disk = {
        path: ContainerStateDisk(usage=int(info.get("usage", 0)))
        for path, info in (getattr(state, "disk", None) or {}).items()
    }

    network: dict[str, ContainerStateInterface] | None = None
    raw_network = getattr(state, "network", None)
    if raw_network is not None:
        network = {}
        for iface, info in raw_network.items():
            network[iface] = ContainerStateInterface(
                addresses=[ContainerStateAddress(**addr) for addr in info.get("addresses", [])],
                counters=ContainerStateCounters(**info.get("counters", {})),
                hwaddr=info.get("hwaddr", ""),
                host_name=info.get("host_name", ""),
                mtu=int(info.get("mtu", 1500)),
                state=info.get("state", ""),
                type=info.get("type", ""),
            )

    return ContainerStateResponse(
        status=container.status,
        status_code=container.status_code,
        cpu=ContainerStateCpu(
            usage=int(cpu.get("usage", 0)),
            user_time=int(cpu.get("user_time", 0)),
            system_time=int(cpu.get("system_time", 0)),
        ),
        memory=ContainerMemoryUsage(
            usage=int(memory.get("usage", 0)),
            usage_peak=int(memory.get("usage_peak", 0)),
            swap_usage=int(memory.get("swap_usage", 0)),
            swap_usage_peak=int(memory.get("swap_usage_peak", 0)),
        ),
        disk=disk,
        network=network,
        pid=int(getattr(state, "pid", 0) or 0),
        processes=int(getattr(state, "processes", 0) or 0),
    )


def _state_to_response(container, state) -> ContainerStateResponse:
    """Map a pylxd state object to ContainerStateResponse.

    Every field is read defensively: LXD omits keys (disk on some instance
    types, network while stopped) and pylxd's AttributeDict raises
    AttributeError instead of returning None for a missing key.
    """
    cpu = getattr(state, "cpu", None) or {}
    memory = getattr(state, "memory", None) or {}

    disk = {
        path: ContainerStateDisk(usage=int(info.get("usage", 0)))
        for path, info in (getattr(state, "disk", None) or {}).items()
    }

    network: dict[str, ContainerStateInterface] | None = None
    raw_network = getattr(state, "network", None)
    if raw_network is not None:
        network = {}
        for iface, info in raw_network.items():
            network[iface] = ContainerStateInterface(
                addresses=[ContainerStateAddress(**addr) for addr in info.get("addresses", [])],
                counters=ContainerStateCounters(**info.get("counters", {})),
                hwaddr=info.get("hwaddr", ""),
                host_name=info.get("host_name", ""),
                mtu=int(info.get("mtu", 1500)),
                state=info.get("state", ""),
                type=info.get("type", ""),
            )

    return ContainerStateResponse(
        status=container.status,
        status_code=container.status_code,
        cpu=ContainerStateCpu(
            usage=int(cpu.get("usage", 0)),
            user_time=int(cpu.get("user_time", 0)),
            system_time=int(cpu.get("system_time", 0)),
        ),
        memory=ContainerMemoryUsage(
            usage=int(memory.get("usage", 0)),
            usage_peak=int(memory.get("usage_peak", 0)),
            swap_usage=int(memory.get("swap_usage", 0)),
            swap_usage_peak=int(memory.get("swap_usage_peak", 0)),
        ),
        disk=disk,
        network=network,
        pid=int(getattr(state, "pid", 0) or 0),
        processes=int(getattr(state, "processes", 0) or 0),
    )


# ---------------------------------------------------------------------------
# GET /containers
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ContainerSummary])
async def list_containers(
    lxd: LXDDep,
    current_user: CurrentUser,
) -> list[ContainerSummary]:
    """Return a slim summary of every container on the specified LXD host.

    The full ``GET /1.0/instances/{name}`` payload (and the per-instance state
    call) is fetched only by the detail route. Here we only need name, status,
    type, the image label and the first global IPv4/IPv6 — so the list stays
    cheap enough to power the dashboard's 5s poll even on a busy host.

    State is fetched in parallel for every instance. One instance being down
    must not blank the whole list, so each state call is shielded with a
    try/except; the corresponding summary simply reports ``ipv4=None`` and
    the frontend renders "—" for that row.
    """
    try:
        containers = await lxd.list_containers()
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    async def _safe_state(name: str):
        try:
            return await lxd.get_container_state(name)
        except (LXDClientError, Exception) as exc:
            # The list endpoint must stay green when one instance is down:
            # surface a debug log and let the row report ipv4=None.
            logger.debug("container.state_unavailable", name=name, error=str(exc))
            return None

    states = await asyncio.gather(*(_safe_state(c.name) for c in containers))
    return [_container_to_summary(c, state) for c, state in zip(containers, states, strict=False)]


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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
                    ContainerNetworkAddress(**addr) for addr in iface_data.get("addresses", [])
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
# GET /containers/{name}/state
# ---------------------------------------------------------------------------


@router.get("/{name}/state", response_model=ContainerStateResponse)
async def get_container_state(
    name: str,
    lxd: LXDDep,
    current_user: CurrentUser,
) -> ContainerStateResponse:
    """Live state of one container — cpu, memory, disk, network, pid, processes.

    This is the endpoint the Resources tab polls every 5s; it mirrors LXD's own
    GET /1.0/instances/{name}/state, which the frontend used to call through a
    route that did not exist here (404).
    """
    try:
        container = await lxd.get_container(name)
        state = await lxd.get_container_state(name)
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return _state_to_response(container, state)


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
        await record_and_notify(
            db,
            user=current_user,
            action="container.create",
            resource_type="container",
            resource_name=body.name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="container.create",
        resource_type="container",
        resource_name=body.name,
        host_id=lxd.host_id,
        status="success",
    )

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
        await record_and_notify(
            db,
            user=current_user,
            action="container.delete",
            resource_type="container",
            resource_name=name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="container.delete",
        resource_type="container",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )


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
        await record_and_notify(
            db,
            user=current_user,
            action="container.start",
            resource_type="container",
            resource_name=name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="container.start",
        resource_type="container",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )
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
        await record_and_notify(
            db,
            user=current_user,
            action="container.stop",
            resource_type="container",
            resource_name=name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="container.stop",
        resource_type="container",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )
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
        await record_and_notify(
            db,
            user=current_user,
            action="container.restart",
            resource_type="container",
            resource_name=name,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="container.restart",
        resource_type="container",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )
    return _container_to_response(container)


# ---------------------------------------------------------------------------
# GET /containers/{name}/snapshots
# ---------------------------------------------------------------------------


@router.get("/{name}/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots(
    name: str,
    lxd: LXDDep,
    current_user: CurrentUser,
) -> list[SnapshotResponse]:
    """List the snapshots taken for a container."""
    try:
        return await lxd.list_snapshots(name)
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /containers/{name}/snapshots
# ---------------------------------------------------------------------------


@router.post(
    "/{name}/snapshots",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshot(
    name: str,
    body: SnapshotCreateRequest,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> SnapshotResponse:
    """Take a snapshot of a container."""
    try:
        snapshot = await lxd.create_snapshot(
            name,
            body.name,
            stateful=body.stateful,
            expires_at=body.expires_at,
        )
    except LXDClientError as exc:
        await record_and_notify(
            db,
            user=current_user,
            action="snapshot.create",
            resource_type="container",
            resource_name=f"{name}/{body.name}",
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="snapshot.create",
        resource_type="container",
        resource_name=f"{name}/{body.name}",
        host_id=lxd.host_id,
        status="success",
    )
    return snapshot


# ---------------------------------------------------------------------------
# DELETE /containers/{name}/snapshots/{snapshot_name}
# ---------------------------------------------------------------------------


@router.delete(
    "/{name}/snapshots/{snapshot_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_snapshot(
    name: str,
    snapshot_name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> None:
    """Delete one snapshot of a container."""
    try:
        await lxd.delete_snapshot(name, snapshot_name)
    except LXDClientError as exc:
        await record_and_notify(
            db,
            user=current_user,
            action="snapshot.delete",
            resource_type="container",
            resource_name=f"{name}/{snapshot_name}",
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="snapshot.delete",
        resource_type="container",
        resource_name=f"{name}/{snapshot_name}",
        host_id=lxd.host_id,
        status="success",
    )


# ---------------------------------------------------------------------------
# POST /containers/{name}/snapshots/{snapshot_name}/restore
# ---------------------------------------------------------------------------


@router.post(
    "/{name}/snapshots/{snapshot_name}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def restore_snapshot(
    name: str,
    snapshot_name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> None:
    """Roll a container back to a snapshot.

    LXD refuses a non-stateful restore while the instance is running, which
    surfaces here as 502 with the daemon's own message in `detail`.
    """
    try:
        await lxd.restore_snapshot(name, snapshot_name)
    except LXDClientError as exc:
        await record_and_notify(
            db,
            user=current_user,
            action="snapshot.restore",
            resource_type="container",
            resource_name=f"{name}/{snapshot_name}",
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="snapshot.restore",
        resource_type="container",
        resource_name=f"{name}/{snapshot_name}",
        host_id=lxd.host_id,
        status="success",
    )
