"""Audit log write path + read API (Phase 5, §6/§7)."""

import pytest

from app.audit import _redact


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


class TestRedaction:
    def test_sensitive_keys_dropped(self):
        out = _redact(
            {
                "host": "smtp.example.com",
                "password": "hunter2",
                "bot_token": "12345:secret",
                "webhook_url": "https://hooks/x?token=abc",
                "api_key": "AIzaXXXX",
            }
        )
        assert out["host"] == "smtp.example.com"
        assert out["password"] == "[redacted]"
        assert out["bot_token"] == "[redacted]"
        assert out["webhook_url"] == "[redacted]"
        assert out["api_key"] == "[redacted]"

    def test_site_url_is_not_redacted(self):
        # A monitored site's URL is legitimate audit content.
        out = _redact({"url": "https://example.com", "name": "blog"})
        assert out["url"] == "https://example.com"

    def test_none_stays_none(self):
        assert _redact(None) is None


class TestAuditWrites:
    async def test_site_create_writes_audit(self, client, auth_headers):
        await client.post(
            "/api/sites", headers=auth_headers, json={"name": "Audited", "url": "https://example.com"}
        )
        log = await client.get("/api/audit-log", headers=auth_headers)
        assert log.status_code == 200
        rows = log.json()["items"]
        create = next(r for r in rows if r["action"] == "site.create")
        assert create["target_type"] == "site"
        assert create["target_label"] == "Audited"
        assert create["actor_email"] == "admin@example.com"
        assert create["after_json"]["url"] == "https://example.com/"

    async def test_settings_update_records_no_secret(self, client, auth_headers):
        await client.put(
            "/api/settings/ollama",
            headers=auth_headers,
            json={"enabled": True, "model": "llama3.2"},
        )
        rows = (await client.get("/api/audit-log", headers=auth_headers)).json()["items"]
        entry = next(r for r in rows if r["action"] == "settings.ollama.update")
        assert entry["after_json"]["enabled"] is True
        # No credential value anywhere in the snapshot.
        assert "password" not in str(entry["after_json"]).lower()

    async def test_filter_by_action_prefix(self, client, auth_headers):
        await client.post(
            "/api/sites", headers=auth_headers, json={"name": "F1", "url": "https://example.com/a"}
        )
        await client.put(
            "/api/settings/ollama", headers=auth_headers, json={"enabled": False}
        )
        site_only = await client.get("/api/audit-log?action=site", headers=auth_headers)
        actions = {r["action"] for r in site_only.json()["items"]}
        assert actions and all(a.startswith("site") for a in actions)

    async def test_filter_by_target_type(self, client, auth_headers):
        await client.post(
            "/api/sites", headers=auth_headers, json={"name": "F2", "url": "https://example.com/b"}
        )
        resp = await client.get("/api/audit-log?target_type=settings", headers=auth_headers)
        assert all(r["target_type"] == "settings" for r in resp.json()["items"])

    async def test_pagination_shape(self, client, auth_headers):
        resp = await client.get("/api/audit-log?limit=1", headers=auth_headers)
        body = resp.json()
        assert set(body) == {"items", "total", "offset", "limit"}
        assert body["limit"] == 1
