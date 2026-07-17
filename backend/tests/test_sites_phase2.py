"""Phase 2 API tests: per-site settings PATCH, scan-detail findings
endpoint, and the new site fields in responses."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.models import Baseline, BaselineStatus, Scan, ScanFinding, ScanStatus, ScanVerdict, Site
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


# --- new site fields ---


async def test_site_defaults_in_response(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    assert site["flag_threshold"] == 0.5
    assert site["auto_scan_enabled"] is True
    assert site["scan_interval_minutes"] == 60
    assert site["next_scan_at"] is not None


async def test_create_site_with_custom_settings(client, auth_headers) -> None:
    site = await _create_site(
        client,
        auth_headers,
        flag_threshold=0.8,
        auto_scan_enabled=False,
        scan_interval_minutes=120,
    )
    assert site["flag_threshold"] == 0.8
    assert site["auto_scan_enabled"] is False
    assert site["scan_interval_minutes"] == 120
    assert site["next_scan_at"] is None  # auto-scan off -> nothing scheduled


async def test_create_site_rejects_bad_settings(client, auth_headers) -> None:
    for bad in (
        {"flag_threshold": 1.5},
        {"flag_threshold": -0.1},
        {"scan_interval_minutes": 1},
        {"scan_interval_minutes": 100000},
    ):
        resp = await client.post(
            "/api/sites",
            json={"name": "x", "url": "https://example.com/", **bad},
            headers=auth_headers,
        )
        assert resp.status_code == 422, bad


# --- PATCH settings ---


async def test_patch_threshold(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.patch(
        f"/api/sites/{site['id']}", json={"flag_threshold": 0.75}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["flag_threshold"] == 0.75


async def test_patch_interval_resets_adaptive_state(client, auth_headers, db_factory) -> None:
    site = await _create_site(client, auth_headers)
    # Simulate adaptive tightening having happened.
    async with db_factory() as db:
        row = await db.get(Site, uuid.UUID(site["id"]))
        row.current_interval_minutes = 15
        await db.commit()

    resp = await client.patch(
        f"/api/sites/{site['id']}", json={"scan_interval_minutes": 30}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_interval_minutes"] == 30
    assert body["current_interval_minutes"] is None  # adaptive state reset


async def test_patch_disable_auto_scan_clears_schedule(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.patch(
        f"/api/sites/{site['id']}", json={"auto_scan_enabled": False}, headers=auth_headers
    )
    assert resp.json()["next_scan_at"] is None

    # Re-enabling schedules the next scan.
    resp = await client.patch(
        f"/api/sites/{site['id']}", json={"auto_scan_enabled": True}, headers=auth_headers
    )
    assert resp.json()["next_scan_at"] is not None


async def test_patch_validation(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    for bad in ({"flag_threshold": 2}, {"scan_interval_minutes": 0}):
        resp = await client.patch(f"/api/sites/{site['id']}", json=bad, headers=auth_headers)
        assert resp.status_code == 422, bad


async def test_patch_requires_auth(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.patch(f"/api/sites/{site['id']}", json={"flag_threshold": 0.9})
    assert resp.status_code == 401


async def test_patch_unknown_site_404(client, auth_headers) -> None:
    resp = await client.patch(
        f"/api/sites/{uuid.uuid4()}", json={"flag_threshold": 0.9}, headers=auth_headers
    )
    assert resp.status_code == 404


# --- scan detail with findings ---


async def _site_with_completed_scan(client, auth_headers, db_factory) -> tuple[dict, uuid.UUID]:
    site = await _create_site(client, auth_headers)
    site_id = uuid.UUID(site["id"])
    async with db_factory() as db:
        baseline = Baseline(
            site_id=site_id,
            status=BaselineStatus.ready,
            is_current=False,  # the pending creation-time row exists too
            content_hash="a" * 64,
        )
        db.add(baseline)
        await db.flush()
        scan = Scan(
            site_id=site_id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.93,
            layer_scores={"layer1_hash": {"score": 1.0, "skipped": False}},
            finished_at=datetime.now(UTC),
        )
        db.add(scan)
        await db.flush()
        db.add(
            ScanFinding(
                scan_id=scan.id,
                layer=1,
                layer_key="layer1_hash",
                score=1.0,
                skipped=False,
                evidence={"identical": False},
            )
        )
        db.add(
            ScanFinding(
                scan_id=scan.id,
                layer=4,
                layer_key="layer4_visual_diff",
                score=None,
                skipped=True,
                evidence={"reason": "gated by layer 1"},
            )
        )
        await db.commit()
        return site, scan.id


async def test_scan_detail_returns_findings(client, auth_headers, db_factory) -> None:
    site, scan_id = await _site_with_completed_scan(client, auth_headers, db_factory)
    resp = await client.get(f"/api/sites/{site['id']}/scans/{scan_id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_score"] == 0.93
    assert body["verdict"] == "flagged"
    assert len(body["findings"]) == 2
    # Ordered by layer; evidence dict comes through intact.
    assert body["findings"][0]["layer"] == 1
    assert body["findings"][0]["evidence"] == {"identical": False}
    assert body["findings"][1]["skipped"] is True


async def test_scan_detail_404s(client, auth_headers, db_factory) -> None:
    site, scan_id = await _site_with_completed_scan(client, auth_headers, db_factory)
    # Unknown scan.
    resp = await client.get(f"/api/sites/{site['id']}/scans/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    # Scan under the wrong site: must not leak across sites.
    other = await _create_site(client, auth_headers, name="Other", url="https://example.org/")
    resp = await client.get(f"/api/sites/{other['id']}/scans/{scan_id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_scan_detail_requires_auth(client, auth_headers, db_factory) -> None:
    site, scan_id = await _site_with_completed_scan(client, auth_headers, db_factory)
    resp = await client.get(f"/api/sites/{site['id']}/scans/{scan_id}")
    assert resp.status_code == 401


async def test_scan_list_includes_risk_score(client, auth_headers, db_factory) -> None:
    site, _ = await _site_with_completed_scan(client, auth_headers, db_factory)
    resp = await client.get(f"/api/sites/{site['id']}/scans", headers=auth_headers)
    assert resp.status_code == 200
    scans = resp.json()["items"]
    assert scans[0]["risk_score"] == 0.93
    assert scans[0]["layer_scores"]["layer1_hash"]["score"] == 1.0


async def test_findings_cascade_on_site_delete(client, auth_headers, db_factory) -> None:
    site, scan_id = await _site_with_completed_scan(client, auth_headers, db_factory)
    resp = await client.delete(f"/api/sites/{site['id']}", headers=auth_headers)
    assert resp.status_code == 204
    async with db_factory() as db:
        remaining = (
            await db.scalars(select(ScanFinding).where(ScanFinding.scan_id == scan_id))
        ).all()
    assert remaining == []
