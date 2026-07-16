"""Auth flow tests: login, token validation, refresh rotation, reuse
detection, logout."""

from datetime import UTC, datetime, timedelta

import httpx

from app.models import RefreshToken, User
from tests.conftest import TEST_PASSWORD


def _refresh_cookie(resp: httpx.Response) -> str | None:
    return resp.cookies.get("wardress_refresh")


async def test_login_success(client: httpx.AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert _refresh_cookie(resp)


async def test_login_wrong_password(client: httpx.AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": "wrong"}
    )
    assert resp.status_code == 401
    assert _refresh_cookie(resp) is None


async def test_login_unknown_email(client: httpx.AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 401
    # Same status/shape as wrong-password: no account enumeration.
    resp2 = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": "wrong"}
    )
    assert resp.json() == resp2.json()


async def test_login_email_case_insensitive(client: httpx.AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": "ADMIN@example.com", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


async def test_me_requires_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_with_token(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@example.com"
    assert resp.json()["role"] == "admin"


async def test_garbage_token_rejected(client: httpx.AsyncClient, admin_user: User) -> None:
    for bad in ("garbage", "Bearer", "a.b.c"):
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert resp.status_code == 401


async def test_refresh_rotates(client: httpx.AsyncClient, admin_user: User) -> None:
    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    first_cookie = _refresh_cookie(login)

    client.cookies.set("wardress_refresh", first_cookie, path="/api/auth")
    refresh = await client.post("/api/auth/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]
    second_cookie = _refresh_cookie(refresh)
    assert second_cookie and second_cookie != first_cookie

    # The rotated (old) token is now dead...
    client.cookies.set("wardress_refresh", first_cookie, path="/api/auth")
    reuse = await client.post("/api/auth/refresh")
    assert reuse.status_code == 401

    # ...and its reuse revoked the whole family, including the successor.
    client.cookies.set("wardress_refresh", second_cookie, path="/api/auth")
    after_reuse = await client.post("/api/auth/refresh")
    assert after_reuse.status_code == 401


async def test_refresh_without_cookie(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_refresh_with_bogus_cookie(client: httpx.AsyncClient, admin_user: User) -> None:
    client.cookies.set("wardress_refresh", "not-a-token", path="/api/auth")
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_logout_revokes_refresh(client: httpx.AsyncClient, admin_user: User) -> None:
    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)
    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_login_validation_errors(client: httpx.AsyncClient) -> None:
    # Empty body, wrong types, oversized fields — parser-level rejection.
    assert (await client.post("/api/auth/login", json={})).status_code == 422
    assert (
        await client.post("/api/auth/login", json={"email": 5, "password": []})
    ).status_code == 422
    assert (
        await client.post("/api/auth/login", json={"email": "a@b.c", "password": "x" * 2000})
    ).status_code == 422


async def test_expired_refresh_token_rejected(
    client: httpx.AsyncClient, admin_user: User, db_factory
) -> None:
    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)

    # Age the stored token past its expiry.
    async with db_factory() as db:
        await db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.user_id == admin_user.id)
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()

    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


async def test_deactivated_user_cannot_login_or_refresh(
    client: httpx.AsyncClient, admin_user: User, db_factory
) -> None:
    # Establish a session first, then deactivate the account.
    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)
    token = login.json()["access_token"]

    async with db_factory() as db:
        user = await db.get(User, admin_user.id)
        user.is_active = False
        await db.commit()

    # Every path is closed: password login, cookie refresh, bearer access.
    relogin = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    assert relogin.status_code == 401

    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
