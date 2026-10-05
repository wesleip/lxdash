from __future__ import annotations

"""In-memory mock LXD client for development without a real LXD daemon.

Activated when LXD_MOCK=true in the environment.  Maintains state across
requests within the same process lifetime so start/stop/delete feel real.
"""

import asyncio
import contextlib
import hashlib
import os
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Fake model objects that mirror the pylxd attribute surface used by routers
# ---------------------------------------------------------------------------


@dataclass
class _FakeState:
    cpu: dict[str, Any] = field(
        default_factory=lambda: {
            "usage": random.randint(0, 4_000_000_000),
            "user_time": random.randint(0, 3_000_000_000),
            "system_time": random.randint(0, 1_000_000_000),
        }
    )
    memory: dict[str, Any] = field(
        default_factory=lambda: {
            "usage": random.randint(50_000_000, 512_000_000),
            "usage_peak": random.randint(512_000_000, 768_000_000),
            "swap_usage": 0,
            "swap_usage_peak": 0,
        }
    )
    disk: dict[str, Any] = field(
        default_factory=lambda: {
            "/": {"usage": random.randint(200_000_000, 4_000_000_000)},
        }
    )
    network: dict[str, Any] = field(
        default_factory=lambda: {
            "eth0": {
                "addresses": [
                    {
                        "family": "inet",
                        "address": f"10.0.0.{random.randint(2, 254)}",
                        "netmask": "24",
                        "scope": "global",
                    }
                ],
                "hwaddr": "00:16:3e:ab:cd:ef",
                "mtu": 1500,
                "state": "up",
            }
        }
    )
    pid: int = field(default_factory=lambda: random.randint(100, 9_999))
    processes: int = field(default_factory=lambda: random.randint(1, 64))


@dataclass
class _FakeSnapshot:
    name: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    stateful: bool = False


@dataclass
class _FakeContainer:
    name: str
    status: str = "Stopped"
    status_code: int = 102
    type: str = "container"
    profiles: list[str] = field(default_factory=lambda: ["default"])
    config: dict[str, Any] = field(default_factory=dict)
    # Mirror of pylxd's `expanded_config` — the resolved view of the
    # instance config that LXD fills with `image.*` keys when the instance
    # is created from an image. Routers read image labels from here, not
    # from `config` (the user-editable override map).
    expanded_config: dict[str, Any] = field(default_factory=dict)
    architecture: str = "x86_64"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used_at: str | None = None
    location: str = "none"
    snapshots: list[_FakeSnapshot] = field(default_factory=list)

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
    upload_date: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    cached: bool = True
    auto_update: bool = False
    aliases: list[dict[str, str]] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)

    def delete(self, wait: bool = True) -> None:
        pass


@dataclass
class _FakeNetwork:
    name: str
    type: str = "bridge"
    managed: bool = True
    description: str = ""
    config: dict[str, Any] = field(
        default_factory=lambda: {
            "ipv4.address": "10.10.0.1/24",
            "ipv4.nat": "true",
            "ipv6.address": "none",
        }
    )
    status: str = "Created"

    def delete(self) -> None:
        pass


