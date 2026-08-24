"""Phase 37 — Low Sweep — Scheduling / Agent / Remediation.

Three findings, one module:

A. Overlapping Beat dispatcher ticks aborted mid-loop with IntegrityError,
   starving every later site in the due list. Fixed with a conditional-
   UPDATE claim per site (rowcount arbitrates overlapping ticks) plus
   per-site exception isolation (one broken site can never abort the tick).
B. Agent conversation creation was uncapped while the listing capped at
   50 — rows 51+ accumulated invisibly. Creation now rejects at the same
   constant instead of pruning history.
C. Auto-execute hooks had no firing cap or cooldown: persistent flagging
   fired destructive webhooks at the tightened cadence indefinitely.
   Auto firings within AUTO_FIRE_COOLDOWN_MINUTES of the hook's last
   outbound attempt are downgraded to the human confirm queue.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt_text
from app.models import (
    AgentConversation,
    Baseline,
    BaselineStatus,
    RemediationActionType,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
    utcnow,
)
from app.remediation import (
    AUTO_FIRE_COOLDOWN_MINUTES,
    create_executions_for_flagged_scan,
)
from app.scanning import MIN_INTERVAL_MINUTES
from worker import beat_tasks

# --- shared helpers ----------------------------------------------------------


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(beat_tasks.celery_app, "send_task", fake_send)
    return calls


@pytest.fixture(autouse=True)
def wire_dispatcher(monkeypatch: pytest.MonkeyPatch, db_factory):
    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(beat_tasks, "task_session", fake_task_session)


async def _make_due_site_with_baseline(db_factory, name: str, *, next_scan_at=None) -> "Site":
    async with db_factory() as db:
        site = Site(
            name=name,
            url=f"https://{uuid.uuid4().hex[:12]}.example.com/",
            auto_scan_enabled=True,
            scan_interval_minutes=60,
            next_scan_at=(
                datetime.now(UTC) - timedelta(minutes=1) if next_scan_at is None else next_scan_at
            ),
        )
        db.add(site)
        await db.flush()
        db.add(
            Baseline(
                site_id=site.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="a" * 64,
            )
        )
        await db.commit()
        await db.refresh(site)
        return site


async def _count(db_factory, model) -> int:
    async with db_factory() as db:
        return await db.scalar(select(func.count()).select_from(model))


# --- Finding A: overlapping Beat dispatcher ticks ----------------------------


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee tick overlap: every commit waits, so both ticks finish
    their due-site SELECT before either finishes claiming (post-fix the
    claim's rowcount arbitrates instead of the unique index erroring)."""
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.3)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


async def test_overlapping_ticks_both_complete_single_scan_per_site(
    db_factory, sent_tasks, widen_commit_window
):
    """The audit's exact repro: six due sites, two concurrent ticks. Pre-fix
    one tick died mid-loop with IntegrityError on ix_scans_one_inflight_per_site;
    post-fix both complete and every site gets exactly one scan."""
    for i in range(6):
        await _make_due_site_with_baseline(db_factory, f"p37-overlap-{i}")

    results = await asyncio.gather(
        beat_tasks._dispatch_due_scans(),
        beat_tasks._dispatch_due_scans(),
        return_exceptions=True,
    )
    for r in results:
        assert not isinstance(r, Exception), f"tick crashed: {r!r}"
    assert sum(r["enqueued"] for r in results) == 6
    assert sum(r["lost_claim"] for r in results) == 6
    assert await _count(db_factory, Scan) == 6
    assert len(sent_tasks) == 6


async def test_per_site_failure_does_not_abort_the_tick(
    db_factory, sent_tasks, monkeypatch: pytest.MonkeyPatch
):
    """A site whose processing explodes must be rolled back and skipped —
    later sites in the same tick still dispatch. Pre-fix the injected error
    aborted the whole coroutine."""
    bomb_created_at = datetime.now(UTC) - timedelta(minutes=31)
    doomed = await _make_due_site_with_baseline(db_factory, "p37-doomed")
    async with db_factory() as db:
        db.add(
            Scan(
                site_id=doomed.id,
                status=ScanStatus.running,
                created_at=bomb_created_at,
            )
        )
        await db.commit()
    survivor = await _make_due_site_with_baseline(db_factory, "p37-survivor")

    real_is_stale = beat_tasks.is_stale

    def exploding_is_stale(created_at, started_at=None):
        if created_at == bomb_created_at:
            raise RuntimeError("injected per-site failure")
        return real_is_stale(created_at, started_at)

    monkeypatch.setattr(beat_tasks, "is_stale", exploding_is_stale)

    stats = await beat_tasks._dispatch_due_scans()

    assert stats["enqueued"] == 1  # the survivor, not the doomed site
    async with db_factory() as db:
        enqueued_scan_id = uuid.UUID(sent_tasks[0][1][0])
        enqueued_scan = await db.get(Scan, enqueued_scan_id)
        assert enqueued_scan.site_id == survivor.id
    # Doomed site's schedule was still claimed (advanced) — no tight loop.
    async with db_factory() as db:
        row = await db.get(Site, doomed.id)
        assert row.next_scan_at > datetime.now(UTC).replace(tzinfo=row.next_scan_at.tzinfo)


