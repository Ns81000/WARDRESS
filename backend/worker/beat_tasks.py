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
import shutil
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, Site
from app.scanning import clamp_interval, is_stale
from worker.artifacts import artifacts_root
from worker.celery_app import celery_app
from worker.db import task_session

logger = logging.getLogger(__name__)

DISPATCH_TICK_SECONDS = 60
# Never let one tick flood the queue (huge site counts drain over a few
# ticks instead; workers are the bottleneck anyway).
MAX_DISPATCH_PER_TICK = 50

# Artifact janitor (closes the Phase 1 deferral): deleted sites cascade
# their DB rows but leave page.html/screenshot.png dirs on the volume.
# A daily sweep removes directories whose owning row no longer exists.
JANITOR_INTERVAL_SECONDS = 24 * 60 * 60
JANITOR_MAX_REMOVALS_PER_RUN = 500

# Agent pending-action TTL is 10 min (guard.PENDING_TTL); sweep a little
# faster so expired confirmation cards don't linger long in the DB.
AGENT_ACTION_JANITOR_SECONDS = 5 * 60

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


async def _cleanup_orphan_artifacts() -> dict:
    """Remove artifact directories whose baseline/scan row is gone.

    Only well-formed UUID directory names directly under <root>/baselines
    and <root>/scans are considered — anything else on the volume is left
    untouched. Removals are capped per run; a large backlog drains over
    successive daily runs.
    """
    stats = {"checked": 0, "removed": 0, "errors": 0}
    root = artifacts_root()
    for kind, model in (("baselines", Baseline), ("scans", Scan)):
        kind_dir = root / kind
        if not kind_dir.is_dir():
            continue
        ids: dict[uuid_mod.UUID, str] = {}
        try:
            for entry in kind_dir.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    ids[uuid_mod.UUID(entry.name)] = entry.name
                except ValueError:
                    continue  # not ours — never touch it
        except OSError:
            logger.exception("Janitor could not list %s", kind_dir)
            stats["errors"] += 1
            continue
        if not ids:
            continue
        stats["checked"] += len(ids)

        existing: set[uuid_mod.UUID] = set()
        async with task_session() as db:
            id_list = list(ids)
            for i in range(0, len(id_list), 500):
                chunk = id_list[i : i + 500]
                rows = (await db.scalars(select(model.id).where(model.id.in_(chunk)))).all()
                existing.update(rows)

        for orphan_id in ids:
            if orphan_id in existing:
                continue
            if stats["removed"] >= JANITOR_MAX_REMOVALS_PER_RUN:
                logger.info("Janitor removal cap reached; remainder next run")
                return stats
            try:
                shutil.rmtree(kind_dir / ids[orphan_id])
                stats["removed"] += 1
            except OSError:
                logger.exception("Janitor could not remove %s/%s", kind, ids[orphan_id])
                stats["errors"] += 1
    return stats


@celery_app.task(name="wardress.cleanup_orphan_artifacts")
def cleanup_orphan_artifacts() -> dict:
    try:
        stats = asyncio.run(_cleanup_orphan_artifacts())
        if stats["removed"] or stats["errors"]:
            logger.info("Artifact janitor: %s", stats)
        return stats
    except Exception:
        # Cleanup is best-effort housekeeping — it must never crash the
        # worker or affect scanning (rule 6).
        logger.exception("Artifact janitor run failed")
        return {"error": True}


@celery_app.task(name="wardress.expire_agent_actions")
def expire_agent_actions() -> dict:
    """Flip agent pending-action rows past their TTL to `expired` so a stale
    confirmation card can never be resolved after the fact. The guard already
    re-checks expiry at confirm time, so this is bookkeeping, not a safety
    gate — and, like every janitor, best-effort: it must never crash the
    worker (rule 6)."""
    try:
        from app.agent.guard import expire_stale

        count = asyncio.run(_run_with_session(expire_stale))
        if count:
            logger.info("Agent action janitor expired %d stale pending action(s)", count)
        return {"expired": count}
    except Exception:
        logger.exception("Agent action janitor run failed")
        return {"error": True}


async def _run_with_session(fn):
    async with task_session() as db:
        return await fn(db)


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
    sender.add_periodic_task(
        JANITOR_INTERVAL_SECONDS,
        cleanup_orphan_artifacts.s(),
        name="cleanup orphan artifacts",
        expires=JANITOR_INTERVAL_SECONDS,
    )
    sender.add_periodic_task(
        AGENT_ACTION_JANITOR_SECONDS,
        expire_agent_actions.s(),
        name="expire agent pending actions",
        expires=AGENT_ACTION_JANITOR_SECONDS,
    )
