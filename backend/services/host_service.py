from __future__ import annotations

"""Host registry: lookup, registration and client construction.

Every router reaches LXD through a ``hosts`` row. This module owns the three
operations that the routers, the WebSocket console, the SSE metrics endpoint
and the startup hook all need, so the rules live in exactly one place:

* :func:`resolve_host` — which host a request targets;
* :func:`connect_host` — turning a row into a connected :class:`LXDClient`;
* :func:`register_host` / :func:`ensure_local_host` — writing the row.

Keeping :func:`resolve_host` and :func:`connect_host` free of FastAPI types is
deliberate: ``routers/console.py`` and ``routers/metrics.py`` need them from
a WebSocket or a streaming response, where raising ``HTTPException`` does not
work.
"""

from datetime import UTC, datetime
from socket import gethostname

import structlog
from sqlalchemy.orm import Session

from config import get_settings
from models.host import ConnectionType, Host
from services.lxd_client import LXDClient, LXDClientError
from services.lxd_client_mock import MockLXDClient
from services.lxd_probe import LXDProbeError, ServerInfo, fetch_server_info

logger = structlog.get_logger(__name__)

# Synthetic host used when LXD_MOCK=true. The address is deliberately not a
# filesystem path so it can never be mistaken for a real socket.
MOCK_HOST_NAME = "mock"
MOCK_HOST_ADDRESS = "mock://lxd"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HostRegistryError(Exception):
    """Base class for host resolution / registration failures."""


class NoHostRegisteredError(HostRegistryError):
    """No active host exists — nothing can be delegated to LXD."""


class AmbiguousHostError(HostRegistryError):
    """More than one active host exists and the caller did not pick one."""


class HostNotFoundError(HostRegistryError):
    """The requested host does not exist or has been deactivated."""


class HostConflictError(HostRegistryError):
    """A host with the same name (or address) is already registered."""


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def resolve_host(db: Session, host_id: int | None) -> Host:
    """Return the :class:`Host` a request should be served from.

    When *host_id* is ``None`` we fall back to the only active host. That
    keeps the single-host deployment — the common case for a panel running
    next to its own LXD daemon — free of a ``host_id`` on every request, while
    still forcing an explicit choice as soon as a second host is registered.

    Raises:
        NoHostRegisteredError: the ``hosts`` table has no active row.
        AmbiguousHostError: several active hosts and no *host_id* was given.
        HostNotFoundError: *host_id* does not match an active host.
    """
    if host_id is not None:
        host: Host | None = (
            db.query(Host).filter(Host.id == host_id, Host.is_active.is_(True)).first()
        )
        if host is None:
            raise HostNotFoundError(f"Host {host_id} not found.")
        return host

    active = db.query(Host).filter(Host.is_active.is_(True)).order_by(Host.id).all()
    if not active:
        raise NoHostRegisteredError(
            "No LXD hosts registered. Register the local daemon with "
            "POST /bootstrap/register (or POST /hosts), then retry."
        )
    if len(active) > 1:
        names = ", ".join(f"{h.id}:{h.name}" for h in active)
        raise AmbiguousHostError(
            f"Query parameter 'host_id' is required — {len(active)} hosts are "
            f"registered ({names})."
        )
    return active[0]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


async def connect_host(host: Host) -> LXDClient:
    """Open a connected :class:`LXDClient` for *host*.

    Raises:
        LXDClientError: the transport could not be established (socket
            missing/inaccessible, TLS material missing, endpoint refusing).
    """
    if host.connection_type.value == "socket":
        return await LXDClient.connect_socket(host.address, host_id=host.id)

    if not host.tls_cert or not host.tls_key:
        raise LXDClientError(f"Host {host.id} is configured for TLS but has no certificate.")
    return await LXDClient.connect_tls(
        endpoint=host.address,
        cert_pem=host.tls_cert,
        key_pem=host.tls_key,
        server_cert_pem=host.tls_server_cert,
        host_id=host.id,
    )


async def open_client(host: Host) -> LXDClient | MockLXDClient:
    """Return the client a request should talk to *host* through.

    The single place where ``LXD_MOCK`` is honoured, shared by the REST
    dependency, the WebSocket console and the SSE metrics stream so that
    development mode behaves identically on all three. Host resolution is the
    caller's job — the mock is returned *after* a host has been resolved,
    which is what keeps the registry gate honest in development.
    """
    if get_settings().LXD_MOCK:
        return MockLXDClient(host_id=host.id)
    return await connect_host(host)


