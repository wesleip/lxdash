from __future__ import annotations

"""Raw HTTP probe against the LXD REST API.

This is the only module that talks to the LXD wire protocol with ``httpx``
directly. It exists for the two situations where a ``pylxd.Client`` cannot be
used:

* the daemon is up but the cluster is not initialised yet — there is no
  client certificate to present, so ``pylxd`` cannot connect at all;
* we are validating a host we have not registered yet (connectivity check at
  registration time, health checks).

Endpoints consumed, per https://canonical.com/lxd/docs/latest/rest-api/:

``GET /1.0``
    Server metadata. Answers 200 as soon as the daemon is reachable, even
    before the cluster exists. Fields used here: ``api_version``,
    ``api_extensions``, ``server``, ``public``, ``auth``, ``auth_user_name``,
    ``auth_user_method``.
``GET /1.0/cluster``
    Cluster metadata (``server_name``, ``enabled``, ``member_config``,
    ``certificate_fingerprint``). Answers 404 when no cluster has been set up
    and 403 when our client certificate is not trusted.
``GET /1.0/resources``
    Host capacity (CPU, memory, system). Best-effort: a daemon that does not
    expose it simply yields ``None`` fields instead of failing the probe.

Note that LXD exposes exactly the same API over a Unix socket and over TLS
with client certificates — the only difference is the transport, which is why
every function here takes an ``address`` plus a ``connection_type``.
"""

import os
import stat
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Host header is irrelevant over a Unix socket but httpx still needs a valid
# absolute URL, and LXD routes on the path only.
_SOCKET_BASE_URL = "http://lxd.local"

DEFAULT_TIMEOUT_SECONDS = 10.0

ClusterState = Literal["absent", "forbidden", "present", "unknown"]


class LXDProbeError(Exception):
    """Raised when the LXD API cannot be reached or answers unexpectedly."""


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """Result of probing ``GET /1.0`` and ``GET /1.0/cluster``."""

    api_version: str | None = None
    api_extensions: tuple[str, ...] = ()
    server: str | None = None
    public: bool | None = None
    auth: str | None = None
    auth_user_name: str | None = None
    auth_user_method: str | None = None
    cluster_state: ClusterState = "unknown"
    # True only when the daemon reports an enabled cluster. A standalone
    # daemon also answers 200 on /1.0/cluster, but with "enabled": false.
    clustered: bool = False
    server_name: str | None = None
    certificate_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ResourcesInfo:
    """Subset of ``GET /1.0/resources`` that is useful for a health panel."""

    cpu_total: int | None = None
    memory_total: int | None = None
    architecture: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    hostname: str | None = None


# ---------------------------------------------------------------------------
# Socket pre-flight
# ---------------------------------------------------------------------------


