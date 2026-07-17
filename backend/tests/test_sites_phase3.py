"""Phase 3 API tests: suppression-rule CRUD/validation and scan-history
pagination."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, SuppressionRule
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


# --- suppression rules: CRUD ---


async def test_create_and_list_rules(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    for payload in (
        {"type": "css_selector", "value": "#visitor-counter", "note": "counter widget"},
        {"type": "regex", "value": r"Session id: \w+"},
        {"type": "bbox", "value": "0.1,0.2,0.3,0.4"},
    ):
        resp = await client.post(
            f"/api/sites/{site['id']}/suppression-rules", json=payload, headers=auth_headers
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["type"] == payload["type"]
        assert body["value"] == payload["value"]
        assert body["site_id"] == site["id"]

    resp = await client.get(f"/api/sites/{site['id']}/suppression-rules", headers=auth_headers)
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) == 3
    assert rules[0]["note"] == "counter widget"


async def test_delete_rule(client, auth_headers, db_factory) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "regex", "value": "dynamic"},
        headers=auth_headers,
    )
    rule_id = resp.json()["id"]

    resp = await client.delete(
        f"/api/sites/{site['id']}/suppression-rules/{rule_id}", headers=auth_headers
    )
    assert resp.status_code == 204
    async with db_factory() as db:
        assert await db.get(SuppressionRule, uuid.UUID(rule_id)) is None

    # Deleting again: 404, not 500.
    resp = await client.delete(
        f"/api/sites/{site['id']}/suppression-rules/{rule_id}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_rules_scoped_to_site(client, auth_headers) -> None:
    """A rule must not be readable or deletable through another site's id."""
    site_a = await _create_site(client, auth_headers)
    site_b = await _create_site(client, auth_headers, name="Other", url="https://example.org/")
    resp = await client.post(
        f"/api/sites/{site_a['id']}/suppression-rules",
        json={"type": "css_selector", "value": ".ad-banner"},
        headers=auth_headers,
    )
    rule_id = resp.json()["id"]

    listing = await client.get(f"/api/sites/{site_b['id']}/suppression-rules", headers=auth_headers)
    assert listing.json() == []
    resp = await client.delete(
        f"/api/sites/{site_b['id']}/suppression-rules/{rule_id}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_rules_cascade_on_site_delete(client, auth_headers, db_factory) -> None:
    site = await _create_site(client, auth_headers)
    await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "regex", "value": "x+"},
        headers=auth_headers,
    )
    resp = await client.delete(f"/api/sites/{site['id']}", headers=auth_headers)
    assert resp.status_code == 204
    async with db_factory() as db:
        remaining = (
            await db.scalars(
                select(SuppressionRule).where(SuppressionRule.site_id == uuid.UUID(site["id"]))
            )
        ).all()
    assert remaining == []


async def test_rules_require_auth(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    assert (await client.get(f"/api/sites/{site['id']}/suppression-rules")).status_code == 401
    assert (
        await client.post(
            f"/api/sites/{site['id']}/suppression-rules",
            json={"type": "regex", "value": "x"},
        )
    ).status_code == 401


async def test_rules_unknown_site_404(client, auth_headers) -> None:
    resp = await client.get(f"/api/sites/{uuid.uuid4()}/suppression-rules", headers=auth_headers)
    assert resp.status_code == 404


# --- suppression rules: validation ---


async def test_invalid_regex_rejected(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "regex", "value": "(unclosed"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "regular expression" in resp.json()["detail"]


async def test_invalid_css_selector_rejected(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "css_selector", "value": "div[["},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "selector" in resp.json()["detail"].lower()


async def test_invalid_bbox_rejected(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    for bad in ("1.5,0,0.2,0.2", "0,0,0,0", "0.9,0.9,0.5,0.5", "nonsense", "0.1,0.1,0.2"):
        resp = await client.post(
            f"/api/sites/{site['id']}/suppression-rules",
            json={"type": "bbox", "value": bad},
            headers=auth_headers,
        )
        assert resp.status_code == 422, f"bbox {bad!r} should be rejected"


async def test_blank_value_rejected(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "regex", "value": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_unknown_type_rejected(client, auth_headers) -> None:
    site = await _create_site(client, auth_headers)
    resp = await client.post(
        f"/api/sites/{site['id']}/suppression-rules",
        json={"type": "xpath", "value": "//div"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# --- scan history pagination ---


async def _site_with_scans(client, auth_headers, db_factory, count: int) -> dict:
    site = await _create_site(client, auth_headers)
    site_id = uuid.UUID(site["id"])
    async with db_factory() as db:
        baseline = Baseline(
            site_id=site_id,
            status=BaselineStatus.ready,
            is_current=False,
            content_hash="a" * 64,
        )
        db.add(baseline)
        await db.flush()
        base_time = datetime.now(UTC) - timedelta(hours=count)
        for i in range(count):
            db.add(
                Scan(
                    site_id=site_id,
                    baseline_id=baseline.id,
                    status=ScanStatus.completed,
                    verdict=ScanVerdict.clean if i % 3 else ScanVerdict.flagged,
                    risk_score=0.9 if i % 3 == 0 else 0.02,
                    created_at=base_time + timedelta(hours=i),
                    finished_at=base_time + timedelta(hours=i, minutes=1),
                )
            )
        await db.commit()
    return site


async def test_scans_paginated_shape_and_order(client, auth_headers, db_factory) -> None:
    site = await _site_with_scans(client, auth_headers, db_factory, 7)
    resp = await client.get(f"/api/sites/{site['id']}/scans?offset=0&limit=3", headers=auth_headers)
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 7
    assert page["offset"] == 0
    assert page["limit"] == 3
    assert len(page["items"]) == 3
    # Newest first.
    created = [s["created_at"] for s in page["items"]]
    assert created == sorted(created, reverse=True)


async def test_scans_pagination_walks_all(client, auth_headers, db_factory) -> None:
    site = await _site_with_scans(client, auth_headers, db_factory, 5)
    seen: list[str] = []
    offset = 0
    while True:
        page = (
            await client.get(
                f"/api/sites/{site['id']}/scans?offset={offset}&limit=2",
                headers=auth_headers,
            )
        ).json()
        seen.extend(s["id"] for s in page["items"])
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5  # no duplicates across pages


async def test_scans_pagination_bounds(client, auth_headers, db_factory) -> None:
    site = await _site_with_scans(client, auth_headers, db_factory, 2)
    # Beyond the end: empty items, correct total, not an error.
    page = (
        await client.get(f"/api/sites/{site['id']}/scans?offset=50&limit=10", headers=auth_headers)
    ).json()
    assert page["items"] == []
    assert page["total"] == 2
    # Invalid params are 422, not 500.
    for bad in ("offset=-1", "limit=0", "limit=201", "offset=abc"):
        resp = await client.get(f"/api/sites/{site['id']}/scans?{bad}", headers=auth_headers)
        assert resp.status_code == 422, bad


async def test_scans_default_pagination(client, auth_headers, db_factory) -> None:
    site = await _site_with_scans(client, auth_headers, db_factory, 3)
    page = (await client.get(f"/api/sites/{site['id']}/scans", headers=auth_headers)).json()
    assert page["limit"] == 50
    assert page["offset"] == 0
    assert len(page["items"]) == 3
