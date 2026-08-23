"""Remediation-hook SSRF discipline + stuck-queued repair (Phase 26).

Finding A: hook URLs bypassed the codebase's entire SSRF discipline —
creation accepted metadata/loopback/RFC1918 targets and execution POSTed
to them unpinned. Now: assert_url_allowed gates every create/update
(with an explicit per-hook private-network opt-in mirroring sites), and
every fire connects through the DNS-pinning transport honoring that flag.

Finding B: schema-valid but unfetchable URLs (bad ports, control chars)
wedged executions `queued` forever — httpx.InvalidURL escaped
post_webhook's HTTPError-only handler, the Celery wrapper swallowed it,
and the resweep re-enqueued the permanently-broken firing every 5
minutes. Now: fetchability is validated at save, post_webhook honors its
never-raises contract, and any delivery-path crash lands the row in an
honest terminal state.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.crypto import encrypt_text
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

GLOBAL_URL = "https://93.184.216.34/hook"
INTERNAL_TARGETS = [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://127.0.0.1:8499/hook",
    "http://[::1]:8499/hook",
    "http://[::ffff:127.0.0.1]:8499/hook",
    "http://10.9.9.9/internal-admin",
]
UNFETCHABLE_URLS = [
    "http://127.0.0.1:abc/nope",
    "http://127.0.0.1\x0a/nope",
]


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


async def _make_site(db_factory, admin_user) -> Site:
    async with db_factory() as db:
        site = Site(name="Hooked", url=f"https://site-{uuid.uuid4().hex[:8]}.example.com")
        site.created_by = admin_user.id
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _create_hook(client, auth_headers, site_id, url, **extra) -> object:
    payload = {"name": "h", "action_type": "custom_webhook", "webhook_url": url}
    payload.update(extra)
    return await client.post(
        f"/api/sites/{site_id}/remediation-hooks", headers=auth_headers, json=payload
    )


class TestHookSsrfGate:
    async def test_internal_targets_refused_by_default(
        self, client, auth_headers, db_factory, admin_user
    ):
        site = await _make_site(db_factory, admin_user)
        for target in INTERNAL_TARGETS:
            resp = await _create_hook(client, auth_headers, site.id, target)
            assert resp.status_code == 422, f"{target}: {resp.text}"
            assert (
                "blocked" in resp.json()["detail"].lower()
                or "resolve" in resp.json()["detail"].lower()
            )
        async with db_factory() as db:
            assert (await db.scalars(select(RemediationHook))).all() == []

    async def test_private_target_allowed_with_explicit_optin(
        self, client, auth_headers, db_factory, admin_user
    ):
        site = await _make_site(db_factory, admin_user)
        resp = await _create_hook(
            client,
            auth_headers,
            site.id,
            "http://127.0.0.1:8499/hook",
            allow_private_networks=True,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["allow_private_networks"] is True
        async with db_factory() as db:
            hook = await db.scalar(select(RemediationHook))
            assert hook.allow_private_networks is True

    async def test_global_target_passes_without_optin(
        self, client, auth_headers, db_factory, admin_user
    ):
        site = await _make_site(db_factory, admin_user)
        resp = await _create_hook(client, auth_headers, site.id, GLOBAL_URL)
        assert resp.status_code == 201, resp.text
        assert resp.json()["allow_private_networks"] is False

    async def test_unfetchable_urls_refused_at_save(
        self, client, auth_headers, db_factory, admin_user
    ):
        site = await _make_site(db_factory, admin_user)
        for bad in UNFETCHABLE_URLS:
            resp = await _create_hook(client, auth_headers, site.id, bad)
            assert resp.status_code == 422, f"{bad!r}: {resp.text}"
        async with db_factory() as db:
            assert (await db.scalars(select(RemediationHook))).all() == []

    async def test_patch_revalidates_new_url(self, client, auth_headers, db_factory, admin_user):
        site = await _make_site(db_factory, admin_user)
        hook_id = (await _create_hook(client, auth_headers, site.id, GLOBAL_URL)).json()["id"]
        base = f"/api/sites/{site.id}/remediation-hooks/{hook_id}"
        # Internal target without opt-in -> refused.
        r = await client.patch(
            base, headers=auth_headers, json={"webhook_url": "http://127.0.0.1:9/hook"}
        )
        assert r.status_code == 422, r.text
        # Internal target WITH opt-in in the same request -> allowed.
        r = await client.patch(
            base,
            headers=auth_headers,
            json={
                "webhook_url": "http://127.0.0.1:9/hook",
                "allow_private_networks": True,
            },
        )
        assert r.status_code == 200, r.text
        # Flipping the flag alone persists.
        r = await client.patch(base, headers=auth_headers, json={"allow_private_networks": False})
        assert r.status_code == 200
        assert r.json()["allow_private_networks"] is False


async def _seed_queued_execution(
    db_factory,
    site: Site,
    *,
    url: str,
    allow_private_networks: bool,
) -> uuid.UUID:
    """Plant a hook + flagged scan + queued execution directly (bypasses
    schema validation — simulates rows saved before Phase 26 existed)."""
    async with db_factory() as db:
        hook = RemediationHook(
            site_id=site.id,
            name="legacy",
            action_type="custom_webhook",
            trigger_threshold=0.5,
            webhook_url_encrypted=encrypt_text(url),
            allow_private_networks=allow_private_networks,
        )
        db.add(hook)
        await db.flush()
        # FK filler only — never read by the firing path; is_current stays
        # False so several seeded executions can share one site.
        baseline = Baseline(
            site_id=site.id, status=BaselineStatus.ready, is_current=False, content_hash="x"
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
            status=RemediationExecutionStatus.queued,
            hook_name="legacy",
            action_type="custom_webhook",
            risk_score=0.9,
        )
        db.add(ex)
        await db.commit()
        await db.refresh(ex)
        return ex.id


@pytest.fixture
async def fire_canary():
    """Loopback HTTP receiver counting POSTs (same shape as the claim-race
    suite's canary)."""

    class _Canary:
        def __init__(self) -> None:
            self.requests = 0
            self.bodies: list[bytes] = []
            self.url = ""

    c = _Canary()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        c.requests += 1
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        await reader.read(65536)
        head = b"HTTP/1.1 200 X\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
        writer.write(head)
        await writer.drain()
        writer.close()

    from asyncio import start_server

    server = await start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    c.url = f"http://127.0.0.1:{port}/fire"
    try:
        yield c
    finally:
        server.close()
        await server.wait_closed()


class TestFireSsrfGate:
    async def test_legacy_internal_hook_fires_nothing_without_optin(
        self, db_factory, admin_user, fire_canary
    ):
        from worker.remediation_tasks import _fire

        site = await _make_site(db_factory, admin_user)
        ex_id = await _seed_queued_execution(
            db_factory, site, url=fire_canary.url, allow_private_networks=False
        )
        result = await _fire(ex_id)
        assert result == "failed"
        assert fire_canary.requests == 0
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.failed
            assert "refused" in (row.detail or "").lower()
            assert row.executed_at is not None

    async def test_optin_hook_fires_end_to_end_with_payload(
        self, db_factory, admin_user, fire_canary
    ):
        from worker.remediation_tasks import _fire

        site = await _make_site(db_factory, admin_user)
        ex_id = await _seed_queued_execution(
            db_factory, site, url=fire_canary.url, allow_private_networks=True
        )
        assert await _fire(ex_id) == "succeeded"
        assert fire_canary.requests == 1
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.succeeded
            assert row.detail == "HTTP 200"


class TestNeverRaisesDelivery:
    async def test_post_webhook_returns_tuple_on_invalid_url(self):
        from app.remediation import post_webhook

        ok, detail = await post_webhook("http://127.0.0.1:abc/nope", {})
        assert ok is False
        assert detail == "webhook error: InvalidURL"

    async def test_post_webhook_refuses_private_target_without_optin(self, fire_canary):
        from app.remediation import post_webhook

        ok, detail = await post_webhook(fire_canary.url, {}, allow_private_networks=False)
        assert ok is False
        assert "refused" in detail.lower()

    async def test_post_webhook_reaches_loopback_receiver_with_optin(self, fire_canary):
        from app.remediation import post_webhook

        ok, detail = await post_webhook(
            fire_canary.url, {"event": "t"}, allow_private_networks=True
        )
        assert ok is True, detail
        assert detail == "HTTP 200"
        assert fire_canary.requests == 1

    async def test_detail_never_carries_url_credentials(self, db_factory, admin_user):
        from worker.remediation_tasks import _fire

        site = await _make_site(db_factory, admin_user)
        secret_url = "http://127.0.0.1:abc/path?token=supersecret-token"
        ex_id = await _seed_queued_execution(
            db_factory, site, url=secret_url, allow_private_networks=False
        )
        await _fire(ex_id)
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
        assert "supersecret-token" not in (row.detail or "")

    async def test_delivery_crash_marks_failed_not_stuck_queued(
        self, db_factory, admin_user, fire_canary, monkeypatch
    ):
        from worker import remediation_tasks

        site = await _make_site(db_factory, admin_user)
        ex_id = await _seed_queued_execution(
            db_factory, site, url=fire_canary.url, allow_private_networks=True
        )

        def _boom(*a, **kw):
            raise RuntimeError("payload builder bug")

        monkeypatch.setattr(remediation_tasks, "build_remediation_payload", _boom)
        assert await remediation_tasks._fire(ex_id) == "failed"
        async with db_factory() as db:
            row = await db.scalar(
                select(RemediationExecution).where(RemediationExecution.id == ex_id)
            )
            assert row.status is RemediationExecutionStatus.failed
            assert row.detail == "delivery failed unexpectedly"
            assert row.executed_at is not None


class TestResweepBounded:
    async def test_terminal_rows_excluded_genuinely_stuck_recovered(
        self, db_factory, admin_user, monkeypatch
    ):
        from worker import beat_tasks

        sent: list[str] = []
        monkeypatch.setattr(
            beat_tasks.celery_app, "send_task", lambda name, args=None, **kw: sent.append(args[0])
        )
        site = await _make_site(db_factory, admin_user)
        old = datetime.now(UTC) - timedelta(minutes=11)

        # A crashed delivery ends TERMINAL — even backdated past the grace,
        # the resweep must leave it alone.
        crashed_id = await _seed_queued_execution(
            db_factory, site, url="http://127.0.0.1:abc/nope", allow_private_networks=False
        )
        from sqlalchemy import update

        from worker.remediation_tasks import _fire

        await _fire(crashed_id)
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution)
                .where(RemediationExecution.id == crashed_id)
                .values(created_at=old)
            )
            await db.commit()

        # A genuinely stranded queued row (lost enqueue) IS recovered.
        stuck_id = await _seed_queued_execution(
            db_factory, site, url=GLOBAL_URL, allow_private_networks=False
        )
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution)
                .where(RemediationExecution.id == stuck_id)
                .values(created_at=old)
            )
            await db.commit()

        stats = await beat_tasks._resweep_undelivered()
        assert stats["remediations_reenqueued"] == 1
        assert sent == [str(stuck_id)]