def ensure_socket_accessible(socket_path: str) -> None:
    """Verify the local LXD socket exists and that we may read it.

    LXD ships its socket as ``root:lxd 0660``. The backend must be in the
    ``lxd`` group (or run as root, which we don't want). On most hosts the
    ``lxd`` group is GID 998, but the operator can override via ``LXD_GID``
    in the compose env (and the matching build arg).
    """
    if not os.path.exists(socket_path):
        raise LXDProbeError(
            f"LXD socket not found at {socket_path}. "
            "Is the LXD daemon installed and running on the host? "
            "If LXD was installed via apt (not snap), the socket lives at "
            "/var/lib/lxd/unix.socket instead."
        )

    try:
        stat_result = os.stat(socket_path)
    except OSError as exc:
        raise LXDProbeError(f"Cannot stat LXD socket at {socket_path}: {exc}") from exc

    if not stat.S_ISSOCK(stat_result.st_mode):
        raise LXDProbeError(
            f"{socket_path} exists but is not a Unix socket "
            f"(mode={oct(stat_result.st_mode & 0o777)})."
        )

    sock_uid = stat_result.st_uid
    sock_gid = stat_result.st_gid
    proc_uid = os.getuid()
    proc_gid = os.getgid()
    proc_groups = os.getgroups()

    if sock_uid == proc_uid:
        return  # we own the socket
    if sock_gid in proc_groups or sock_gid == proc_gid:
        return  # we are in the right group

    raise LXDProbeError(
        f"Permission denied on LXD socket {socket_path}: "
        f"socket is owned by UID {sock_uid} GID {sock_gid}, "
        f"backend runs as UID {proc_uid} GID {proc_gid} "
        f"(supplementary groups: {proc_groups}). "
        "Add the backend to the lxd group, or set LXD_GID in the "
        "compose env to match the host's lxd group GID."
    )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _write_temp(content: str, suffix: str) -> str:
    """Persist *content* to a private temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    os.chmod(path, 0o600)
    return path


@asynccontextmanager
async def _client_for(
    address: str,
    connection_type: str,
    cert_pem: str | None,
    key_pem: str | None,
    server_cert_pem: str | None,
    timeout: float,
) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    """Yield a configured ``httpx.AsyncClient`` and the base URL to prefix paths with.

    Temp files holding PEM material stay alive for the lifetime of the client
    (the TLS stack reads them lazily) and are removed on exit.
    """
    temp_files: list[str] = []

    try:
        if connection_type == "socket":
            ensure_socket_accessible(address)
            client = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=address),
                timeout=timeout,
            )
            async with client:
                yield client, _SOCKET_BASE_URL
            return

        if not cert_pem or not key_pem:
            raise LXDProbeError(
                f"Host {address} is configured for TLS but has no client certificate."
            )

        cert_path = _write_temp(cert_pem, ".crt")
        temp_files.append(cert_path)
        key_path = _write_temp(key_pem, ".key")
        temp_files.append(key_path)

        # Mirrors LXDClient.connect_tls: without an explicit server certificate
        # we cannot build a trust chain (LXD uses a self-signed CA by default),
        # so verification is disabled rather than failing every remote host.
        if server_cert_pem:
            ca_path = _write_temp(server_cert_pem, ".crt")
            temp_files.append(ca_path)
            verify: str | bool = ca_path
        else:
            verify = False

        client = httpx.AsyncClient(
            verify=verify,
            cert=(cert_path, key_path),
            timeout=timeout,
        )
        async with client:
            yield client, address.rstrip("/")
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:  # pragma: no cover — best-effort cleanup
                logger.debug("lxd_probe.temp_cleanup_failed", path=path)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _metadata(response: httpx.Response) -> dict[str, Any]:
    """Return the ``metadata`` object of a standard LXD sync response."""
    try:
        body = response.json()
    except ValueError:
        return {}
    metadata = body.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _error_text(response: httpx.Response) -> str:
    """Return the ``error`` field LXD uses for failures, falling back to the body."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict):
        error = body.get("error")
        if error:
            return str(error)
    return response.text


async def _get(client: httpx.AsyncClient, base_url: str, path: str) -> httpx.Response:
    """GET *path* over the LXD API, converting transport errors to LXDProbeError."""
    try:
        return await client.get(f"{base_url}{path}")
    except httpx.HTTPError as exc:
        raise LXDProbeError(f"Cannot reach LXD daemon ({path}): {exc}") from exc


async def _post(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    json_body: dict[str, Any],
) -> httpx.Response:
    """POST *json_body* to *path*, converting transport errors to LXDProbeError."""
    try:
        return await client.post(f"{base_url}{path}", json=json_body)
    except httpx.HTTPError as exc:
        raise LXDProbeError(f"Cannot reach LXD daemon ({path}): {exc}") from exc


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


