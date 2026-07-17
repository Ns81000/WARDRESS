"""Celery Beat dispatcher — recurring scans with adaptive intervals.

One periodic task (`wardress.dispatch_due_scans`, every 60 s) polls for
sites whose `next_scan_at` is due and enqueues a scan for each, applying
exactly the same rules as the API's scan-now endpoint:

- no ready current baseline -> push the site's schedule forward and skip
  (a site mid-rebaseline is not scanned against a stale trust anchor);
- a genuine in-flight scan -> skip WITHOUT creating a row (Beat must
  respect the 409 semantics, never pile up duplicates);
- a stale in-flight row (worker killed too hard for its failure handler)
  -> fail it and proceed, same as the API's stale-row recovery.

The dispatcher advances `next_scan_at` *before* enqueueing, so even a
lost enqueue can only delay a site by one interval, never duplicate it.
Completed scans reschedule themselves adaptively in scan_tasks; the
dispatcher's advance is the safety net for scans that never complete.

Beat itself stays dumb (fixed 60 s tick): adaptive logic lives in DB
state, so a Beat restart loses nothing and a single Beat instance is the
only scheduler-side requirement (per the Celery docs).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, Site
from app.scanning import clamp_interval, is_stale
from worker.celery_app import celery_app
from worker.db import task_session

logger = logging.getLogger(__name__)

DISPATCH_TICK_SECONDS = 60
# Never let one tick flood the queue (huge site counts drain over a few
# ticks instead; workers are the bottleneck anyway).
MAX_DISPATCH_PER_TICK = 50

# Redis heartbeat key the health page reads (Phase 5 §7): proof that
# Beat is scheduling AND a worker is executing (the tick runs on a
# worker). Written best-effort — a Redis blip must not fail the tick.
DISPATCH_HEARTBEAT_KEY = "wardress:heartbeat:dispatch"
HEARTBEAT_TTL_SECONDS = DISPATCH_TICK_SECONDS * 10


def _write_heartbeat() -> None:
    try:
        import os

        import redis

        client = redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"), socket_connect_timeout=2
        )
        try:
            client.set(
                DISPATCH_HEARTBEAT_KEY,
                datetime.now(UTC).isoformat(),
                ex=HEARTBEAT_TTL_SECONDS,
            )
        finally:
            client.close()
    except Exception:
        logger.debug("Could not write dispatch heartbeat", exc_info=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _dispatch_due_scans() -> dict:
    """Returns counters for observability/tests."""
    stats = {
        "due": 0,
        "enqueued": 0,
        "skipped_inflight": 0,
        "skipped_no_baseline": 0,
        "recovered_stale": 0,
    }
    async with task_session() as db:
        now = _utcnow()
        due_sites = (
            await db.scalars(
                select(Site)
                .where(
                    Site.is_active.is_(True),
                    Site.auto_scan_enabled.is_(True),
                    Site.next_scan_at.is_not(None),
                    Site.next_scan_at <= now,
                )
                .order_by(Site.next_scan_at)
                .limit(MAX_DISPATCH_PER_TICK)
            )
        ).all()
        stats["due"] = len(due_sites)

        for site in due_sites:
            interval = clamp_interval(site.current_interval_minutes or site.scan_interval_minutes)
            # Advance the schedule first: a crash below can only delay
            # this site by one interval, never tight-loop or duplicate it.
            site.next_scan_at = now + timedelta(minutes=interval)
            await db.commit()

            baseline = await db.scalar(
                select(Baseline).where(
                    Baseline.site_id == site.id,
                    Baseline.is_current.is_(True),
                    Baseline.status == BaselineStatus.ready,
                )
            )
            if baseline is None:
                stats["skipped_no_baseline"] += 1
                logger.info("Auto-scan skipped for %s: no ready baseline", site.id)
                continue

            in_flight = await db.scalar(
                select(Scan).where(
                    Scan.site_id == site.id,
                    Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
                )
            )
            if in_flight is not None:
                if is_stale(in_flight.created_at):
                    in_flight.status = ScanStatus.failed
                    in_flight.verdict = ScanVerdict.error
                    in_flight.error = "Scan never completed — superseded by a scheduled scan"
                    in_flight.finished_at = now
                    stats["recovered_stale"] += 1
                else:
                    # Same semantics as the API's 409: never pile up.
                    stats["skipped_inflight"] += 1
                    continue

            scan = Scan(site_id=site.id, baseline_id=baseline.id, status=ScanStatus.pending)
            db.add(scan)
            await db.commit()
            try:
                celery_app.send_task("wardress.run_scan", args=[str(scan.id)])
                stats["enqueued"] += 1
            except Exception:
                # Redis hiccup: the pending row will be recovered as stale
                # by the next due tick (or the API) — log and continue.
                logger.exception("Could not enqueue scheduled scan %s", scan.id)
    return stats


@celery_app.task(name="wardress.dispatch_due_scans")
def dispatch_due_scans() -> dict:
    try:
        stats = asyncio.run(_dispatch_due_scans())
        if stats["due"]:
            logger.info("Scan dispatch tick: %s", stats)
        _write_heartbeat()
        return stats
    except Exception:
        # The dispatcher must survive DB outages — Beat keeps ticking and
        # the next tick retries.
        logger.exception("Scan dispatch tick failed")
        return {"error": True}


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs) -> None:
    sender.add_periodic_task(
        DISPATCH_TICK_SECONDS,
        dispatch_due_scans.s(),
        name="dispatch due scans",
        # A tick that can't be delivered promptly is worthless — drop it
        # rather than letting a Redis backlog burst-fire stale ticks.
        expires=DISPATCH_TICK_SECONDS * 2,
    )
