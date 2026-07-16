"""Adaptive interval policy + Beat dispatcher tests.

The dispatcher must apply exactly the API's semantics: skip (not
duplicate) genuine in-flight scans, recover stale rows, skip sites with
no ready baseline, and advance next_scan_at before enqueueing so a crash
can only delay a site, never tight-loop it."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, Site
from app.scanning import (
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    clamp_interval,
    next_interval_after_scan,
)
from worker import beat_tasks

# --- adaptive interval policy ---


def test_change_tightens_interval() -> None:
    assert next_interval_after_scan(60, None, changed=True) == 15
    assert next_interval_after_scan(60, 60, changed=True) == 15


def test_tighten_respects_minimum() -> None:
    assert next_interval_after_scan(8, 8, changed=True) == MIN_INTERVAL_MINUTES


def test_stable_relaxes_gradually_back_to_base() -> None:
    base = 60
    current = next_interval_after_scan(base, None, changed=True)  # 15
    seen = [current]
    for _ in range(10):
        current = next_interval_after_scan(base, current, changed=False)
        seen.append(current)
        if current == base:
            break
    assert seen[0] == 15
    assert all(a <= b for a, b in zip(seen, seen[1:], strict=False))
    assert seen[-1] == base


def test_stable_at_base_stays_at_base() -> None:
    assert next_interval_after_scan(60, 60, changed=False) == 60
    assert next_interval_after_scan(60, None, changed=False) == 60


def test_clamp_interval_bounds() -> None:
    assert clamp_interval(0) == MIN_INTERVAL_MINUTES
    assert clamp_interval(10**6) == MAX_INTERVAL_MINUTES
    assert clamp_interval(45) == 45


def test_interval_shrunk_base_caps_current() -> None:
    # User lowers base below the current relaxed value: next scan honors it.
    assert next_interval_after_scan(30, 60, changed=False) == 30


# --- Beat dispatcher ---


@pytest.fixture(autouse=True)
def wire_dispatcher(monkeypatch: pytest.MonkeyPatch, db_factory):
    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(beat_tasks, "task_session", fake_task_session)


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(beat_tasks.celery_app, "send_task", fake_send)
    return calls


async def _make_site(db_factory, *, due: bool = True, **overrides) -> Site:
    defaults = {
        "name": "Example",
        "url": "https://example.com/",
        "auto_scan_enabled": True,
        "scan_interval_minutes": 60,
        "next_scan_at": datetime.now(UTC) - timedelta(minutes=1) if due else None,
    }
    defaults.update(overrides)
    async with db_factory() as db:
        site = Site(**defaults)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _add_ready_baseline(db_factory, site_id: uuid.UUID) -> Baseline:
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


async def _get_site(db_factory, site_id) -> Site:
    async with db_factory() as db:
        return await db.get(Site, site_id)


async def test_due_site_gets_scan_enqueued(db_factory, sent_tasks) -> None:
    site = await _make_site(db_factory)
    await _add_ready_baseline(db_factory, site.id)

    stats = await beat_tasks._dispatch_due_scans()

    assert stats["enqueued"] == 1
    assert sent_tasks[0][0] == "wardress.run_scan"
    # Schedule advanced.
    row = await _get_site(db_factory, site.id)
    assert row.next_scan_at > datetime.now(UTC).replace(tzinfo=row.next_scan_at.tzinfo)


async def test_not_due_site_untouched(db_factory, sent_tasks) -> None:
    site = await _make_site(db_factory, next_scan_at=datetime.now(UTC) + timedelta(hours=1))
    await _add_ready_baseline(db_factory, site.id)
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["due"] == 0 and sent_tasks == []


async def test_disabled_site_skipped(db_factory, sent_tasks) -> None:
    site = await _make_site(db_factory, auto_scan_enabled=False)
    await _add_ready_baseline(db_factory, site.id)
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["due"] == 0 and sent_tasks == []


async def test_no_ready_baseline_skips_but_advances(db_factory, sent_tasks) -> None:
    site = await _make_site(db_factory)  # no baseline at all
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["skipped_no_baseline"] == 1
    assert sent_tasks == []
    # Schedule still advanced — no tight loop against a broken site.
    row = await _get_site(db_factory, site.id)
    assert row.next_scan_at > datetime.now(UTC).replace(tzinfo=row.next_scan_at.tzinfo)


async def test_inflight_scan_not_duplicated(db_factory, sent_tasks) -> None:
    """Beat must respect the 409 semantics: a running scan means skip,
    with no new row created."""
    site = await _make_site(db_factory)
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        db.add(Scan(site_id=site.id, baseline_id=baseline.id, status=ScanStatus.running))
        await db.commit()

    stats = await beat_tasks._dispatch_due_scans()

    assert stats["skipped_inflight"] == 1
    assert sent_tasks == []
    async with db_factory() as db:
        count = len((await db.execute(Scan.__table__.select())).all())
    assert count == 1  # no duplicate row


async def test_stale_inflight_recovered_and_new_scan_enqueued(db_factory, sent_tasks) -> None:
    site = await _make_site(db_factory)
    baseline = await _add_ready_baseline(db_factory, site.id)
    async with db_factory() as db:
        stale = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.running,
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db.add(stale)
        await db.commit()
        stale_id = stale.id

    stats = await beat_tasks._dispatch_due_scans()

    assert stats["recovered_stale"] == 1
    assert stats["enqueued"] == 1
    async with db_factory() as db:
        old = await db.get(Scan, stale_id)
        assert old.status is ScanStatus.failed
        assert "never completed" in old.error


async def test_enqueue_failure_does_not_crash_tick(db_factory, monkeypatch) -> None:
    site = await _make_site(db_factory)
    await _add_ready_baseline(db_factory, site.id)

    def broken_send(name, args=None, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(beat_tasks.celery_app, "send_task", broken_send)
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["enqueued"] == 0  # logged, not raised
    # Site's schedule advanced; pending row will be stale-recovered later.
    row = await _get_site(db_factory, site.id)
    assert row.next_scan_at is not None


def test_dispatch_survives_db_outage(monkeypatch) -> None:
    """Sync on purpose: the task wrapper's asyncio.run must execute for
    real so the ConnectionError comes from the session, not from nesting
    event loops."""

    @asynccontextmanager
    async def broken_session():
        raise ConnectionError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(beat_tasks, "task_session", broken_session)
    result = beat_tasks.dispatch_due_scans()
    assert result == {"error": True}  # tick failed gracefully, Beat keeps going


async def test_dispatch_respects_per_tick_cap(db_factory, sent_tasks, monkeypatch) -> None:
    monkeypatch.setattr(beat_tasks, "MAX_DISPATCH_PER_TICK", 2)
    for _ in range(4):
        site = await _make_site(db_factory)
        await _add_ready_baseline(db_factory, site.id)
    stats = await beat_tasks._dispatch_due_scans()
    assert stats["enqueued"] == 2  # remainder drains on the next tick


# --- material-change scheduling (risk-based, not any-nonzero-score) ---


async def test_dynamic_noise_does_not_tighten_schedule(db_factory, monkeypatch) -> None:
    """A page whose hash flips every scan but carries ~zero risk must
    relax back toward base cadence, not stay permanently tightened."""
    from worker import scan_tasks

    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)

    site = await _make_site(db_factory, current_interval_minutes=15)
    async with db_factory() as db:
        row = await db.get(Site, site.id)
        await scan_tasks._schedule_next(db, row, changed=False)
        assert row.current_interval_minutes > 15  # relaxed, not tightened


async def test_material_change_tightens_schedule(db_factory, monkeypatch) -> None:
    from worker import scan_tasks

    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)

    site = await _make_site(db_factory)
    async with db_factory() as db:
        row = await db.get(Site, site.id)
        await scan_tasks._schedule_next(db, row, changed=True)
        assert row.current_interval_minutes == 15  # 60/4
        assert row.next_scan_at is not None