async def post_cluster_preseed(
    address: str,
    preseed: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """POST a cluster preseed to ``/1.0/cluster`` and return the HTTP status.

    LXD answers 202 with a background operation URL when it accepts the
    preseed; 200 is also treated as success. Anything else raises, carrying
    the ``error`` field LXD puts in the response body.
    """
    async with _client_for(address, "socket", None, None, None, timeout) as (client, base_url):
        response = await _post(client, base_url, "/1.0/cluster", preseed)

        if response.status_code in (200, 202):
            return response.status_code

        raise LXDProbeError(
            f"LXD refused bootstrap (HTTP {response.status_code}): {_error_text(response)}"
        )


async def fetch_server_info(
    address: str,
    connection_type: str = "socket",
    *,
    cert_pem: str | None = None,
    key_pem: str | None = None,
    server_cert_pem: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ServerInfo:
    """Probe ``GET /1.0`` and ``GET /1.0/cluster``.

    Raises:
        LXDProbeError: the daemon is unreachable, the socket is not
            accessible, or ``/1.0`` answered with a non-200 status.
    """
    async with _client_for(
        address, connection_type, cert_pem, key_pem, server_cert_pem, timeout
    ) as (client, base_url):
        root = await _get(client, base_url, "/1.0")
        if root.status_code != 200:
            raise LXDProbeError(
                f"Unexpected response from LXD /1.0: HTTP {root.status_code} "
                f"({_error_text(root)})"
            )
        meta = _metadata(root)

        cluster_meta: dict[str, Any] = {}
        cluster_state: ClusterState
        cluster_resp = await _get(client, base_url, "/1.0/cluster")
        if cluster_resp.status_code == 200:
            cluster_state = "present"
            cluster_meta = _metadata(cluster_resp)
        elif cluster_resp.status_code == 403:
            # A cluster exists but our client certificate is not trusted.
            cluster_state = "forbidden"
        elif cluster_resp.status_code == 404:
            # No cluster has been set up yet.
            cluster_state = "absent"
        else:
            cluster_state = "unknown"
            logger.debug(
                "lxd_probe.cluster_unexpected",
                address=address,
                status_code=cluster_resp.status_code,
            )

    extensions = meta.get("api_extensions")
    return ServerInfo(
        api_version=meta.get("api_version"),
        api_extensions=tuple(extensions) if isinstance(extensions, list) else (),
        server=meta.get("server"),
        public=meta.get("public"),
        auth=meta.get("auth"),
        auth_user_name=meta.get("auth_user_name"),
        auth_user_method=meta.get("auth_user_method"),
        cluster_state=cluster_state,
        clustered=bool(cluster_meta.get("enabled", False)),
        server_name=cluster_meta.get("server_name"),
        certificate_fingerprint=cluster_meta.get("certificate_fingerprint"),
    )


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


async def fetch_resources(
    address: str,
    connection_type: str = "socket",
    *,
    cert_pem: str | None = None,
    key_pem: str | None = None,
    server_cert_pem: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ResourcesInfo:
    """Probe ``GET /1.0/resources``.

    Never raises for a missing/denied endpoint: a daemon that does not expose
    resources simply yields a fully-default ``ResourcesInfo``. Transport
    failures still raise, since the caller has already proven reachability
    via :func:`fetch_server_info`.
    """
    async with _client_for(
        address, connection_type, cert_pem, key_pem, server_cert_pem, timeout
    ) as (client, base_url):
        response = await _get(client, base_url, "/1.0/resources")
        if response.status_code != 200:
            logger.debug(
                "lxd_probe.resources_unavailable",
                address=address,
                status_code=response.status_code,
            )
            return ResourcesInfo()
        meta = _metadata(response)

    cpu = meta.get("cpu") if isinstance(meta.get("cpu"), dict) else {}
    memory = meta.get("memory") if isinstance(meta.get("memory"), dict) else {}
    system = meta.get("system") if isinstance(meta.get("system"), dict) else {}

    return ResourcesInfo(
        cpu_total=_as_int(cpu.get("total")),
        memory_total=_as_int(memory.get("total")),
        architecture=_as_str(system.get("architecture")),
        os_name=_as_str(system.get("os_name")),
        os_version=_as_str(system.get("os_version")),
        hostname=_as_str(system.get("hostname")),
    )
