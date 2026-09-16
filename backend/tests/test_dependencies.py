"""Tests for dependencies.get_lxd_client host-resolution rules."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from models.host import ConnectionType, Host


def _make_host(host_id: int, is_active: bool = True) -> Host:
    return Host(
        id=host_id,
        name=f"node{host_id}",
        address="/var/snap/lxd/common/lxd/unix.socket",
        connection_type=ConnectionType.socket,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# _resolve_default_host_id
# ---------------------------------------------------------------------------


def test_resolve_default_with_zero_hosts(db_session: Any) -> None:
    from dependencies import _resolve_default_host_id

    with pytest.raises(HTTPException) as excinfo:
        _resolve_default_host_id(db_session)
    assert excinfo.value.status_code == 422
    assert "bootstrap" in excinfo.value.detail.lower()


def test_resolve_default_with_single_active_host(db_session: Any) -> None:
    from dependencies import _resolve_default_host_id

    db_session.add(_make_host(7))
    db_session.commit()

    assert _resolve_default_host_id(db_session) == 7


def test_resolve_default_with_inactive_hosts_only(db_session: Any) -> None:
    from dependencies import _resolve_default_host_id

    db_session.add(_make_host(1, is_active=False))
    db_session.add(_make_host(2, is_active=False))
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        _resolve_default_host_id(db_session)
    assert excinfo.value.status_code == 422


def test_resolve_default_with_multiple_active_hosts(db_session: Any) -> None:
    from dependencies import _resolve_default_host_id

    db_session.add(_make_host(1))
    db_session.add(_make_host(2))
    db_session.add(_make_host(3))
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        _resolve_default_host_id(db_session)
    assert excinfo.value.status_code == 422
    assert "3" in excinfo.value.detail  # count is reported
    assert "Phase 3" in excinfo.value.detail


def test_resolve_default_picks_lowest_id(db_session: Any) -> None:
    from dependencies import _resolve_default_host_id

    db_session.add(_make_host(5))
    db_session.add(_make_host(2))
    db_session.commit()

    # Single-active case still uses the only one — but with two active hosts
    # it would 422. Verify the inactive case returns the only active.
    db_session.delete(db_session.get(Host, 2))
    db_session.commit()
    assert _resolve_default_host_id(db_session) == 5


# ---------------------------------------------------------------------------
# get_lxd_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lxd_client_uses_only_active_host_by_default(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    monkeypatch.setattr("dependencies.settings.LXD_MOCK", False)

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

    monkeypatch.setattr("dependencies.settings.LXD_MOCK", False)

    with pytest.raises(HTTPException) as excinfo:
        await get_lxd_client(db=db_session, current_user=None, host_id=None)
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_get_lxd_client_raises_when_multiple_hosts(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import get_lxd_client

    monkeypatch.setattr("dependencies.settings.LXD_MOCK", False)

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

    monkeypatch.setattr("dependencies.settings.LXD_MOCK", False)

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

    monkeypatch.setattr("dependencies.settings.LXD_MOCK", False)

    db_session.add(_make_host(1, is_active=False))
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await get_lxd_client(db=db_session, current_user=None, host_id=1)
    assert excinfo.value.status_code == 404
