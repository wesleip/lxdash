from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AuditLog(Base):
    """Append-only audit log.

    Rules:
    - No UPDATE or DELETE on this table — ever.
    - created_at is set once at insert time and never changed.
    - updated_at intentionally omitted.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # The user who performed the action (nullable in case of system/anonymous ops).
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Short verb: "container.create", "container.stop", "image.delete", etc.
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # "container" | "image" | "network" | "storage_pool" | "user" | …
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # The LXD resource name or fingerprint.
    resource_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Which LXD host was targeted (nullable for host-independent actions).
    host_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("hosts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # "success" | "failure"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")

    # JSON-serialisable extra detail (error message, diff, etc.)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"resource={self.resource_type}/{self.resource_name} status={self.status}>"
        )
