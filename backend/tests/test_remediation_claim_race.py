"""Concurrency proofs for remediation confirm/dismiss/fire atomic claims.

Every race test drives the real endpoint and task code against real
Postgres. The commit-window shim only widens the interleaving gap so the
pre-fix check-then-set race reproduces deterministically; post-fix the
outcomes are arbitrated by conditional UPDATEs in the database, not by
the shim.
"""

import asyncio
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt_text
from app.models import (
    AuditLog,
    Baseline,
    BaselineStatus,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
    utcnow,
)

CANARY_DELAY_S = 0.1


class _Canary:
    def __init__(self) -> None:
        self.requests = 0
        self.status_code = 200
        self.delay = CANARY_DELAY_S
        self.url = ""


@pytest.fixture
async def canary():
    c = _Canary()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        c.requests += 1
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        await asyncio.sleep(c.delay)
        body = b"ok"
        head = (
            f"HTTP/1.1 {c.status_code} X\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        writer.write(head + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    c.url = f"http://127.0.0.1:{port}/fire"
    try:
        yield c
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.05)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


async def _seed_site(db_factory, admin_user) -> Site:
    async with db_factory() as db:
        site = Site(name="Race", url=f"https://race-{uuid_mod.uuid4().hex[:8]}.example.com")
        site.created_by = admin_user.id
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _seed_execution(
    db_factory,
    site: Site,
    status_value: str,
    *,
    webhook_url_encrypted: str | None = None,
    confirmed_at: datetime | None = None,
    allow_private_networks: bool = False,
) -> uuid_mod.UUID:
    async with db_factory() as db:
        hook = RemediationHook(
            site_id=site.id,
            name="race-hook",
            action_type="custom_webhook",
            trigger_threshold=0.5,
            webhook_url_encrypted=webhook_url_encrypted or encrypt_text("http://127.0.0.1:9/fire"),
            allow_private_networks=allow_private_networks,
            requires_manual_confirm=True,
        )
        db.add(hook)
        await db.flush()
        baseline = Baseline(
            site_id=site.id, status=BaselineStatus.ready, is_current=True, content_hash="x"
        )
        db.add(baseline)
        await db.flush()
        scan = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(scan)
        await db.flush()
        ex = RemediationExecution(
            hook_id=hook.id,
            site_id=site.id,
            scan_id=scan.id,
            status=RemediationExecutionStatus(status_value),
            hook_name="race-hook",
            action_type="custom_webhook",
            risk_score=0.9,
            confirmed_at=confirmed_at,
        )
        db.add(ex)
        await db.commit()
        await db.refresh(ex)
        return ex.id


async def _audit_rows(db_factory, execution_id: uuid_mod.UUID) -> int:
    async with db_factory() as db:
        rows = (
            await db.scalars(select(AuditLog).where(AuditLog.target_id == str(execution_id)))
        ).all()
        return len(rows)


class TestConfirmRace:
    async def test_concurrent_confirms_single_winner_single_enqueue_single_audit(
        self,
        client,
        auth_headers,
        analyst_headers,
        db_factory,
        admin_user,
        stub_all_enqueues,
        widen_commit_window,
    ):
        for rnd in range(3):
            site = await _seed_site(db_factory, admin_user)
            ex_id = await _seed_execution(db_factory, site, "pending_confirm")
            before = len(stub_all_enqueues["remediation"])
            barrier = asyncio.Barrier(6)

            async def one(b=barrier, ex=ex_id):
                await b.wait()
                resp = await client.post(
                    f"/api/remediation/executions/{ex}/confirm", headers=analyst_headers
                )
                return resp.status_code

            codes = sorted(await asyncio.gather(*[one() for _ in range(6)]))
            assert codes == [200, 409, 409, 409, 409, 409], f"round {rnd}: {codes}"
            assert len(stub_all_enqueues["remediation"]) - before == 1
            async with db_factory() as db:
                row = await db.scalar(
                    select(RemediationExecution).where(RemediationExecution.id == ex_id)
                )
                assert row.status is RemediationExecutionStatus.queued
                assert await _audit_rows(db_factory, ex_id) == 1

    async def test_confirm_dismiss_race_single_winner(
        self,
        client,
        auth_headers,
        analyst_headers,
        db_factory,
        admin_user,
        stub_all_enqueues,
        widen_commit_window,
    ):
        for rnd in range(6):
            site = await _seed_site(db_factory, admin_user)
            ex_id = await _seed_execution(db_factory, site, "pending_confirm")

            async def confirm(ex=ex_id):
                r = await client.post(
                    f"/api/remediation/executions/{ex}/confirm", headers=analyst_headers
                )
                return "confirm", r.status_code

            async def dismiss(ex=ex_id):
                r = await client.post(
                    f"/api/remediation/executions/{ex}/dismiss", headers=analyst_headers
                )
                return "dismiss", r.status_code

            results = await asyncio.gather(confirm(), dismiss())
            winners = [name for name, code in results if code == 200]
            assert len(winners) == 1, f"round {rnd}: {results}"
            async with db_factory() as db:
                row = await db.scalar(
                    select(RemediationExecution).where(RemediationExecution.id == ex_id)
                )
                if winners == ["confirm"]:
                    assert row.status is RemediationExecutionStatus.queued
                else:
                    assert row.status is RemediationExecutionStatus.dismissed
            assert await _audit_rows(db_factory, ex_id) == 1

    async def test_stale_queued_reconfirm_succeeds_and_refreshes(
        self, client, auth_headers, db_factory, admin_user, stub_all_enqueues
    ):
        site = await _seed_site(db_factory, admin_user)
        stale_time = datetime.now(UTC) - timedelta(minutes=11)
        ex_id = await _seed_execution(db_factory, site, "queued", confirmed_at=stale_time)
        resp = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert stub_all_enqueues["remediation"] == [ex_id]
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.confirmed_at is not None
            assert row.confirmed_at > datetime.now(UTC) - timedelta(minutes=1)

    async def test_concurrent_stale_reconfirms_single_winner(
        self,
        client,
        auth_headers,
        analyst_headers,
        db_factory,
        admin_user,
        stub_all_enqueues,
        widen_commit_window,
    ):
        for rnd in range(3):
            stale_time = datetime.now(UTC) - timedelta(minutes=11)
            site = await _seed_site(db_factory, admin_user)
            ex_id = await _seed_execution(db_factory, site, "queued", confirmed_at=stale_time)
            barrier = asyncio.Barrier(2)

            async def one(headers, b=barrier, ex=ex_id):
                await b.wait()
                r = await client.post(f"/api/remediation/executions/{ex}/confirm", headers=headers)
                return r.status_code

            codes = sorted(await asyncio.gather(one(auth_headers), one(analyst_headers)))
            assert codes == [200, 409], f"round {rnd}: {codes}"
            assert stub_all_enqueues["remediation"].count(ex_id) == 1

    async def test_enqueue_failure_reverts_claim_then_retry_succeeds(
        self,
        client,
        auth_headers,
        db_factory,
        admin_user,
        monkeypatch,
        stub_all_enqueues,
    ):
        from fastapi import HTTPException

        from app.routers import remediation as remediation_router

        site = await _seed_site(db_factory, admin_user)
        ex_id = await _seed_execution(db_factory, site, "pending_confirm")

        def boom(_eid):
            raise HTTPException(status_code=503, detail="Task queue is unavailable")

        monkeypatch.setattr(remediation_router, "enqueue_remediation", boom)
        resp = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers
        )
        assert resp.status_code == 503
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.pending_confirm
            assert row.detail == "task queue unavailable — confirm again shortly"

        monkeypatch.setattr(
            remediation_router,
            "enqueue_remediation",
            lambda eid: stub_all_enqueues["remediation"].append(eid),
        )
        retry = await client.post(
            f"/api/remediation/executions/{ex_id}/confirm", headers=auth_headers
        )
        assert retry.status_code == 200
        assert retry.json()["status"] == "queued"


