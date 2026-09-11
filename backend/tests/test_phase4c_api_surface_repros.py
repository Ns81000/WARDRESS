"""PROMPT-003 Audit Phase 4C fresh-eyes repros: API-surface findings.

Each test pins one Phase 4C finding as observed behavior (not correctness):

1. Single-site create with a dead broker answers 503 "try again shortly"
   while the site row is already committed — a client that retries hits
   409 "A site with this URL already exists", contradicting the retry hint.
   (Bulk import handles this per-row; single create does not.)
2. FastAPI's default /docs, /redoc and /openapi.json are served
   unauthenticated and outside the /api/ rate-limit middleware — the full
   API surface description is public on a security-monitoring tool.
3. Mute-by-REST (PATCH /api/sites) records a site.mute audit snapshot
   without a `via` field, while the shared services.mute_site (bot/agent
   surface) records one — same action, two audit shapes, two mute
   implementations (the drift class services.py exists to eliminate).
"""

import uuid

import httpx
import pytest
from celery import Celery
from sqlalchemy import select

from app import services
from app.models import AuditLog, Baseline, BaselineStatus, Site


def _dead_broker_client() -> Celery:
    client = Celery("wardress-4c-dead-broker", broker="redis://127.0.0.1:1/0")
    client.conf.broker_transport_options = {"max_retries": 2, "interval_start": 0.1}
    return client


async def test_create_site_dead_broker_commits_site_then_503s(db_factory, monkeypatch):
    """Finding 4C-1 repro: 503 with a retry hint after the site already
    committed; an immediate retry of the same create 409s instead."""
    from app import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "_client", _dead_broker_client())

    async with db_factory() as db:
        with pytest.raises(services.QueueUnavailableError) as excinfo:
            await services.create_site(
                db,
                name="4C-partial",
                url="http://127.0.0.1:9/4c-partial",
                actor=None,
                via="4c-test",
                allow_private_networks=True,
            )
        assert "try again" in excinfo.value.message.lower()

    async with db_factory() as db:
        site = await db.scalar(select(Site).where(Site.url == "http://127.0.0.1:9/4c-partial"))
        assert site is not None  # committed despite the 503 the client saw
        baselines = (await db.scalars(select(Baseline).where(Baseline.site_id == site.id))).all()
        assert all(b.status == BaselineStatus.failed for b in baselines)

        # The retry the 503 invites is answered with a contradiction:
        with pytest.raises(services.ConflictError) as conflict:
            await services.create_site(
                db,
                name="4C-partial retry",
                url="http://127.0.0.1:9/4c-partial",
                actor=None,
                via="4c-test",
                allow_private_networks=True,
            )
        assert "already exists" in conflict.value.message


async def test_openapi_docs_redoc_public_unauthenticated(client: httpx.AsyncClient):
    """Finding 4C-2 repro: the interactive docs and the full schema are
    reachable with no credential, and (path prefix) outside the per-IP
    rate-limit middleware that only meters /api/*."""
    for path in ("/openapi.json", "/docs", "/redoc"):
        resp = await client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


async def test_rest_mute_audit_shape_diverges_from_services_mute(
    client, analyst_headers, db_factory, admin_user
):
    """Finding 4C-3 repro: PATCH mute (REST) vs services.mute_site (bot and
    agent) write different audit snapshots for the same action."""
    async with db_factory() as db:
        site = Site(name="4C-mute", url="https://4c-mute.example.com", created_by=admin_user.id)
        db.add(site)
        await db.commit()
        site_id = site.id

    resp = await client.patch(
        f"/api/sites/{site_id}",
        headers=analyst_headers,
        json={"mute_minutes": 10},
    )
    assert resp.status_code == 200, resp.text

    async with db_factory() as db:
        row = await db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "site.mute", AuditLog.target_id == str(site_id))
            .order_by(AuditLog.created_at.desc())
        )
        assert row is not None
        assert "via" not in (row.after_json or {})

        fresh = await db.get(Site, site_id)
        await services.mute_site(db, fresh, minutes=10, actor=None, via="telegram")
        bot_row = await db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "site.mute", AuditLog.target_id == str(site_id))
            .order_by(AuditLog.created_at.desc())
        )
        assert (bot_row.after_json or {}).get("via") == "telegram"
