"""PROMPT-003 Audit Phase 4D repro tests — alert/remediation delivery.

These tests characterize behaviors found by the fresh-eyes delivery audit
(worker/alert_tasks.py, worker/beat_tasks.py resweep, worker/remediation_tasks.py,
app/remediation.py, app/site_icons.py). They are documentation-as-tests of
CURRENT behavior, not proposed fixes (Rule 1: diagnosis only):

- test_crash_mid_delivery_orphans_remaining_channels_permanently: the
  per-channel commit + any-delivery-row idempotence guard means a crash
  after the first channel's commit marks every later channel "done"
  without a row and without any retry path (AUDIT-4D-1).
- test_concurrent_delivery_invocations_double_send: the delivery guard is
  check-then-act, not an atomic claim — two concurrent invocations both
  pass the zero-rows check and every channel double-sends (AUDIT-4D-2).
- test_no_channel_alert_resweep_reenqueues_forever: an alert whose site
  has no active channels can never produce a delivery row, so the
  re-delivery sweep re-enqueues it every 5 minutes indefinitely
  (AUDIT-4D-6).
- test_auto_fire_cooldown_anchors_on_created_at_not_executed_at: the
  AUTO_FIRE_COOLDOWN window reads executions' created_at, not executed_at
  (the actual outbound POST stamp), so a firing delayed by queue backlog
  lands outside the intended cooldown (AUDIT-4D-5).
- test_favicon_fetch_builds_unpinned_httpx_client: the favicon resolver
  constructs a plain httpx client with no SSRFPinningTransport — every
  hop is re-gated at check time, but connect re-resolves DNS, leaving the
  check-vs-connect rebinding window the rest of the raw-httpx stack pins
  shut (AUDIT-4D-3).
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

import worker.alert_tasks as alert_tasks
import worker.beat_tasks as beat_tasks
from app.crypto import encrypt_json
from app.models import (
    Alert,
    AlertDelivery,
    NotificationChannel,
    NotificationChannelType,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
)
from app.remediation import create_executions_for_flagged_scan
from app.ssrf import SSRFBlockedError
from worker.alert_tasks import _deliver_alert


@pytest.fixture(autouse=True)
def _wire_sessions(monkeypatch: pytest.MonkeyPatch, db_factory):
    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    monkeypatch.setattr(alert_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(beat_tasks, "task_session", fake_task_session)

    # Hermetic broker: send_task must never reach the real Redis
    # (its result backend would retry-connect and stall the suite).
    sent: list = []

    def fake_send(name, args=None, **kwargs):
        sent.append((name, args))

    monkeypatch.setattr(alert_tasks.celery_app, "send_task", fake_send)
    monkeypatch.setattr(beat_tasks.celery_app, "send_task", fake_send)
    return sent



async def _flagged_alert(db_factory, *, age_minutes: int = 0) -> uuid.UUID:
    """Site + completed flagged scan + alert row (optionally aged past the
    resweep's grace period)."""
    async with db_factory() as db:
        site = Site(name="audit4d", url="https://audit4d.example.com")
        db.add(site)
        await db.flush()
        scan = Scan(
            site_id=site.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
            finished_at=datetime.now(UTC),
        )
        db.add(scan)
        await db.flush()
        alert = Alert(site_id=site.id, scan_id=scan.id, risk_score=0.9)
        if age_minutes:
            alert.created_at = datetime.now(UTC) - timedelta(minutes=age_minutes)
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        return alert.id


async def _add_channel(db_factory, name: str) -> None:
    async with db_factory() as db:
        db.add(
            NotificationChannel(
                type=NotificationChannelType.apprise_url,
                name=name,
                config_encrypted=encrypt_json({"url": f"json://{name}/path", "kind": name}),
            )
        )
        await db.commit()


# --- AUDIT-4D-1: mid-delivery crash orphans every later channel ------------


async def test_crash_mid_delivery_orphans_remaining_channels_permanently(
    db_factory, monkeypatch
):
    """A hard death (kill / DB hiccup / unexpected exception) after the
    first channel's per-channel commit leaves later channels with NO row:
    the any-row-exists guard reports "already-delivered" forever, and the
    re-delivery sweep only re-enqueues alerts with zero delivery rows.
    Those channels are silently and permanently undelivered — and invisible
    (no failed row, nothing in the dashboard)."""
    alert_id = await _flagged_alert(db_factory)
    await _add_channel(db_factory, "first")
    await _add_channel(db_factory, "second")

    async def crashing_deliver(channel_type, config, content, *, smtp, telegram):
        if config.get("url") == "json://second/path":
            raise RuntimeError("worker died mid-delivery-loop")
        return True, "sent"

    monkeypatch.setattr(alert_tasks, "deliver_to_channel", crashing_deliver)
    # The crash propagates out of the task body; the Celery wrapper
    # (deliver_alert) contains it and returns "error" — the message is
    # then acked with no redelivery, which is what makes the loss final.
    with pytest.raises(RuntimeError, match="worker died mid-delivery-loop"):
        await _deliver_alert(alert_id)

    async with db_factory() as db:
        rows = (await db.scalars(select(AlertDelivery))).all()
        assert [r.channel_name for r in rows] == ["first"]
        assert rows[0].status.value == "sent"

    # Redelivery is a no-op despite the second channel never being attempted:
    assert await _deliver_alert(alert_id) == "already-delivered"
    # And the sweep re-enqueues only alerts with ZERO delivery rows:
    stats = await beat_tasks._resweep_undelivered()
    assert stats["alerts_reenqueued"] == 0
    async with db_factory() as db:
        rows = (await db.scalars(select(AlertDelivery))).all()
        assert [r.channel_name for r in rows] == ["first"]  # unchanged forever


# --- AUDIT-4D-2: check-then-act delivery guard double-sends -----------------


async def test_concurrent_delivery_invocations_double_send(db_factory, monkeypatch):
    """The idempotence guard is a plain SELECT, not an atomic claim: two
    concurrent invocations (e.g. the original message plus a resweep
    re-enqueue, or a broker duplicate) both observe zero delivery rows and
    both POST to every channel. The remediation path solved this with the
    conditional-UPDATE claim; delivery has no equivalent."""
    alert_id = await _flagged_alert(db_factory)
    await _add_channel(db_factory, "solo")

    async def slow_deliver(channel_type, config, content, *, smtp, telegram):
        await asyncio.sleep(0.1)  # widen the guard's check-then-act window
        return True, "sent"

    monkeypatch.setattr(alert_tasks, "deliver_to_channel", slow_deliver)
    results = await asyncio.gather(*[_deliver_alert(alert_id) for _ in range(2)])
    assert all("sent=1" in r for r in results)
    async with db_factory() as db:
        rows = (await db.scalars(select(AlertDelivery))).all()
        assert len(rows) == 2  # the single channel was POSTed twice


# --- AUDIT-4D-6: channel-less alerts are re-swept forever ------------------


async def test_no_channel_alert_resweep_reenqueues_forever(db_factory):
    """An alert whose site has no active channels returns "no-channels"
    without writing any delivery row, so the sweep's zero-rows predicate
    matches it on every run, forever — unbounded enqueue churn for an
    alert that can never be delivered."""
    alert_id = await _flagged_alert(db_factory, age_minutes=10)

    stats1 = await beat_tasks._resweep_undelivered()
    assert stats1["alerts_reenqueued"] == 1
    assert await _deliver_alert(alert_id) == "no-channels"
    async with db_factory() as db:
        assert (await db.scalars(select(AlertDelivery))).all() == []
    stats2 = await beat_tasks._resweep_undelivered()
    assert stats2["alerts_reenqueued"] == 1  # matches again, every sweep
    async with db_factory() as db:
        assert (await db.scalars(select(AlertDelivery))).all() == []




# --- AUDIT-4D-5: cooldown anchored to created_at, not executed_at ----------


async def test_auto_fire_cooldown_anchors_on_created_at_not_executed_at(db_factory):
    """The AUTO_FIRE_COOLDOWN window (30 min) reads past executions'
    created_at. An execution that was created long ago but only actually
    POSTed recently (queue backlog / stale reclaim) does not hold the
    cooldown: a fresh flagged scan enqueues a new auto firing even though
    the receiver was hit minutes ago."""
    async with db_factory() as db:
        site = Site(name="cooldown", url="https://cooldown.example.com")
        db.add(site)
        await db.flush()
        hook = RemediationHook(
            site_id=site.id,
            name="auto-hook",
            action_type="custom_webhook",
            trigger_threshold=0.5,
            webhook_url_encrypted=encrypt_json({"u": "x"}),  # never decrypted here
            requires_manual_confirm=False,
        )
        db.add(hook)
        await db.flush()
        prior_scan = Scan(
            site_id=site.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(prior_scan)
        await db.flush()
        db.add(
            RemediationExecution(
                hook_id=hook.id,
                site_id=site.id,
                scan_id=prior_scan.id,
                status=RemediationExecutionStatus.succeeded,
                hook_name="auto-hook",
                action_type="custom_webhook",
                risk_score=0.9,
                # Row created 40 min ago, but the actual POST only landed
                # 5 minutes ago (delayed by backlog / stale reclaim):
                created_at=datetime.now(UTC) - timedelta(minutes=40),
                executed_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        fresh_scan = Scan(
            site_id=site.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(fresh_scan)
        await db.commit()

    async with db_factory() as db:
        ready = await create_executions_for_flagged_scan(db, fresh_scan)

    # The last POST was 5 minutes ago (< AUTO_FIRE_COOLDOWN_MINUTES), yet the
    # new firing is queued for immediate unattended execution, not parked:
    assert len(ready) == 1
    async with db_factory() as db:
        row = await db.get(RemediationExecution, ready[0])
        assert row.status is RemediationExecutionStatus.queued


# --- AUDIT-4D-3: favicon fetch rides an unpinned httpx client --------------


async def test_favicon_fetch_builds_unpinned_httpx_client(monkeypatch):
    """attempt_favicon_fetch constructs its own httpx.AsyncClient with no
    SSRFPinningTransport. Each hop is re-gated at check time
    (assert_url_allowed resolves DNS), but the transport resolves DNS a
    second time at connect — the check-vs-connect rebinding window that
    worker/probe.py and app/remediation.py close with the pinning
    transport. Characterized here as documentation; no fix applied."""
    recorded_kwargs: list[dict] = []

    class _RecordingClient:
        def __init__(self, **kwargs):
            recorded_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            raise httpx.ConnectError("offline")  # pragma: no cover

    import app.site_icons as site_icons

    async def refuse_all(url, allow_private_networks):
        raise SSRFBlockedError("hermetic: no network in unit tests")

    monkeypatch.setattr(site_icons.httpx, "AsyncClient", _RecordingClient)
    monkeypatch.setattr(site_icons, "_gate_url", refuse_all)

    site = Site(name="icons", url="https://icons.example.com")
    with pytest.raises(SSRFBlockedError):
        await site_icons.attempt_favicon_fetch(site)

    assert recorded_kwargs, "client must be constructed before the first gate"
    for kwargs in recorded_kwargs:
        assert "transport" not in kwargs  # no SSRFPinningTransport on this path
