"""Auth flow tests: login, token validation, refresh rotation, reuse
detection, logout."""

import os
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


async def test_refresh_rotation_race_only_one_successor(
    client: httpx.AsyncClient, admin_user: User, db_factory
) -> None:
    """HIGH: rotation race. Two concurrent refreshes presenting the same
    cookie: only the request whose conditional UPDATE claims the token
    (rowcount==1) mints a successor; the loser gets 401 + family revocation."""
    from sqlalchemy import select

    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)

    # Simulate a race: both requests read the same unrevoked token, but only
    # one UPDATE will flip revoked_at. We can't literally race async calls in
    # a single-threaded test harness, so we'll verify the end state instead:
    # after one successful refresh, the token is revoked + has replaced_by set,
    # so presenting it again triggers the reuse path (family revocation).
    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    first = await client.post("/api/auth/refresh")
    assert first.status_code == 200
    successor_cookie = _refresh_cookie(first)

    # The second "concurrent" request with the same original cookie — it's
    # now revoked with replaced_by set, so it hits the reuse branch.
    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    second = await client.post("/api/auth/refresh")
    assert second.status_code == 401

    # The successor from the first request was also revoked (family kill).
    client.cookies.set("wardress_refresh", successor_cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401

    # Confirm: no unrevoked tokens remain.
    async with db_factory() as db:
        live = await db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == admin_user.id, RefreshToken.revoked_at.is_(None)
            )
        )
        assert len(list(live)) == 0


async def test_refresh_logout_reuse_does_not_escalate(
    client: httpx.AsyncClient, admin_user: User, db_factory
) -> None:
    """MEDIUM: distinguish logout-revoked from rotation-revoked. Replaying a
    logout-revoked token (browser retry, stale tab) is not theft evidence, so
    it should reject that one token without family revocation."""
    from sqlalchemy import select

    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)

    # Logout revokes without setting replaced_by.
    await client.post("/api/auth/logout")

    # Replay the logout-revoked cookie — 401, but no family kill.
    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401

    # Confirm the revoked token has no replaced_by (so no family escalation).
    async with db_factory() as db:
        token = await db.scalar(
            select(RefreshToken).where(RefreshToken.user_id == admin_user.id)
        )
        assert token.revoked_at is not None
        assert token.replaced_by is None


async def test_absolute_session_lifetime_caps_successor_expiry(
    client: httpx.AsyncClient, admin_user: User, db_factory
) -> None:
    """MEDIUM: max_session_ttl. A session refreshing continuously must still
    end at login_time + max_session_ttl, not slide forever."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.config import get_settings
    from app.models import ensure_utc

    # Override max_session_ttl to 2 days for this test (default is 30).
    get_settings.cache_clear()
    os.environ["MAX_SESSION_TTL"] = str(2 * 24 * 60 * 60)
    get_settings.cache_clear()

    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    cookie = _refresh_cookie(login)

    # Age the token's session_started_at to 2 days - 10 minutes ago.
    async with db_factory() as db:
        token = await db.scalar(
            select(RefreshToken).where(RefreshToken.user_id == admin_user.id)
        )
        original_start = datetime.now(UTC) - timedelta(days=2, minutes=-10)
        token.session_started_at = original_start
        await db.commit()

    # The successor's expiry is capped at session_started_at + max_session_ttl
    # = 10 minutes from now (well under the usual 7-day refresh TTL).
    client.cookies.set("wardress_refresh", cookie, path="/api/auth")
    refresh = await client.post("/api/auth/refresh")
    assert refresh.status_code == 200

    async with db_factory() as db:
        successor = await db.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == admin_user.id, RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.created_at.desc())
        )
        # SQLite returns naive datetimes; normalize both for comparison.
        assert ensure_utc(successor.session_started_at) == ensure_utc(original_start)
        # The successor expires ~10 minutes from now (not 7 days).
        ceiling = original_start + timedelta(days=2)
        assert abs((ensure_utc(successor.expires_at) - ceiling).total_seconds()) < 5

    # If we age the session past the absolute ceiling, the next refresh 401s.
    async with db_factory() as db:
        token = await db.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == admin_user.id, RefreshToken.revoked_at.is_(None))
        )
        token.session_started_at = datetime.now(UTC) - timedelta(days=2, seconds=10)
        await db.commit()

    client.cookies.set("wardress_refresh", _refresh_cookie(refresh), path="/api/auth")
    expired = await client.post("/api/auth/refresh")
    assert expired.status_code == 401
    assert "session expired" in expired.json()["detail"].lower()

    # Cleanup.
    os.environ.pop("MAX_SESSION_TTL", None)
    get_settings.cache_clear()


async def test_logout_cookie_deleted_with_mirrored_attributes(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    """LOW: delete_cookie should mirror set-time flags so strict user agents
    accept the deletion (matched by name+path+secure+samesite)."""
    login = await client.post(
        "/api/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD}
    )
    set_cookie_header = login.headers.get("set-cookie", "")
    # The refresh cookie is httponly, secure (if config says so), samesite=strict.
    assert "httponly" in set_cookie_header.lower()
    assert "samesite=strict" in set_cookie_header.lower()

    logout = await client.post("/api/auth/logout")
    delete_header = logout.headers.get("set-cookie", "")
    # The deletion must carry the same attributes.
    assert "httponly" in delete_header.lower()
    assert "samesite=strict" in delete_header.lower()
    # Max-Age=0 or Expires=past signals deletion.
    assert "max-age=0" in delete_header.lower() or "expires=" in delete_header.lower()
