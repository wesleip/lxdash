from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class NetworkCreate(BaseModel):
    # The host is selected via the `host_id` query parameter; the body field is
    # accepted for backwards compatibility but ignored, so it must not be
    # required.
    host_id: int | None = Field(default=None, description="Deprecated: use ?host_id= instead")
    name: str = Field(
        ..., min_length=1, max_length=15, description="Network bridge name, e.g. lxdbr1"
    )
    description: str = ""
    type: str = Field(default="bridge", description="Network type: bridge | macvlan | sriov | …")
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "ipv4.address": "auto",
            "ipv4.nat": "true",
            "ipv6.address": "none",
        }
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class NetworkLeaseEntry(BaseModel):
    hostname: str
    address: str
    hwaddr: str
    type: str  # "static" | "dynamic"


class NetworkResponse(BaseModel):
    name: str
    description: str
    type: str
    config: dict[str, Any] = {}
    managed: bool
    status: str  # "Created" | "Pending" | "Errored"
    locations: list[str] = []
    used_by: list[str] = []  # list of container/profile URLs
