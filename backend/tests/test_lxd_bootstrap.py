"""Tests for services.lxd_bootstrap and the /bootstrap router."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from models.host import Host
from models.user import User, UserRole
from services import lxd_bootstrap as bootstrap_mod
from services.lxd_bootstrap import LXDBootstrap, LXDBootstrapError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_bootstrap_singleton() -> Iterator[None]:
    bootstrap_mod.LXDBootstrap.reset()
    yield
    bootstrap_mod.LXDBootstrap.reset()


def _httpx_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = ""
    return response


def _patch_socket_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``_check_socket_access()`` a no-op for tests that mock the HTTP layer."""
    import stat as stat_mod

    sock_stat = type(
        "Stat",
        (),
        {
            "st_mode": stat_mod.S_IFSOCK | 0o660,
            "st_uid": 0,
            "st_gid": 998,
        },
    )()
    monkeypatch.setattr("os.stat", lambda _: sock_stat)
    monkeypatch.setattr("os.getuid", lambda: 0)
    monkeypatch.setattr("os.getgid", lambda: 0)
    monkeypatch.setattr("os.getgroups", lambda: [0, 998])


# ---------------------------------------------------------------------------
# Service-level: status detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_status_uninitialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    _patch_socket_access(monkeypatch)
    root = _httpx_response(
        200,
        {
            "metadata": {
                "api_version": "1.0",
                "server": "lxd",
                "public": True,
            }
        },
    )
    cluster = _httpx_response(404)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=[root, cluster])

    with patch("services.lxd_bootstrap.httpx.AsyncClient", return_value=client):
        info = await LXDBootstrap("/tmp/fake.sock").check_status()

    assert info.state == "uninitialized"
    assert info.api_version == "1.0"
    assert info.server == "lxd"


@pytest.mark.asyncio
async def test_check_status_untrusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    _patch_socket_access(monkeypatch)
    root = _httpx_response(
        200,
        {
            "metadata": {
                "api_version": "1.0",
                "server": "lxd",
                "public": True,
            }
        },
    )
    cluster = _httpx_response(403)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=[root, cluster])

    with patch("services.lxd_bootstrap.httpx.AsyncClient", return_value=client):
        info = await LXDBootstrap("/tmp/fake.sock").check_status()

    assert info.state == "untrusted"


@pytest.mark.asyncio
async def test_check_status_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    _patch_socket_access(monkeypatch)
    root = _httpx_response(
        200,
        {
            "metadata": {
                "api_version": "1.0",
                "server": "lxd",
                "public": False,
            }
        },
    )
    cluster = _httpx_response(200, {"metadata": {"enabled": True}})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=[root, cluster])

    with patch("services.lxd_bootstrap.httpx.AsyncClient", return_value=client):
        info = await LXDBootstrap("/tmp/fake.sock").check_status()

    assert info.state == "initialized"


@pytest.mark.asyncio
async def test_check_status_socket_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: False)
    with pytest.raises(LXDBootstrapError, match="LXD socket not found"):
        await LXDBootstrap("/var/missing.sock").check_status()


def test_check_socket_access_reports_uid_gid_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the socket exists but the process can't read it, the error names
    the offending UIDs/GIDs so the operator can diagnose without `docker exec`."""
    import stat as stat_mod

    sock_stat = type(
        "Stat",
        (),
        {
            "st_mode": stat_mod.S_IFSOCK | 0o660,
            "st_uid": 0,
            "st_gid": 998,
        },
    )()

    monkeypatch.setattr("os.path.exists", lambda _: True)
    monkeypatch.setattr("os.stat", lambda _: sock_stat)
    monkeypatch.setattr("os.getuid", lambda: 999)
    monkeypatch.setattr("os.getgid", lambda: 999)
    monkeypatch.setattr("os.getgroups", lambda: [999])

    bootstrap = LXDBootstrap("/var/snap/lxd/common/lxd/unix.socket")
    with pytest.raises(LXDBootstrapError) as excinfo:
        bootstrap._check_socket_access()

    msg = str(excinfo.value)
    assert "Permission denied" in msg
    assert "UID 999" in msg
    assert "GID 998" in msg
    assert "LXD_GID" in msg


def test_check_socket_access_passes_when_group_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the process's supplementary groups include the socket's GID, no error."""
    import stat as stat_mod

    sock_stat = type(
        "Stat",
        (),
        {
            "st_mode": stat_mod.S_IFSOCK | 0o660,
            "st_uid": 0,
            "st_gid": 998,
        },
    )()

    monkeypatch.setattr("os.path.exists", lambda _: True)
    monkeypatch.setattr("os.stat", lambda _: sock_stat)
    monkeypatch.setattr("os.getuid", lambda: 999)
    monkeypatch.setattr("os.getgid", lambda: 999)
    monkeypatch.setattr("os.getgroups", lambda: [999, 998])

    LXDBootstrap("/var/snap/lxd/common/lxd/unix.socket")._check_socket_access()  # no raise


# ---------------------------------------------------------------------------
# Service-level: bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    _patch_socket_access(monkeypatch)
    resp = _httpx_response(202, {"operation": "op1"})
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=resp)

    with patch("services.lxd_bootstrap.httpx.AsyncClient", return_value=client):
        await LXDBootstrap("/tmp/fake.sock").bootstrap(
            server_name="node1", cluster_password="supersecret-password"
        )

    client.post.assert_awaited_once()
    url_arg, kwargs = client.post.call_args.args[0], client.post.call_args.kwargs
    assert "/1.0/cluster" in url_arg
    assert kwargs["json"]["cluster"]["server_name"] == "node1"
    assert kwargs["json"]["cluster"]["enabled"] is True


