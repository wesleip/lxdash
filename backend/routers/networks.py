from __future__ import annotations

from typing import List

import structlog
from fastapi import APIRouter, HTTPException, status

from dependencies import CurrentUser, DBDep, LXDDep
from schemas.network import NetworkCreate, NetworkResponse
from services.audit_service import log_action
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/networks", tags=["networks"])
logger = structlog.get_logger(__name__)


def _network_to_response(net) -> NetworkResponse:  # noqa: ANN001
    return NetworkResponse(
        name=net.name,
        description=getattr(net, "description", ""),
        type=net.type,
        config=dict(net.config),
        managed=net.managed,
        status=getattr(net, "status", ""),
        locations=list(getattr(net, "locations", [])),
        used_by=list(getattr(net, "used_by", [])),
    )


# ---------------------------------------------------------------------------
# GET /networks
# ---------------------------------------------------------------------------

@router.get("", response_model=List[NetworkResponse])
async def list_networks(
    lxd: LXDDep,
    current_user: CurrentUser,
) -> List[NetworkResponse]:
    """List all networks on the LXD host."""
    try:
        networks = await lxd.list_networks()
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [_network_to_response(n) for n in networks]


# ---------------------------------------------------------------------------
# POST /networks
# ---------------------------------------------------------------------------

@router.post("", response_model=NetworkResponse, status_code=status.HTTP_201_CREATED)
async def create_network(
    body: NetworkCreate,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> NetworkResponse:
    """Create a new managed network bridge."""
    config = {
        "name": body.name,
        "description": body.description,
        "type": body.type,
        "config": body.config,
    }
    try:
        network = await lxd.create_network(config)
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="network.create",
            resource_type="network",
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
        action="network.create",
        resource_type="network",
        resource_name=body.name,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()
    return _network_to_response(network)


# ---------------------------------------------------------------------------
# DELETE /networks/{name}
# ---------------------------------------------------------------------------

@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_network(
    name: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> None:
    """Delete a managed network by name."""
    try:
        await lxd.delete_network(name)
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="network.delete",
            resource_type="network",
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
        action="network.delete",
        resource_type="network",
        resource_name=name,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()
