"""Celery scan tasks — Phase 1: baseline capture and layer-1 scan.

Design rules (master prompt rule 6): an unreachable site, a timeout, or a
blocked URL must mark the row failed with a user-safe error and exit
cleanly — never crash the worker, never leave a row stuck in
pending/capturing/running.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, Site
from app.ssrf import SSRFBlockedError
from worker.artifacts import store_artifacts
from worker.celery_app import celery_app
from worker.db import task_session
from worker.fetcher import FetchError, fetch_page
from worker.hashing import content_sha256, layer1_hash_diff

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _capture_baseline(baseline_id: uuid.UUID) -> str:
    async with task_session() as db:
        baseline = await db.scalar(select(Baseline).where(Baseline.id == baseline_id))
        if baseline is None:
            return "baseline-row-missing"
        if baseline.status not in (BaselineStatus.pending, BaselineStatus.capturing):
            return f"baseline-already-{baseline.status.value}"
        site = await db.scalar(select(Site).where(Site.id == baseline.site_id))
        if site is None:
            baseline.status = BaselineStatus.failed
            baseline.error = "Site was deleted before capture started"
            await db.commit()
            return "site-missing"

        baseline.status = BaselineStatus.capturing
        await db.commit()

        try:
            result = await fetch_page(site.url, allow_private_networks=site.allow_private_networks)
        except (FetchError, SSRFBlockedError) as exc:
            baseline.status = BaselineStatus.failed
            baseline.error = str(exc)
            await db.commit()
            logger.warning("Baseline %s failed: %s", baseline_id, exc)
            return "failed"

        # A baseline is the trust anchor for every future verdict. An HTTP
        # error page (site down, rate-limited, auth-walled) must never be
        # stored as "trusted" — it would poison all later comparisons.
        # Scans are different: fetching an error page during a scan is a
        # legitimate scan result and still completes.
        if result.http_status is not None and result.http_status >= 400:
            baseline.status = BaselineStatus.failed
            baseline.error = (
                f"Site responded with HTTP {result.http_status} — a trusted baseline "
                "needs a healthy response. Try again when the site is up."
            )
            await db.commit()
            logger.warning(
                "Baseline %s refused: target returned HTTP %s", baseline_id, result.http_status
            )
            return "failed"

        html_rel, shot_rel = store_artifacts(
            "baselines", str(baseline.id), result.html, result.screenshot
        )

        # Demote any previous current baseline, then promote this one —
        # single transaction, and the partial unique index backstops races.
        await db.execute(
            update(Baseline)
            .where(Baseline.site_id == site.id, Baseline.is_current.is_(True))
            .values(is_current=False)
        )
        baseline.content_hash = content_sha256(result.html)
        baseline.html_path = html_rel
        baseline.screenshot_path = shot_rel
        baseline.capture_meta = {
            "final_url": result.final_url,
            "http_status": result.http_status,
            "headers": result.headers,
        }
        baseline.status = BaselineStatus.ready
        baseline.is_current = True
        baseline.captured_at = _utcnow()
        baseline.error = None
        await db.commit()
        return "ready"


async def _run_scan(scan_id: uuid.UUID) -> str:
    async with task_session() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        if scan is None:
            return "scan-row-missing"
        if scan.status not in (ScanStatus.pending, ScanStatus.running):
            return f"scan-already-{scan.status.value}"
        site = await db.scalar(select(Site).where(Site.id == scan.site_id))
        baseline = (
            await db.scalar(select(Baseline).where(Baseline.id == scan.baseline_id))
            if scan.baseline_id
            else None
        )
        if site is None or baseline is None or baseline.content_hash is None:
            scan.status = ScanStatus.failed
            scan.error = "Site or its baseline disappeared before the scan ran"
            scan.finished_at = _utcnow()
            await db.commit()
            return "missing-prereqs"

        scan.status = ScanStatus.running
        scan.started_at = _utcnow()
        await db.commit()

        try:
            result = await fetch_page(site.url, allow_private_networks=site.allow_private_networks)
        except (FetchError, SSRFBlockedError) as exc:
            scan.status = ScanStatus.failed
            scan.verdict = ScanVerdict.error
            scan.error = str(exc)
            scan.finished_at = _utcnow()
            await db.commit()
            logger.warning("Scan %s failed: %s", scan_id, exc)
            return "failed"

        html_rel, shot_rel = store_artifacts("scans", str(scan.id), result.html, result.screenshot)
        current_hash = content_sha256(result.html)
        layer1 = layer1_hash_diff(baseline.content_hash, current_hash)

        scan.content_hash = current_hash
        scan.html_path = html_rel
        scan.screenshot_path = shot_rel
        scan.layer_scores = {"layer1_hash": layer1}
        scan.verdict = ScanVerdict.clean if layer1["score"] == 0.0 else ScanVerdict.changed
        scan.status = ScanStatus.completed
        scan.finished_at = _utcnow()
        scan.error = None
        await db.commit()
        return scan.verdict.value


async def _mark_baseline_failed(baseline_id: uuid.UUID, message: str) -> None:
    """Best-effort: record an unexpected failure on the row so it never
    sits in pending/capturing forever (which would 409-block rebaseline)."""
    async with task_session() as db:
        baseline = await db.scalar(select(Baseline).where(Baseline.id == baseline_id))
        if baseline is not None and baseline.status in (
            BaselineStatus.pending,
            BaselineStatus.capturing,
        ):
            baseline.status = BaselineStatus.failed
            baseline.error = message
            await db.commit()


async def _mark_scan_failed(scan_id: uuid.UUID, message: str) -> None:
    async with task_session() as db:
        scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
        if scan is not None and scan.status in (ScanStatus.pending, ScanStatus.running):
            scan.status = ScanStatus.failed
            scan.verdict = ScanVerdict.error
            scan.error = message
            scan.finished_at = _utcnow()
            await db.commit()


@celery_app.task(name="wardress.capture_baseline")
def capture_baseline(baseline_id: str) -> str:
    """Fetch a site and store its trusted baseline (HTML, screenshot,
    SHA-256 of normalized content)."""
    try:
        parsed = uuid.UUID(baseline_id)
    except ValueError:
        logger.error("capture_baseline got a non-UUID id: %r", baseline_id)
        return "bad-id"
    try:
        return asyncio.run(_capture_baseline(parsed))
    except Exception:
        # Expected failure modes (unreachable site, timeout, blocked URL)
        # are handled inside _capture_baseline; anything landing here is
        # unexpected (disk full, DB outage mid-task, soft time limit).
        # The row must still leave the in-flight state.
        logger.exception("Unexpected error capturing baseline %s", baseline_id)
        try:
            asyncio.run(
                _mark_baseline_failed(parsed, "Capture failed unexpectedly — see worker logs")
            )
        except Exception:
            logger.exception("Could not mark baseline %s failed", baseline_id)
        return "error"


@celery_app.task(name="wardress.run_scan")
def run_scan(scan_id: str) -> str:
    """Re-fetch a site and compute detection layer 1 (hash diff) against
    its current baseline. Layers 2-9 attach here in Phase 2."""
    try:
        parsed = uuid.UUID(scan_id)
    except ValueError:
        logger.error("run_scan got a non-UUID id: %r", scan_id)
        return "bad-id"
    try:
        return asyncio.run(_run_scan(parsed))
    except Exception:
        logger.exception("Unexpected error running scan %s", scan_id)
        try:
            asyncio.run(_mark_scan_failed(parsed, "Scan failed unexpectedly — see worker logs"))
        except Exception:
            logger.exception("Could not mark scan %s failed", scan_id)
        return "error"