async def probe_host(host: Host) -> ServerInfo:
    """Probe *host* through the LXD REST API and return what it reports.

    Raises:
        LXDProbeError: the daemon is unreachable or refused the request.
    """
    return await fetch_server_info(
        host.address,
        host.connection_type.value,
        cert_pem=host.tls_cert,
        key_pem=host.tls_key,
        server_cert_pem=host.tls_server_cert,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def default_host_name(info_server_name: str | None = None) -> str:
    """Best-effort friendly name for the local daemon.

    Prefers the name LXD itself reports (``server_name`` from
    ``/1.0/cluster``), then the OS hostname, then a static fallback.
    """
    if info_server_name:
        return info_server_name[:128]
    try:
        hostname = gethostname()
    except OSError:  # pragma: no cover — depends on host environment
        hostname = ""
    return (hostname or "local")[:128]


def register_host(
    db: Session,
    *,
    name: str,
    address: str,
    connection_type: ConnectionType,
    tls_cert: str | None = None,
    tls_key: str | None = None,
    tls_server_cert: str | None = None,
    is_active: bool = True,
) -> Host:
    """Insert a new ``hosts`` row.

    Raises:
        HostConflictError: the name is taken, or the same address is already
            registered — two rows for one daemon would make ``host_id``
            ambiguous in a way the operator cannot reason about.
    """
    if db.query(Host).filter(Host.name == name).first():
        raise HostConflictError(f"A host named '{name}' is already registered.")
    if (
        db.query(Host)
        .filter(Host.address == address, Host.connection_type == connection_type)
        .first()
    ):
        raise HostConflictError(f"Host address '{address}' is already registered.")

    host = Host(
        name=name,
        address=address,
        connection_type=connection_type,
        tls_cert=tls_cert,
        tls_key=tls_key,
        tls_server_cert=tls_server_cert,
        is_active=is_active,
        created_at=datetime.now(UTC),
    )
    db.add(host)
    db.commit()
    db.refresh(host)
    logger.info(
        "host.registered",
        host_id=host.id,
        host_name=host.name,
        connection_type=host.connection_type.value,
    )
    return host


def ensure_host(
    db: Session,
    *,
    name: str,
    address: str,
    connection_type: ConnectionType,
    tls_cert: str | None = None,
    tls_key: str | None = None,
    tls_server_cert: str | None = None,
) -> Host:
    """Idempotently make sure a ``hosts`` row exists for this address.

    Returns the existing row when the address is already registered —
    reactivating it if it had been deactivated, so an operator who disabled a
    host temporarily does not have to re-register it after a restart.
    """
    existing: Host | None = (
        db.query(Host)
        .filter(Host.address == address, Host.connection_type == connection_type)
        .first()
    )
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            logger.info("host.reactivated", host_id=existing.id, host_name=existing.name)
        return existing

    return register_host(
        db,
        name=name,
        address=address,
        connection_type=connection_type,
        tls_cert=tls_cert,
        tls_key=tls_key,
        tls_server_cert=tls_server_cert,
    )


async def ensure_local_host(db: Session, socket_path: str) -> Host | None:
    """Idempotently register the local LXD daemon, if it answers.

    Called on startup so a fresh deployment is usable without a manual
    registration step. Returns the existing row when the socket is already
    registered (reactivating it if it had been deactivated), the freshly
    created row when registration happened, and ``None`` when there is no
    reachable daemon — a missing LXD must never stop the app from booting.
    """
    try:
        info = await fetch_server_info(socket_path, ConnectionType.socket.value)
    except LXDProbeError as exc:
        logger.info("host.local_skipped", socket=socket_path, reason=str(exc))
        return None

    host = ensure_host(
        db,
        name=default_host_name(info.server_name),
        address=socket_path,
        connection_type=ConnectionType.socket,
    )
    logger.info(
        "host.local_registered",
        host_id=host.id,
        host_name=host.name,
        api_version=info.api_version,
        clustered=info.clustered,
    )
    return host


def ensure_mock_host(db: Session) -> Host:
    """Register a synthetic host so ``LXD_MOCK`` still goes through the gate.

    Development mode must exercise the same host-resolution path as
    production, otherwise the "no host registered" failure only ever shows up
    in production.
    """
    host = ensure_host(
        db,
        name=MOCK_HOST_NAME,
        address=MOCK_HOST_ADDRESS,
        connection_type=ConnectionType.socket,
    )
    logger.info("host.mock_registered", host_id=host.id, host_name=host.name)
    return host


__all__ = [
    "MOCK_HOST_ADDRESS",
    "MOCK_HOST_NAME",
    "AmbiguousHostError",
    "HostConflictError",
    "HostNotFoundError",
    "HostRegistryError",
    "NoHostRegisteredError",
    "connect_host",
    "default_host_name",
    "ensure_host",
    "ensure_local_host",
    "ensure_mock_host",
    "open_client",
    "probe_host",
    "register_host",
    "resolve_host",
]