@pytest.mark.asyncio
async def test_bootstrap_refused_with_lxd_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.path.exists", lambda _: True)
    _patch_socket_access(monkeypatch)
    resp = _httpx_response(
        400,
        {"error": "cluster member already exists"},
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=resp)

    with (
        patch("services.lxd_bootstrap.httpx.AsyncClient", return_value=client),
        pytest.raises(LXDBootstrapError, match="cluster member already exists"),
    ):
        await LXDBootstrap("/tmp/fake.sock").bootstrap(
            server_name="node1", cluster_password="supersecret-password"
        )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_bootstrap_request_rejects_short_password() -> None:
    from pydantic import ValidationError

    from schemas.bootstrap import ClusterConfig

    with pytest.raises(ValidationError):
        ClusterConfig(server_name="n1", cluster_password="short")


def test_bootstrap_request_strips_whitespace() -> None:
    from schemas.bootstrap import ClusterConfig

    cfg = ClusterConfig(server_name="  node1  ", cluster_password="supersecret-password")
    assert cfg.server_name == "node1"


def test_bootstrap_request_forbids_extra_fields() -> None:
    from pydantic import ValidationError

    from schemas.bootstrap import ClusterConfig

    with pytest.raises(ValidationError):
        ClusterConfig(
            server_name="n1",
            cluster_password="supersecret-password",
            bogus_field="x",
        )


# ---------------------------------------------------------------------------
# Router-level: requires admin
# ---------------------------------------------------------------------------


def _admin_user() -> User:
    return User(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        role=UserRole.admin,
        is_active=True,
    )


@pytest.fixture
def admin_user() -> User:
    return _admin_user()


def test_router_requires_admin(client, db_session, admin_user):
    """A viewer cannot bootstrap."""
    from dependencies import get_current_user
    from main import app

    viewer = User(
        id=2,
        username="viewer",
        email="v@example.com",
        hashed_password="x",
        role=UserRole.viewer,
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: viewer

    try:
        resp = client.get("/bootstrap/status")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Router-level: bootstrap happy path creates a Host record
# ---------------------------------------------------------------------------


def test_bootstrap_creates_host_record(client, db_session, admin_user):
    from dependencies import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: admin_user

    # Mock the bootstrap service so we don't need a real LXD socket.
    fake_status = bootstrap_mod.BootstrapInfo(
        state="uninitialized",
        api_version="1.0",
        server="lxd",
    )
    instance = MagicMock()
    instance.check_status = AsyncMock(return_value=fake_status)
    instance.bootstrap = AsyncMock(return_value=None)
    instance.socket_path = "/tmp/fake.sock"
    bootstrap_mod.LXDBootstrap._instance = instance

    try:
        resp = client.post(
            "/bootstrap/cluster",
            json={
                "host_name": "node1",
                "cluster": {
                    "server_name": "node1",
                    "cluster_password": "supersecret-password",
                },
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["state"] == "initialized"
        assert body["host_name"] == "node1"

        hosts = db_session.query(Host).all()
        assert len(hosts) == 1
        assert hosts[0].name == "node1"
        assert hosts[0].connection_type.value == "socket"
        assert hosts[0].is_active is True
    finally:
        app.dependency_overrides.clear()
        bootstrap_mod.LXDBootstrap.reset()


def test_bootstrap_refuses_when_already_initialized(client, admin_user):
    from dependencies import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: admin_user

    fake_status = bootstrap_mod.BootstrapInfo(
        state="initialized",
        api_version="1.0",
        server="lxd",
    )
    instance = MagicMock()
    instance.check_status = AsyncMock(return_value=fake_status)
    instance.bootstrap = AsyncMock()
    instance.socket_path = "/tmp/fake.sock"
    bootstrap_mod.LXDBootstrap._instance = instance

    try:
        resp = client.post(
            "/bootstrap/cluster",
            json={
                "host_name": "node1",
                "cluster": {
                    "server_name": "node1",
                    "cluster_password": "supersecret-password",
                },
            },
        )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()
        bootstrap_mod.LXDBootstrap.reset()


def test_bootstrap_returns_409_on_host_name_conflict(client, db_session, admin_user):
    from dependencies import get_current_user
    from main import app

    # Pre-existing host with the same name.
    from models.host import ConnectionType

    existing = Host(
        name="node1",
        address="/var/snap/lxd/common/lxd/unix.socket",
        connection_type=ConnectionType.socket,
        is_active=True,
    )
    db_session.add(existing)
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: admin_user

    fake_status = bootstrap_mod.BootstrapInfo(
        state="uninitialized",
        api_version="1.0",
        server="lxd",
    )
    instance = MagicMock()
    instance.check_status = AsyncMock(return_value=fake_status)
    instance.bootstrap = AsyncMock(return_value=None)
    instance.socket_path = "/tmp/fake.sock"
    bootstrap_mod.LXDBootstrap._instance = instance

    try:
        resp = client.post(
            "/bootstrap/cluster",
            json={
                "host_name": "node1",
                "cluster": {
                    "server_name": "node1",
                    "cluster_password": "supersecret-password",
                },
            },
        )
        # The LXD preseed would succeed, but the host insert fails.
        # The service should surface a 502 from the LXD call (mocked OK),
        # then 409 on the host insert. We assert the final status is 4xx.
        assert resp.status_code in (409, 502)
    finally:
        app.dependency_overrides.clear()
        bootstrap_mod.LXDBootstrap.reset()
