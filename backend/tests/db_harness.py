"""Disposable-Postgres test-harness mechanics.

The suite runs against the production dialect with the production schema
chain applied (`alembic upgrade head`), never `Base.metadata.create_all`,
so migration-only objects — partial unique indexes, VARCHAR widths,
native enums — are actually enforced in tests. This module holds the
plumbing; conftest.py wires it into fixtures and README.md's "Backend
Development" section documents the operator contract (one pytest session
per database; table contents are wiped between tests).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_test"
URL_ENV = "WARDRESS_TEST_DATABASE_URL"
UNSAFE_ALLOW_ENV = "WARDRESS_TEST_DB_UNSAFE_ALLOW"


class HarnessError(RuntimeError):
    """The configured test database cannot be used safely."""


def resolve_test_database_url(env: dict[str, str] | None = None) -> str:
    """Resolve and safety-check the suite's target database URL.

    The harness TRUNCATEs every table in the target between tests, so it
    refuses anything that does not unambiguously look like a test database:
    the scheme must be postgresql+asyncpg and the database name must
    contain "test" (case-insensitive). The name check can be overridden
    deliberately with UNSAFE_ALLOW_ENV=1.
    """
    env = os.environ if env is None else env
    raw = (env.get(URL_ENV) or "").strip() or DEFAULT_TEST_DATABASE_URL
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError) as exc:
        raise HarnessError(f"{URL_ENV} is not a valid database URL ({raw!r}): {exc}") from exc
    if url.get_backend_name() != "postgresql" or url.get_driver_name() != "asyncpg":
        raise HarnessError(
            f"{URL_ENV} must be a postgresql+asyncpg:// URL (got {raw!r}); "
            "the app and its migrations run on the asyncpg driver."
        )
    dbname = url.database or ""
    allowed = "test" in dbname.lower()
    if not dbname or (not allowed and env.get(UNSAFE_ALLOW_ENV) != "1"):
        raise HarnessError(
            f"Refusing to target database {dbname!r}: this harness wipes its table "
            f"contents between tests. Point {URL_ENV} at a database whose name "
            f"contains 'test', or set {UNSAFE_ALLOW_ENV}=1 to accept the risk."
        )
    return raw


def ensure_database_exists(database_url: str) -> bool:
    """Create the target database if missing; True when created here."""

    url = make_url(database_url)
    host = url.host or "127.0.0.1"
    port = url.port or 5432
    user = url.username
    password = url.password
    dbname = url.database

    async def _create_if_missing() -> bool:
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password, database="postgres"
        )
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
            if exists:
                return False
            try:
                await conn.execute('CREATE DATABASE "' + dbname.replace('"', '""') + '"')
            except asyncpg.exceptions.DuplicateDatabaseError:
                pass  # lost a creation race — either way it exists now
            return True
        finally:
            await conn.close()

    try:
        return asyncio.run(_create_if_missing())
    except (OSError, asyncpg.PostgresError) as exc:
        raise HarnessError(
            f"Cannot reach PostgreSQL at {host}:{port} (user {user!r}): {exc}\n"
            "Start the disposable test database with:\n"
            "  docker run -d --name wardress-test-pg -e POSTGRES_USER=wardress "
            "-e POSTGRES_PASSWORD=wardress -p 127.0.0.1:5433:5432 postgres:16-alpine\n"
            f"or point {URL_ENV} at an already-running instance."
        ) from exc


def apply_migrations(database_url: str, backend_dir: Path, timeout_s: float = 300.0) -> None:
    """Bring the test database to alembic head via the real migration chain."""
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(backend_dir),
            env=env,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessError(f"alembic upgrade head timed out after {timeout_s:.0f}s") from exc
    if proc.returncode != 0:
        stdout_tail = proc.stdout.decode("utf-8", "replace").strip()[-2000:]
        stderr_tail = proc.stderr.decode("utf-8", "replace").strip()[-2000:]
        raise HarnessError(
            "alembic upgrade head failed against the test database.\n"
            f"--- stdout ---\n{stdout_tail}\n--- stderr ---\n{stderr_tail}"
        )


async def truncate_all_tables(engine: AsyncEngine) -> list[str]:
    """Wipe all table contents between tests (schema and alembic_version stay).

    Returns the truncated table names so failures can name what was touched.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                " ORDER BY tablename"
            )
        )
        tables = [row[0] for row in result]
        # A transaction leaked by a previous test would otherwise block the
        # TRUNCATE forever; bound it so that failure mode fails loudly.
        await conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        if tables:
            listing = ", ".join('"' + name.replace('"', '""') + '"' for name in tables)
            await conn.execute(text(f"TRUNCATE TABLE {listing} RESTART IDENTITY CASCADE"))
        return tables
