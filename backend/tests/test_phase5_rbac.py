"""RBAC enforcement across the endpoint surface (Phase 5, §11).

admin: everything. analyst: sites/scans/suppression/alerts/explains/
bulk-import/remediation-confirm. viewer: read-only. Every mutating
endpoint must 403 for a role that lacks it while still 200/201-ing for
one that has it.
"""

import pytest

from app.models import Site


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    """No Redis in unit tests — site creation enqueues are stubbed."""
    return stub_all_enqueues


async def _make_site(db_factory, admin_user) -> Site:
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com", created_by=admin_user.id)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


class TestViewerIsReadOnly:
    async def test_viewer_can_list_sites(self, client, viewer_headers):
        resp = await client.get("/api/sites", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_viewer_cannot_create_site(self, client, viewer_headers):
        resp = await client.post(
            "/api/sites",
            headers=viewer_headers,
            json={"name": "Blocked", "url": "https://example.org"},
        )
        assert resp.status_code == 403
        assert "role" in resp.json()["detail"].lower()

    async def test_viewer_cannot_delete_site(self, client, viewer_headers, db_factory, admin_user):
        site = await _make_site(db_factory, admin_user)
        resp = await client.delete(f"/api/sites/{site.id}", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_viewer_cannot_bulk_import(self, client, viewer_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=viewer_headers,
            json={"csv_text": "https://example.com"},
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_list_users(self, client, viewer_headers):
        resp = await client.get("/api/users", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_viewer_cannot_read_audit_log(self, client, viewer_headers):
        resp = await client.get("/api/audit-log", headers=viewer_headers)
        assert resp.status_code == 403


class TestAnalystScope:
    async def test_analyst_can_create_site(self, client, analyst_headers):
        resp = await client.post(
            "/api/sites",
            headers=analyst_headers,
            json={"name": "Analyst Site", "url": "https://example.com"},
        )
        assert resp.status_code == 201, resp.text

    async def test_analyst_cannot_manage_users(self, client, analyst_headers):
        resp = await client.post(
            "/api/users",
            headers=analyst_headers,
            json={"email": "new@example.com", "password": "a-strong-passphrase", "role": "viewer"},
        )
        assert resp.status_code == 403

    async def test_analyst_cannot_change_settings(self, client, analyst_headers):
        resp = await client.put(
            "/api/settings/ollama",
            headers=analyst_headers,
            json={"enabled": True, "model": "llama3.2"},
        )
        assert resp.status_code == 403

    async def test_settings_reads_are_admin_only(self, client, analyst_headers, viewer_headers):
        # Settings GETs return configuration hints (SMTP host/username,
        # token prefixes, channel inventory) that only admins need — the
        # settings surface is admin scope end to end (Phase 6 QA fix).
        for path in (
            "/api/settings/smtp",
            "/api/settings/telegram",
            "/api/settings/gemini",
            "/api/settings/ollama",
            "/api/notification-channels",
        ):
            for headers in (analyst_headers, viewer_headers):
                resp = await client.get(path, headers=headers)
                assert resp.status_code == 403, f"{path} returned {resp.status_code}"

    async def test_analyst_cannot_read_audit_log(self, client, analyst_headers):
        resp = await client.get("/api/audit-log", headers=analyst_headers)
        assert resp.status_code == 403

    async def test_analyst_cannot_create_remediation_hook(
        self, client, analyst_headers, db_factory, admin_user
    ):
        site = await _make_site(db_factory, admin_user)
        resp = await client.post(
            f"/api/sites/{site.id}/remediation-hooks",
            headers=analyst_headers,
            json={
                "name": "rollback",
                "action_type": "custom_webhook",
                "webhook_url": "https://hooks.example.com/x",
            },
        )
        assert resp.status_code == 403


class TestAdminEverything:
    async def test_admin_manages_settings(self, client, auth_headers):
        resp = await client.put(
            "/api/settings/ollama",
            headers=auth_headers,
            json={"enabled": True, "model": "llama3.2"},
        )
        assert resp.status_code == 200

    async def test_admin_reads_audit_log(self, client, auth_headers):
        resp = await client.get("/api/audit-log", headers=auth_headers)
        assert resp.status_code == 200


class TestUnauthenticated:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/sites"),
            ("get", "/api/users"),
            ("get", "/api/audit-log"),
            ("get", "/api/health/details"),
            ("get", "/api/api-keys"),
            ("post", "/api/sites/bulk-import"),
        ],
    )
    async def test_requires_auth(self, client, method, path):
        resp = await getattr(client, method)(path)
        assert resp.status_code in (401, 403)

    async def test_liveness_is_public(self, client):
        resp = await client.get("/api/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
