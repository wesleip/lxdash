"""Tests for the /containers router."""

from __future__ import annotations

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
