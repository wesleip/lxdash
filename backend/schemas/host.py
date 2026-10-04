"""Schemas for the host registry (``/hosts``) and the bootstrap register flow."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.host import ConnectionType


class HostCreate(BaseModel):
    """Body for ``POST /hosts``.

    ``address`` is the Unix socket path for ``socket`` connections and the
    HTTPS endpoint for ``tls`` ones — the same field, because the LXD REST API
    is identical over both transports.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    address: str = Field(..., min_length=1, max_length=512)
    connection_type: ConnectionType = ConnectionType.socket
    tls_cert: str | None = None
    tls_key: str | None = None
    tls_server_cert: str | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_transport(self) -> HostCreate:
        address = self.address.strip()
        if not address:
            raise ValueError("address must not be empty")
        self.address = address

        if self.connection_type is ConnectionType.socket:
            if not address.startswith("/"):
                raise ValueError("A socket host address must be an absolute path.")
            return self

        if not (self.tls_cert and self.tls_key):
            raise ValueError("TLS hosts require both tls_cert and tls_key.")
        parsed = urlparse(address)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(
                "A TLS host address must be an https:// URL, e.g. https://10.0.0.1:8443"
            )
        return self


class HostResponse(BaseModel):
    id: int
    name: str
    address: str
    connection_type: ConnectionType
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class HostHealth(BaseModel):
    """Answer of ``GET /hosts/{id}/health``.

    Populated from the LXD REST API (``GET /1.0``, ``GET /1.0/cluster`` and
    ``GET /1.0/resources``). ``reachable`` is ``False`` — with ``message``
    explaining why — instead of an error status, so a panel can show one host
    as down without the whole list failing.
    """

    host_id: int
    host_name: str
    reachable: bool
    address: str
    connection_type: ConnectionType
    api_version: str | None = None
    api_extensions_count: int | None = None
    server: str | None = None
    public: bool | None = None
    auth: str | None = None
    auth_user_method: str | None = None
    clustered: bool | None = None
    server_name: str | None = None
    certificate_fingerprint: str | None = None
    architecture: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    hostname: str | None = None
    cpu_total: int | None = None
    memory_total: int | None = None
    message: str | None = None


class HostRegisterRequest(BaseModel):
    """Body for ``POST /bootstrap/register``.

    Deliberately has no cluster fields: this flow adopts a daemon that is
    *already* initialised, which is the common case for an existing LXD host.
    ``POST /bootstrap/cluster`` remains the path for a brand-new daemon.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("host_name")
    @classmethod
    def _strip_host_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("host_name must not be empty")
        return v
