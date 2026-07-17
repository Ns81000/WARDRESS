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
# Rate limits off by default across the suite (all ASGI-transport requests
# share the client IP "unknown", so a live limit would cross-contaminate
# unrelated tests). test_ratelimit.py sets its own limits explicitly.
os.environ.setdefault("RATE_LIMIT_PER_IP", "0")
os.environ.setdefault("RATE_LIMIT_PER_USER", "0")

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

    # Rate limits off by default in unit tests (a dedicated test sets its
    # own env and exercises them). Reset accumulated counter state so
    # tests never leak windows into one another.
    from app.config import get_settings
    from app.ratelimit import reset_limiters

    get_settings.cache_clear()
    reset_limiters()

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


async def _make_role_user(db_factory, email: str, role: UserRole) -> User:
    async with db_factory() as db:
        user = User(email=email, password_hash=hash_password(TEST_PASSWORD), role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _login_headers(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def analyst_user(db_factory) -> User:
    return await _make_role_user(db_factory, "analyst@example.com", UserRole.analyst)


@pytest.fixture
async def viewer_user(db_factory) -> User:
    return await _make_role_user(db_factory, "viewer@example.com", UserRole.viewer)


@pytest.fixture
async def analyst_headers(client: httpx.AsyncClient, analyst_user: User) -> dict[str, str]:
    return await _login_headers(client, analyst_user.email)


@pytest.fixture
async def viewer_headers(client: httpx.AsyncClient, viewer_user: User) -> dict[str, str]:
    return await _login_headers(client, viewer_user.email)


@pytest.fixture
def stub_all_enqueues(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub every Celery enqueue helper so router tests never touch Redis.
    Individual test modules with their own stub_enqueue still work; this is
    an opt-in convenience for Phase 5 tests that create sites/remediations."""
    calls: dict[str, list] = {"baseline": [], "scan": [], "remediation": []}
    from app.routers import imports as imports_router
    from app.routers import remediation as remediation_router
    from app.routers import sites as sites_router

    monkeypatch.setattr(
        sites_router, "enqueue_baseline_capture", lambda bid: calls["baseline"].append(bid)
    )
    monkeypatch.setattr(sites_router, "enqueue_scan", lambda sid: calls["scan"].append(sid))
    monkeypatch.setattr(
        imports_router, "enqueue_baseline_capture", lambda bid: calls["baseline"].append(bid)
    )
    monkeypatch.setattr(
        remediation_router, "enqueue_remediation", lambda eid: calls["remediation"].append(eid)
    )
    return calls
