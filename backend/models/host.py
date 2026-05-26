from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ConnectionType(str, enum.Enum):
    socket = "socket"
    tls = "tls"


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # For socket connections this holds the socket path; for TLS it is the
    # HTTPS endpoint (e.g. "https://10.0.0.1:8443").
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    connection_type: Mapped[ConnectionType] = mapped_column(
        Enum(ConnectionType, name="connection_type"),
        nullable=False,
        default=ConnectionType.socket,
    )
    # PEM-encoded client certificate used for TLS auth (nullable for socket).
    tls_cert: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PEM-encoded client private key (nullable for socket).
    tls_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PEM-encoded server certificate to trust (nullable — uses system CA otherwise).
    tls_server_cert: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Host id={self.id} name={self.name!r} type={self.connection_type}>"