class TestFireClaim:
    async def _seed_fireable(self, db_factory, site, canary_url: str) -> uuid_mod.UUID:
        # The canary listens on loopback, so the seeded hook must carry the
        # SSRF private-network opt-in for its firing to be allowed.
        return await _seed_execution(
            db_factory,
            site,
            "queued",
            webhook_url_encrypted=encrypt_text(canary_url),
            allow_private_networks=True,
        )

    async def test_concurrent_fire_single_post(self, db_factory, admin_user, canary: _Canary):
        from worker.remediation_tasks import _fire

        site = await _seed_site(db_factory, admin_user)
        ex_id = await self._seed_fireable(db_factory, site, canary.url)
        results = sorted(await asyncio.gather(*[_fire(ex_id) for _ in range(3)]))
        assert results == ["not-claimed", "not-claimed", "succeeded"]
        assert canary.requests == 1
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.succeeded
            assert row.executed_at is not None

    async def test_redelivery_after_success_skips(self, db_factory, admin_user, canary: _Canary):
        from worker.remediation_tasks import _fire

        site = await _seed_site(db_factory, admin_user)
        ex_id = await self._seed_fireable(db_factory, site, canary.url)
        assert await _fire(ex_id) == "succeeded"
        assert await _fire(ex_id) == "not-queued-succeeded"
        assert canary.requests == 1

    async def test_fresh_claim_blocks_retry_until_stale_window_passes(
        self, db_factory, admin_user, canary: _Canary
    ):
        from worker.remediation_tasks import _fire

        site = await _seed_site(db_factory, admin_user)
        ex_id = await self._seed_fireable(db_factory, site, canary.url)
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution)
                .where(RemediationExecution.id == ex_id)
                .values(executed_at=utcnow())
            )
            await db.commit()
        assert await _fire(ex_id) == "not-claimed"
        assert canary.requests == 0

        stale = datetime.now(UTC) - timedelta(minutes=11)
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution)
                .where(RemediationExecution.id == ex_id)
                .values(executed_at=stale)
            )
            await db.commit()
        assert await _fire(ex_id) == "succeeded"
        assert canary.requests == 1

    async def test_undecryptable_url_marks_failed_after_winning_claim(self, db_factory, admin_user):
        from worker.remediation_tasks import _fire

        site = await _seed_site(db_factory, admin_user)
        ex_id = await _seed_execution(
            db_factory, site, "queued", webhook_url_encrypted="garbage-not-fernet"
        )
        result = await asyncio.wait_for(_fire(ex_id), timeout=30)
        assert result == "url-undecryptable"
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.failed
            assert "re-save the hook" in row.detail

    async def test_non_2xx_webhook_maps_to_failed(self, db_factory, admin_user, canary: _Canary):
        from worker.remediation_tasks import _fire

        site = await _seed_site(db_factory, admin_user)
        canary.status_code = 500
        ex_id = await self._seed_fireable(db_factory, site, canary.url)
        assert await _fire(ex_id) == "failed"
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.failed
            assert row.detail == "webhook returned HTTP 500"
