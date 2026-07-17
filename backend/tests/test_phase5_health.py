"""Health / status endpoints (Phase 5, §7). Redis/worker probes are
patched — unit tests never touch a live broker."""

import pytest

from app.routers import health as health_router
from app.schemas import HealthComponent


@pytest.fixture(autouse=True)
def _stub_probes(monkeypatch):
    """Patch the sync broker probes so health_details never blocks on a
    real Redis/Celery connection in unit tests."""
    monkeypatch.setattr(health_router, "_redis_component", lambda: HealthComponent(status="ok"))
    monkeypatch.setattr(
        health_router,
        "_worker_component",
        lambda: HealthComponent(status="ok", detail="1 worker(s)"),
    )
    monkeypatch.setattr(health_router, "_queue_depth", lambda: 0)
    monkeypatch.setattr(health_router, "_dispatch_heartbeat", lambda: None)


class TestLiveness:
    async def test_live_is_public_and_cheap(self, client):
        resp = await client.get("/api/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readiness_ok_with_db(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDetails:
    async def test_requires_auth(self, client):
        resp = await client.get("/api/health/details")
        assert resp.status_code in (401, 403)

    async def test_details_shape(self, client, auth_headers):
        resp = await client.get("/api/health/details", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for key in (
            "status",
            "uptime_seconds",
            "queue_depth",
            "sites_total",
            "scans_last_24h",
            "components",
        ):
            assert key in body
        assert body["components"]["database"]["status"] == "ok"
        assert body["status"] == "ok"

    async def test_degraded_when_worker_down(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            health_router,
            "_worker_component",
            lambda: HealthComponent(status="down", detail="no workers responded"),
        )
        resp = await client.get("/api/health/details", headers=auth_headers)
        assert resp.json()["status"] == "degraded"
