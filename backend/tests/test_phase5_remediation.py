"""Remediation hooks, confirm queue, and webhook firing (Phase 5, §6/§9)."""

import uuid

import pytest
from sqlalchemy import select

from app.crypto import decrypt_text
from app.models import (
    Baseline,
    BaselineStatus,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
)


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


async def _make_site(db_factory, admin_user) -> Site:
    async with db_factory() as db:
        site = Site(name="Prod", url="https://prod.example.com", created_by=admin_user.id)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _make_flagged_scan(db_factory, site_id, risk=0.9) -> uuid.UUID:
    async with db_factory() as db:
        baseline = Baseline(site_id=site_id, status=BaselineStatus.ready, is_current=True,
                            content_hash="x")
        db.add(baseline)
        await db.flush()
        scan = Scan(
            site_id=site_id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=risk,
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        return scan.id


class TestHookCrud:
    async def test_create_hook_encrypts_url(self, client, auth_headers, db_factory, admin_user):
        site = await _make_site(db_factory, admin_user)
        resp = await client.post(
            f"/api/sites/{site.id}/remediation-hooks",
            headers=auth_headers,
            json={
                "name": "rollback",
                "action_type": "git_rollback",
                "webhook_url": "https://hooks.example.com/deploy?token=secret",
                "trigger_threshold": 0.7,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # URL never round-trips whole.
        assert "secret" not in str(body)
        assert body["url_hint"].startswith("https://hooks.example.com")
        assert body["requires_manual_confirm"] is True  # default

        async with db_factory() as db:
            hook = await db.scalar(select(RemediationHook))
            assert decrypt_text(hook.webhook_url_encrypted) == (
                "https://hooks.example.com/deploy?token=secret"
            )

    async def test_reject_non_http_url(self, client, auth_headers, db_factory, admin_user):
        site = await _make_site(db_factory, admin_user)
        resp = await client.post(
            f"/api/sites/{site.id}/remediation-hooks",
            headers=auth_headers,
            json={"name": "x", "action_type": "custom_webhook", "webhook_url": "ftp://nope/"},
        )
        assert resp.status_code == 422


class TestExecutionCreation:
    async def test_manual_confirm_hook_parks_pending(self, client, db_factory, admin_user):
        from app.remediation import create_executions_for_flagged_scan

        site = await _make_site(db_factory, admin_user)
        async with db_factory() as db:
            db.add(
                RemediationHook(
                    site_id=site.id,
                    name="manual",
                    action_type="custom_webhook",
                    trigger_threshold=0.5,
                    webhook_url_encrypted="ignored",
                    requires_manual_confirm=True,
                )
            )
            await db.commit()
        scan_id = await _make_flagged_scan(db_factory, site.id)
        async with db_factory() as db:
            scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
            ready = await create_executions_for_flagged_scan(db, scan)
        assert ready == []  # nothing fires without confirmation
        async with db_factory() as db:
            ex = await db.scalar(select(RemediationExecution))
            assert ex.status is RemediationExecutionStatus.pending_confirm

    async def test_auto_execute_hook_is_ready(self, client, db_factory, admin_user):
        from app.remediation import create_executions_for_flagged_scan

        site = await _make_site(db_factory, admin_user)
        async with db_factory() as db:
            db.add(
                RemediationHook(
                    site_id=site.id,
                    name="auto",
                    action_type="custom_webhook",
                    trigger_threshold=0.5,
                    webhook_url_encrypted="ignored",
                    requires_manual_confirm=False,
                )
            )
            await db.commit()
        scan_id = await _make_flagged_scan(db_factory, site.id)
        async with db_factory() as db:
            scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
            ready = await create_executions_for_flagged_scan(db, scan)
        assert len(ready) == 1

    async def test_below_threshold_no_execution(self, client, db_factory, admin_user):
        from app.remediation import create_executions_for_flagged_scan

        site = await _make_site(db_factory, admin_user)
        async with db_factory() as db:
            db.add(
                RemediationHook(
                    site_id=site.id,
                    name="high-bar",
                    action_type="custom_webhook",
                    trigger_threshold=0.95,
                    webhook_url_encrypted="ignored",
                    requires_manual_confirm=False,
                )
            )
            await db.commit()
        scan_id = await _make_flagged_scan(db_factory, site.id, risk=0.6)
        async with db_factory() as db:
            scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
            ready = await create_executions_for_flagged_scan(db, scan)
            count = len((await db.scalars(select(RemediationExecution))).all())
        assert ready == [] and count == 0


class TestConfirmQueue:
    async def _seed_pending(self, client, auth_headers, db_factory, admin_user):
        site = await _make_site(db_factory, admin_user)
        scan_id = await _make_flagged_scan(db_factory, site.id)
        async with db_factory() as db:
            hook = RemediationHook(
                site_id=site.id,
                name="manual",
                action_type="custom_webhook",
                trigger_threshold=0.5,
                webhook_url_encrypted="ignored",
                requires_manual_confirm=True,
            )
            db.add(hook)
            await db.flush()
            ex = RemediationExecution(
                hook_id=hook.id,
                site_id=site.id,
                scan_id=scan_id,
                status=RemediationExecutionStatus.pending_confirm,
                hook_name="manual",
                action_type="custom_webhook",
                risk_score=0.9,
            )
            db.add(ex)
            await db.commit()
            await db.refresh(ex)
            return ex.id

    async def test_confirm_queues_and_enqueues(
        self, client, auth_headers, db_factory, admin_user, stub_all_enqueues
    ):
        ex_id = await self._seed_pending(client, auth_headers, db_factory, admin_user)
        resp = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "queued"
        assert ex_id in stub_all_enqueues["remediation"]

    async def test_dismiss(self, client, auth_headers, db_factory, admin_user):
        ex_id = await self._seed_pending(client, auth_headers, db_factory, admin_user)
        resp = await client.post(
            f"/api/remediation/executions/{ex_id}/dismiss", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    async def test_confirm_twice_conflicts(self, client, auth_headers, db_factory, admin_user):
        ex_id = await self._seed_pending(client, auth_headers, db_factory, admin_user)
        await client.post(f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers)
        again = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers
        )
        assert again.status_code == 409

    async def test_viewer_cannot_confirm(
        self, client, viewer_headers, db_factory, admin_user, auth_headers
    ):
        ex_id = await self._seed_pending(client, auth_headers, db_factory, admin_user)
        resp = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=viewer_headers
        )
        assert resp.status_code == 403
