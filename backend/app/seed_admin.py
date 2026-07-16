"""Seed (or update) the first admin user.

Run inside the app container:
    python -m app.seed_admin
Reads ADMIN_EMAIL and ADMIN_PASSWORD from the environment (set them in
.env). Idempotent: if the user exists, only resets the password when
ADMIN_RESET_PASSWORD=true — re-running install scripts must never
silently change credentials.
"""

import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import User, UserRole
from app.security import hash_password

MIN_PASSWORD_LENGTH = 12


async def seed() -> int:
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    reset = os.environ.get("ADMIN_RESET_PASSWORD", "").lower() == "true"

    if not email or "@" not in email:
        print("ERROR: set ADMIN_EMAIL to a valid email address", file=sys.stderr)
        return 2
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"ERROR: ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 2

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            existing = await db.scalar(select(User).where(User.email == email))
            if existing is None:
                db.add(
                    User(
                        email=email,
                        password_hash=hash_password(password),
                        role=UserRole.admin,
                    )
                )
                await db.commit()
                print(f"Created admin user {email}")
            elif reset:
                existing.password_hash = hash_password(password)
                existing.is_active = True
                await db.commit()
                print(f"Reset password for existing user {email}")
            else:
                print(f"User {email} already exists (set ADMIN_RESET_PASSWORD=true to reset)")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
