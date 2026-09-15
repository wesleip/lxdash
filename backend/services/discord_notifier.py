"""Discord webhook notifier.

Sends rich embed messages to a Discord channel when auditable events occur
(container create/stop, login, failures, …). The notifier is intentionally
isolated from routers: routers call ``record_and_notify`` in
``services/audit_service``, which dispatches here.

Design notes
------------
* Best-effort delivery — failed POSTs are logged via structlog and never
  propagated. The HTTP response is never delayed or failed by Discord.
* Fire-and-forget — ``schedule_event`` enqueues an asyncio task; the caller
  returns immediately.
* No-op when ``DISCORD_WEBHOOK_URL`` is empty — zero overhead.
* ``_should_send`` applies three filters: status (success/failure) and a
  configurable allowlist of actions (``DISCORD_NOTIFY_ACTIONS``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from config import get_settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Denormalised view of an audit log entry used to build the Discord embed."""

    action: str
    status: str
    resource_type: str
    resource_name: str | None
    user_id: int | None
    username: str | None
    host_id: int | None
    detail: Any | None


# ---------------------------------------------------------------------------
# Filter parsing
# ---------------------------------------------------------------------------


def _parse_action_filter(raw: str) -> set[str] | None:
    """Parse ``DISCORD_NOTIFY_ACTIONS``.

    ``"*"`` returns ``None`` (meaning "all actions"). Anything else is a CSV
    that becomes a set of explicit action names.
    """
    cleaned = raw.strip()
    if not cleaned or cleaned == "*":
        return None
    return {item.strip() for item in cleaned.split(",") if item.strip()}


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------


_EMBED_COLOR_SUCCESS = 0x2ECC71  # green
_EMBED_COLOR_FAILURE = 0xE74C3C  # red
_EMBED_COLOR_INFO = 0x3498DB  # blue (auth events)


class DiscordNotifier:
    """Stateless wrapper around an ``httpx.AsyncClient`` posting to Discord.

    One instance lives for the duration of the FastAPI process. Call
    :meth:`start` from the lifespan handler to build the HTTP client and
    :meth:`stop` to close it cleanly on shutdown.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._webhook_url: str | None = None
        self._username: str = "LXDash"
        self._notify_success: bool = True
        self._notify_failure: bool = True
        self._action_filter: set[str] | None = None
        self._timeout: float = 5.0

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Read settings and build the httpx client. Idempotent."""
        settings = get_settings()
        url = (settings.DISCORD_WEBHOOK_URL or "").strip()
        if not url:
            logger.info("discord_notifier.disabled", reason="DISCORD_WEBHOOK_URL is empty")
            return

        self._webhook_url = url
        self._username = settings.DISCORD_NOTIFY_USERNAME
        self._notify_success = settings.DISCORD_NOTIFY_ON_SUCCESS
        self._notify_failure = settings.DISCORD_NOTIFY_ON_FAILURE
        self._action_filter = _parse_action_filter(settings.DISCORD_NOTIFY_ACTIONS)
        self._timeout = settings.DISCORD_NOTIFY_TIMEOUT_SECONDS

        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info(
            "discord_notifier.enabled",
            username=self._username,
            notify_success=self._notify_success,
            notify_failure=self._notify_failure,
            action_filter="*" if self._action_filter is None else sorted(self._action_filter),
            timeout=self._timeout,
        )

    async def stop(self) -> None:
        """Close the underlying httpx client. Safe to call when never started."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- filter -----------------------------------------------------------

    def should_send(self, action: str, status: str) -> bool:
        """Return True if the event passes the configured filters."""
        if self._webhook_url is None:
            return False
        if status == "success" and not self._notify_success:
            return False
        if status == "failure" and not self._notify_failure:
            return False
        return self._action_filter is None or action in self._action_filter

    # -- public dispatch --------------------------------------------------

    async def notify_event(self, event: AuditEvent) -> None:
        """Send one embed for an audit event. Never raises."""
        if not self.should_send(event.action, event.status):
            return
        if self._client is None or self._webhook_url is None:
            return

        payload = self._build_payload(event)
        try:
            response = await self._client.post(self._webhook_url, json=payload)
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning(
                "discord_notifier.post_failed",
                action=event.action,
                status=event.status,
                error=str(exc),
            )
            return

        if response.status_code >= 400:
            # Discord returns 204 on success and 429 when rate-limited.
            logger.warning(
                "discord_notifier.bad_status",
                status_code=response.status_code,
                action=event.action,
                body=response.text[:200],
            )
            return

        logger.debug(
            "discord_notifier.sent",
            action=event.action,
            status=event.status,
        )

    # -- payload construction --------------------------------------------

    def _build_payload(self, event: AuditEvent) -> dict[str, Any]:
        title, color = self._title_and_color(event)
        fields: list[dict[str, Any]] = [
            {"name": "Action", "value": f"`{event.action}`", "inline": True},
            {"name": "Status", "value": event.status, "inline": True},
            {"name": "Resource", "value": event.resource_type, "inline": True},
        ]
        if event.resource_name:
            fields.append(
                {"name": "Name", "value": f"`{event.resource_name}`", "inline": True},
            )
        if event.username:
            fields.append(
                {"name": "User", "value": f"{event.username} (#{event.user_id})", "inline": True},
            )
        elif event.user_id is not None:
            fields.append(
                {"name": "User", "value": f"#{event.user_id}", "inline": True},
            )
        if event.host_id is not None:
            fields.append(
                {"name": "Host", "value": f"#{event.host_id}", "inline": True},
            )

        embed: dict[str, Any] = {
            "title": title,
            "color": color,
            "timestamp": datetime.now(UTC).isoformat(),
            "fields": fields,
        }
        if event.detail:
            embed["description"] = self._format_detail(event.detail)

        return {
            "username": self._username,
            "embeds": [embed],
        }

    @staticmethod
    def _title_and_color(event: AuditEvent) -> tuple[str, int]:
        """Pick a title and an accent colour for the embed."""
        verb, _, _ = event.action.partition(".")
        resource = event.resource_name or event.resource_type
        if event.status == "failure":
            return (f"{verb} failed: {resource}", _EMBED_COLOR_FAILURE)
        if event.action.startswith("auth."):
            return (f"{verb}: {resource}", _EMBED_COLOR_INFO)
        return (f"{verb}: {resource}", _EMBED_COLOR_SUCCESS)

    @staticmethod
    def _format_detail(detail: Any) -> str:
        """Render arbitrary ``detail`` as a short markdown string."""
        text = str(detail)
        if len(text) > 500:
            text = text[:497] + "..."
        # Discord markdown escaping for backticks and asterisks keeps the
        # embed readable when detail is a raw error message.
        return f"```{text}```"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_notifier: DiscordNotifier | None = None


def get_discord_notifier() -> DiscordNotifier:
    """Return the process-wide DiscordNotifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = DiscordNotifier()
    return _notifier


def reset_discord_notifier() -> None:
    """Drop the singleton. Test-only — never call from production code."""
    global _notifier
    _notifier = None
