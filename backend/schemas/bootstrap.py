"""Schemas for the first-node bootstrap endpoint.

Used by an admin to drive ``POST /1.0/cluster`` on a freshly-installed LXD
daemon. Successful bootstrap creates the first ``hosts`` record so the rest
of the app becomes usable immediately.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.host import ConnectionType


class ClusterConfig(BaseModel):
    """Subset of the LXD preseed schema that we expose in the wizard."""

    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(..., min_length=1, max_length=63)
    cluster_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("server_name")
    @classmethod
    def _validate_server_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("server_name must not be empty")
        return v


class BootstrapRequest(BaseModel):
    """Body for POST /bootstrap/cluster."""

    model_config = ConfigDict(extra="forbid")

    host_name: str = Field(..., min_length=1, max_length=128)
    cluster: ClusterConfig

    @field_validator("host_name")
    @classmethod
    def _validate_host_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("host_name must not be empty")
        return v


class BootstrapStatus(BaseModel):
    """Body for GET /bootstrap/status."""

    # ``unreachable`` is not a daemon state but a panel state: the socket is
    # missing or not readable, which is the one case where no other answer is
    # truthful. The wizard shows the socket-permission hint instead of
    # offering to bootstrap a daemon it cannot even see.
    state: Literal["unreachable", "uninitialized", "untrusted", "initialized"]
    api_version: str | None = None
    server: str | None = None
    # ``enabled: true`` on /1.0/cluster. A standalone (non-clustered) daemon
    # still answers 200 there, so this is what tells the two apart.
    clustered: bool = False
    server_name: str | None = None
    socket: str | None = None
    # Set when the local daemon already has a ``hosts`` row.
    host_id: int | None = None
    host_name: str | None = None
    message: str | None = None


class BootstrapResult(BaseModel):
    """Body returned by POST /bootstrap/cluster on success."""

    state: Literal["initialized"]
    host_id: int
    host_name: str
    address: str
    connection_type: ConnectionType
    is_active: bool
    created_at: datetime
