"""Tests for dependencies.get_lxd_client host-resolution rules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from config import get_settings
from models.host import ConnectionType, Host


def _make_host(host_id: int, is_active: bool = True) -> Host:
    return Host(
        id=host_id,
        name=f"node{host_id}",
        address="/var/snap/lxd/common/lxd/unix.socket",
        connection_type=ConnectionType.socket,
        is_active=is_active,
    )


def _force_lxd_mock(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Force ``LXD_MOCK`` for host_service without touching the global settings."""
    stub = SimpleNamespace(**{**vars(get_settings()), "LXD_MOCK": enabled})
    monkeypatch.setattr("services.host_service.get_settings", lambda: stub)


# ---------------------------------------------------------------------------
# resolve_host
# ---------------------------------------------------------------------------


def test_resolve_host_with_zero_hosts(db_session: Any) -> None:
    from services.host_service import NoHostRegisteredError, resolve_host

    with pytest.raises(NoHostRegisteredError) as excinfo:
        resolve_host(db_session, None)
    assert "register" in str(excinfo.value).lower()


def test_resolve_host_with_single_active_host(db_session: Any) -> None:
    from services.host_service import resolve_host

    db_session.add(_make_host(7))
    db_session.commit()

    assert resolve_host(db_session, None).id == 7


def test_resolve_host_with_inactive_hosts_only(db_session: Any) -> None:
    from services.host_service import NoHostRegisteredError, resolve_host

    db_session.add(_make_host(1, is_active=False))
    db_session.add(_make_host(2, is_active=False))
    db_session.commit()

    with pytest.raises(NoHostRegisteredError):
        resolve_host(db_session, None)


def test_resolve_host_with_multiple_active_hosts(db_session: Any) -> None:
    from services.host_service import AmbiguousHostError, resolve_host

    db_session.add(_make_host(1))
    db_session.add(_make_host(2))
    db_session.add(_make_host(3))
    db_session.commit()

    with pytest.raises(AmbiguousHostError) as excinfo:
        resolve_host(db_session, None)
    assert "3" in str(excinfo.value)  # count is reported
    assert "host_id" in str(excinfo.value)


def test_resolve_host_skips_inactive_hosts(db_session: Any) -> None:
    from services.host_service import resolve_host

    db_session.add(_make_host(5))
    db_session.add(_make_host(2, is_active=False))
    db_session.commit()

    # The inactive host must not turn a single-host deployment ambiguous.
    assert resolve_host(db_session, None).id == 5


# ---------------------------------------------------------------------------
# get_lxd_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lxd_client_uses_only_active_host_by_default(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    _force_lxd_mock(monkeypatch, False)

    db_session.add(_make_host(42))
    db_session.commit()

    fake_client = AsyncMock()
    with patch("dependencies.LXDClient.connect_socket", AsyncMock(return_value=fake_client)):
        result = await get_lxd_client(db=db_session, current_user=None, host_id=None)

    assert result is fake_client


@pytest.mark.asyncio
async def test_get_lxd_client_raises_when_no_hosts(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    _force_lxd_mock(monkeypatch, False)

    with pytest.raises(HTTPException) as excinfo:
        await get_lxd_client(db=db_session, current_user=None, host_id=None)
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_get_lxd_client_raises_when_multiple_hosts(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    _force_lxd_mock(monkeypatch, False)

    db_session.add(_make_host(1))
    db_session.add(_make_host(2))
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await get_lxd_client(db=db_session, current_user=None, host_id=None)
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_get_lxd_client_explicit_host_overrides_default(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    _force_lxd_mock(monkeypatch, False)

    db_session.add(_make_host(1))
    db_session.add(_make_host(2))
    db_session.commit()

    fake_client = AsyncMock()
    with patch("dependencies.LXDClient.connect_socket", AsyncMock(return_value=fake_client)):
        # Explicit host_id=2 must succeed even though no default can be picked.
        result = await get_lxd_client(db=db_session, current_user=None, host_id=2)

    assert result is fake_client


@pytest.mark.asyncio
async def test_get_lxd_client_404_for_inactive_explicit_host(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    _force_lxd_mock(monkeypatch, False)

    db_session.add(_make_host(1, is_active=False))
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await get_lxd_client(db=db_session, current_user=None, host_id=1)
    assert excinfo.value.status_code == 404
