"""First-node LXD cluster bootstrap.

Talks to the LXD daemon directly over the Unix socket via ``httpx`` while
the cluster is in the *uninitialized* or *untrusted* state — there is no
client certificate yet, so ``pylxd`` (and our ``LXDClient`` wrapper) cannot
be used here. This is the only legitimate exception to the
"only lxd_client.py imports pylxd" rule: pylxd does not even support the
uninitialized state.

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
    Cluster is set up and a host record is registered in our DB. Future
    connections use the wrapped ``LXDClient``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog

from config import get_settings

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


class LXDBootstrap:
    """Stateless client that talks to the LXD socket during cluster bootstrap."""

    def __init__(self, socket_path: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self.socket_path = socket_path or settings.LXD_SOCKET_PATH
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        if not os.path.exists(self.socket_path):
            raise LXDBootstrapError(
                f"LXD socket not found at {self.socket_path}. "
                "Is the LXD daemon installed and running on the host?",
            )
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        return httpx.AsyncClient(transport=transport, timeout=self._timeout)

    async def _get(self, client: httpx.AsyncClient, path: str) -> httpx.Response:
        return await client.get(f"http://lxd.local{path}")

    async def _post(
        self,
        client: httpx.AsyncClient,
        path: str,
        json_body: dict[str, Any],
    ) -> httpx.Response:
        return await client.post(f"http://lxd.local{path}", json=json_body)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def check_status(self) -> BootstrapInfo:
        """Detect the current bootstrap state of the daemon.

        Heuristic:
        - If GET /1.0 returns 200 with ``public=true`` AND GET /1.0/cluster
          returns 404, the daemon is running but no cluster has been set up
          yet (uninitialized).
        - If /1.0/cluster returns 403, the cluster exists but we're not
          trusted (untrusted).
        - If /1.0 returns 200 with ``public=false`` (the client-cert path)
          or /1.0/cluster returns 200, the cluster is initialized.
        """
        async with self._client() as client:
            try:
                root = await self._get(client, "/1.0")
            except httpx.HTTPError as exc:
                raise LXDBootstrapError(f"Cannot reach LXD daemon: {exc}") from exc

            if root.status_code != 200:
                raise LXDBootstrapError(
                    f"Unexpected response from LXD /1.0: HTTP {root.status_code}",
                    status_code=root.status_code,
                )

            metadata = root.json().get("metadata") or {}
            api_version = metadata.get("api_version")
            server = metadata.get("server")
            public = bool(metadata.get("public", False))

            # Try the cluster endpoint to refine the state.
            try:
                cluster_resp = await self._get(client, "/1.0/cluster")
            except httpx.HTTPError as exc:
                raise LXDBootstrapError(f"Cannot reach /1.0/cluster: {exc}") from exc

            if cluster_resp.status_code == 200:
                state: BootstrapState = "initialized"
            elif cluster_resp.status_code == 403:
                # Cluster exists, we are not trusted.
                state = "untrusted"
            elif cluster_resp.status_code == 404 and public:
                # No cluster yet — but we might still need to handle the case
                # where the LXD daemon returned 404 on /1.0/cluster because
                # of routing issues. The 200 on /1.0 confirms the daemon is up.
                state = "uninitialized"
            else:
                raise LXDBootstrapError(
                    f"Unexpected response from /1.0/cluster: HTTP {cluster_resp.status_code}",
                    status_code=cluster_resp.status_code,
                )

            return BootstrapInfo(
                state=state,
                api_version=api_version,
                server=server,
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

        async with self._client() as client:
            try:
                resp = await self._post(client, "/1.0/cluster", preseed)
            except httpx.HTTPError as exc:
                raise LXDBootstrapError(
                    f"Cannot reach LXD daemon for bootstrap: {exc}",
                ) from exc

            if resp.status_code in (200, 202):
                logger.info(
                    "lxd.bootstrap.accepted",
                    server_name=server_name,
                    http_status=resp.status_code,
                )
                return

            # LXD returns error details in the "error" field of the response.
            try:
                err = resp.json().get("error", "")
            except ValueError:
                err = resp.text

            raise LXDBootstrapError(
                f"LXD refused bootstrap (HTTP {resp.status_code}): {err}",
                status_code=resp.status_code,
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
