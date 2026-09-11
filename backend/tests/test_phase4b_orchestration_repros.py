"""PROMPT-003 Audit Phase 4B repro tests — orchestration & scheduling.

These tests characterize behaviors found by the fresh-eyes orchestration
audit (worker/celery_app.py, worker/scan_tasks.py, worker/beat_tasks.py,
app/scanning.py, app/tasks.py). They are documentation-as-tests of CURRENT
behavior, not proposed fixes (Rule 1: diagnosis only):

- test_flagged_scan_redelivery_cannot_recover_missing_alert: the alert
  creation handoff runs after the scan's terminal commit; the idempotent
  redelivery path early-returns before it, and the re-delivery sweep only
  re-enqueues alerts that exist — so a worker death in the handoff window
  loses the alert permanently.
- test_resweep_recovers_stranded_alert_enqueue: positive control — when
  the alert row DOES exist, the sweep re-enqueues its delivery.
- test_backlogged_pending_scan_superseded_by_dispatch_tick: a pending
  row older than STALE_INFLIGHT is treated as a lost enqueue even while
  its message may still be sitting in the broker queue; the superseded
  row's eventual redelivery no-ops.
- test_inflight_skip_still_advances_next_scan_at: the dispatcher's
  advance-then-check order pushes the schedule forward even on a tick
  that enqueues nothing.
- test_repeated_material_risk_transients_hold_cadence_at_base_quarter:
  the AUDIT-4-2 transient class (probe blips fusing >= 0.40) keeps a
  site pinned at base/4 while it recurs, and relaxes only via the x1.5
  clean-scan ladder.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Alert, Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, Site
from app.scanning import next_interval_after_scan
from worker import beat_tasks, scan_tasks


@pytest.fixture(autouse=True)
def _wire_sessions(monkeypatch: pytest.MonkeyPatch, db_factory):
    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(beat_tasks, "task_session", fake_task_session)


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send)
    monkeypatch.setattr(beat_tasks.celery_app, "send_task", fake_send)
    return calls


async def _make_site(db_factory, **overrides) -> Site:
    defaults = {
        "name": "audit4b",
        "url": f"https://{uuid.uuid4().hex[:12]}.example.com/",
        "auto_scan_enabled": True,
        "scan_interval_minutes": 60,
    }
    defaults.update(overrides)
    async with db_factory() as db:
        site = Site(**defaults)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _add_ready_baseline(db_factory, site_id) -> Baseline:
    async with db_factory() as db:
        baseline = Baseline(
            site_id=site_id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="a" * 64,
        )
        db.add(baseline)
        await db.commit()
        await db.refresh(baseline)
        return baseline


# --- AUDIT-4B-1: the alert-creation crash window is unrecoverable ---------


async def test_flagged_scan_redelivery_cannot_recover_missing_alert(db_factory, sent_tasks):
    """A flagged scan whose worker died between the terminal scan commit and
    _create_alert's commit has NO alert row. The acks_late redelivery of the
    run_scan message early-returns on the completed status, and the re-delivery
    sweep only re-enqueues deliveries for alerts that exist — so the alert is
    lost permanently. (RemediationExecutions are symmetric: sole creation site
    is the same handoff, guarded by uq_remediation_executions_hook_scan.)"""
    site = await _make_site(db_factory)
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        scan = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        scan_id = scan.id

    result = await scan_tasks._run_scan(scan_id)

    assert result == "scan-already-completed"
    async with db_factory() as db:
        assert await db.scalar(select(Alert).where(Alert.scan_id == scan_id)) is None

    stats = await beat_tasks._resweep_undelivered()
    assert stats["alerts_reenqueued"] == 0
    async with db_factory() as db:
        assert await db.scalar(select(Alert).where(Alert.scan_id == scan_id)) is None


async def test_resweep_recovers_stranded_alert_enqueue(db_factory, sent_tasks):
    """Positive control for the same mechanism: an alert row that exists but
    whose delivery enqueue was lost IS re-enqueued by the sweep."""
    site = await _make_site(db_factory)
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        scan = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(scan)
        await db.flush()
        alert = Alert(
            site_id=site.id,
            scan_id=scan.id,
            risk_score=0.9,
            created_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        alert_id = alert.id

    stats = await beat_tasks._resweep_undelivered()

    assert stats["alerts_reenqueued"] == 1
    assert ("wardress.deliver_alert", [str(alert_id)]) in sent_tasks


# --- stale-pending supersede under a (possibly still-queued) message ------


async def test_backlogged_pending_scan_superseded_by_dispatch_tick(db_factory, sent_tasks):
    """A pending row older than STALE_INFLIGHT is treated as a lost enqueue:
    the tick fails it, supersedes it, and enqueues a fresh scan. If the
    original message was merely sitting in a broker backlog (not lost), its
    eventual delivery no-ops on the failed status — the cost is a failed
    history row and one extra no-op message, not a double scan."""
    site = await _make_site(
        db_factory, next_scan_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        backlogged = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.pending,
            created_at=datetime.now(UTC) - timedelta(minutes=15),
        )
        db.add(backlogged)
        await db.commit()
        await db.refresh(backlogged)
        backlogged_id = backlogged.id

    stats = await beat_tasks._dispatch_due_scans()

    assert stats["recovered_stale"] == 1
    assert stats["enqueued"] == 1
    async with db_factory() as db:
        row = await db.get(Scan, backlogged_id)
        assert row.status == ScanStatus.failed
        assert "superseded" in (row.error or "")
    # The stale row's own redelivery (if its message was only backlogged)
    # is a no-op:
    assert await scan_tasks._run_scan(backlogged_id) == "scan-already-failed"


# --- skip-advances-schedule semantics -------------------------------------


async def test_inflight_skip_still_advances_next_scan_at(db_factory, sent_tasks):
    """The dispatcher advances next_scan_at (claim) BEFORE the in-flight
    check, so a tick that enqueues nothing because a fresh scan is running
    still pushes the schedule out one interval."""
    site = await _make_site(
        db_factory, next_scan_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        db.add(
            Scan(
                site_id=site.id,
                baseline_id=baseline.id,
                status=ScanStatus.running,
                started_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
        await db.commit()

    before = datetime.now(UTC)
    stats = await beat_tasks._dispatch_due_scans()

    assert stats["skipped_inflight"] == 1
    assert stats["enqueued"] == 0
    async with db_factory() as db:
        refreshed = await db.get(Site, site.id)
        assert refreshed.next_scan_at is not None
        assert refreshed.next_scan_at.replace(tzinfo=UTC) > before + timedelta(minutes=55)


# --- AUDIT-4-2 transient x adaptive-cadence coupling -----------------------


def test_repeated_material_risk_transients_hold_cadence_at_base_quarter():
    """While material-band transients recur (AUDIT-4-2: probe-side blinks
    fusing >= 0.40 with no content change), every tighten resets the
    interval to base/4 and one clean scan only multiplies by 1.5 — so any
    transient period shorter than the relax ladder keeps the site on a
    ~base/4..base/3 cadence indefinitely instead of returning to base."""
    base = 1440
    current = None
    seen = []
    for changed in (True, False) * 6:
        current = next_interval_after_scan(base, current, changed=changed)
        seen.append(current)
    assert all(value == base // 4 for value in seen[::2])
    assert seen[-1] < base

    # Full relaxation from one tightened step takes 4 clean scans:
    ladder = []
    current = next_interval_after_scan(base, None, changed=True)
    while current < base:
        ladder.append(current)
        current = next_interval_after_scan(base, current, changed=False)
    assert ladder == [360, 540, 810, 1215]
    assert current == base

