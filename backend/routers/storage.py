from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from dependencies import CurrentUser, DBDep, LXDDep
from services.audit_service import record_and_notify
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/storage", tags=["storage"])
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Local schemas (storage doesn't warrant a separate schemas/storage.py yet)
# ---------------------------------------------------------------------------


class StorageVolumeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    type: str = Field(default="custom", description="Volume type: custom | image | container | …")
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    content_type: str = Field(default="filesystem", description="filesystem | block")


class StorageVolumeResponse(BaseModel):
    name: str
    type: str
    config: dict[str, Any] = {}
    description: str = ""
    content_type: str = ""
    location: str = ""
    used_by: list[str] = []


class StoragePoolResponse(BaseModel):
    name: str
    driver: str
    description: str = ""
    config: dict[str, Any] = {}
    status: str = ""
    locations: list[str] = []
    used_by: list[str] = []


def _pool_to_response(pool) -> StoragePoolResponse:
    return StoragePoolResponse(
        name=pool.name,
        driver=pool.driver,
        description=getattr(pool, "description", ""),
        config=dict(pool.config),
        status=getattr(pool, "status", ""),
        locations=list(getattr(pool, "locations", [])),
        used_by=list(getattr(pool, "used_by", [])),
    )


def _volume_to_response(vol) -> StorageVolumeResponse:
    return StorageVolumeResponse(
        name=vol.name,
        type=vol.type,
        config=dict(vol.config),
        description=getattr(vol, "description", ""),
        content_type=getattr(vol, "content_type", ""),
        location=getattr(vol, "location", ""),
        used_by=list(getattr(vol, "used_by", [])),
    )


# ---------------------------------------------------------------------------
# GET /storage
# ---------------------------------------------------------------------------


@router.get("", response_model=list[StoragePoolResponse])
async def list_storage_pools(
    lxd: LXDDep,
    current_user: CurrentUser,
) -> list[StoragePoolResponse]:
    """List all storage pools on the LXD host."""
    try:
        pools = await lxd.list_storage_pools()
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [_pool_to_response(p) for p in pools]


# ---------------------------------------------------------------------------
# GET /storage/{pool}/volumes
# ---------------------------------------------------------------------------


@router.get("/{pool}/volumes", response_model=list[StorageVolumeResponse])
async def list_volumes(
    pool: str,
    lxd: LXDDep,
    current_user: CurrentUser,
) -> list[StorageVolumeResponse]:
    """List all volumes in a storage pool."""
    try:
        volumes = await lxd.list_storage_volumes(pool)
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [_volume_to_response(v) for v in volumes]


# ---------------------------------------------------------------------------
# POST /storage/{pool}/volumes
# ---------------------------------------------------------------------------


@router.post(
    "/{pool}/volumes",
    response_model=StorageVolumeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_volume(
    pool: str,
    body: StorageVolumeCreate,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> StorageVolumeResponse:
    """Create a custom storage volume in the named pool."""
    volume_config = {
        "name": body.name,
        "type": body.type,
        "config": body.config,
        "description": body.description,
        "content_type": body.content_type,
    }
    try:
        volume = await lxd.create_storage_volume(pool, volume_config)
    except LXDClientError as exc:
        await record_and_notify(
            db,
            user=current_user,
            action="storage_volume.create",
            resource_type="storage_volume",
            resource_name=f"{pool}/{body.name}",
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await record_and_notify(
        db,
        user=current_user,
        action="storage_volume.create",
        resource_type="storage_volume",
        resource_name=f"{pool}/{body.name}",
        host_id=lxd.host_id,
        status="success",
    )
    return _volume_to_response(volume)
