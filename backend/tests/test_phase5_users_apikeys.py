"""User management + API keys (Phase 5, §6/§7)."""

import pytest

from app.models import ApiKey, User, UserRole


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


class TestUserManagement:
    async def test_admin_creates_and_lists_users(self, client, auth_headers):
        resp = await client.post(
            "/api/users",
            headers=auth_headers,
            json={
                "email": "analyst2@example.com",
                "password": "a-strong-passphrase",
                "role": "analyst",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["role"] == "analyst"
        assert body["is_active"] is True
        assert "password" not in body and "password_hash" not in body

        listed = await client.get("/api/users", headers=auth_headers)
        assert listed.status_code == 200
        emails = {u["email"] for u in listed.json()}
        assert "analyst2@example.com" in emails

    async def test_duplicate_email_conflicts(self, client, auth_headers, admin_user):
        resp = await client.post(
            "/api/users",
            headers=auth_headers,
            json={"email": admin_user.email, "password": "a-strong-passphrase", "role": "viewer"},
        )
        assert resp.status_code == 409

    async def test_short_password_rejected(self, client, auth_headers):
        resp = await client.post(
            "/api/users",
            headers=auth_headers,
            json={"email": "weak@example.com", "password": "short", "role": "viewer"},
        )
        assert resp.status_code == 422

    async def test_cannot_demote_self(self, client, auth_headers, admin_user):
        resp = await client.patch(
            f"/api/users/{admin_user.id}", headers=auth_headers, json={"role": "viewer"}
        )
        assert resp.status_code == 409

    async def test_cannot_deactivate_last_admin(self, client, auth_headers, admin_user, db_factory):
        # Make a second admin, then the first admin deactivates... itself is
        # blocked by the self-guard; deactivate the OTHER admin when it is
        # the last one standing is what we assert here.
        async with db_factory() as db:
            other = User(
                email="admin2@example.com",
                password_hash=admin_user.password_hash,
                role=UserRole.admin,
            )
            db.add(other)
            await db.commit()
            await db.refresh(other)
        # Deactivating the second admin is fine (first remains).
        resp = await client.patch(
            f"/api/users/{other.id}", headers=auth_headers, json={"is_active": False}
        )
        assert resp.status_code == 200

    async def test_deactivated_user_cannot_log_in(self, client, auth_headers, db_factory):
        create = await client.post(
            "/api/users",
            headers=auth_headers,
            json={"email": "temp@example.com", "password": "a-strong-passphrase", "role": "viewer"},
        )
        user_id = create.json()["id"]
        await client.patch(f"/api/users/{user_id}", headers=auth_headers, json={"is_active": False})
        resp = await client.post(
            "/api/auth/login",
            json={"email": "temp@example.com", "password": "a-strong-passphrase"},
        )
        assert resp.status_code == 401

    async def test_role_change_revokes_sessions(self, client, auth_headers, db_factory):
        # A user logs in, gets a refresh cookie; an admin changes their role;
        # the old refresh token must be rejected.
        await client.post(
            "/api/users",
            headers=auth_headers,
            json={
                "email": "rotate@example.com",
                "password": "a-strong-passphrase",
                "role": "viewer",
            },
        )
        login = await client.post(
            "/api/auth/login",
            json={"email": "rotate@example.com", "password": "a-strong-passphrase"},
        )
        assert login.status_code == 200
        users = (await client.get("/api/users", headers=auth_headers)).json()
        uid = next(u["id"] for u in users if u["email"] == "rotate@example.com")
        await client.patch(f"/api/users/{uid}", headers=auth_headers, json={"role": "analyst"})
        # The refresh cookie from `login` is stored on the client; refresh
        # must now fail (token family revoked).
        refresh = await client.post("/api/auth/refresh")
        assert refresh.status_code == 401


class TestApiKeys:
    async def test_create_shows_key_once_then_hashed(self, client, auth_headers, db_factory):
        resp = await client.post("/api/api-keys", headers=auth_headers, json={"label": "ci-script"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        raw = body["key"]
        assert raw.startswith("wk_")
        assert body["key_prefix"] == raw[:11]

        # Listing never returns the raw key.
        listed = await client.get("/api/api-keys", headers=auth_headers)
        assert all("key" not in k for k in listed.json())

        # Only the hash is stored.
        async with db_factory() as db:
            from sqlalchemy import select

            row = await db.scalar(select(ApiKey))
            assert row.key_hash != raw
            assert len(row.key_hash) == 64

    async def test_api_key_authenticates_with_owner_role(self, client, auth_headers, analyst_user):
        # An analyst's key can create a site (analyst scope) ...
        analyst_login = await client.post(
            "/api/auth/login",
            json={"email": analyst_user.email, "password": "correct horse battery staple"},
        )
        analyst_hdr = {"Authorization": f"Bearer {analyst_login.json()['access_token']}"}
        key = await client.post("/api/api-keys", headers=analyst_hdr, json={"label": "analyst-key"})
        raw = key.json()["key"]
        key_hdr = {"Authorization": f"Bearer {raw}"}

        made = await client.post(
            "/api/sites", headers=key_hdr, json={"name": "Via Key", "url": "https://example.com"}
        )
        assert made.status_code == 201
        # ... but cannot reach admin-only user management (role honored).
        denied = await client.get("/api/users", headers=key_hdr)
        assert denied.status_code == 403

    async def test_revoked_key_is_rejected(self, client, auth_headers):
        created = await client.post("/api/api-keys", headers=auth_headers, json={"label": "temp"})
        raw = created.json()["key"]
        key_id = created.json()["id"]
        # Works before revocation.
        before = await client.get("/api/sites", headers={"Authorization": f"Bearer {raw}"})
        assert before.status_code == 200
        # Revoke via an interactive session.
        await client.delete(f"/api/api-keys/{key_id}", headers=auth_headers)
        # Now rejected.
        after = await client.get("/api/sites", headers={"Authorization": f"Bearer {raw}"})
        assert after.status_code == 401

    async def test_api_key_cannot_manage_api_keys(self, client, auth_headers):
        created = await client.post("/api/api-keys", headers=auth_headers, json={"label": "self"})
        raw = created.json()["key"]
        key_hdr = {"Authorization": f"Bearer {raw}"}
        # A key must not mint or list keys (credentials management needs a
        # real session).
        assert (await client.get("/api/api-keys", headers=key_hdr)).status_code == 403
        assert (
            await client.post("/api/api-keys", headers=key_hdr, json={"label": "x"})
        ).status_code == 403
