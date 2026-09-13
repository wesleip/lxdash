from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ImageImport(BaseModel):
    """Import an image from a remote simplestreams or LXD server."""

    host_id: int = Field(..., description="Target LXD host ID")
    server: str = Field(
        default="https://images.linuxcontainers.org",
        description="URL of the remote image server",
    )
    alias: str = Field(..., description="Remote image alias, e.g. 'ubuntu/22.04/amd64'")
    local_alias: str | None = Field(
        default=None, description="Alias to assign locally after import"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ImageAlias(BaseModel):
    name: str
    description: str = ""


class ImageResponse(BaseModel):
    fingerprint: str
    public: bool
    description: str
    architecture: str
    type: str  # "container" | "virtual-machine"
    size: int = 0  # bytes
    upload_date: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    aliases: list[ImageAlias] = []
    properties: dict[str, Any] = {}
    profiles: list[str] = []
    cached: bool = False
    auto_update: bool = False