@dataclass
class _FakeStoragePool:
    name: str
    driver: str = "dir"
    status: str = "Created"
    config: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    class _Volumes:
        def all(self) -> list[Any]:
            return []

        def create(self, config: dict[str, Any]) -> Any:
            return config

    volumes: _Volumes = field(default_factory=_Volumes)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def _seed_containers() -> dict[str, _FakeContainer]:
    return {
        "archlinux": _FakeContainer(
            name="archlinux",
            status="Running",
            status_code=103,
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Archlinux current (20260401)",
                "image.os": "Archlinux",
                "image.release": "rolling",
                "image.serial": "20260401",
                "image.type": "squashfs",
                "image.version": "20260401",
            },
        ),
        "ubuntu": _FakeContainer(
            name="ubuntu",
            status="Running",
            status_code=103,
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Ubuntu 24.04 LTS (Noble Numbat)",
                "image.os": "Ubuntu",
                "image.release": "noble",
            },
        ),
        "web-prod": _FakeContainer(
            name="web-prod",
            status="Running",
            status_code=103,
            config={"limits.cpu": "2", "limits.memory": "512MB"},
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Ubuntu 24.04 LTS (Noble Numbat)",
                "image.os": "Ubuntu",
                "image.release": "noble",
                "image.version": "24.04",
            },
            snapshots=[
                _FakeSnapshot(name="snap0", created_at="2024-05-01T10:00:00+00:00"),
            ],
        ),
        "db-prod": _FakeContainer(
            name="db-prod",
            status="Running",
            status_code=103,
            config={"limits.cpu": "1", "limits.memory": "1GB"},
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Debian 12 (Bookworm)",
                "image.os": "Debian",
                "image.release": "bookworm",
            },
        ),
        "dev-env": _FakeContainer(
            name="dev-env",
            status="Stopped",
            status_code=102,
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Alpine 3.19",
                "image.os": "Alpine",
                "image.release": "3.19",
            },
        ),
        "test-runner": _FakeContainer(
            name="test-runner",
            status="Stopped",
            status_code=102,
            expanded_config={
                "image.architecture": "x86_64",
                "image.description": "Ubuntu 22.04 LTS (Jammy Jellyfish)",
                "image.os": "Ubuntu",
                "image.release": "jammy",
            },
        ),
    }


