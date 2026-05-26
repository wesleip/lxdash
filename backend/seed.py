"""Create the initial admin user if it doesn't exist yet.

Usage:
    python seed.py
    python seed.py --username admin --password secret --email admin@example.com
"""
from __future__ import annotations

import argparse
import sys

from database import Base, SessionLocal, engine
from models.user import User, UserRole
from services.auth_service import hash_password


def seed(username: str, password: str, email: str) -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"User '{username}' already exists — skipping.")
            return

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Admin user '{username}' created successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed initial admin user")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--email", default="admin@lxdash.local")
    args = parser.parse_args()

    seed(args.username, args.password, args.email)
