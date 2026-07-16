"""Phase 0 smoke tests: prove the app imports and the health endpoint answers."""

import httpx
import pytest

from app.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_endpoint(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "wardress-api"


def test_celery_app_configured() -> None:
    from worker.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True
    assert "wardress.ping" in celery_app.tasks
