from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class ContainerNetworkAddress(BaseModel):
    family: str  # "inet" | "inet6"
    address: str
    netmask: str
    scope: str  # "global" | "link" | "local"


class ContainerNetworkInterface(BaseModel):
    name: str
    addresses: list[ContainerNetworkAddress] = []
    mac_address: str = ""
    mtu: int = 1500
    state: str = ""  # "up" | "down"


class ContainerCpuUsage(BaseModel):
    usage: int = 0  # nanoseconds


class ContainerMemoryUsage(BaseModel):
    usage: int = 0  # bytes
    usage_peak: int = 0
    swap_usage: int = 0
    swap_usage_peak: int = 0


class ContainerStats(BaseModel):
    cpu: ContainerCpuUsage = ContainerCpuUsage()
    memory: ContainerMemoryUsage = ContainerMemoryUsage()
    network: dict[str, ContainerNetworkInterface] = {}


# ---------------------------------------------------------------------------
# GET /containers/{name}/state — what the Resources tab polls
# ---------------------------------------------------------------------------


class ContainerStateCpu(BaseModel):
    usage: int = 0  # cumulative CPU time, nanoseconds
    user_time: int = 0
    system_time: int = 0


class ContainerStateDisk(BaseModel):
    usage: int = 0  # bytes


class ContainerStateCounters(BaseModel):
    bytes_received: int = 0
    bytes_sent: int = 0
    packets_received: int = 0
    packets_sent: int = 0


class ContainerStateAddress(BaseModel):
    family: str  # "inet" | "inet6"
    address: str
    netmask: str
    scope: str  # "global" | "link" | "local"


class ContainerStateInterface(BaseModel):
    addresses: list[ContainerStateAddress] = []
    counters: ContainerStateCounters = Field(default_factory=ContainerStateCounters)
    hwaddr: str = ""
    host_name: str = ""
    mtu: int = 1500
    state: str = ""  # "up" | "down"
    type: str = ""


class ContainerStateResponse(BaseModel):
    """Mirror of LXD's GET /1.0/instances/{name}/state, shaped for the UI."""

    status: str
    status_code: int
    cpu: ContainerStateCpu = Field(default_factory=ContainerStateCpu)
    memory: ContainerMemoryUsage = Field(default_factory=ContainerMemoryUsage)
    disk: dict[str, ContainerStateDisk] = {}
    network: dict[str, ContainerStateInterface] | None = None
    pid: int = 0
    processes: int = 0


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ContainerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$")
    image: str = Field(..., description="Image alias or fingerprint, e.g. 'ubuntu:22.04'")
    # The host is selected via the `host_id` query parameter (see
    # dependencies.get_lxd_client); the body field is accepted for
    # backwards compatibility but ignored, so it must not be required.
    host_id: int | None = Field(default=None, description="Deprecated: use ?host_id= instead")
    profiles: list[str] = Field(default=["default"])
    config: dict[str, Any] = Field(default_factory=dict)
    devices: dict[str, Any] = Field(default_factory=dict)
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
    status: str  # "Running" | "Stopped" | "Frozen" | …
    status_code: int
    pid: int | None = None


class ContainerResponse(BaseModel):
    name: str
    status: str
    status_code: int
    type: str  # "container" | "virtual-machine"
    profiles: list[str] = []
    config: dict[str, Any] = {}
    architecture: str = ""
    created_at: str | None = None
    last_used_at: str | None = None
    location: str = ""  # cluster member name
    # Populated only when fetching a single container with ?stats=true
    stats: ContainerStats | None = None
