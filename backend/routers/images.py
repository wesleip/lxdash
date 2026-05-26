from __future__ import annotations

from typing import List

import structlog
from fastapi import APIRouter, HTTPException, status

from dependencies import CurrentUser, DBDep, LXDDep
from schemas.image import ImageAlias, ImageImport, ImageResponse
from services.audit_service import log_action
from services.lxd_client import LXDClientError

router = APIRouter(prefix="/images", tags=["images"])
logger = structlog.get_logger(__name__)


def _image_to_response(img) -> ImageResponse:  # noqa: ANN001
    """Map a pylxd Image to ImageResponse."""
    aliases = [
        ImageAlias(name=a.get("name", ""), description=a.get("description", ""))
        for a in (img.aliases or [])
    ]
    return ImageResponse(
        fingerprint=img.fingerprint,
        public=img.public,
        description=img.properties.get("description", ""),
        architecture=img.architecture,
        type=getattr(img, "type", "container"),
        size=getattr(img, "size", 0),
        upload_date=str(img.upload_date) if getattr(img, "upload_date", None) else None,
        created_at=str(img.created_at) if getattr(img, "created_at", None) else None,
        expires_at=str(img.expires_at) if getattr(img, "expires_at", None) else None,
        aliases=aliases,
        properties=dict(img.properties),
        profiles=list(getattr(img, "profiles", [])),
        cached=getattr(img, "cached", False),
        auto_update=getattr(img, "auto_update", False),
    )


# ---------------------------------------------------------------------------
# GET /images
# ---------------------------------------------------------------------------

@router.get("", response_model=List[ImageResponse])
async def list_images(
    lxd: LXDDep,
    current_user: CurrentUser,
) -> List[ImageResponse]:
    """List all images cached on the LXD host."""
    try:
        images = await lxd.list_images()
    except LXDClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [_image_to_response(img) for img in images]


# ---------------------------------------------------------------------------
# POST /images/import
# ---------------------------------------------------------------------------

@router.post("/import", response_model=ImageResponse, status_code=status.HTTP_201_CREATED)
async def import_image(
    body: ImageImport,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> ImageResponse:
    """Pull an image from a remote simplestreams server onto the LXD host."""
    try:
        image = await lxd.import_image_from_simplestream(
            server=body.server,
            alias=body.alias,
            local_alias=body.local_alias,
        )
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="image.import",
            resource_type="image",
            resource_name=body.alias,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db,
        user_id=current_user.id,
        action="image.import",
        resource_type="image",
        resource_name=image.fingerprint,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()

    return _image_to_response(image)


# ---------------------------------------------------------------------------
# DELETE /images/{fingerprint}
# ---------------------------------------------------------------------------

@router.delete("/{fingerprint}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_image(
    fingerprint: str,
    lxd: LXDDep,
    db: DBDep,
    current_user: CurrentUser,
) -> None:
    """Delete an image from the LXD host by fingerprint."""
    try:
        await lxd.delete_image(fingerprint)
    except LXDClientError as exc:
        log_action(
            db,
            user_id=current_user.id,
            action="image.delete",
            resource_type="image",
            resource_name=fingerprint,
            host_id=lxd.host_id,
            status="failure",
            detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    log_action(
        db,
        user_id=current_user.id,
        action="image.delete",
        resource_type="image",
        resource_name=fingerprint,
        host_id=lxd.host_id,
        status="success",
    )
    db.commit()
