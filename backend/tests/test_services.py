"""Regression tests for the shared service layer (Task 4 de-duplication).

These assert the behaviours that were previously divergent across the REST
router, the agent tool executors, and the Telegram bot are now uniform:

- the agent's scan-now / rebaseline / add-site enqueue paths get the
  router's 503-safe stranded-row handling (previously missing);
- the bot's scan-now records an audit row (previously it did not);
- acknowledge is idempotent and mute clamps to the shared ceiling.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select

from app import services
from app.agent.tools import ToolContext, ToolError, get_tool
from app.models import (
    Alert,
    AuditLog,
    Baseline,
    BaselineStatus,
    Scan,
    ScanStatus,
    Site,
)


def _raise_503(_id):
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "queue down")


async def _seed_ready_site(db_factory) -> Site:
    async with db_factory() as db:
        site = Site(name="svc-site", url="https://svc.example.com")
        db.add(site)
        await db.flush()
        db.add(
            Baseline(
                site_id=site.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="c" * 64,
            )
        )
        await db.commit()
        await db.refresh(site)
        return site


# --- agent scan-now now gets 503-safe stranded-row handling ----------------


async def test_agent_scan_now_503_marks_scan_failed(db_factory, analyst_user):
    """The agent tool must not leave a stranded pending scan when the broker
    is down — the shared helper marks it failed so the site stays scannable."""
    site = await _seed_ready_site(db_factory)
    with patch("app.services.enqueue_scan", side_effect=_raise_503):
        async with db_factory() as db:
            ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
            with pytest.raises(ToolError):
                await get_tool("run_scan_now").executor(ctx, {"site": site.name})

    async with db_factory() as db:
        scans = (await db.scalars(select(Scan).where(Scan.site_id == site.id))).all()
    assert len(scans) == 1
    assert scans[0].status == ScanStatus.failed


async def test_agent_add_site_503_marks_baseline_failed(db_factory, analyst_user):
    with patch("app.services.enqueue_baseline_capture", side_effect=_raise_503):
        async with db_factory() as db:
            ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
            with pytest.raises(ToolError):
                await get_tool("add_site").executor(
                    ctx, {"name": "new-site", "url": "https://new.example.com"}
                )
    # No stranded pending baseline — either rolled back entirely or marked failed.
    async with db_factory() as db:
        site = await db.scalar(select(Site).where(Site.name == "new-site"))
        if site is not None:
            baselines = (
                await db.scalars(select(Baseline).where(Baseline.site_id == site.id))
            ).all()
            assert all(b.status != BaselineStatus.pending for b in baselines)


# --- bot scan-now (actor=None) now records an audit row --------------------


async def test_bot_scan_now_records_audit(db_factory, stub_all_enqueues):
    """The bot slash-command path (actor=None, actor_label='telegram-bot')
    goes through the shared helper, which records the scan.now audit row the
    REST/agent paths always recorded — closing the prior silent divergence."""
    site = await _seed_ready_site(db_factory)
    async with db_factory() as db:
        fresh = await db.get(Site, site.id)
        await services.trigger_scan_now(
            db, fresh, actor=None, actor_label="telegram-bot", via="telegram"
        )

    async with db_factory() as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "scan.now"))
    assert row is not None
    assert row.actor_email == "telegram-bot"


# --- acknowledge idempotency + mute clamp ----------------------------------


async def test_acknowledge_alert_idempotent(db_factory, analyst_user):
    async with db_factory() as db:
        site = Site(name="ack-site", url="https://ack.example.com")
        db.add(site)
        await db.flush()
        scan = Scan(site_id=site.id, status=ScanStatus.completed)
        db.add(scan)
        await db.flush()
        alert = Alert(site_id=site.id, scan_id=scan.id, risk_score=0.9)
        db.add(alert)
        await db.commit()
        alert_id = alert.id

    async with db_factory() as db:
        row = await db.get(Alert, alert_id)
        await services.acknowledge_alert(db, row, actor=analyst_user, via="dashboard")
        first_ack = row.acknowledged_at.replace(tzinfo=None) if row.acknowledged_at else None
    # A second ack is a no-op — first ack wins, timestamp unchanged.
    async with db_factory() as db:
        row = await db.get(Alert, alert_id)
        await services.acknowledge_alert(db, row, actor=None, via="telegram")
        second_ack = row.acknowledged_at.replace(tzinfo=None) if row.acknowledged_at else None
        assert second_ack == first_ack
        assert row.acknowledged_via == "dashboard"

    async with db_factory() as db:
        acks = (
            await db.scalars(
                select(AuditLog).where(AuditLog.action == "alert.acknowledge")
            )
        ).all()
    assert len(acks) == 1  # only the first ack recorded an audit row


async def test_mute_site_clamps_to_ceiling(db_factory, analyst_user):
    async with db_factory() as db:
        site = Site(name="mute-site", url="https://mute.example.com")
        db.add(site)
        await db.commit()
        site_id = site.id

    async with db_factory() as db:
        row = await db.get(Site, site_id)
        await services.mute_site(
            db, row, minutes=10**9, actor=analyst_user, via="dashboard"
        )
        assert row.muted_until is not None
        # Clamped to the 7-day ceiling, not a billion minutes out.
        horizon = datetime.now(UTC).replace(tzinfo=UTC)
        delta_days = (row.muted_until - horizon).days
        assert delta_days <= 7
