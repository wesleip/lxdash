from __future__ import annotations

"""LXD client service.

IMPORTANT RULES (enforced here, nowhere else):
- This is the ONLY module that imports pylxd.
- Every pylxd call is wrapped in asyncio.to_thread() so that the blocking
  C-extension code does not stall the event loop.
- Routers MUST NOT import pylxd directly.
"""

import asyncio
import ssl
import tempfile
import os
from typing import Any, Dict, List, Optional

import pylxd  # type: ignore[import]
import structlog

logger = structlog.get_logger(__name__)


class LXDClientError(Exception):
    """Raised when a pylxd operation fails in a known way."""


class LXDClient:
    """Async-friendly wrapper around pylxd.Client.

    Usage::

        client = await LXDClient.connect_socket("/var/snap/lxd/common/lxd/unix.socket")
        containers = await client.list_containers()
    """

    def __init__(self, _client: pylxd.Client, host_id: Optional[int] = None) -> None:
        self._client = _client
        self.host_id = host_id

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    async def connect_socket(
        cls,
        socket_path: str,
        host_id: Optional[int] = None,
    ) -> "LXDClient":
        """Connect to a local LXD daemon via Unix socket."""

        def _connect() -> pylxd.Client:
            return pylxd.Client(endpoint=f"http+unix://{socket_path}")

        try:
            raw = await asyncio.to_thread(_connect)
        except pylxd.exceptions.ClientConnectionFailed as exc:
            raise LXDClientError(f"Cannot connect to socket {socket_path}: {exc}") from exc

        logger.info("lxd.connected", mode="socket", socket=socket_path)
        return cls(raw, host_id=host_id)

    @classmethod
    async def connect_tls(
        cls,
        endpoint: str,
        cert_pem: str,
        key_pem: str,
        server_cert_pem: Optional[str] = None,
        host_id: Optional[int] = None,
    ) -> "LXDClient":
        """Connect to a remote LXD daemon via TLS."""

        # pylxd expects paths to cert files, not PEM strings — write to tmpfiles.
        def _connect() -> pylxd.Client:
            with (
                tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as cf,
                tempfile.NamedTemporaryFile(suffix=".key", delete=False) as kf,
            ):
                cf.write(cert_pem.encode())
                kf.write(key_pem.encode())
                cert_path = cf.name
                key_path = kf.name

            try:
                kwargs: Dict[str, Any] = {
                    "endpoint": endpoint,
                    "cert": (cert_path, key_path),
                    "verify": False,
                }
                if server_cert_pem:
                    with tempfile.NamedTemporaryFile(
                        suffix=".crt", delete=False
                    ) as scf:
                        scf.write(server_cert_pem.encode())
                        kwargs["verify"] = scf.name
                return pylxd.Client(**kwargs)
            finally:
                os.unlink(cert_path)
                os.unlink(key_path)

        try:
            raw = await asyncio.to_thread(_connect)
        except pylxd.exceptions.ClientConnectionFailed as exc:
            raise LXDClientError(f"Cannot connect to {endpoint}: {exc}") from exc

        logger.info("lxd.connected", mode="tls", endpoint=endpoint)
        return cls(raw, host_id=host_id)

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    async def list_containers(self) -> List[pylxd.models.Container]:
        """Return all containers (including VMs) on the host."""
        return await asyncio.to_thread(self._client.containers.all)

    async def get_container(self, name: str) -> pylxd.models.Container:
        try:
            return await asyncio.to_thread(self._client.containers.get, name)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Container '{name}' not found: {exc}") from exc

    async def create_container(self, config: Dict[str, Any], wait: bool = True) -> pylxd.models.Container:
        """Create a container from *config* dict.

        *config* must follow the LXD REST API shape, e.g.::

            {
                "name": "my-container",
                "source": {"type": "image", "alias": "ubuntu/22.04"},
                "profiles": ["default"],
            }
        """
        try:
            return await asyncio.to_thread(self._client.containers.create, config, wait=wait)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to create container: {exc}") from exc

    async def delete_container(self, name: str) -> None:
        container = await self.get_container(name)
        try:
            await asyncio.to_thread(container.delete, wait=True)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to delete container '{name}': {exc}") from exc

    async def start_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        container = await self.get_container(name)
        try:
            await asyncio.to_thread(container.start, timeout=timeout, force=force, wait=True)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to start container '{name}': {exc}") from exc

    async def stop_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        container = await self.get_container(name)
        try:
            await asyncio.to_thread(container.stop, timeout=timeout, force=force, wait=True)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to stop container '{name}': {exc}") from exc

    async def restart_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        container = await self.get_container(name)
        try:
            await asyncio.to_thread(container.restart, timeout=timeout, force=force, wait=True)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to restart container '{name}': {exc}") from exc

    async def get_container_state(self, name: str) -> Any:
        container = await self.get_container(name)
        return await asyncio.to_thread(container.state)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def list_images(self) -> List[pylxd.models.Image]:
        return await asyncio.to_thread(self._client.images.all)

    async def get_image(self, fingerprint: str) -> pylxd.models.Image:
        try:
            return await asyncio.to_thread(self._client.images.get, fingerprint)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Image '{fingerprint}' not found: {exc}") from exc

    async def import_image_from_simplestream(
        self,
        server: str,
        alias: str,
        local_alias: Optional[str] = None,
    ) -> pylxd.models.Image:
        """Pull an image from a remote simplestreams / LXD server."""

        def _import() -> pylxd.models.Image:
            img = self._client.images.create_from_simplestreams(server, alias)
            if local_alias:
                img.add_alias(local_alias, "")
            return img

        try:
            return await asyncio.to_thread(_import)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to import image '{alias}': {exc}") from exc

    async def delete_image(self, fingerprint: str) -> None:
        image = await self.get_image(fingerprint)
        try:
            await asyncio.to_thread(image.delete, wait=True)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to delete image '{fingerprint}': {exc}") from exc

    # ------------------------------------------------------------------
    # Networks
    # ------------------------------------------------------------------

    async def list_networks(self) -> List[pylxd.models.Network]:
        return await asyncio.to_thread(self._client.networks.all)

    async def get_network(self, name: str) -> pylxd.models.Network:
        try:
            return await asyncio.to_thread(self._client.networks.get, name)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Network '{name}' not found: {exc}") from exc

    async def create_network(self, config: Dict[str, Any]) -> pylxd.models.Network:
        try:
            return await asyncio.to_thread(self._client.networks.create, **config)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to create network: {exc}") from exc

    async def delete_network(self, name: str) -> None:
        network = await self.get_network(name)
        try:
            await asyncio.to_thread(network.delete)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Failed to delete network '{name}': {exc}") from exc

    # ------------------------------------------------------------------
    # Storage pools
    # ------------------------------------------------------------------

    async def list_storage_pools(self) -> List[pylxd.models.StoragePool]:
        return await asyncio.to_thread(self._client.storage_pools.all)

    async def get_storage_pool(self, name: str) -> pylxd.models.StoragePool:
        try:
            return await asyncio.to_thread(self._client.storage_pools.get, name)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(f"Storage pool '{name}' not found: {exc}") from exc

    async def create_storage_volume(
        self,
        pool_name: str,
        volume_config: Dict[str, Any],
    ) -> Any:
        pool = await self.get_storage_pool(pool_name)
        try:
            return await asyncio.to_thread(pool.volumes.create, volume_config)
        except pylxd.exceptions.LXDAPIException as exc:
            raise LXDClientError(
                f"Failed to create volume in pool '{pool_name}': {exc}"
            ) from exc

    async def list_storage_volumes(self, pool_name: str) -> List[Any]:
        pool = await self.get_storage_pool(pool_name)
        return await asyncio.to_thread(pool.volumes.all)
