"""Site CRUD + scan-trigger endpoint tests. Celery enqueues are stubbed —
queue behavior is covered by the compose-stack verification, not unit tests."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import Baseline, BaselineStatus, Scan, ScanStatus
from app.routers import sites as sites_router


@pytest.fixture(autouse=True)
def stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict[str, list] = {"baseline": [], "scan": []}
    monkeypatch.setattr(
        sites_router, "enqueue_baseline_capture", lambda bid: calls["baseline"].append(bid)
    )
    monkeypatch.setattr(sites_router, "enqueue_scan", lambda sid: calls["scan"].append(sid))
    return calls


async def _create_site(client: httpx.AsyncClient, headers: dict, **overrides) -> dict:
    payload = {"name": "Example", "url": "https://example.com/", **overrides}
    resp = await client.post("/api/sites", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_sites_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/sites")).status_code == 401
    assert (
        await client.post("/api/sites", json={"name": "x", "url": "https://example.com"})
    ).status_code == 401
    assert (await client.delete(f"/api/sites/{uuid.uuid4()}")).status_code == 401


async def test_create_and_list_site(
    client: httpx.AsyncClient, auth_headers: dict, stub_enqueue: dict
) -> None:
    created = await _create_site(client, auth_headers)
    assert created["name"] == "Example"
    assert created["baseline_status"] == "pending"
    assert len(stub_enqueue["baseline"]) == 1

    listed = (await client.get("/api/sites", headers=auth_headers)).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


async def test_create_site_blocks_private_url(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/api/sites",
        json={"name": "internal", "url": "http://192.168.1.1/"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "blocked" in resp.json()["detail"].lower() or "private" in resp.json()["detail"].lower()


async def test_create_site_private_optin(
    client: httpx.AsyncClient, auth_headers: dict, stub_enqueue: dict
) -> None:
    created = await _create_site(
        client, auth_headers, url="http://192.168.1.1/", allow_private_networks=True
    )
    assert created["allow_private_networks"] is True


async def test_create_site_validation(client: httpx.AsyncClient, auth_headers: dict) -> None:
    bad_payloads = [
        {},
        {"name": "", "url": "https://example.com"},
        {"name": "   ", "url": "https://example.com"},
        {"name": "x", "url": "not-a-url"},
        {"name": "x", "url": "ftp://example.com"},
        {"name": "x" * 500, "url": "https://example.com"},
    ]
    for payload in bad_payloads:
        resp = await client.post("/api/sites", json=payload, headers=auth_headers)
        assert resp.status_code == 422, payload


async def test_get_site_404(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(f"/api/sites/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_site_bad_uuid(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/api/sites/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 422


async def test_delete_site(client: httpx.AsyncClient, auth_headers: dict) -> None:
    created = await _create_site(client, auth_headers)
    resp = await client.delete(f"/api/sites/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    gone = await client.get(f"/api/sites/{created['id']}", headers=auth_headers)
    assert gone.status_code == 404
    # Idempotence: second delete is a clean 404, not a 500.
    assert (
        await client.delete(f"/api/sites/{created['id']}", headers=auth_headers)
    ).status_code == 404


async def test_scan_now_requires_ready_baseline(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    created = await _create_site(client, auth_headers)
    resp = await client.post(f"/api/sites/{created['id']}/scan-now", headers=auth_headers)
    assert resp.status_code == 409


async def test_scan_now_with_ready_baseline(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, stub_enqueue: dict
) -> None:
    created = await _create_site(client, auth_headers)
    site_id = uuid.UUID(created["id"])

    async with db_factory() as db:
        baseline = Baseline(
            site_id=site_id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="a" * 64,
            captured_at=datetime.now(UTC),
        )
        db.add(baseline)
        await db.commit()

    resp = await client.post(f"/api/sites/{site_id}/scan-now", headers=auth_headers)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "pending"
    assert len(stub_enqueue["scan"]) == 1

    # A second scan while one is pending is refused.
    resp2 = await client.post(f"/api/sites/{site_id}/scan-now", headers=auth_headers)
    assert resp2.status_code == 409

    scans = (await client.get(f"/api/sites/{site_id}/scans", headers=auth_headers)).json()
    assert len(scans) == 1


async def test_rebaseline_conflict_while_pending(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    created = await _create_site(client, auth_headers)
    # Initial baseline is still pending -> rebaseline conflicts.
    resp = await client.post(f"/api/sites/{created['id']}/rebaseline", headers=auth_headers)
    assert resp.status_code == 409


async def test_rebaseline_recovers_stale_inflight(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, stub_enqueue: dict
) -> None:
    """An in-flight baseline whose worker died (row stuck in pending far
    past the task time limit) must not block rebaseline forever."""
    created = await _create_site(client, auth_headers)
    site_id = uuid.UUID(created["id"])
    async with db_factory() as db:
        await db.execute(
            Baseline.__table__.update()
            .where(Baseline.__table__.c.site_id == site_id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()

    resp = await client.post(f"/api/sites/{site_id}/rebaseline", headers=auth_headers)
    assert resp.status_code == 202
    assert len(stub_enqueue["baseline"]) == 2

    # The abandoned row was marked failed, not left pending.
    async with db_factory() as db:
        stale = (
            await db.scalars(
                select(Baseline).where(
                    Baseline.site_id == site_id, Baseline.status == BaselineStatus.failed
                )
            )
        ).all()
        assert len(stale) == 1


async def test_scan_now_recovers_stale_inflight(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, stub_enqueue: dict
) -> None:
    created = await _create_site(client, auth_headers)
    site_id = uuid.UUID(created["id"])
    async with db_factory() as db:
        db.add(
            Baseline(
                site_id=site_id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="a" * 64,
                captured_at=datetime.now(UTC),
            )
        )
        db.add(
            Scan(
                site_id=site_id,
                status=ScanStatus.running,
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db.commit()

    resp = await client.post(f"/api/sites/{site_id}/scan-now", headers=auth_headers)
    assert resp.status_code == 202
    assert len(stub_enqueue["scan"]) == 1

    scans = (await client.get(f"/api/sites/{site_id}/scans", headers=auth_headers)).json()
    statuses = sorted(s["status"] for s in scans)
    assert statuses == ["failed", "pending"]


async def test_rebaseline_after_failure(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, stub_enqueue: dict
) -> None:
    created = await _create_site(client, auth_headers)
    site_id = uuid.UUID(created["id"])
    async with db_factory() as db:
        await db.execute(
            Baseline.__table__.update()
            .where(Baseline.__table__.c.site_id == site_id)
            .values(status=BaselineStatus.failed, error="boom")
        )
        await db.commit()

    resp = await client.post(f"/api/sites/{site_id}/rebaseline", headers=auth_headers)
    assert resp.status_code == 202
    assert len(stub_enqueue["baseline"]) == 2  # initial + rebaseline


async def test_scans_of_unknown_site_404(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(f"/api/sites/{uuid.uuid4()}/scans", headers=auth_headers)
    assert resp.status_code == 404