def _seed_images() -> dict[str, _FakeImage]:
    imgs = [
        _FakeImage(
            fingerprint=hashlib.sha256(b"ubuntu-22.04").hexdigest()[:12],
            aliases=[{"name": "ubuntu/22.04", "description": "Ubuntu 22.04 LTS"}],
            properties={
                "description": "Ubuntu 22.04 LTS (Jammy Jellyfish)",
                "os": "Ubuntu",
                "release": "jammy",
            },
            size=120_000_000,
            created_at="2024-01-15T00:00:00Z",
        ),
        _FakeImage(
            fingerprint=hashlib.sha256(b"ubuntu-24.04").hexdigest()[:12],
            aliases=[{"name": "ubuntu/24.04", "description": "Ubuntu 24.04 LTS"}],
            properties={
                "description": "Ubuntu 24.04 LTS (Noble Numbat)",
                "os": "Ubuntu",
                "release": "noble",
            },
            size=130_000_000,
            created_at="2024-04-25T00:00:00Z",
        ),
        _FakeImage(
            fingerprint=hashlib.sha256(b"debian-12").hexdigest()[:12],
            aliases=[{"name": "debian/12", "description": "Debian 12 Bookworm"}],
            properties={
                "description": "Debian 12 (Bookworm)",
                "os": "Debian",
                "release": "bookworm",
            },
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


def _seed_networks() -> dict[str, _FakeNetwork]:
    return {
        "lxdbr0": _FakeNetwork(name="lxdbr0", description="Default LXD bridge"),
        "dmz-net": _FakeNetwork(
            name="dmz-net",
            description="DMZ network",
            config={"ipv4.address": "192.168.100.1/24", "ipv4.nat": "true", "ipv6.address": "none"},
        ),
    }


def _seed_storage() -> dict[str, _FakeStoragePool]:
    return {
        "default": _FakeStoragePool(
            name="default", driver="dir", description="Default storage pool"
        ),
        "ssd": _FakeStoragePool(name="ssd", driver="btrfs", description="Fast SSD pool"),
    }


# ---------------------------------------------------------------------------
# Mock console session — a real /bin/sh impersonating the container
# ---------------------------------------------------------------------------


class _MockConsoleSession:
    """Console session that backs a fake LXD container with a real shell.

    Implements the subset of :class:`InteractiveConsoleSession` that the
    console router actually calls (``send_stdin``, ``recv_data``,
    ``send_resize``, ``aclose``). We deliberately do not subclass the real
    one because that would pull ``websockets`` into the mock path, and the
    mock only needs the contract, not the transport.
    """

    def __init__(self, container_name: str, process: asyncio.subprocess.Process) -> None:
        self._container_name = container_name
        self._process = process
        self._closed = False

    async def send_stdin(self, data: bytes) -> None:
        if self._closed:
            from services.lxd_client import LXDClientError

            raise LXDClientError("Mock console session is closed")
        if self._process.stdin is None:
            return
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def recv_data(self) -> bytes | None:
        """Return the next chunk of shell output, or ``None`` on EOF.

        A short timeout is used so an idle shell does not stall the
        bridge; on timeout we return ``b""`` (a legitimate zero-length
        chunk) so the caller can loop again without misinterpreting it as
        EOF. Only an actual EOF (``read`` returns ``b""`` without timing
        out) signals the shell exited.
        """
        if self._closed or self._process.stdout is None:
            return None
        try:
            chunk = await asyncio.wait_for(self._process.stdout.read(4096), timeout=0.5)
        except TimeoutError:
            return b""
        if chunk == b"":
            await self.aclose()
            return None
        return chunk
        return chunk

    async def send_resize(self, cols: int, rows: int) -> None:
        # No real PTY in the mock — ignore. Real LXD reports the new
        # window size to the kernel via TIOCSWINSZ so apps that depend on
        # it (top, less, vim) redraw correctly.
        return

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Interactive ``sh -i`` catches SIGTERM and tries to keep the session
        # alive, so we escalate to SIGKILL immediately. Once the process is
        # dead, drain stdin so the asyncio loop does not warn about unclosed
        # transports when the subprocess object is GC'd.
        with contextlib.suppress(ProcessLookupError):
            self._process.kill()
        with contextlib.suppress(ProcessLookupError):
            await self._process.wait()
        if self._process.stdin is not None:
            with contextlib.suppress(Exception):
                self._process.stdin.close()
        if self._process.stdout is not None:
            with contextlib.suppress(Exception):
                self._process.stdout.feed_eof()

    async def __aenter__(self) -> _MockConsoleSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# MockLXDClient
# ---------------------------------------------------------------------------


class MockLXDClient:
    """Drop-in replacement for LXDClient that uses in-memory fake data."""

    # Shared state across all instances in the same process.
    _containers: dict[str, _FakeContainer] = _seed_containers()
    _images: dict[str, _FakeImage] = _seed_images()
    _networks: dict[str, _FakeNetwork] = _seed_networks()
    _storage_pools: dict[str, _FakeStoragePool] = _seed_storage()

    def __init__(self, host_id: int | None = 0) -> None:
        self.host_id: int | None = host_id
        logger.info("lxd.mock_client_created", host_id=host_id)

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    async def list_containers(self) -> list[_FakeContainer]:
        return list(self._containers.values())

    async def get_container(self, name: str) -> _FakeContainer:
        if name not in self._containers:
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Container '{name}' not found")
        return self._containers[name]

    async def create_container(self, config: dict[str, Any], wait: bool = True) -> _FakeContainer:
        name = config["name"]
        source = config.get("source") or {}
        # LXD stamps `image.description`/`image.os`/etc. onto the instance
        # expanded_config at create time. The mock looks up the seeded image
        # by alias so newly created containers also report a sensible
        # label on the panel.
        alias = source.get("alias") if source.get("type") == "image" else None
        image_alias = None
        image_os = None
        image_description = None
        if alias:
            for img in self._images.values():
                for entry in img.aliases:
                    if entry.get("name") == alias:
                        image_alias = alias
                        image_os = img.properties.get("os") or alias.split("/", 1)[0]
                        image_description = img.properties.get("description") or alias
                        break
                if image_alias:
                    break
        expanded_config: dict[str, Any] = {}
        if image_description:
            expanded_config["image.description"] = image_description
        if image_os:
            expanded_config["image.os"] = image_os
        if image_alias:
            expanded_config["image.release"] = image_alias

        c = _FakeContainer(
            name=name,
            status="Stopped",
            status_code=102,
            profiles=config.get("profiles", ["default"]),
            config=config.get("config", {}),
            expanded_config=expanded_config,
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

    async def open_interactive_exec(
        self,
        container_name: str,
        command: list[str],
        environment: dict[str, Any] | None = None,
    ) -> _MockConsoleSession:
        """Spawn a real shell that impersonates the container.

        Using a real ``/bin/sh -i`` keeps the dev experience honest: the
        operator can type ``ls``, ``cat``, etc. and watch the output scroll.
        The shell carries a ``mock@<container>:$`` prompt so it's obvious
        which "container" the terminal is attached to.
        """
        await self.get_container(container_name)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/root"),
            "TERM": "xterm-256color",
            "PS1": f"mock@{container_name}:$ ",
            **(environment or {}),
        }
        # Drop the user's PS1 override; we want a stable prompt.
        env["PS1"] = f"mock@{container_name}:$ "
        try:
            process = await asyncio.subprocess.create_subprocess_exec(
                "/bin/sh",
                "-i",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except FileNotFoundError as exc:
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Cannot spawn mock shell for '{container_name}': {exc}") from exc
        return _MockConsoleSession(container_name, process)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def list_snapshots(self, container_name: str) -> list[_FakeSnapshot]:
        container = await self.get_container(container_name)
        return list(container.snapshots)

    async def create_snapshot(
        self,
        container_name: str,
        snapshot_name: str,
        stateful: bool = False,
        expires_at: str | None = None,
        wait: bool = True,
    ) -> _FakeSnapshot:
        container = await self.get_container(container_name)
        if any(s.name == snapshot_name for s in container.snapshots):
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Snapshot '{container_name}/{snapshot_name}' already exists")

        snapshot = _FakeSnapshot(name=snapshot_name, expires_at=expires_at, stateful=stateful)
        container.snapshots.append(snapshot)
        logger.info("mock.snapshot_created", container=container_name, name=snapshot_name)
        return snapshot

    async def delete_snapshot(
        self, container_name: str, snapshot_name: str, wait: bool = True
    ) -> None:
        container = await self.get_container(container_name)
        for index, snapshot in enumerate(container.snapshots):
            if snapshot.name == snapshot_name:
                del container.snapshots[index]
                logger.info("mock.snapshot_deleted", container=container_name, name=snapshot_name)
                return

        from services.lxd_client import LXDClientError

        raise LXDClientError(f"Snapshot '{container_name}/{snapshot_name}' not found")

    async def restore_snapshot(
        self, container_name: str, snapshot_name: str, wait: bool = True
    ) -> None:
        container = await self.get_container(container_name)
        if not any(s.name == snapshot_name for s in container.snapshots):
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Snapshot '{container_name}/{snapshot_name}' not found")

        logger.info("mock.snapshot_restored", container=container_name, name=snapshot_name)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def list_images(self) -> list[_FakeImage]:
        return list(self._images.values())

    async def get_image(self, fingerprint: str) -> _FakeImage:
        if fingerprint not in self._images:
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Image '{fingerprint}' not found")
        return self._images[fingerprint]

    async def import_image_from_simplestream(
        self, server: str, alias: str, local_alias: str | None = None
    ) -> _FakeImage:
        fp = hashlib.sha256(alias.encode()).hexdigest()[:12]
        img = _FakeImage(
            fingerprint=fp,
            aliases=[{"name": local_alias or alias, "description": alias}],
            properties={"description": alias, "os": alias.split("/")[0]},
            size=random.randint(50_000_000, 200_000_000),
            created_at=datetime.now(UTC).isoformat(),
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

    async def list_networks(self) -> list[_FakeNetwork]:
        return list(self._networks.values())

    async def get_network(self, name: str) -> _FakeNetwork:
        if name not in self._networks:
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Network '{name}' not found")
        return self._networks[name]

    async def create_network(self, config: dict[str, Any]) -> _FakeNetwork:
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

    async def list_storage_pools(self) -> list[_FakeStoragePool]:
        return list(self._storage_pools.values())

    async def get_storage_pool(self, name: str) -> _FakeStoragePool:
        if name not in self._storage_pools:
            from services.lxd_client import LXDClientError

            raise LXDClientError(f"Storage pool '{name}' not found")
        return self._storage_pools[name]

    async def create_storage_volume(self, pool_name: str, volume_config: dict[str, Any]) -> Any:
        await self.get_storage_pool(pool_name)
        logger.info("mock.volume_created", pool=pool_name, config=volume_config)
        return volume_config

    async def list_storage_volumes(self, pool_name: str) -> list[Any]:
        pool = await self.get_storage_pool(pool_name)
        return pool.volumes.all()
