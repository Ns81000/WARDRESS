"""Site CRUD + baseline/scan endpoints (§7, extended for Phase 2)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import CurrentUser
from app.explain import ExplainError, explain_scan
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
from app.scanning import clamp_interval, is_stale
from app.schemas import (
    BaselineOut,
    ExplainResponse,
    ScanDetailOut,
    ScanFindingOut,
    ScanOut,
    ScanPage,
    SiteCreate,
    SiteDetailOut,
    SiteOut,
    SiteUpdate,
    SuppressionRuleCreate,
    SuppressionRuleOut,
)
from app.ssrf import SSRFBlockedError, assert_url_allowed
from app.tasks import enqueue_baseline_capture, enqueue_scan

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _is_stale(created_at: datetime) -> bool:
    return is_stale(created_at)


async def _get_site_or_404(db: AsyncSession, site_id: uuid.UUID) -> Site:
    site = await db.scalar(select(Site).where(Site.id == site_id))
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


async def _current_baseline(db: AsyncSession, site_id: uuid.UUID) -> Baseline | None:
    return await db.scalar(
        select(Baseline).where(Baseline.site_id == site_id, Baseline.is_current.is_(True))
    )


@router.post("", response_model=SiteDetailOut, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailOut:
    url = str(body.url)
    try:
        # SSRF policy check at creation time gives the user immediate
        # feedback; the worker re-validates before every actual fetch.
        # Runs in a thread: the check resolves DNS, which would otherwise
        # block the event loop for up to the resolver timeout.
        await asyncio.to_thread(
            assert_url_allowed, url, allow_private_networks=body.allow_private_networks
        )
    except SSRFBlockedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    site = Site(
        name=body.name,
        url=url,
        created_by=user.id,
        allow_private_networks=body.allow_private_networks,
        flag_threshold=body.flag_threshold,
        auto_scan_enabled=body.auto_scan_enabled,
        scan_interval_minutes=clamp_interval(body.scan_interval_minutes),
    )
    db.add(site)
    await db.flush()
    # First auto-scan due one interval after creation (the baseline
    # capture below anchors "now"); manual scan-now works immediately.
    if site.auto_scan_enabled:
        site.next_scan_at = datetime.now(UTC) + timedelta(minutes=site.scan_interval_minutes)

    # Kick off the initial baseline capture immediately.
    baseline = Baseline(site_id=site.id, status=BaselineStatus.pending, is_current=False)
    db.add(baseline)
    await db.commit()
    enqueue_baseline_capture(baseline.id)

    return SiteDetailOut(
        **SiteOut.model_validate(site).model_dump(),
        baseline_id=baseline.id,
        baseline_status=baseline.status,
    )


@router.get("", response_model=list[SiteDetailOut])
async def list_sites(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SiteDetailOut]:
    sites = (await db.scalars(select(Site).order_by(Site.created_at.desc()))).all()
    out = []
    for site in sites:
        baseline = await _current_baseline(db, site.id)
        if baseline is None:
            # No current baseline yet — surface the newest attempt instead
            # so pending/failed captures are visible in the list.
            baseline = await db.scalar(
                select(Baseline)
                .where(Baseline.site_id == site.id)
                .order_by(Baseline.created_at.desc())
                .limit(1)
            )
        out.append(
            SiteDetailOut(
                **SiteOut.model_validate(site).model_dump(),
                baseline_id=baseline.id if baseline else None,
                baseline_status=baseline.status if baseline else None,
                baseline_captured_at=baseline.captured_at if baseline else None,
                baseline_error=baseline.error if baseline else None,
            )
        )
    return out


@router.get("/{site_id}", response_model=SiteDetailOut)
async def get_site(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailOut:
    site = await _get_site_or_404(db, site_id)
    baseline = await _current_baseline(db, site.id)
    if baseline is None:
        baseline = await db.scalar(
            select(Baseline)
            .where(Baseline.site_id == site.id)
            .order_by(Baseline.created_at.desc())
            .limit(1)
        )
    return SiteDetailOut(
        **SiteOut.model_validate(site).model_dump(),
        baseline_id=baseline.id if baseline else None,
        baseline_status=baseline.status if baseline else None,
        baseline_captured_at=baseline.captured_at if baseline else None,
        baseline_error=baseline.error if baseline else None,
    )


@router.patch("/{site_id}", response_model=SiteDetailOut)
async def update_site(
    site_id: uuid.UUID,
    body: SiteUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailOut:
    """Per-site detection/scheduling settings (§5 threshold, §11 adaptive
    interval). Name/URL edits are deliberately excluded — a different URL
    means a different trust anchor, i.e. a new site."""
    site = await _get_site_or_404(db, site_id)
    if body.flag_threshold is not None:
        site.flag_threshold = body.flag_threshold
    if body.auto_scan_enabled is not None:
        site.auto_scan_enabled = body.auto_scan_enabled
        if not body.auto_scan_enabled:
            site.next_scan_at = None
        elif site.next_scan_at is None:
            site.next_scan_at = datetime.now(UTC) + timedelta(
                minutes=clamp_interval(site.scan_interval_minutes)
            )
    if body.scan_interval_minutes is not None:
        site.scan_interval_minutes = clamp_interval(body.scan_interval_minutes)
        # A new base cadence resets the adaptive state: the user asked for
        # this rhythm, so honor it from the next scan onward.
        site.current_interval_minutes = None
        if site.auto_scan_enabled:
            site.next_scan_at = datetime.now(UTC) + timedelta(minutes=site.scan_interval_minutes)
    if body.mute_minutes is not None:
        # Alert mute (Phase 4): scans continue, only delivery is skipped
        # (and recorded as skipped). 0 unmutes immediately.
        site.muted_until = (
            datetime.now(UTC) + timedelta(minutes=body.mute_minutes)
            if body.mute_minutes > 0
            else None
        )
    await db.commit()

    baseline = await _current_baseline(db, site.id)
    if baseline is None:
        baseline = await db.scalar(
            select(Baseline)
            .where(Baseline.site_id == site.id)
            .order_by(Baseline.created_at.desc())
            .limit(1)
        )
    return SiteDetailOut(
        **SiteOut.model_validate(site).model_dump(),
        baseline_id=baseline.id if baseline else None,
        baseline_status=baseline.status if baseline else None,
        baseline_captured_at=baseline.captured_at if baseline else None,
        baseline_error=baseline.error if baseline else None,
    )


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    site = await _get_site_or_404(db, site_id)
    # Rows cascade; artifact files are cleaned by a janitor task in a later
    # phase (deliberate deferral — files are small and harmless meanwhile).
    await db.delete(site)
    await db.commit()


@router.post(
    "/{site_id}/rebaseline",
    response_model=BaselineOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rebaseline(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BaselineOut:
    site = await _get_site_or_404(db, site_id)
    in_flight = await db.scalar(
        select(Baseline).where(
            Baseline.site_id == site.id,
            Baseline.status.in_([BaselineStatus.pending, BaselineStatus.capturing]),
        )
    )
    if in_flight is not None:
        if _is_stale(in_flight.created_at):
            # Orphaned row (worker killed, enqueue lost) — fail it and
            # let this request proceed instead of 409-blocking forever.
            in_flight.status = BaselineStatus.failed
            in_flight.error = "Capture never completed — superseded by a new capture"
        else:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A baseline capture is already in progress"
            )
    baseline = Baseline(site_id=site.id, status=BaselineStatus.pending, is_current=False)
    db.add(baseline)
    await db.commit()
    enqueue_baseline_capture(baseline.id)
    return BaselineOut.model_validate(baseline)


@router.post(
    "/{site_id}/scan-now",
    response_model=ScanOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def scan_now(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScanOut:
    site = await _get_site_or_404(db, site_id)
    baseline = await _current_baseline(db, site.id)
    if baseline is None or baseline.status != BaselineStatus.ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Site has no ready baseline yet — capture a baseline first",
        )
    in_flight = await db.scalar(
        select(Scan).where(
            Scan.site_id == site.id,
            Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
        )
    )
    if in_flight is not None:
        if _is_stale(in_flight.created_at):
            in_flight.status = ScanStatus.failed
            in_flight.verdict = ScanVerdict.error
            in_flight.error = "Scan never completed — superseded by a new scan"
            in_flight.finished_at = datetime.now(UTC)
        else:
            raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already in progress")
    scan = Scan(site_id=site.id, baseline_id=baseline.id, status=ScanStatus.pending)
    db.add(scan)
    await db.commit()
    enqueue_scan(scan.id)
    return ScanOut.model_validate(scan)


@router.get("/{site_id}/scans", response_model=ScanPage)
async def list_scans(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ScanPage:
    """Scan history, newest first, offset/limit paginated (deferred from
    Phase 1) — the incident timeline reads deep history through this."""
    await _get_site_or_404(db, site_id)
    total = await db.scalar(select(func.count()).select_from(Scan).where(Scan.site_id == site_id))
    scans = (
        await db.scalars(
            select(Scan)
            .where(Scan.site_id == site_id)
            .order_by(Scan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return ScanPage(
        items=[ScanOut.model_validate(s) for s in scans],
        total=int(total or 0),
        offset=offset,
        limit=limit,
    )


@router.get("/{site_id}/scans/{scan_id}", response_model=ScanDetailOut)
async def get_scan(
    site_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScanDetailOut:
    """One scan with its per-layer findings — the §5 evidence drilldown
    (full dashboard UI lands in Phase 3; the data contract lands now)."""
    await _get_site_or_404(db, site_id)
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id, Scan.site_id == site_id))
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    findings = (
        await db.scalars(
            select(ScanFinding).where(ScanFinding.scan_id == scan.id).order_by(ScanFinding.layer)
        )
    ).all()
    return ScanDetailOut(
        **ScanOut.model_validate(scan).model_dump(),
        findings=[ScanFindingOut.model_validate(f) for f in findings],
        explanation=scan.explanation,
        explanation_provider=scan.explanation_provider,
        explanation_at=scan.explanation_at,
    )


@router.post("/{site_id}/scans/{scan_id}/explain", response_model=ExplainResponse)
async def explain_incident(
    site_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    force: Annotated[bool, Query()] = False,
) -> ExplainResponse:
    """§8 "Explain this incident": plain-English summary of the scan's
    findings via the configured Gemini/Ollama provider, cached on the
    scan. 503 when no provider is configured or it cannot answer — never
    a crash, and never a blocker for anything else."""
    await _get_site_or_404(db, site_id)
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id, Scan.site_id == site_id))
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    try:
        result = await explain_scan(db, scan_id, force=force)
    except ExplainError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    return ExplainResponse(
        explanation=result["explanation"],
        provider=result["provider"],
        generated_at=result["generated_at"],
        cached=result["cached"],
    )


# --- Suppression rules (§5 false-positive suppression, §7 CRUD) ---


@router.get("/{site_id}/suppression-rules", response_model=list[SuppressionRuleOut])
async def list_suppression_rules(
    site_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SuppressionRuleOut]:
    await _get_site_or_404(db, site_id)
    rules = (
        await db.scalars(
            select(SuppressionRule)
            .where(SuppressionRule.site_id == site_id)
            .order_by(SuppressionRule.created_at)
        )
    ).all()
    return [SuppressionRuleOut.model_validate(r) for r in rules]


@router.post(
    "/{site_id}/suppression-rules",
    response_model=SuppressionRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_suppression_rule(
    site_id: uuid.UUID,
    body: SuppressionRuleCreate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SuppressionRuleOut:
    """A new exclusion applies from the next scan onward — already-stored
    findings are historical evidence and are never rewritten."""
    site = await _get_site_or_404(db, site_id)
    try:
        # Per-type validation (regex compiles, bbox in range, selector
        # parseable by the same translator the worker uses).
        body.validate_for_type()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    rule = SuppressionRule(
        site_id=site.id,
        type=body.type,
        value=body.value,
        note=body.note,
        created_by=user.id,
    )
    db.add(rule)
    await db.commit()
    return SuppressionRuleOut.model_validate(rule)


@router.delete(
    "/{site_id}/suppression-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_suppression_rule(
    site_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _get_site_or_404(db, site_id)
    rule = await db.scalar(
        select(SuppressionRule).where(
            SuppressionRule.id == rule_id, SuppressionRule.site_id == site_id
        )
    )
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suppression rule not found")
    await db.delete(rule)
    await db.commit()
