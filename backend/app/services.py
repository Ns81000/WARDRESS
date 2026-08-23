"""Shared domain-action service layer (code-quality de-duplication).

Single implementation of the core site actions — add-site, scan-now,
rebaseline, acknowledge-alert, mute-site — called by the REST routers
(``routers/sites.py``, ``routers/alerts.py``), the conversational agent
tool executors (``agent/tools.py``), **and** the Telegram bot
(``worker/telegram_bot.py``).

Before this module each action was hand-maintained in up to three copies,
which was the root cause of several divergence bugs: the agent's enqueue
paths lacked the router's 503-safe stranded-row handling, and the bot's
``/scan`` skipped the audit call the REST/agent paths both record. Now the
in-flight/stale-supersede check, the audit row, the enqueue, and the
503-safe failure handling live here **once**.

Each surface translates a :class:`ServiceError` to its own convention:

- the REST router maps ``exc.status_code`` to an ``HTTPException``;
- the agent executor raises ``ToolError(exc.message)``;
- the Telegram bot replies with ``exc.message``.

Everything else (row lifecycle, audit, enqueue) is shared, so the three
surfaces can never again drift on the semantics of a core action.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.models import (
    Alert,
    Baseline,
    BaselineStatus,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
    SuppressionRule,
    User,
    utcnow,
)
from app.scanning import clamp_interval, is_stale
from app.ssrf import SSRFBlockedError, assert_url_allowed
from app.tasks import enqueue_baseline_capture, enqueue_scan

# Alert-mute ceiling shared by every surface (§ agent + bot + REST parity).
MUTE_CAP_MINUTES = 7 * 24 * 60


# --- error translation contract -------------------------------------------


class ServiceError(Exception):
    """A user-safe domain failure. Surfaces translate this to their own
    convention; ``message`` is safe to show verbatim (no internals)."""

    status_code = http_status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ConflictError(ServiceError):
    """The action collides with current state (in-flight scan/capture, no
    ready baseline) — maps to HTTP 409."""

    status_code = http_status.HTTP_409_CONFLICT


class ValidationError(ServiceError):
    """The request is malformed or blocked by policy (SSRF, missing field)
    — maps to HTTP 422."""

    status_code = http_status.HTTP_422_UNPROCESSABLE_CONTENT


class QueueUnavailableError(ServiceError):
    """The task broker could not be reached — maps to HTTP 503. The pending
    row has already been marked failed so the site is not left 409-blocked."""

    status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE


def _pg_sqlstate(exc: Exception) -> str | None:
    """SQLSTATE of the driving DBAPI error, when the backend reports one."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _unique_violation_on(exc: Exception, constraint: str) -> bool:
    """True when the database rejected a statement for violating the named
    unique index. Unnamed 23505s count too: callers use this only around an
    INSERT/UPDATE shape where that one constraint is the only uniqueness
    backstop that can fire."""
    if _pg_sqlstate(exc) != "23505":  # unique_violation
        return False
    orig = getattr(exc, "orig", None)
    constraint_name = getattr(orig, "constraint_name", None)
    return constraint_name in (None, "", constraint)


def sites_url_unique_violation(exc: Exception) -> bool:
    """True when the database rejected a sites INSERT for violating
    ``uq_sites_url`` — the backstop that makes URL uniqueness hold under
    concurrent creates/imports."""
    return _unique_violation_on(exc, "uq_sites_url")


def scans_inflight_unique_violation(exc: Exception) -> bool:
    """True when a scans INSERT lost the race for the site's single
    in-flight slot (``ix_scans_one_inflight_per_site``) — the DB-level
    arbiter both the API and the Beat dispatcher rely on."""
    return _unique_violation_on(exc, "ix_scans_one_inflight_per_site")


def baselines_inflight_unique_violation(exc: Exception) -> bool:
    """True when a baselines INSERT lost the race for the site's single
    in-flight capture slot (``uq_baselines_one_inflight_per_site``)."""
    return _unique_violation_on(exc, "uq_baselines_one_inflight_per_site")


def concurrent_write_aborted(exc: Exception) -> bool:
    """True for deadlock/serialization aborts (40P01/40001): Postgres has
    rolled the entire transaction back, so nothing from it persists and
    the operation is safe to retry."""
    return _pg_sqlstate(exc) in ("40P01", "40001")


# --- shared read helpers ---------------------------------------------------


