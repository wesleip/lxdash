from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class NetworkCreate(BaseModel):
    host_id: int = Field(..., description="Target LXD host ID")
    name: str = Field(..., min_length=1, max_length=15, description="Network bridge name, e.g. lxdbr1")
    description: str = ""
    type: str = Field(default="bridge", description="Network type: bridge | macvlan | sriov | …")
    config: Dict[str, Any] = Field(
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
    config: Dict[str, Any] = {}
    managed: bool
    status: str  # "Created" | "Pending" | "Errored"
    locations: List[str] = []
    used_by: List[str] = []  # list of container/profile URLs
