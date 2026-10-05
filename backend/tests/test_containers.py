"""Tests for the /containers router."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from models.host import ConnectionType, Host
from models.user import User, UserRole


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


def _auth(app, user: User) -> None:
    from dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def _make_host(db_session, name: str = "node1") -> Host:
    host = Host(
        name=name,
        address=f"/var/snap/lxd/common/lxd/unix.socket.{name}",
        connection_type=ConnectionType.socket,
        is_active=True,
    )
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)
    return host


def test_create_container_without_body_host_id(client, db_session, admin_user):
    """Regression: `host_id` used to be required in the body while the frontend
    only ever sends it as `?host_id=`, so creating a container always failed
    with 422 `body.host_id: Field required`.
    """
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.post(
            "/containers",
            json={"name": "regression-check", "image": "ubuntu:22.04"},
        )
    finally:
        app.dependency_overrides.clear()
        # MockLXDClient keeps class-level state across tests.
        from services.lxd_client_mock import MockLXDClient

        MockLXDClient._containers.pop("regression-check", None)

    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "regression-check"


def test_list_containers_falls_back_to_the_single_host(client, db_session, admin_user):
    """Without `?host_id=` the backend must pick the single registered host —
    that is the "Automatic" selection the frontend sends by default.
    """
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) > 0


def test_create_container_rejects_an_invalid_name(client, db_session, admin_user):
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.post("/containers", json={"name": "bad name!", "image": "ubuntu:22.04"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_start_and_stop_container(client, db_session, admin_user):
    """The routes the frontend start/stop/restart buttons call."""
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        started = client.post("/containers/web-prod/start", json={"timeout": 30})
        assert started.status_code == 200, started.text

        stopped = client.post("/containers/web-prod/stop", json={"timeout": 30})
        assert stopped.status_code == 200, stopped.text
    finally:
        app.dependency_overrides.clear()
        from services.lxd_client_mock import MockLXDClient

        # Restore the seeded container's original running state.
        MockLXDClient._containers["web-prod"].status = "Running"
        MockLXDClient._containers["web-prod"].status_code = 103


def test_get_container_state(client, db_session, admin_user):
    """GET /containers/{name}/state — the endpoint the Resources tab polls."""
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.get("/containers/web-prod/state")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "Running"
    assert data["status_code"] == 103
    assert data["cpu"]["usage"] >= 0
    assert data["memory"]["usage"] > 0
    assert "/" in data["disk"]
    assert data["network"]["eth0"]["hwaddr"] == "00:16:3e:ab:cd:ef"
    assert data["network"]["eth0"]["addresses"][0]["scope"] == "global"
    assert data["pid"] > 0
    assert data["processes"] >= 1


def test_container_state_is_404_for_an_unknown_container(client, db_session, admin_user):
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.get("/containers/no-such-container/state")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_unknown_container_is_404(client, db_session, admin_user):
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.get("/containers/no-such-container")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_list_requires_authentication(client):
    resp = client.get("/containers")
    assert resp.status_code == 401


def test_snapshots_list_create_restore_and_delete(client, db_session, admin_user):
    """The four snapshot routes behind the Snapshots tab."""
    from main import app
    from services.lxd_client_mock import MockLXDClient

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        listed = client.get("/containers/web-prod/snapshots")
        assert listed.status_code == 200, listed.text
        assert {s["name"] for s in listed.json()} == {"snap0"}
        assert listed.json()[0]["created_at"]

        created = client.post("/containers/web-prod/snapshots", json={"name": "nightly"})
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "nightly"
        assert created.json()["expires_at"] is None

        restored = client.post("/containers/web-prod/snapshots/snap0/restore")
        assert restored.status_code == 204, restored.text

        deleted = client.delete("/containers/web-prod/snapshots/nightly")
        assert deleted.status_code == 204, deleted.text

        listed_again = client.get("/containers/web-prod/snapshots")
        assert {s["name"] for s in listed_again.json()} == {"snap0"}
    finally:
        app.dependency_overrides.clear()
        # MockLXDClient keeps class-level state across tests: drop the snapshot
        # this test created and restore the seeded one if it was deleted.
        snaps = MockLXDClient._containers["web-prod"].snapshots
        snaps[:] = [s for s in snaps if s.name == "snap0"]
        if not snaps:
            from services.lxd_client_mock import _FakeSnapshot

            snaps.append(_FakeSnapshot(name="snap0", created_at="2024-05-01T10:00:00+00:00"))


def test_snapshot_name_is_validated(client, db_session, admin_user):
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.post("/containers/web-prod/snapshots", json={"name": "bad name!"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_snapshots_of_an_unknown_container_are_404(client, db_session, admin_user):
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    try:
        resp = client.get("/containers/no-such-container/snapshots")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: non-clustered LXD daemons report ``location: null``
# ---------------------------------------------------------------------------


class _StubContainer:
    """Mirror the pylxd attribute surface used by the mapper.

    pylxd forces ``location = None`` on non-clustered daemons (its
    own ``Instance.__setattr__`` does it), which is the exact shape
    that made ``GET /containers`` answer 500: an explicit ``None``
    never falls back to the pydantic field default (``location: str
    = ""``) — the default only applies when the key is absent.
    """

    def __init__(self, **overrides):
        self.name = "web"
        self.status = "Running"
        self.status_code = 103
        self.type = "container"
        self.profiles = ["default"]
        self.config = {}
        self.architecture = "x86_64"
        self.created_at = "2026-10-04T00:00:00Z"
        self.last_used_at = None
        self.location = None
        for key, value in overrides.items():
            setattr(self, key, value)


def test_mapper_normalises_none_location_to_empty_string():
    from routers.containers import _container_to_response

    assert _container_to_response(_StubContainer()).location == ""


def test_summary_pulls_image_label_from_expanded_config():
    from routers.containers import _container_to_summary

    container = _StubContainer(
        expanded_config={
            "image.description": "Ubuntu 24.04 LTS (Noble Numbat)",
            "image.os": "Ubuntu",
            "image.release": "noble",
        }
    )
    summary = _container_to_summary(container)
    assert summary.image == "Ubuntu 24.04 LTS (Noble Numbat)"
    assert summary.name == "web"


def test_summary_falls_back_to_image_os_when_description_missing():
    from routers.containers import _container_to_summary

    container = _StubContainer(expanded_config={"image.os": "Alpine"})
    assert _container_to_summary(container).image == "Alpine"


def test_summary_image_is_empty_when_no_image_keys():
    from routers.containers import _container_to_summary

    assert _container_to_summary(_StubContainer(expanded_config={})).image == ""


def test_summary_extracts_first_global_ipv4_from_state():
    from routers.containers import _container_to_summary

    state = SimpleNamespace(
        network={
            "lo": {"addresses": [{"family": "inet", "address": "127.0.0.1", "scope": "local"}]},
            "eth0": {
                "addresses": [
                    {"family": "inet", "address": "10.0.0.42", "scope": "global"},
                    {"family": "inet6", "address": "fe80::1", "scope": "link"},
                    {"family": "inet6", "address": "2001:db8::1", "scope": "global"},
                ]
            },
        }
    )
    container = _StubContainer()
    summary = _container_to_summary(container, state)
    assert summary.ipv4 == "10.0.0.42"
    assert summary.ipv6 == "2001:db8::1"


def test_summary_keeps_ipv4_null_when_state_is_missing():
    from routers.containers import _container_to_summary

    assert _container_to_summary(_StubContainer(), state=None).ipv4 is None


def test_list_returns_image_and_ipv4_for_running_containers(client, db_session, admin_user):
    """Regression: the list payload used to omit both image and ipv4, so the
    panel rendered blank cells in the /containers table. The summary mapper
    must surface image.description and the first global inet address.
    """
    from unittest.mock import AsyncMock

    from dependencies import get_lxd_client
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    lxd = AsyncMock()
    lxd.list_containers.return_value = [
        _StubContainer(
            expanded_config={"image.description": "Archlinux current (20260401)"},
        ),
    ]
    lxd.get_container_state.return_value = SimpleNamespace(
        network={
            "eth0": {"addresses": [{"family": "inet", "address": "10.42.0.5", "scope": "global"}]}
        }
    )
    app.dependency_overrides[get_lxd_client] = lambda: lxd
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["image"] == "Archlinux current (20260401)"
    assert body[0]["ipv4"] == "10.42.0.5"
    assert body[0]["ipv6"] is None


def test_mapper_keeps_real_cluster_location():
    from routers.containers import _container_to_response

    container = _StubContainer(location="node-1")
    assert _container_to_response(container).location == "node-1"


def test_list_containers_survives_a_none_location(client, db_session, admin_user):
    """The dashboard polls GET /containers every 5s — it must not 500
    on a non-clustered daemon, where pylxd exposes location=None.
    """
    from unittest.mock import AsyncMock

    from dependencies import get_lxd_client
    from main import app

    _make_host(db_session)
    _auth(app, admin_user)
    lxd = AsyncMock()
    lxd.list_containers.return_value = [_StubContainer()]
    # No state — must not raise; ipv4 simply stays null.
    lxd.get_container_state.side_effect = RuntimeError("state unreachable")
    app.dependency_overrides[get_lxd_client] = lambda: lxd
    try:
        resp = client.get("/containers")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["name"] == "web"
    assert body[0]["status"] == "Running"
    assert body[0]["ipv4"] is None
    assert body[0]["image"] == ""
