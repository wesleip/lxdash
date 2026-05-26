from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

from models.audit_log import AuditLog

logger = structlog.get_logger(__name__)


def log_action(
    db: Session,
    *,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_name: Optional[str] = None,
    host_id: Optional[int] = None,
    status: str = "success",
    detail: Optional[Any] = None,
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
    serialised_detail: Optional[str] = None
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