async def test_sequential_dispatch_behavior_preserved(db_factory, sent_tasks):
    """Behavior-preservation guard: the normal single-tick path is unchanged
    (claim wins, scan inserted, enqueue recorded, schedule advanced)."""
    site = await _make_due_site_with_baseline(db_factory, "p37-seq")
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["due"] == 1
    assert stats["enqueued"] == 1
    assert stats["lost_claim"] == 0
    assert sent_tasks[0][0] == "wardress.run_scan"
    async with db_factory() as db:
        row = await db.get(Site, site.id)
        assert row.next_scan_at > datetime.now(UTC).replace(tzinfo=row.next_scan_at.tzinfo)


# --- Finding B: agent conversation creation cap -------------------------------


class TestConversationCap:
    async def _create(self, client, headers):
        return await client.post("/api/agent/conversations", headers=headers)

    async def test_creation_capped_and_overflow_conflicts(
        self, client, analyst_headers, db_factory
    ):
        """51st conversation must conflict instead of accumulating invisibly.
        FAILED pre-fix: every create returned 201 and rows piled up."""
        for _ in range(50):
            resp = await self._create(client, analyst_headers)
            assert resp.status_code == 201
        overflow = await self._create(client, analyst_headers)
        assert overflow.status_code == 409
        assert "delete older conversations" in overflow.json()["detail"]
        listing = await client.get("/api/agent/conversations", headers=analyst_headers)
        assert len(listing.json()) == 50
        assert await _count(db_factory, AgentConversation) == 50

    async def test_deletion_frees_capacity(self, client, analyst_headers):
        for _ in range(50):
            await self._create(client, analyst_headers)
        listed = await client.get("/api/agent/conversations", headers=analyst_headers)
        victim_id = listed.json()[0]["id"]
        deleted = await client.delete(
            f"/api/agent/conversations/{victim_id}", headers=analyst_headers
        )
        assert deleted.status_code == 204
        resp = await self._create(client, analyst_headers)
        assert resp.status_code == 201

    async def test_caps_are_per_user(self, client, analyst_headers, viewer_headers):
        for _ in range(50):
            await self._create(client, analyst_headers)
        resp = await self._create(client, viewer_headers)
        assert resp.status_code == 201  # another user's quota is untouched


# --- Finding C: auto-execute hook cooldown ------------------------------------


