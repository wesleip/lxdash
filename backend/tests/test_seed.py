"""Tests for seed.py — admin user creation and idempotency."""

from __future__ import annotations

from unittest.mock import patch


def test_seed_creates_admin_user(db_session):
    from models.user import User, UserRole
    from seed import seed

    with patch("seed.SessionLocal", lambda: db_session):
        seed(username="admin", password="strong-password-123", email="admin@test.local")

    user = db_session.query(User).filter_by(username="admin").first()
    assert user is not None
    assert user.email == "admin@test.local"
    assert user.role == UserRole.admin
    assert user.is_active is True


def test_seed_stores_hashed_password_not_plaintext(db_session):
    from models.user import User
    from seed import seed

    with patch("seed.SessionLocal", lambda: db_session):
        seed(username="admin", password="strong-password-123", email="admin@test.local")

    user = db_session.query(User).one()
    assert user.hashed_password != "strong-password-123"
    assert user.hashed_password.startswith("$2")


def test_seed_is_idempotent(db_session):
    from models.user import User
    from seed import seed

    with patch("seed.SessionLocal", lambda: db_session):
        seed(username="admin", password="first-password", email="admin@test.local")
        seed(username="admin", password="different-password", email="admin@test.local")

    users = db_session.query(User).filter_by(username="admin").all()
    assert len(users) == 1
    # Original password is preserved; the second call was a no-op.
    assert users[0].hashed_password != "different-password"
