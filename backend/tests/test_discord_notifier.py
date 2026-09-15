"""Tests for services.discord_notifier.

The notifier is best-effort and never raises — these tests pin down the
filter logic, payload shape, and graceful handling of HTTP failures.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.discord_notifier import (
    AuditEvent,
    DiscordNotifier,
    _parse_action_filter,
    reset_discord_notifier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_notifier() -> DiscordNotifier:
    """Return a notifier with the webhook pre-enabled and a mocked client."""
    reset_discord_notifier()
    notifier = DiscordNotifier()
    notifier._client = MagicMock(spec=httpx.AsyncClient)
    notifier._webhook_url = "https://discord.com/api/webhooks/1/abc"
    notifier._username = "LXDash"
    notifier._notify_success = True
    notifier._notify_failure = True
    notifier._action_filter = None
    return notifier


def _make_event(**overrides: Any) -> AuditEvent:
    base = {
        "action": "container.delete",
        "status": "success",
        "resource_type": "container",
        "resource_name": "web01",
        "user_id": 7,
        "username": "alice",
        "host_id": 3,
        "detail": None,
    }
    base.update(overrides)
    return AuditEvent(**base)


# ---------------------------------------------------------------------------
# _parse_action_filter
# ---------------------------------------------------------------------------


def test_parse_action_filter_star_returns_none() -> None:
    assert _parse_action_filter("*") is None


def test_parse_action_filter_empty_returns_none() -> None:
    assert _parse_action_filter("") is None
    assert _parse_action_filter("   ") is None


def test_parse_action_filter_csv_returns_set() -> None:
    result = _parse_action_filter("container.delete, container.start , auth.login")
    assert result == {"container.delete", "container.start", "auth.login"}


# ---------------------------------------------------------------------------
# should_send
# ---------------------------------------------------------------------------


def test_should_send_disabled_when_no_url(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._webhook_url = None
    assert fresh_notifier.should_send("container.delete", "success") is False


def test_should_send_respects_success_flag(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._notify_success = False
    assert fresh_notifier.should_send("container.delete", "success") is False
    assert fresh_notifier.should_send("container.delete", "failure") is True


def test_should_send_respects_failure_flag(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._notify_failure = False
    assert fresh_notifier.should_send("container.delete", "failure") is False
    assert fresh_notifier.should_send("container.delete", "success") is True


def test_should_send_respects_action_filter(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._action_filter = {"container.delete"}
    assert fresh_notifier.should_send("container.delete", "success") is True
    assert fresh_notifier.should_send("container.start", "success") is False


def test_should_send_accepts_every_action_when_filter_is_none(
    fresh_notifier: DiscordNotifier,
) -> None:
    fresh_notifier._action_filter = None
    assert fresh_notifier.should_send("anything.at_all", "success") is True


# ---------------------------------------------------------------------------
# notify_event — payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_event_sends_expected_payload(fresh_notifier: DiscordNotifier) -> None:
    response = MagicMock()
    response.status_code = 204
    response.text = ""
    fresh_notifier._client.post = AsyncMock(return_value=response)

    event = _make_event(detail="manual op")
    await fresh_notifier.notify_event(event)

    fresh_notifier._client.post.assert_awaited_once()
    call = fresh_notifier._client.post.call_args
    assert call.args[0] == "https://discord.com/api/webhooks/1/abc"
    payload = call.kwargs["json"]
    assert payload["username"] == "LXDash"
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["color"] == 0x2ECC71  # success green
    assert "container: web01" in embed["title"]
    assert any(
        f["name"] == "Action" and f["value"] == "`container.delete`" for f in embed["fields"]
    )
    field_names = {f["name"] for f in embed["fields"]}
    assert {"Action", "Status", "Resource", "Name", "User", "Host"} <= field_names
    assert "manual op" in embed["description"]


@pytest.mark.asyncio
async def test_notify_event_uses_red_for_failure(fresh_notifier: DiscordNotifier) -> None:
    response = MagicMock()
    response.status_code = 204
    fresh_notifier._client.post = AsyncMock(return_value=response)

    event = _make_event(status="failure", detail="boom")
    await fresh_notifier.notify_event(event)

    payload = fresh_notifier._client.post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    assert embed["color"] == 0xE74C3C
    assert "failed" in embed["title"]


@pytest.mark.asyncio
async def test_notify_event_uses_blue_for_auth(fresh_notifier: DiscordNotifier) -> None:
    response = MagicMock()
    response.status_code = 204
    fresh_notifier._client.post = AsyncMock(return_value=response)

    event = _make_event(action="auth.login", resource_type="auth", resource_name="alice")
    await fresh_notifier.notify_event(event)

    payload = fresh_notifier._client.post.call_args.kwargs["json"]
    embed = payload["embeds"][0]
    assert embed["color"] == 0x3498DB


@pytest.mark.asyncio
async def test_notify_event_skips_when_filtered(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._action_filter = {"image.delete"}
    fresh_notifier._client.post = AsyncMock()

    event = _make_event()
    await fresh_notifier.notify_event(event)
    fresh_notifier._client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_event_skips_when_no_client(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._client = None
    fresh_notifier._client = None  # explicit
    # No exception raised.
    await fresh_notifier.notify_event(_make_event())


# ---------------------------------------------------------------------------
# notify_event — failure modes (must never raise)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_event_swallows_timeout(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._client.post = AsyncMock(side_effect=httpx.TimeoutException("nope"))
    await fresh_notifier.notify_event(_make_event())  # no raise


@pytest.mark.asyncio
async def test_notify_event_swallows_request_error(fresh_notifier: DiscordNotifier) -> None:
    fresh_notifier._client.post = AsyncMock(
        side_effect=httpx.RequestError("connect refused", request=MagicMock()),
    )
    await fresh_notifier.notify_event(_make_event())  # no raise


@pytest.mark.asyncio
async def test_notify_event_logs_on_4xx(fresh_notifier: DiscordNotifier) -> None:
    response = MagicMock()
    response.status_code = 429
    response.text = "rate limited"
    fresh_notifier._client.post = AsyncMock(return_value=response)
    await fresh_notifier.notify_event(_make_event())  # no raise


@pytest.mark.asyncio
async def test_notify_event_truncates_long_detail(fresh_notifier: DiscordNotifier) -> None:
    response = MagicMock()
    response.status_code = 204
    fresh_notifier._client.post = AsyncMock(return_value=response)

    huge = "x" * 1000
    event = _make_event(detail=huge)
    await fresh_notifier.notify_event(event)

    embed = fresh_notifier._client.post.call_args.kwargs["json"]["embeds"][0]
    assert "..." in embed["description"]
    assert len(embed["description"]) < 600


# ---------------------------------------------------------------------------
# Lifecycle — start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_no_op_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_discord_notifier()
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    from services import discord_notifier as mod

    mod._notifier = None
    notifier = DiscordNotifier()
    await notifier.start()
    assert notifier._webhook_url is None
    assert notifier._client is None


@pytest.mark.asyncio
async def test_start_creates_client_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_discord_notifier()
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    monkeypatch.setenv("DISCORD_NOTIFY_ON_SUCCESS", "false")
    monkeypatch.setenv("DISCORD_NOTIFY_ACTIONS", "container.delete,auth.login")

    # Settings are cached via lru_cache — drop the cache so env changes are honoured.
    from config import get_settings

    get_settings.cache_clear()

    notifier = DiscordNotifier()

    with patch("services.discord_notifier.httpx.AsyncClient") as client_cls:
        await notifier.start()
        client_cls.assert_called_once()

    assert notifier._webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert notifier._notify_success is False
    assert notifier._action_filter == {"container.delete", "auth.login"}

    # Replace the patched MagicMock with an AsyncMock so aclose() is awaitable.
    notifier._client = AsyncMock()
    await notifier.stop()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_stop_safe_when_never_started() -> None:
    notifier = DiscordNotifier()
    await notifier.stop()  # must not raise
    assert notifier._client is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_discord_notifier_returns_singleton() -> None:
    reset_discord_notifier()
    from services.discord_notifier import get_discord_notifier

    a = get_discord_notifier()
    b = get_discord_notifier()
    assert a is b
