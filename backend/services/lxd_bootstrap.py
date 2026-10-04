"""First-node LXD cluster bootstrap.

Talks to the LXD daemon over the Unix socket while the cluster is in the
*uninitialized* or *untrusted* state — there is no client certificate yet, so
``pylxd`` (and our ``LXDClient`` wrapper) cannot be used here. The wire
protocol itself lives in :mod:`services.lxd_probe`; this module only maps the
probed cluster state onto the bootstrap state machine and drives
``POST /1.0/cluster``.

State machine
-------------
``uninitialized``
    Daemon is running but no cluster/database has been set up. The bootstrap
    POST hits ``/1.0/cluster`` with a preseed body.

``untrusted``
    Daemon is up and cluster is initialized, but we have no trusted client
    certificate. The bootstrap endpoint cannot help here — the operator must
    add the cert on the host with ``lxc config trust add``.

``initialized``
    Cluster is set up (standalone or clustered). Nothing needs to be
    bootstrapped; the daemon only has to be *registered* as a host, which is
    what ``POST /bootstrap/register`` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from config import get_settings
from services.lxd_probe import (
    DEFAULT_TIMEOUT_SECONDS,
    LXDProbeError,
    ensure_socket_accessible,
    fetch_server_info,
    post_cluster_preseed,
)

logger = structlog.get_logger(__name__)

BootstrapState = Literal["uninitialized", "untrusted", "initialized"]


class LXDBootstrapError(Exception):
    """Raised when the bootstrap flow cannot complete."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class BootstrapInfo:
    state: BootstrapState
    api_version: str | None = None
    server: str | None = None
    # ``enabled: true`` on /1.0/cluster. A standalone (non-clustered) daemon
    # still answers 200 there, so this is what actually tells the two apart.
    clustered: bool = False
    server_name: str | None = None


class LXDBootstrap:
    """Stateless client that talks to the LXD socket during cluster bootstrap."""

    def __init__(self, socket_path: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self.socket_path = socket_path or settings.LXD_SOCKET_PATH
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_socket_access(self) -> None:
        """Verify the current process can read the Unix socket.

        Raises ``LXDBootstrapError`` so callers of the bootstrap flow never
        have to import the probe module.
        """
        try:
            ensure_socket_accessible(self.socket_path)
        except LXDProbeError as exc:
            raise LXDBootstrapError(str(exc)) from exc

    async def _server_info(self):
        return await fetch_server_info(
            self.socket_path,
            "socket",
            timeout=self._timeout,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def check_status(self) -> BootstrapInfo:
        """Detect the current bootstrap state of the daemon.

        Heuristic, based on what the LXD REST API reports:

        - ``GET /1.0`` answers 200 as soon as the daemon is reachable — this
          is the liveness signal.
        - ``GET /1.0/cluster`` answers 404 when no cluster has been set up
          (``uninitialized``), 403 when a cluster exists but our certificate
          is not trusted (``untrusted``), and 200 once the daemon is
          initialized (``initialized``) — whether standalone or clustered.
        """
        try:
            info = await self._server_info()
        except LXDProbeError as exc:
            raise LXDBootstrapError(str(exc)) from exc

        state: BootstrapState
        if info.cluster_state == "absent":
            state = "uninitialized"
        elif info.cluster_state == "forbidden":
            state = "untrusted"
        else:
            state = "initialized"

        return BootstrapInfo(
            state=state,
            api_version=info.api_version,
            server=info.server,
            clustered=info.clustered,
            server_name=info.server_name,
        )

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def bootstrap(self, *, server_name: str, cluster_password: str) -> None:
        """Drive the first-node cluster bootstrap via ``POST /1.0/cluster``.

        LXD expects a YAML preseed; we send an equivalent JSON body
        (``application/json`` is supported on /1.0/cluster). The endpoint
        returns 202 with an operation URL when accepted.
        """
        preseed = {
            "cluster": {
                "server_name": server_name,
                "enabled": True,
                "cluster_password": cluster_password,
            },
            "networks": [],
            "storage_pools": [],
            "profiles": [],
        }

        try:
            status_code = await post_cluster_preseed(
                self.socket_path,
                preseed,
                timeout=self._timeout,
            )
        except LXDProbeError as exc:
            raise LXDBootstrapError(str(exc)) from exc

        logger.info(
            "lxd.bootstrap.accepted",
            server_name=server_name,
            http_status=status_code,
        )

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    _instance: LXDBootstrap | None = None

    @classmethod
    def instance(cls) -> LXDBootstrap:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test-only — drop the cached instance."""
        cls._instance = None


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "BootstrapInfo",
    "BootstrapState",
    "LXDBootstrap",
    "LXDBootstrapError",
]
