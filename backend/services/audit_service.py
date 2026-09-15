from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.orm import Session

from models.audit_log import AuditLog
from models.user import User
from services.discord_notifier import AuditEvent, get_discord_notifier

logger = structlog.get_logger(__name__)


def log_action(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_name: str | None = None,
    host_id: int | None = None,
    status: str = "success",
    detail: Any | None = None,
) -> AuditLog:
    """Insert an append-only audit log entry and return it.

    Args:
        db:            Active SQLAlchemy session.
        user_id:       ID of the acting user (None for system actions).
        action:        Dot-namespaced verb, e.g. ``"container.create"``.
        resource_type: Short resource category, e.g. ``"container"``.
        resource_name: LXD resource name or fingerprint.
        host_id:       LXD host ID (None for host-independent actions).
        status:        ``"success"`` or ``"failure"``.
        detail:        Arbitrary JSON-serialisable data (dict, str, …).
    """
    serialised_detail: str | None = None
    if detail is not None:
        if isinstance(detail, str):
            serialised_detail = detail
        else:
            try:
                serialised_detail = json.dumps(detail, default=str)
            except (TypeError, ValueError):
                serialised_detail = str(detail)

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_name=resource_name,
        host_id=host_id,
        status=status,
        detail=serialised_detail,
    )
    db.add(entry)
    db.flush()  # Assign PK without committing — let the caller commit.

    logger.info(
        "audit",
        audit_id=entry.id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_name=resource_name,
        host_id=host_id,
        status=status,
    )

    return entry


async def record_and_notify(
    db: Session,
    *,
    user: User | None,
    action: str,
    resource_type: str,
    resource_name: str | None = None,
    host_id: int | None = None,
    status: str = "success",
    detail: Any | None = None,
) -> AuditLog:
    """Persist the audit entry, commit the transaction, then schedule the Discord notification.

    Single replacement for the ``log_action(...); db.commit()`` pattern used by
    routers. Keeping the commit here guarantees the notification only fires for
    events that actually landed in the DB.

    Args:
        db:            Active SQLAlchemy session.
        user:          Acting user (or ``None`` for system actions). Used to
                       enrich the Discord embed with ``username``.
        action:        Dot-namespaced verb.
        resource_type: Short resource category.
        resource_name: LXD resource name or fingerprint.
        host_id:       LXD host ID.
        status:        ``"success"`` or ``"failure"``.
        detail:        Arbitrary JSON-serialisable data.
    """
    entry = log_action(
        db,
        user_id=user.id if user else None,
        action=action,
        resource_type=resource_type,
        resource_name=resource_name,
        host_id=host_id,
        status=status,
        detail=detail,
    )
    db.commit()

    event = AuditEvent(
        action=action,
        status=status,
        resource_type=resource_type,
        resource_name=resource_name,
        user_id=user.id if user else None,
        username=user.username if user else None,
        host_id=host_id,
        detail=detail,
    )
    schedule_notification(event)
    return entry


def schedule_notification(event: AuditEvent) -> None:
    """Fire-and-forget enqueue of a Discord notification.

    Falls back to a synchronous send when no event loop is running (e.g.
    during seeding scripts or tests that exercise the audit layer outside of
    FastAPI). This keeps the notifier observable from any context.
    """
    notifier = get_discord_notifier()
    if not notifier.should_send(event.action, event.status):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — emit a debug log and skip. The audit entry is
        # already persisted, so nothing is lost.
        logger.debug("notification.skipped", reason="no_event_loop", action=event.action)
        return
    # Hold a strong reference so the task isn't garbage-collected mid-flight.
    task = loop.create_task(notifier.notify_event(event))
    task.add_done_callback(_discard_task_ref)


_active_tasks: set[asyncio.Task[None]] = set()


def _discard_task_ref(task: asyncio.Task[None]) -> None:
    _active_tasks.discard(task)