def site_snapshot(site: Site) -> dict:
    """Audit snapshot of a site's configurable state (no secrets)."""
    return {
        "name": site.name,
        "url": site.url,
        "allow_private_networks": site.allow_private_networks,
        "flag_threshold": site.flag_threshold,
        "auto_scan_enabled": site.auto_scan_enabled,
        "scan_interval_minutes": site.scan_interval_minutes,
        "muted_until": site.muted_until.isoformat() if site.muted_until else None,
    }


async def current_baseline(db: AsyncSession, site_id: uuid.UUID) -> Baseline | None:
    return await db.scalar(
        select(Baseline).where(Baseline.site_id == site_id, Baseline.is_current.is_(True))
    )


async def _enqueue_or_fail(
    db: AsyncSession,
    enqueue_fn: Callable[[uuid.UUID], None],
    task_id: uuid.UUID,
    *,
    on_fail: Callable[[], None],
) -> None:
    """Publish a task after the row is committed. On a broker-down (503),
    mark the just-committed row failed via ``on_fail`` and re-commit so it
    can't 409-block the site forever, then raise ``QueueUnavailableError``.
    Any non-503 enqueue error propagates unchanged.

    Runs the (blocking) broker publish off the event loop so neither an API
    request nor the bot's poll loop stalls on a slow socket.
    """
    try:
        await asyncio.to_thread(enqueue_fn, task_id)
    except HTTPException as exc:
        if exc.status_code != http_status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        on_fail()
        await db.commit()
        raise QueueUnavailableError("Task queue is unavailable — try again shortly") from exc


# --- add-site --------------------------------------------------------------


async def create_site(
    db: AsyncSession,
    *,
    name: str,
    url: str,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
    allow_private_networks: bool = False,
    flag_threshold: float | None = None,
    auto_scan_enabled: bool | None = None,
    scan_interval_minutes: int | None = None,
) -> tuple[Site, Baseline]:
    """Create a site and kick off its initial baseline capture. The SSRF
    policy is checked at creation time (immediate feedback); the worker
    re-validates before every fetch. A site for the same exact URL string
    (the dedup contract bulk import uses) already existing is a 409-class
    ``ConflictError`` — checked up front and backstopped by the database's
    unique index so concurrent creators still get exactly one winner.
    Returns (site, baseline)."""
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or not url:
        raise ValidationError("Both a name and a URL are required to add a site.")
    try:
        # Runs in a thread: the check resolves DNS, which would otherwise
        # block the event loop for up to the resolver timeout.
        await asyncio.to_thread(
            assert_url_allowed, url, allow_private_networks=allow_private_networks
        )
    except SSRFBlockedError as exc:
        raise ValidationError(str(exc)) from None

    duplicate = await db.scalar(select(Site.id).where(Site.url == url))
    if duplicate is not None:
        raise ConflictError("A site with this URL already exists")

    site = Site(
        name=name,
        url=url,
        created_by=actor.id if actor is not None else None,
        allow_private_networks=allow_private_networks,
    )
    # Optional detection/scheduling knobs default to the model's own defaults
    # when the caller omits them (the agent add-site does; REST passes them).
    if flag_threshold is not None:
        site.flag_threshold = flag_threshold
    if auto_scan_enabled is not None:
        site.auto_scan_enabled = auto_scan_enabled
    if scan_interval_minutes is not None:
        site.scan_interval_minutes = clamp_interval(scan_interval_minutes)
    db.add(site)
    try:
        await db.flush()
    except SQLAlchemyError as exc:
        await db.rollback()
        if sites_url_unique_violation(exc):
            raise ConflictError("A site with this URL already exists") from None
        if concurrent_write_aborted(exc):
            raise ValidationError(
                "Site creation collided with a concurrent change — try again"
            ) from None
        raise
    # First auto-scan due one interval after creation; manual scan-now works
    # immediately once the baseline is ready.
    if site.auto_scan_enabled:
        site.next_scan_at = datetime.now(UTC) + timedelta(minutes=site.scan_interval_minutes)

    baseline = Baseline(site_id=site.id, status=BaselineStatus.pending, is_current=False)
    db.add(baseline)
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="site.create",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        after=site_snapshot(site),
    )
    await db.commit()

    def _fail() -> None:
        baseline.status = BaselineStatus.failed
        baseline.error = "Could not enqueue capture — task queue was unavailable"

    await _enqueue_or_fail(db, enqueue_baseline_capture, baseline.id, on_fail=_fail)
    return site, baseline


# --- scan-now --------------------------------------------------------------


