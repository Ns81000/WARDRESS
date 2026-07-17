"""Celery scan tasks — Phase 2: baseline capture with metadata probe and
the full nine-layer scan pipeline.

Design rules (master prompt rule 6): an unreachable site, a timeout, or a
blocked URL must mark the row failed with a user-safe error and exit
cleanly — never crash the worker, never leave a row stuck in
pending/capturing/running.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.models import (
    Baseline,
    BaselineStatus,
    Scan,
    ScanFinding,
    ScanStatus,
    ScanVerdict,
    Site,
    SuppressionRule,
)
from app.scanning import MATERIAL_CHANGE_RISK, next_interval_after_scan
from app.ssrf import SSRFBlockedError
from worker.artifacts import read_artifact_bytes, read_artifact_text, store_artifacts
from worker.celery_app import celery_app
from worker.db import task_session
from worker.detection.pipeline import LAYERS, run_detection
from worker.detection.suppress import Suppression, build_suppression
from worker.detection.types import PageData, ScanPageData
from worker.fetcher import FetchError, fetch_page
from worker.hashing import content_sha256
from worker.probe import probe_site

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

        # Metadata probe (layer 6 inputs): TLS cert, robots.txt, full
        # security-relevant header map. Individually fail-safe.
        probe = await probe_site(site.url, allow_private_networks=site.allow_private_networks)

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
            # Phase 2 layer-6 anchors:
            "probe_headers": probe.headers,
            "tls": probe.tls,
            "robots_txt": probe.robots_txt,
        }
        baseline.status = BaselineStatus.ready
        baseline.is_current = True
        baseline.captured_at = _utcnow()
        baseline.error = None
        await db.commit()
        return "ready"


def _baseline_page_data(baseline: Baseline) -> PageData:
    """Materialize the baseline side of the comparison from stored rows +
    artifacts. Missing artifacts degrade (empty html/screenshot) — the
    pipeline records the degradation per layer instead of failing."""
    meta = baseline.capture_meta or {}
    return PageData(
        html=read_artifact_text(baseline.html_path) or "",
        screenshot=read_artifact_bytes(baseline.screenshot_path) or b"",
        final_url=meta.get("final_url") or "",
        http_status=meta.get("http_status"),
        # Layer 6 compares full header maps only: the probe's capture, not
        # the fetcher's curated 4-header subset — comparing full-vs-subset
        # would report every security header as "removed". A Phase 1-era
        # baseline without probe_headers yields {} and the layer skips the
        # header comparison with a note.
        headers=meta.get("probe_headers") or {},
        tls=meta.get("tls"),
        robots_txt=meta.get("robots_txt"),
        content_hash=baseline.content_hash or "",
    )


async def _persist_findings(db, scan: Scan, results: dict[str, dict]) -> None:
    """One scan_findings row per layer (skips included). Idempotent under
    acks_late redelivery: clear-and-rewrite inside the caller's txn."""
    await db.execute(delete(ScanFinding).where(ScanFinding.scan_id == scan.id))
    for number, key in LAYERS:
        result = results.get(key)
        if result is None:
            continue
        db.add(
            ScanFinding(
                scan_id=scan.id,
                layer=number,
                layer_key=key,
                score=result.get("score"),
                skipped=bool(result.get("skipped")),
                evidence=result.get("evidence"),
            )
        )


async def _load_suppression(db, site_id: uuid.UUID) -> Suppression:
    """Site's §5 suppression rules as pipeline plain-data. Never raises —
    a failure to load rules degrades to 'no suppression' (the scan must
    run; the worst outcome is a suppressible false positive)."""
    try:
        rows = (
            await db.scalars(select(SuppressionRule).where(SuppressionRule.site_id == site_id))
        ).all()
        return build_suppression([(r.type.value, r.value) for r in rows])
    except Exception:
        logger.exception("Could not load suppression rules for site %s", site_id)
        return Suppression()


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
            await _schedule_next(db, site, changed=False)
            logger.warning("Scan %s failed: %s", scan_id, exc)
            return "failed"

        probe = await probe_site(site.url, allow_private_networks=site.allow_private_networks)

        html_rel, shot_rel = store_artifacts("scans", str(scan.id), result.html, result.screenshot)
        current_hash = content_sha256(result.html)

        baseline_page = _baseline_page_data(baseline)
        current_page = ScanPageData(
            html=result.html,
            screenshot=result.screenshot,
            final_url=result.final_url,
            http_status=result.http_status,
            # Probe headers only (full map or {}): never the fetcher's
            # curated subset — see _baseline_page_data.
            headers=probe.headers,
            tls=probe.tls,
            robots_txt=probe.robots_txt,
            content_hash=current_hash,
            ua_variants=probe.ua_variants,
        )

        # The nine layers run in a worker thread: they are CPU-bound
        # (lxml/SSIM/MiniLM) and must not stall the event loop's DB
        # heartbeats under asyncio.run.
        suppression = await _load_suppression(db, site.id)
        results = await asyncio.to_thread(run_detection, baseline_page, current_page, suppression)

        fusion = results["layer9_fusion"]
        risk = float(fusion["score"] or 0.0)
        changed = any(
            (r.get("score") or 0.0) > 0.0
            for k, r in results.items()
            if k != "layer9_fusion" and not r.get("skipped")
        )
        flagged = risk >= site.flag_threshold

        scan.content_hash = current_hash
        scan.html_path = html_rel
        scan.screenshot_path = shot_rel
        # Compact summary for the scan table; full evidence in findings.
        scan.layer_scores = {
            k: {"score": r.get("score"), "skipped": bool(r.get("skipped"))}
            for k, r in results.items()
        }
        scan.risk_score = risk
        if flagged:
            scan.verdict = ScanVerdict.flagged
        elif changed:
            scan.verdict = ScanVerdict.changed
        else:
            scan.verdict = ScanVerdict.clean
        scan.status = ScanStatus.completed
        scan.finished_at = _utcnow()
        scan.error = None
        await _persist_findings(db, scan, results)
        await db.commit()

        # Scheduling tightens on *material* change (risk-based), not on
        # any nonzero layer score — a dynamic page whose hash flips every
        # scan must still relax back to its base cadence.
        await _schedule_next(db, site, changed=flagged or risk >= MATERIAL_CHANGE_RISK)
        return scan.verdict.value


async def _schedule_next(db, site: Site, *, changed: bool) -> None:
    """Adaptive rescheduling (§11): tighten after a change, relax while
    stable. Never raises — scheduling is best-effort bookkeeping."""
    try:
        if not site.auto_scan_enabled:
            return
        interval = next_interval_after_scan(
            site.scan_interval_minutes, site.current_interval_minutes, changed
        )
        site.current_interval_minutes = interval
        site.next_scan_at = _utcnow() + timedelta(minutes=interval)
        await db.commit()
    except Exception:
        logger.exception("Could not update schedule for site %s", site.id)


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
    SHA-256 of normalized content, TLS/robots/header metadata)."""
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
    """Re-fetch a site and run all nine detection layers (§5) against its
    current baseline, storing per-layer evidence and the fused risk."""
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
