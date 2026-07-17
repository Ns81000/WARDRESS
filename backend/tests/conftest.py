"""Shared test fixtures: in-memory SQLite (aiosqlite) app instance.

DATABASE_URL/JWT_SECRET are injected before app modules import so
Settings never demands a real .env in unit tests.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
os.environ.setdefault(
    "CREDENTIALS_ENCRYPTION_KEY", "test-encryption-key-not-for-production-0123456789"
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User, UserRole  # noqa: E402
from app.security import hash_password  # noqa: E402

TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(db_factory):
    async def override_get_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin_user(db_factory) -> User:
    async with db_factory() as db:
        user = User(
            email="admin@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.admin,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient, admin_user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        json={"email": admin_user.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
