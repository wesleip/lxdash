from __future__ import annotations

"""In-memory mock LXD client for development without a real LXD daemon.

Activated when LXD_MOCK=true in the environment.  Maintains state across
requests within the same process lifetime so start/stop/delete feel real.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Fake model objects that mirror the pylxd attribute surface used by routers
# ---------------------------------------------------------------------------

@dataclass
class _FakeState:
    cpu: Dict[str, Any] = field(default_factory=lambda: {"usage": random.randint(0, 4_000_000_000)})
    memory: Dict[str, Any] = field(default_factory=lambda: {
        "usage": random.randint(50_000_000, 512_000_000),
        "usage_peak": random.randint(512_000_000, 768_000_000),
        "swap_usage": 0,
        "swap_usage_peak": 0,
    })
    network: Dict[str, Any] = field(default_factory=lambda: {
        "eth0": {
            "addresses": [{"family": "inet", "address": f"10.0.0.{random.randint(2, 254)}", "netmask": "24", "scope": "global"}],
            "hwaddr": "00:16:3e:ab:cd:ef",
            "mtu": 1500,
            "state": "up",
        }
    })


@dataclass
class _FakeContainer:
    name: str
    status: str = "Stopped"
    status_code: int = 102
    type: str = "container"
    profiles: List[str] = field(default_factory=lambda: ["default"])
    config: Dict[str, Any] = field(default_factory=dict)
    architecture: str = "x86_64"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: Optional[str] = None
    location: str = "none"

    def state(self) -> _FakeState:
        return _FakeState()


@dataclass
class _FakeImageAlias:
    name: str
    description: str = ""


@dataclass
class _FakeImage:
    fingerprint: str
    public: bool = False
    architecture: str = "x86_64"
    type: str = "container"
    size: int = 0
    upload_date: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    cached: bool = True
    auto_update: bool = False
    aliases: List[Dict[str, str]] = field(default_factory=list)
    properties: Dict[str, str] = field(default_factory=dict)
    profiles: List[str] = field(default_factory=list)

    def delete(self, wait: bool = True) -> None:
        pass


@dataclass
class _FakeNetwork:
    name: str
    type: str = "bridge"
    managed: bool = True
    description: str = ""
    config: Dict[str, Any] = field(default_factory=lambda: {
        "ipv4.address": "10.10.0.1/24",
        "ipv4.nat": "true",
        "ipv6.address": "none",
    })
    status: str = "Created"

    def delete(self) -> None:
        pass


@dataclass
class _FakeStoragePool:
    name: str
    driver: str = "dir"
    status: str = "Created"
    config: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    class _Volumes:
        def all(self) -> List[Any]:
            return []

        def create(self, config: Dict[str, Any]) -> Any:
            return config

    volumes: _Volumes = field(default_factory=_Volumes)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def _seed_containers() -> Dict[str, _FakeContainer]:
    return {
        "web-prod": _FakeContainer(name="web-prod", status="Running", status_code=103,
                                   config={"limits.cpu": "2", "limits.memory": "512MB"}),
        "db-prod": _FakeContainer(name="db-prod", status="Running", status_code=103,
                                  config={"limits.cpu": "1", "limits.memory": "1GB"}),
        "dev-env": _FakeContainer(name="dev-env", status="Stopped", status_code=102),
        "test-runner": _FakeContainer(name="test-runner", status="Stopped", status_code=102),
    }


def _seed_images() -> Dict[str, _FakeImage]:
    imgs = [
        _FakeImage(
            fingerprint=hashlib.sha256(b"ubuntu-22.04").hexdigest()[:12],
            aliases=[{"name": "ubuntu/22.04", "description": "Ubuntu 22.04 LTS"}],
            properties={"description": "Ubuntu 22.04 LTS (Jammy Jellyfish)", "os": "Ubuntu", "release": "jammy"},
            size=120_000_000,
            created_at="2024-01-15T00:00:00Z",
        ),
        _FakeImage(
            fingerprint=hashlib.sha256(b"ubuntu-24.04").hexdigest()[:12],
            aliases=[{"name": "ubuntu/24.04", "description": "Ubuntu 24.04 LTS"}],
            properties={"description": "Ubuntu 24.04 LTS (Noble Numbat)", "os": "Ubuntu", "release": "noble"},
            size=130_000_000,
            created_at="2024-04-25T00:00:00Z",
        ),
        _FakeImage(
            fingerprint=hashlib.sha256(b"debian-12").hexdigest()[:12],
            aliases=[{"name": "debian/12", "description": "Debian 12 Bookworm"}],
            properties={"description": "Debian 12 (Bookworm)", "os": "Debian", "release": "bookworm"},
            size=90_000_000,
            created_at="2023-06-10T00:00:00Z",
        ),
        _FakeImage(
            fingerprint=hashlib.sha256(b"alpine-3.19").hexdigest()[:12],
            aliases=[{"name": "alpine/3.19", "description": "Alpine 3.19"}],
            properties={"description": "Alpine Linux 3.19", "os": "Alpine", "release": "3.19"},
            size=8_000_000,
            created_at="2023-11-20T00:00:00Z",
        ),
    ]
    return {img.fingerprint: img for img in imgs}


def _seed_networks() -> Dict[str, _FakeNetwork]:
    return {
        "lxdbr0": _FakeNetwork(name="lxdbr0", description="Default LXD bridge"),
        "dmz-net": _FakeNetwork(name="dmz-net", description="DMZ network",
                                config={"ipv4.address": "192.168.100.1/24", "ipv4.nat": "true", "ipv6.address": "none"}),
    }


def _seed_storage() -> Dict[str, _FakeStoragePool]:
    return {
        "default": _FakeStoragePool(name="default", driver="dir", description="Default storage pool"),
        "ssd": _FakeStoragePool(name="ssd", driver="btrfs", description="Fast SSD pool"),
    }


# ---------------------------------------------------------------------------
# MockLXDClient
# ---------------------------------------------------------------------------

class MockLXDClient:
    """Drop-in replacement for LXDClient that uses in-memory fake data."""

    # Shared state across all instances in the same process.
    _containers: Dict[str, _FakeContainer] = _seed_containers()
    _images: Dict[str, _FakeImage] = _seed_images()
    _networks: Dict[str, _FakeNetwork] = _seed_networks()
    _storage_pools: Dict[str, _FakeStoragePool] = _seed_storage()

    def __init__(self) -> None:
        self.host_id: Optional[int] = 0
        logger.info("lxd.mock_client_created")

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    async def list_containers(self) -> List[_FakeContainer]:
        return list(self._containers.values())

    async def get_container(self, name: str) -> _FakeContainer:
        if name not in self._containers:
            from services.lxd_client import LXDClientError
            raise LXDClientError(f"Container '{name}' not found")
        return self._containers[name]

    async def create_container(self, config: Dict[str, Any], wait: bool = True) -> _FakeContainer:
        name = config["name"]
        c = _FakeContainer(
            name=name,
            status="Stopped",
            status_code=102,
            profiles=config.get("profiles", ["default"]),
            config=config.get("config", {}),
        )
        self._containers[name] = c
        logger.info("mock.container_created", name=name)
        return c

    async def delete_container(self, name: str) -> None:
        await self.get_container(name)
        del self._containers[name]
        logger.info("mock.container_deleted", name=name)

    async def start_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        c = await self.get_container(name)
        c.status = "Running"
        c.status_code = 103
        logger.info("mock.container_started", name=name)

    async def stop_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        c = await self.get_container(name)
        c.status = "Stopped"
        c.status_code = 102
        logger.info("mock.container_stopped", name=name)

    async def restart_container(self, name: str, timeout: int = 30, force: bool = False) -> None:
        c = await self.get_container(name)
        c.status = "Running"
        c.status_code = 103
        logger.info("mock.container_restarted", name=name)

    async def get_container_state(self, name: str) -> _FakeState:
        await self.get_container(name)
        return _FakeState()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def list_images(self) -> List[_FakeImage]:
        return list(self._images.values())

    async def get_image(self, fingerprint: str) -> _FakeImage:
        if fingerprint not in self._images:
            from services.lxd_client import LXDClientError
            raise LXDClientError(f"Image '{fingerprint}' not found")
        return self._images[fingerprint]

    async def import_image_from_simplestream(
        self, server: str, alias: str, local_alias: Optional[str] = None
    ) -> _FakeImage:
        fp = hashlib.sha256(alias.encode()).hexdigest()[:12]
        img = _FakeImage(
            fingerprint=fp,
            aliases=[{"name": local_alias or alias, "description": alias}],
            properties={"description": alias, "os": alias.split("/")[0]},
            size=random.randint(50_000_000, 200_000_000),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._images[fp] = img
        logger.info("mock.image_imported", alias=alias, fingerprint=fp)
        return img

    async def delete_image(self, fingerprint: str) -> None:
        await self.get_image(fingerprint)
        del self._images[fingerprint]
        logger.info("mock.image_deleted", fingerprint=fingerprint)

    # ------------------------------------------------------------------
    # Networks
    # ------------------------------------------------------------------

    async def list_networks(self) -> List[_FakeNetwork]:
        return list(self._networks.values())

    async def get_network(self, name: str) -> _FakeNetwork:
        if name not in self._networks:
            from services.lxd_client import LXDClientError
            raise LXDClientError(f"Network '{name}' not found")
        return self._networks[name]

    async def create_network(self, config: Dict[str, Any]) -> _FakeNetwork:
        name = config.get("name", "net-unknown")
        net = _FakeNetwork(
            name=name,
            type=config.get("type", "bridge"),
            description=config.get("description", ""),
            config=config.get("config", {}),
        )
        self._networks[name] = net
        logger.info("mock.network_created", name=name)
        return net

    async def delete_network(self, name: str) -> None:
        await self.get_network(name)
        del self._networks[name]
        logger.info("mock.network_deleted", name=name)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def list_storage_pools(self) -> List[_FakeStoragePool]:
        return list(self._storage_pools.values())

    async def get_storage_pool(self, name: str) -> _FakeStoragePool:
        if name not in self._storage_pools:
            from services.lxd_client import LXDClientError
            raise LXDClientError(f"Storage pool '{name}' not found")
        return self._storage_pools[name]

    async def create_storage_volume(self, pool_name: str, volume_config: Dict[str, Any]) -> Any:
        await self.get_storage_pool(pool_name)
        logger.info("mock.volume_created", pool=pool_name, config=volume_config)
        return volume_config

    async def list_storage_volumes(self, pool_name: str) -> List[Any]:
        pool = await self.get_storage_pool(pool_name)
        return pool.volumes.all()
