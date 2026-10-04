"""Tests for the host registry: services.host_service and the /hosts router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.host import ConnectionType, Host
from models.user import User, UserRole
from services import host_service
from services.host_service import (
    AmbiguousHostError,
    HostConflictError,
    HostNotFoundError,
    NoHostRegisteredError,
    ensure_local_host,
    register_host,
    resolve_host,
)
from services.lxd_probe import LXDProbeError, ResourcesInfo, ServerInfo

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user() -> User:
    return User(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        role=UserRole.admin,
        is_active=True,
    )


@pytest.fixture
def viewer_user() -> User:
    return User(
        id=2,
        username="viewer",
        email="v@example.com",
        hashed_password="x",
        role=UserRole.viewer,
        is_active=True,
    )


def _auth(app, user: User) -> None:
    from dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def _make_host(db_session, name: str, **kwargs) -> Host:
    defaults = {
        "address": f"/var/snap/lxd/common/lxd/unix.socket.{name}",
        "connection_type": ConnectionType.socket,
        "is_active": True,
    }
    defaults.update(kwargs)
    host = Host(name=name, **defaults)
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)
    return host


def _server_info(**kwargs) -> ServerInfo:
    defaults = {
        "api_version": "1.0",
        "api_extensions": ("storage", "container_exec_recording"),
        "server": "lxd",
        "public": False,
        "auth": "trusted",
        "cluster_state": "present",
        "clustered": False,
        "server_name": "node1",
    }
    defaults.update(kwargs)
    return ServerInfo(**defaults)


# ---------------------------------------------------------------------------
# Service: resolve_host
# ---------------------------------------------------------------------------


def test_resolve_host_without_any_host_raises(db_session):
    with pytest.raises(NoHostRegisteredError, match="No LXD hosts registered"):
        resolve_host(db_session, None)


def test_resolve_host_falls_back_to_the_only_active_host(db_session):
    host = _make_host(db_session, "node1")

    assert resolve_host(db_session, None).id == host.id


def test_resolve_host_ignores_inactive_hosts_in_the_fallback(db_session):
    """A deactivated host must not keep the panel alive on stale credentials."""
    _make_host(db_session, "node1", is_active=False)

    with pytest.raises(NoHostRegisteredError):
        resolve_host(db_session, None)


def test_resolve_host_requires_an_explicit_choice_when_ambiguous(db_session):
    _make_host(db_session, "node1")
    _make_host(db_session, "node2")

    with pytest.raises(AmbiguousHostError, match="host_id"):
        resolve_host(db_session, None)


def test_resolve_host_honours_explicit_id_among_several(db_session):
    first = _make_host(db_session, "node1")
    _make_host(db_session, "node2")

    assert resolve_host(db_session, first.id).id == first.id


def test_resolve_host_rejects_unknown_id(db_session):
    _make_host(db_session, "node1")

    with pytest.raises(HostNotFoundError, match="Host 99 not found"):
        resolve_host(db_session, 99)


def test_resolve_host_rejects_inactive_host_by_id(db_session):
    host = _make_host(db_session, "node1", is_active=False)

    with pytest.raises(HostNotFoundError):
        resolve_host(db_session, host.id)


# ---------------------------------------------------------------------------
# Service: register_host
# ---------------------------------------------------------------------------


def test_register_host_rejects_duplicate_name(db_session):
    _make_host(db_session, "node1")

    with pytest.raises(HostConflictError, match="already registered"):
        register_host(
            db_session,
            name="node1",
            address="/var/snap/lxd/common/lxd/unix.socket.other",
            connection_type=ConnectionType.socket,
        )


def test_register_host_rejects_duplicate_address(db_session):
    """Two rows for one daemon would make host_id ambiguous for the operator."""
    _make_host(db_session, "node1", address="/shared/unix.socket")

    with pytest.raises(HostConflictError, match="already registered"):
        register_host(
            db_session,
            name="node2",
            address="/shared/unix.socket",
            connection_type=ConnectionType.socket,
        )


def test_register_host_allows_the_same_address_on_a_different_transport(db_session):
    _make_host(db_session, "node1", address="https://10.0.0.1:8443")

    host = register_host(
        db_session,
        name="node1-tls",
        address="https://10.0.0.1:8443",
        connection_type=ConnectionType.tls,
    )
    assert host.connection_type is ConnectionType.tls


# ---------------------------------------------------------------------------
# Service: ensure_local_host
# ---------------------------------------------------------------------------


async def test_ensure_local_host_registers_the_local_daemon(db_session):
    with patch(
        "services.host_service.fetch_server_info",
        AsyncMock(return_value=_server_info()),
    ):
        host = await ensure_local_host(db_session, "/var/snap/lxd/common/lxd/unix.socket")

    assert host is not None
    assert host.name == "node1"
    assert host.connection_type is ConnectionType.socket
    assert host.is_active is True


async def test_ensure_local_host_is_idempotent(db_session):
    with patch(
        "services.host_service.fetch_server_info",
        AsyncMock(return_value=_server_info()),
    ):
        first = await ensure_local_host(db_session, "/var/snap/lxd/common/lxd/unix.socket")
        second = await ensure_local_host(db_session, "/var/snap/lxd/common/lxd/unix.socket")

    assert first.id == second.id
    assert db_session.query(Host).count() == 1


async def test_ensure_local_host_reactivates_a_deactivated_host(db_session):
    _make_host(db_session, "node1", address="/var/snap/lxd/common/lxd/unix.socket", is_active=False)

    with patch("services.host_service.fetch_server_info", AsyncMock(return_value=_server_info())):
        host = await ensure_local_host(db_session, "/var/snap/lxd/common/lxd/unix.socket")

    assert host.is_active is True


async def test_ensure_local_host_is_a_noop_without_a_daemon(db_session):
    """A missing LXD must never stop the app from booting."""
    with patch(
        "services.host_service.fetch_server_info",
        AsyncMock(side_effect=LXDProbeError("LXD socket not found")),
    ):
        host = await ensure_local_host(db_session, "/var/snap/lxd/common/lxd/unix.socket")

    assert host is None
    assert db_session.query(Host).count() == 0


# ---------------------------------------------------------------------------
# Router: GET /hosts
# ---------------------------------------------------------------------------


def test_list_hosts_requires_authentication(client):
    assert client.get("/hosts").status_code == 401


def test_list_hosts_returns_every_host(client, db_session, admin_user):
    from main import app

    _make_host(db_session, "node1")
    _make_host(db_session, "node2", is_active=False)
    _auth(app, admin_user)
    try:
        resp = client.get("/hosts")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert [h["name"] for h in body] == ["node1", "node2"]
    assert body[1]["is_active"] is False
    # TLS material must never leave the backend.
    assert "tls_cert" not in body[0]


# ---------------------------------------------------------------------------
# Router: POST /hosts
# ---------------------------------------------------------------------------


def test_create_host_requires_admin(client, viewer_user):
    from main import app

    _auth(app, viewer_user)
    try:
        resp = client.post("/hosts", json={"name": "node1", "address": "/lxd-test/unix.socket"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_create_host_rejects_an_unreachable_daemon(client, db_session, admin_user):
    from main import app

    _auth(app, admin_user)
    with patch(
        "routers.hosts.fetch_server_info",
        AsyncMock(side_effect=LXDProbeError("connection refused")),
    ):
        try:
            resp = client.post("/hosts", json={"name": "node1", "address": "/lxd-test/unix.socket"})
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 502
    assert "connection refused" in resp.json()["detail"]
    assert db_session.query(Host).count() == 0


def test_create_host_registers_after_a_successful_probe(client, db_session, admin_user):
    from main import app

    _auth(app, admin_user)
    with patch("routers.hosts.fetch_server_info", AsyncMock(return_value=_server_info())):
        try:
            resp = client.post("/hosts", json={"name": "node1", "address": "/lxd-test/unix.socket"})
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
    assert resp.json()["connection_type"] == "socket"
    assert db_session.query(Host).count() == 1


def test_create_host_rejects_a_duplicate_name(client, db_session, admin_user):
    from main import app

    _make_host(db_session, "node1")

    _auth(app, admin_user)
    with patch("routers.hosts.fetch_server_info", AsyncMock(return_value=_server_info())):
        try:
            resp = client.post("/hosts", json={"name": "node1", "address": "/lxd-test/other.sock"})
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 409


def test_create_host_validates_the_transport_fields(client, admin_user):
    from main import app

    _auth(app, admin_user)
    try:
        relative = client.post("/hosts", json={"name": "node1", "address": "lxd.sock"})
        no_certs = client.post(
            "/hosts",
            json={
                "name": "node2",
                "address": "https://10.0.0.1:8443",
                "connection_type": "tls",
            },
        )
        bad_scheme = client.post(
            "/hosts",
            json={
                "name": "node3",
                "address": "http://10.0.0.1:8443",
                "connection_type": "tls",
                "tls_cert": "cert",
                "tls_key": "key",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert relative.status_code == 422
    assert no_certs.status_code == 422
    assert bad_scheme.status_code == 422


# ---------------------------------------------------------------------------
# Router: DELETE /hosts/{id}
# ---------------------------------------------------------------------------


def test_delete_host_requires_admin(client, db_session, viewer_user):
    from main import app

    host = _make_host(db_session, "node1")
    _auth(app, viewer_user)
    try:
        resp = client.delete(f"/hosts/{host.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_delete_host_removes_the_row(client, db_session, admin_user):
    from main import app

    host = _make_host(db_session, "node1")
    _auth(app, admin_user)
    try:
        resp = client.delete(f"/hosts/{host.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204
    assert db_session.query(Host).count() == 0


def test_delete_unknown_host_is_404(client, admin_user):
    from main import app

    _auth(app, admin_user)
    try:
        resp = client.delete("/hosts/999")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Router: GET /hosts/{id}/health
# ---------------------------------------------------------------------------


def test_health_reports_an_unreachable_host_without_failing(client, db_session, admin_user):
    """A down host must not break the whole fleet listing."""
    from main import app

    host = _make_host(db_session, "node1")
    _auth(app, admin_user)
    with patch(
        "routers.hosts.probe_host",
        AsyncMock(side_effect=LXDProbeError("LXD socket not found")),
    ):
        try:
            resp = client.get(f"/hosts/{host.id}/health")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is False
    assert "LXD socket not found" in body["message"]


def test_health_reports_what_the_daemon_says(client, db_session, admin_user):
    from main import app

    host = _make_host(db_session, "node1")
    resources = ResourcesInfo(
        cpu_total=8,
        memory_total=16_000_000_000,
        architecture="x86_64",
        os_name="Ubuntu",
        os_version="24.04",
        hostname="srv01",
    )

    _auth(app, admin_user)
    with (
        patch("routers.hosts.probe_host", AsyncMock(return_value=_server_info())),
        patch("routers.hosts.fetch_resources", AsyncMock(return_value=resources)),
    ):
        try:
            resp = client.get(f"/hosts/{host.id}/health")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["api_version"] == "1.0"
    assert body["api_extensions_count"] == 2
    assert body["clustered"] is False
    assert body["server_name"] == "node1"
    assert body["cpu_total"] == 8
    assert body["os_name"] == "Ubuntu"


def test_health_survives_a_daemon_without_resources(client, db_session, admin_user):
    from main import app

    host = _make_host(db_session, "node1")
    _auth(app, admin_user)
    with (
        patch("routers.hosts.probe_host", AsyncMock(return_value=_server_info())),
        patch(
            "routers.hosts.fetch_resources",
            AsyncMock(side_effect=LXDProbeError("not found")),
        ),
    ):
        try:
            resp = client.get(f"/hosts/{host.id}/health")
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["cpu_total"] is None


def test_health_of_unknown_host_is_404(client, admin_user):
    from main import app

    _auth(app, admin_user)
    try:
        resp = client.get("/hosts/999/health")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: the panel is usable again with no host_id on the request
# ---------------------------------------------------------------------------


def test_resource_routes_fall_back_to_the_single_host(client, db_session, admin_user):
    """The bug this whole registry exists for: /containers used to 422 without
    a host_id and there was no way to create the row."""
    from main import app

    _make_host(db_session, "node1")
    _auth(app, admin_user)
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text


def test_resource_routes_ask_for_a_choice_when_ambiguous(client, db_session, admin_user):
    from main import app

    _make_host(db_session, "node1")
    _make_host(db_session, "node2")
    _auth(app, admin_user)
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert "host_id" in resp.json()["detail"]


def test_resource_routes_report_when_nothing_is_registered(client, db_session, admin_user):
    from main import app

    _auth(app, admin_user)
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert "No LXD hosts registered" in resp.json()["detail"]


def test_module_exposes_the_registry_entrypoints():
    """Guard against the shared helpers being renamed out from under callers."""
    for name in ("resolve_host", "connect_host", "register_host", "ensure_local_host"):
        assert callable(getattr(host_service, name))


# ---------------------------------------------------------------------------
# Startup hook: main._autoregister_local_host
# ---------------------------------------------------------------------------


async def test_startup_hook_registers_the_mock_host(db_session, engine, monkeypatch):
    """LXD_MOCK deployments get a host row too, so dev mode exercises the gate."""
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    import main

    monkeypatch.setattr(main, "settings", SimpleNamespace(LXD_MOCK=True))
    monkeypatch.setattr(
        main,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    await main._autoregister_local_host()

    hosts = db_session.query(Host).all()
    assert [h.name for h in hosts] == [host_service.MOCK_HOST_NAME]
    assert hosts[0].address == host_service.MOCK_HOST_ADDRESS
    assert hosts[0].is_active is True


async def test_startup_hook_ignores_an_unreachable_local_daemon(db_session, engine, monkeypatch):
    """Production mode with no reachable daemon: boot anyway, register nothing."""
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    import main

    monkeypatch.setattr(main, "settings", SimpleNamespace(LXD_MOCK=False))
    monkeypatch.setattr(
        main,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with patch(
        "main.ensure_local_host",
        AsyncMock(side_effect=RuntimeError("socket is not mounted")),
    ):
        # A missing LXD must never stop the app from booting.
        await main._autoregister_local_host()

    assert db_session.query(Host).count() == 0


async def test_startup_hook_swallows_registration_failures(db_session, engine, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    import main

    monkeypatch.setattr(main, "settings", SimpleNamespace(LXD_MOCK=True))
    monkeypatch.setattr(
        main,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )

    with patch("main.ensure_mock_host", MagicMock(side_effect=RuntimeError("boom"))):
        await main._autoregister_local_host()

    assert db_session.query(Host).count() == 0