async def _seed_auto_hook_scenario(
    db_factory, *, requires_manual_confirm: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    async with db_factory() as db:
        site = Site(name="p37c-site", url="https://p37c.example.com/")
        db.add(site)
        await db.flush()
        hook = RemediationHook(
            site_id=site.id,
            name="restart",
            action_type=RemediationActionType.docker_restart,
            trigger_threshold=0.5,
            webhook_url_encrypted=encrypt_text("http://192.0.2.1/hook"),
            requires_manual_confirm=requires_manual_confirm,
        )
        db.add(hook)
        await db.commit()
        await db.refresh(hook)
        return site.id, hook.id


async def _flagged_scan(db_factory, site_id: uuid.UUID, *, age_minutes: int = 0):
    async with db_factory() as db:
        scan = Scan(
            site_id=site_id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
            created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        return scan.id


async def _backdate_all_executions(db_factory, minutes: int) -> None:
    async with db_factory() as db:
        await db.execute(
            update(RemediationExecution).values(created_at=utcnow() - timedelta(minutes=minutes))
        )
        await db.commit()


async def _run_create(db_factory, scan_id: uuid.UUID) -> list:
    async with db_factory() as db:
        scan = await db.get(Scan, scan_id)
        return await create_executions_for_flagged_scan(db, scan)


class TestAutoFireCooldown:
    async def test_persistent_flagging_downgrades_second_auto_fire_to_confirm_queue(
        self, db_factory
    ):
        """The filed defect: persistent flagging fired destructive webhooks at
        the tightened ~5-min cadence indefinitely. Post-fix the second firing
        inside the cooldown window parks in the confirm queue instead.
        FAILED pre-fix: the second execution went straight to queued/ready."""
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory)

        scan1_id = await _flagged_scan(db_factory, site_id)
        ready1 = await _run_create(db_factory, scan1_id)
        assert len(ready1) == 1  # first-ever fire goes out unattended

        scan2_id = await _flagged_scan(db_factory, site_id)
        await _backdate_all_executions(db_factory, MIN_INTERVAL_MINUTES)
        ready2 = await _run_create(db_factory, scan2_id)

        assert ready2 == []
        async with db_factory() as db:
            latest = (
                await db.scalars(
                    select(RemediationExecution)
                    .order_by(desc(RemediationExecution.created_at))
                    .limit(1)
                )
            ).one()
            assert latest.scan_id == scan2_id
            assert latest.status is RemediationExecutionStatus.pending_confirm
            assert str(AUTO_FIRE_COOLDOWN_MINUTES) in (latest.detail or "")

    async def test_cooldown_expires_after_the_window(self, db_factory):
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory)
        scan1_id = await _flagged_scan(db_factory, site_id)
        await _run_create(db_factory, scan1_id)
        await _backdate_all_executions(db_factory, AUTO_FIRE_COOLDOWN_MINUTES + 1)

        scan2_id = await _flagged_scan(db_factory, site_id)
        ready2 = await _run_create(db_factory, scan2_id)
        assert len(ready2) == 1

    async def test_failed_outbound_attempt_still_counts_toward_cooldown(self, db_factory):
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory)
        scan1_id = await _flagged_scan(db_factory, site_id)
        await _run_create(db_factory, scan1_id)
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution).values(
                    status=RemediationExecutionStatus.failed, executed_at=utcnow()
                )
            )
            await db.commit()
        await _backdate_all_executions(db_factory, MIN_INTERVAL_MINUTES)

        scan2_id = await _flagged_scan(db_factory, site_id)
        ready2 = await _run_create(db_factory, scan2_id)
        assert ready2 == []  # hammering a down receiver is the same flap harm

    async def test_dismissed_row_does_not_trigger_cooldown(self, db_factory):
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory)
        scan1_id = await _flagged_scan(db_factory, site_id)
        await _run_create(db_factory, scan1_id)
        async with db_factory() as db:
            await db.execute(
                update(RemediationExecution).values(status=RemediationExecutionStatus.dismissed)
            )
            await db.commit()
        await _backdate_all_executions(db_factory, MIN_INTERVAL_MINUTES)

        scan2_id = await _flagged_scan(db_factory, site_id)
        ready2 = await _run_create(db_factory, scan2_id)
        assert len(ready2) == 1  # the operator rejected that one; this is new

    async def test_manual_confirm_hooks_are_never_cooled(self, db_factory):
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory, requires_manual_confirm=True)
        scan1_id = await _flagged_scan(db_factory, site_id)
        ready1 = await _run_create(db_factory, scan1_id)
        assert ready1 == []  # manual hooks park regardless

        scan2_id = await _flagged_scan(db_factory, site_id)
        await _backdate_all_executions(db_factory, MIN_INTERVAL_MINUTES)
        ready2 = await _run_create(db_factory, scan2_id)
        assert ready2 == []  # still parked — cooldown never applies to them
        async with db_factory() as db:
            rows = (await db.scalars(select(RemediationExecution))).all()
            assert len(rows) == 2
            assert all(r.status is RemediationExecutionStatus.pending_confirm for r in rows)

    async def test_redelivery_of_same_scan_is_idempotent(self, db_factory):
        site_id, _hook_id = await _seed_auto_hook_scenario(db_factory)
        scan1_id = await _flagged_scan(db_factory, site_id)
        async with db_factory() as db:
            scan = await db.get(Scan, scan1_id)
            ready_a = await create_executions_for_flagged_scan(db, scan)
            ready_b = await create_executions_for_flagged_scan(db, scan)
        assert ready_a == ready_b
        assert await _count(db_factory, RemediationExecution) == 1
