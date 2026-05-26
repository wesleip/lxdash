from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class ContainerNetworkAddress(BaseModel):
    family: str        # "inet" | "inet6"
    address: str
    netmask: str
    scope: str         # "global" | "link" | "local"


class ContainerNetworkInterface(BaseModel):
    name: str
    addresses: List[ContainerNetworkAddress] = []
    mac_address: str = ""
    mtu: int = 1500
    state: str = ""    # "up" | "down"


class ContainerCpuUsage(BaseModel):
    usage: int = 0  # nanoseconds


class ContainerMemoryUsage(BaseModel):
    usage: int = 0     # bytes
    usage_peak: int = 0
    swap_usage: int = 0
    swap_usage_peak: int = 0


class ContainerStats(BaseModel):
    cpu: ContainerCpuUsage = ContainerCpuUsage()
    memory: ContainerMemoryUsage = ContainerMemoryUsage()
    network: Dict[str, ContainerNetworkInterface] = {}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ContainerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$")
    image: str = Field(..., description="Image alias or fingerprint, e.g. 'ubuntu:22.04'")
    host_id: int = Field(..., description="ID of the Host record to create the container on")
    profiles: List[str] = Field(default=["default"])
    config: Dict[str, Any] = Field(default_factory=dict)
    devices: Dict[str, Any] = Field(default_factory=dict)
    ephemeral: bool = False
    start_after_create: bool = True


class ContainerActionRequest(BaseModel):
    """Optional body for start/stop/restart — allows passing a timeout."""
    timeout: int = Field(default=30, ge=1, le=300)
    force: bool = False


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ContainerStatus(BaseModel):
    status: str           # "Running" | "Stopped" | "Frozen" | …
    status_code: int
    pid: Optional[int] = None


class ContainerResponse(BaseModel):
    name: str
    status: str
    status_code: int
    type: str             # "container" | "virtual-machine"
    profiles: List[str] = []
    config: Dict[str, Any] = {}
    architecture: str = ""
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    location: str = ""    # cluster member name
    # Populated only when fetching a single container with ?stats=true
    stats: Optional[ContainerStats] = None
