"""Shared pytest fixtures.

Environment is set BEFORE any backend module is imported, because
`config.get_settings()` is wrapped in `lru_cache` and reads the env
on first call. Do not move these assignments below the imports.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LXD_MOCK", "true")

# Importing the model modules registers them on Base.metadata so that
# `Base.metadata.create_all()` builds the full schema (audit_logs has FKs
# into users and hosts, which would otherwise be unresolved).
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models.audit_log
import models.host
import models.user  # noqa: F401


@pytest.fixture
def engine():
    """A fresh in-memory SQLite engine with the production schema.

    Uses StaticPool so every Session sees the same database (the default
    :memory: SQLite gives each connection its own private DB).
    """
    from database import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db_session(engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    """FastAPI TestClient with the get_db dependency overridden to use the
    test engine.
    """
    from dependencies import get_db
    from main import app

    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def mock_lxd():
    """Return a fresh MockLXDClient instance for the duration of the test."""
    from services.lxd_client_mock import MockLXDClient

    return MockLXDClient()
