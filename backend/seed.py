"""Create the initial admin user if it doesn't exist yet.

Usage:
    python seed.py --password <strong-password>
    python seed.py --username admin --password <strong-password> --email admin@example.com

The --password flag is required — there is no default, on purpose. Running
this script without arguments must never produce a user with a weak,
guessable password. The entrypoint.sh honors the ADMIN_PASSWORD env var;
this CLI is the manual escape hatch.
"""

from __future__ import annotations

import argparse

from database import SessionLocal
from models.user import User, UserRole
from services.auth_service import hash_password


def seed(username: str, password: str, email: str) -> None:
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
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument(
        "--password",
        required=True,
        help="Admin password (required — no default, refuses to run without it)",
    )
    parser.add_argument(
        "--email", default="admin@lxdash.local", help="Admin email (default: admin@lxdash.local)"
    )
    args = parser.parse_args()

    seed(args.username, args.password, args.email)