async def trigger_scan_now(
    db: AsyncSession,
    site: Site,
    *,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
) -> Scan:
    """Queue an immediate scan. Requires a ready baseline; supersedes a
    stale in-flight scan; 409s on a live one.

    Both transitions are arbitrated by the database, not by this check:
    the supersession is a conditional UPDATE whose rowcount picks exactly
    one winner among concurrent requests, and a lost race for the
    in-flight slot surfaces as a unique-index violation at flush that is
    translated to the same 409 (the index also backstops races with the
    Beat dispatcher's own scan creation)."""
    baseline = await current_baseline(db, site.id)
    if baseline is None or baseline.status != BaselineStatus.ready:
        raise ConflictError(f"{site.name} has no ready baseline yet — capture a baseline first")
    # Captured up front: a rollback below expires ORM instances, and the
    # conflict messages must not touch them afterwards.
    site_name = site.name
    in_flight = await db.scalar(
        select(Scan).where(
            Scan.site_id == site.id,
            Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
        )
    )
    if in_flight is not None:
        if is_stale(in_flight.created_at, in_flight.started_at):
            # Orphaned row (worker killed, enqueue lost) — fail it and let
            # this request proceed instead of 409-blocking forever. The
            # status predicate makes concurrent supersessions single-winner:
            # a loser's rowcount-0 means another request already recovered
            # the row and created its own scan.
            claimed = await db.execute(
                update(Scan)
                .where(
                    Scan.id == in_flight.id,
                    Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
                )
                .values(
                    status=ScanStatus.failed,
                    verdict=ScanVerdict.error,
                    error="Scan never completed — superseded by a new scan",
                    finished_at=datetime.now(UTC),
                )
            )
            if claimed.rowcount == 0:
                await db.rollback()
                raise ConflictError(f"A scan of {site_name} is already in progress")
        else:
            raise ConflictError(f"A scan of {site_name} is already in progress")
    scan = Scan(site_id=site.id, baseline_id=baseline.id, status=ScanStatus.pending)
    db.add(scan)
    try:
        # The in-flight unique index fires here when a concurrent request
        # (or the dispatcher) won the slot between our check and now.
        await db.flush()
    except SQLAlchemyError as exc:
        await db.rollback()
        if scans_inflight_unique_violation(exc):
            raise ConflictError(f"A scan of {site_name} is already in progress") from None
        if concurrent_write_aborted(exc):
            raise ConflictError(f"A scan of {site_name} is already in progress") from None
        raise
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="scan.now",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
    )
    await db.commit()

    def _fail() -> None:
        scan.status = ScanStatus.failed
        scan.verdict = ScanVerdict.error
        scan.error = "Could not enqueue scan — task queue was unavailable"
        scan.finished_at = datetime.now(UTC)

    await _enqueue_or_fail(db, enqueue_scan, scan.id, on_fail=_fail)
    return scan


# --- rebaseline ------------------------------------------------------------


async def rebaseline_site(
    db: AsyncSession,
    site: Site,
    *,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
) -> Baseline:
    """Capture a fresh baseline, replacing the current trust anchor.
    Supersedes a stale in-flight capture; 409s on a live one.

    Like scan-now, both transitions are database-arbitrated: the
    supersession is a single-winner conditional UPDATE, and the in-flight
    partial unique index (``uq_baselines_one_inflight_per_site``) turns a
    lost check-then-insert race into a translated 409 instead of N
    simultaneous captures of one site."""
    # Captured up front: a rollback below expires ORM instances, and the
    # conflict messages must not touch them afterwards.
    site_name = site.name
    in_flight = await db.scalar(
        select(Baseline).where(
            Baseline.site_id == site.id,
            Baseline.status.in_([BaselineStatus.pending, BaselineStatus.capturing]),
        )
    )
    if in_flight is not None:
        if is_stale(in_flight.created_at):
            claimed = await db.execute(
                update(Baseline)
                .where(
                    Baseline.id == in_flight.id,
                    Baseline.status.in_([BaselineStatus.pending, BaselineStatus.capturing]),
                )
                .values(
                    status=BaselineStatus.failed,
                    error="Capture never completed — superseded by a new capture",
                )
            )
            if claimed.rowcount == 0:
                await db.rollback()
                raise ConflictError(f"A baseline capture is already in progress for {site_name}")
        else:
            raise ConflictError(f"A baseline capture is already in progress for {site_name}")
    baseline = Baseline(site_id=site.id, status=BaselineStatus.pending, is_current=False)
    db.add(baseline)
    try:
        await db.flush()
    except SQLAlchemyError as exc:
        await db.rollback()
        if baselines_inflight_unique_violation(exc):
            raise ConflictError(
                f"A baseline capture is already in progress for {site_name}"
            ) from None
        if concurrent_write_aborted(exc):
            raise ConflictError(
                f"A baseline capture is already in progress for {site_name}"
            ) from None
        raise
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="site.rebaseline",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
    )
    await db.commit()

    def _fail() -> None:
        baseline.status = BaselineStatus.failed
        baseline.error = "Could not enqueue capture — task queue was unavailable"

    await _enqueue_or_fail(db, enqueue_baseline_capture, baseline.id, on_fail=_fail)
    return baseline


# --- acknowledge-alert -----------------------------------------------------


async def acknowledge_alert(
    db: AsyncSession,
    alert: Alert,
    *,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
) -> Alert:
    """Idempotent ack: the first ack wins (the bot and dashboard may race),
    a re-ack returns the row unchanged and records no second audit row.

    The transition is claimed atomically instead of check-then-set: a plain
    read-modify-write lets every concurrent ack pass the same ``None``
    check, each record an audit row, and whichever commits last overwrite
    the attribution. The conditional UPDATE's rowcount is the arbiter —
    when a losing writer's lock wait ends, Postgres re-evaluates the
    ``acknowledged_at IS NULL`` predicate against the winner's committed
    state, so exactly one ack lands. (Same primitive as refresh-token
    rotation and the remediation confirm/dismiss claims.)
    """
    claim = await db.execute(
        update(Alert)
        .where(Alert.id == alert.id, Alert.acknowledged_at.is_(None))
        .values(
            acknowledged_at=utcnow(),
            acknowledged_by=actor.id if actor is not None else None,
            acknowledged_via=via,
        )
    )
    if claim.rowcount == 0:
        # Lost the race (or a benign re-ack): reflect the winner's state.
        await db.refresh(alert)
        return alert
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="alert.acknowledge",
        target_type="alert",
        target_id=alert.id,
        target_label=f"Alert {str(alert.id)[:8]}",
        after={"risk_score": alert.risk_score, "via": via},
    )
    await db.commit()
    await db.refresh(alert)
    return alert


# --- mute-site -------------------------------------------------------------


async def mute_site(
    db: AsyncSession,
    site: Site,
    *,
    minutes: int,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
) -> Site:
    """Mute (or, with minutes<=0, unmute) alert *delivery* for a site.
    Scans keep running; skipped deliveries stay visible. Clamped to the
    shared 7-day ceiling."""
    minutes = max(0, min(int(minutes), MUTE_CAP_MINUTES))
    before = site_snapshot(site)
    site.muted_until = datetime.now(UTC) + timedelta(minutes=minutes) if minutes > 0 else None
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="site.mute",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        before=before,
        after={**site_snapshot(site), "via": via},
    )
    await db.commit()
    return site


# --- suppression rules -----------------------------------------------------


async def list_suppression_rules(db: AsyncSession, site: Site) -> list[SuppressionRule]:
    """List all suppression rules for a site. Used by REST, agent, and bot."""
    rules = (
        await db.scalars(
            select(SuppressionRule)
            .where(SuppressionRule.site_id == site.id)
            .order_by(SuppressionRule.created_at)
        )
    ).all()
    return list(rules)


async def create_suppression_rule(
    db: AsyncSession,
    site: Site,
    *,
    type: str,
    value: str,
    note: str | None,
    actor: User | None,
    via: str,
    actor_label: str | None = None,
) -> SuppressionRule:
    """Create a suppression rule for a site. Validates per-type constraints
    (regex compiles, bbox in range, selector parseable) before persisting.
    Used by REST, agent, and bot surfaces."""
    from app.schemas import SuppressionRuleCreate, SuppressionRuleType

    # Build a schema instance to reuse its validation logic.
    try:
        rule_type = SuppressionRuleType(type)
    except ValueError:
        raise ValidationError(f"Invalid suppression type: {type}") from None

    body = SuppressionRuleCreate(type=rule_type, value=value, note=note)
    try:
        body.validate_for_type()
    except ValueError as exc:
        raise ValidationError(str(exc)) from None

    rule = SuppressionRule(
        site_id=site.id,
        type=body.type,
        value=body.value,
        note=body.note,
        created_by=actor.id if actor is not None else None,
    )
    db.add(rule)
    await db.flush()
    record_audit(
        db,
        actor=actor,
        actor_label=actor_label,
        action="suppression_rule.create",
        target_type="suppression_rule",
        target_id=rule.id,
        target_label=f"{site.name}: {rule.type.value}",
        after={"type": rule.type.value, "value": rule.value, "note": rule.note, "via": via},
    )
    await db.commit()
    return rule
