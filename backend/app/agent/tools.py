"""Agent tool registry — the bridge between the model's tool calls and the
same domain logic the REST routers run.

Each tool is a :class:`Tool`: an OpenAI-style tool schema (name +
description + JSON-schema parameters), normalised across providers by
litellm, plus an async executor, a `tier` (auto vs confirm-required) and a
`min_role`. Executors call the *same* code paths the routers use — site
lookup, scan-now stale-supersede, mute clamp, explain_scan, interval clamp —
so RBAC, SSRF, audit logging and detection semantics stay identical across
surfaces. Nothing here trusts the model: role and confirmation gating happen
in the dispatcher, not in the schemas the model sees.

Executors return compact, JSON-serialisable dicts (ids truncated, no raw
HTML / evidence blobs) — token efficiency and prompt-injection containment
in one rule: tool output is *data*, never instructions.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.explain import ExplainError, explain_scan
from app.models import (
    Alert,
    Baseline,
    Scan,
    ScanFinding,
    ScanStatus,
    ScanVerdict,
    Site,
    User,
    UserRole,
    ensure_utc,
    utcnow,
)
from app.scanning import clamp_interval
from app.services import (
    ServiceError,
    acknowledge_alert,
    create_site,
    mute_site,
    rebaseline_site,
    site_snapshot,
    trigger_scan_now,
)

# Role ordering for min_role checks (viewer < analyst < admin).
_ROLE_RANK = {UserRole.viewer: 0, UserRole.analyst: 1, UserRole.admin: 2}

# Tiers: 0/1 auto-execute (reads / safe writes); 2+ require confirmation.
TIER_READ = 0
TIER_SAFE = 1
TIER_HIGH_IMPACT = 2
TIER_DESTRUCTIVE = 3

# List caps returned to the model — keeps context small and bounds cost.
_MAX_SITES = 30
_MAX_SCANS = 20
_MAX_ALERTS = 10
_NAME_CAP = 120


class ToolError(Exception):
    """A user-safe tool failure. The message is fed back to the model as the
    tool result and is safe to surface verbatim (no internals/tracebacks)."""


@dataclass
class ToolContext:
    """Everything an executor needs: the DB session, the acting user, and the
    surface label (audit 'via' + injected into no prompt)."""

    db: AsyncSession
    user: User
    surface: str  # "agent-web" | "agent-telegram"


Executor = Callable[[ToolContext, dict], Awaitable[dict]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    executor: Executor
    tier: int = TIER_READ
    min_role: UserRole = UserRole.viewer
    # One-line human summary for the confirmation card (tier >= 2 only).
    summarize: Callable[[dict], str] | None = None

    def openai_tool(self) -> dict:
        """OpenAI-style tool schema litellm normalises across every provider
        (translated per-provider internally). `parameters` is already a
        JSON-Schema object, so this is a thin wrapper."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, Tool] = {}


def _register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def tools_for_role(role: UserRole) -> list[Tool]:
    """Only the tools this role may call — the model never sees declarations
    above the user's permissions (smaller schema, nothing to social-engineer
    the model into calling)."""
    rank = _ROLE_RANK[role]
    return [t for t in _REGISTRY.values() if _ROLE_RANK[t.min_role] <= rank]


def can_call(tool: Tool, role: UserRole) -> bool:
    return _ROLE_RANK[role] >= _ROLE_RANK[tool.min_role]


# --- shared helpers -------------------------------------------------------


def _sid(value: uuid.UUID) -> str:
    """Short id form used in tool output (full uuid is noise for the model)."""
    return str(value)[:8]


def _cap(text: str | None, limit: int = _NAME_CAP) -> str:
    """Length-cap free text (site names etc.) before it enters the model."""
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


async def _resolve_site(ctx: ToolContext, ref: str) -> Site:
    """Find a site by short-id prefix, full uuid, or exact/`ilike` name.
    Raises ToolError with an actionable message on miss/ambiguity."""
    ref = (ref or "").strip()
    if not ref:
        raise ToolError("Which site? Give a site name or id.")
    # Try uuid / short-id prefix first.
    try:
        full = uuid.UUID(ref)
        site = await ctx.db.scalar(select(Site).where(Site.id == full))
        if site:
            return site
    except ValueError:
        pass
    # short id prefix (first 8 chars) — match on cast text.
    candidates = (
        await ctx.db.scalars(select(Site).where(func.lower(Site.name) == ref.lower()))
    ).all()
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ToolError(f"More than one site is named {ref!r} — use the site id instead.")
    # Fuzzy contains match as a last resort.
    like = (await ctx.db.scalars(select(Site).where(Site.name.ilike(f"%{ref}%")).limit(5))).all()
    if len(like) == 1:
        return like[0]
    if len(like) > 1:
        names = ", ".join(_cap(s.name, 40) for s in like)
        raise ToolError(f"Several sites match {ref!r}: {names}. Be more specific or use the id.")
    # short-id prefix scan (rare; small table).
    if len(ref) >= 4:
        everything = (await ctx.db.scalars(select(Site))).all()
        pref = [s for s in everything if str(s.id).startswith(ref.lower())]
        if len(pref) == 1:
            return pref[0]
    raise ToolError(f"No site found matching {ref!r}.")


async def _current_baseline(db: AsyncSession, site_id: uuid.UUID) -> Baseline | None:
    return await db.scalar(
        select(Baseline).where(Baseline.site_id == site_id, Baseline.is_current.is_(True))
    )


def _site_brief(site: Site, baseline: Baseline | None) -> dict:
    muted_until = ensure_utc(site.muted_until)
    return {
        "id": _sid(site.id),
        "name": _cap(site.name),
        "url": site.url,
        "baseline": baseline.status.value if baseline else "none",
        "auto_scan": site.auto_scan_enabled,
        "interval_min": site.scan_interval_minutes,
        "flag_threshold": site.flag_threshold,
        "muted": muted_until is not None and muted_until > utcnow(),
    }


def _scan_brief(scan: Scan) -> dict:
    return {
        "id": _sid(scan.id),
        "status": scan.status.value,
        "verdict": scan.verdict.value if scan.verdict else None,
        "risk": round(scan.risk_score, 3) if scan.risk_score is not None else None,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
    }


# --- Tier 0: reads --------------------------------------------------------


async def _list_sites(ctx: ToolContext, args: dict) -> dict:
    sites = (await ctx.db.scalars(select(Site).order_by(Site.created_at.desc()))).all()
    truncated = len(sites) > _MAX_SITES
    out = []
    for site in sites[:_MAX_SITES]:
        out.append(_site_brief(site, await _current_baseline(ctx.db, site.id)))
    return {"sites": out, "count": len(sites), "truncated": truncated}


async def _get_site(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    baseline = await _current_baseline(ctx.db, site.id)
    latest = await ctx.db.scalar(
        select(Scan).where(Scan.site_id == site.id).order_by(Scan.created_at.desc()).limit(1)
    )
    brief = _site_brief(site, baseline)
    brief["latest_scan"] = _scan_brief(latest) if latest else None
    return brief


async def _status_overview(ctx: ToolContext, args: dict) -> dict:
    total = await ctx.db.scalar(select(func.count()).select_from(Site)) or 0
    unacked = (
        await ctx.db.scalar(
            select(func.count()).select_from(Alert).where(Alert.acknowledged_at.is_(None))
        )
        or 0
    )
    # Flagged sites = those whose latest scan verdict is flagged.
    flagged = 0
    sites = (await ctx.db.scalars(select(Site))).all()
    for site in sites:
        latest = await ctx.db.scalar(
            select(Scan)
            .where(Scan.site_id == site.id, Scan.status == ScanStatus.completed)
            .order_by(Scan.created_at.desc())
            .limit(1)
        )
        if latest and latest.verdict == ScanVerdict.flagged:
            flagged += 1
    return {
        "sites_total": int(total),
        "sites_flagged": flagged,
        "alerts_unacknowledged": int(unacked),
    }


async def _list_scans(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    limit = min(int(args.get("limit", 5) or 5), _MAX_SCANS)
    scans = (
        await ctx.db.scalars(
            select(Scan)
            .where(Scan.site_id == site.id)
            .order_by(Scan.created_at.desc())
            .limit(limit)
        )
    ).all()
    return {"site": _cap(site.name), "scans": [_scan_brief(s) for s in scans]}


async def _get_scan_findings(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    scan_ref = (args.get("scan_id") or "").strip()
    scan: Scan | None = None
    if scan_ref:
        try:
            scan = await ctx.db.scalar(
                select(Scan).where(Scan.id == uuid.UUID(scan_ref), Scan.site_id == site.id)
            )
        except ValueError:
            everything = (await ctx.db.scalars(select(Scan).where(Scan.site_id == site.id))).all()
            match = [s for s in everything if str(s.id).startswith(scan_ref.lower())]
            scan = match[0] if len(match) == 1 else None
    if scan is None:
        scan = await ctx.db.scalar(
            select(Scan)
            .where(Scan.site_id == site.id, Scan.status == ScanStatus.completed)
            .order_by(Scan.created_at.desc())
            .limit(1)
        )
    if scan is None:
        raise ToolError(f"No completed scan found for {_cap(site.name)}.")
    findings = (
        await ctx.db.scalars(
            select(ScanFinding).where(ScanFinding.scan_id == scan.id).order_by(ScanFinding.layer)
        )
    ).all()
    layers = []
    for f in findings:
        if f.skipped:
            continue
        layers.append(
            {
                "layer": f.layer_key,
                "score": round(f.score, 3) if f.score is not None else None,
            }
        )
    brief = _scan_brief(scan)
    brief["site"] = _cap(site.name)
    brief["layers"] = layers
    return brief


async def _explain_incident(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    scan_ref = (args.get("scan_id") or "").strip()
    scan: Scan | None = None
    if scan_ref:
        try:
            scan = await ctx.db.scalar(
                select(Scan).where(Scan.id == uuid.UUID(scan_ref), Scan.site_id == site.id)
            )
        except ValueError:
            scan = None
    if scan is None:
        scan = await ctx.db.scalar(
            select(Scan)
            .where(Scan.site_id == site.id, Scan.status == ScanStatus.completed)
            .order_by(Scan.created_at.desc())
            .limit(1)
        )
    if scan is None:
        raise ToolError(f"No completed scan to explain for {_cap(site.name)}.")
    try:
        result = await explain_scan(ctx.db, scan.id)
    except ExplainError as exc:
        raise ToolError(str(exc)) from None
    return {
        "site": _cap(site.name),
        "scan_id": _sid(scan.id),
        "explanation": result["explanation"],
        "cached": result.get("cached", False),
    }


async def _list_alerts(ctx: ToolContext, args: dict) -> dict:
    unacked_only = bool(args.get("unacknowledged_only", False))
    query = select(Alert)
    if unacked_only:
        query = query.where(Alert.acknowledged_at.is_(None))
    alerts = (
        await ctx.db.scalars(query.order_by(Alert.created_at.desc()).limit(_MAX_ALERTS))
    ).all()
    site_ids = {a.site_id for a in alerts}
    names: dict[uuid.UUID, str] = {}
    if site_ids:
        rows = (await ctx.db.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids)))).all()
        names = {r[0]: r[1] for r in rows}
    out = [
        {
            "id": _sid(a.id),
            "site": _cap(names.get(a.site_id, "unknown")),
            "risk": round(a.risk_score, 3) if a.risk_score is not None else None,
            "acknowledged": a.acknowledged_at is not None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]
    return {"alerts": out}


# --- Tier 1: safe actions (analyst+, auto-execute, audited) ---------------


async def _run_scan_now(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    try:
        scan = await trigger_scan_now(ctx.db, site, actor=ctx.user, via=ctx.surface)
    except ServiceError as exc:
        raise ToolError(exc.message) from None
    return {"queued": True, "site": _cap(site.name), "scan_id": _sid(scan.id)}


async def _acknowledge_alert(ctx: ToolContext, args: dict) -> dict:
    ref = (args.get("alert_id") or "").strip()
    if not ref:
        raise ToolError("Which alert? Give an alert id.")
    alert: Alert | None = None
    try:
        alert = await ctx.db.scalar(select(Alert).where(Alert.id == uuid.UUID(ref)))
    except ValueError:
        everything = (
            await ctx.db.scalars(select(Alert).where(Alert.acknowledged_at.is_(None)))
        ).all()
        match = [a for a in everything if str(a.id).startswith(ref.lower())]
        alert = match[0] if len(match) == 1 else None
    if alert is None:
        raise ToolError(f"No alert found matching {ref!r}.")
    await acknowledge_alert(ctx.db, alert, actor=ctx.user, via=ctx.surface)
    return {"acknowledged": True, "alert_id": _sid(alert.id)}


async def _mute_site(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    minutes = int(args.get("minutes", 0) or 0)
    await mute_site(ctx.db, site, minutes=minutes, actor=ctx.user, via=ctx.surface)
    return {
        "site": _cap(site.name),
        "muted_until": site.muted_until.isoformat() if site.muted_until else None,
        "muted": site.muted_until is not None,
    }


async def _unmute_site(ctx: ToolContext, args: dict) -> dict:
    return await _mute_site(ctx, {"site": args.get("site", ""), "minutes": 0})


# --- Tier 2/3: high-impact + destructive (confirmation-gated) -------------


async def _add_site(ctx: ToolContext, args: dict) -> dict:
    name = _cap((args.get("name") or "").strip(), 200)
    url = (args.get("url") or "").strip()
    if not name or not url:
        raise ToolError("Both a name and a URL are required to add a site.")
    allow_private = bool(args.get("allow_private_networks", False))
    try:
        site, _ = await create_site(
            ctx.db,
            name=name,
            url=url,
            actor=ctx.user,
            via=ctx.surface,
            allow_private_networks=allow_private,
        )
    except ServiceError as exc:
        raise ToolError(exc.message) from None
    return {"created": True, "site": _cap(site.name), "site_id": _sid(site.id)}


async def _rebaseline_site(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    try:
        await rebaseline_site(ctx.db, site, actor=ctx.user, via=ctx.surface)
    except ServiceError as exc:
        raise ToolError(exc.message) from None
    return {"rebaselining": True, "site": _cap(site.name)}


async def _set_flag_threshold(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    try:
        threshold = float(args.get("threshold"))
    except (TypeError, ValueError):
        raise ToolError("threshold must be a number between 0 and 1.") from None
    if not 0.0 <= threshold <= 1.0:
        raise ToolError("threshold must be between 0 and 1.")
    before = site_snapshot(site)
    site.flag_threshold = threshold
    record_audit(
        ctx.db,
        actor=ctx.user,
        action="site.update",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        before=before,
        after=site_snapshot(site),
    )
    await ctx.db.commit()
    return {"site": _cap(site.name), "flag_threshold": threshold}


async def _set_scan_interval(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    try:
        minutes = int(args.get("minutes"))
    except (TypeError, ValueError):
        raise ToolError("minutes must be a whole number.") from None
    before = site_snapshot(site)
    site.scan_interval_minutes = clamp_interval(minutes)
    site.current_interval_minutes = None
    if site.auto_scan_enabled:
        site.next_scan_at = datetime.now(UTC) + timedelta(minutes=site.scan_interval_minutes)
    record_audit(
        ctx.db,
        actor=ctx.user,
        action="site.update",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        before=before,
        after=site_snapshot(site),
    )
    await ctx.db.commit()
    return {"site": _cap(site.name), "scan_interval_minutes": site.scan_interval_minutes}


async def _delete_site(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    name = site.name
    record_audit(
        ctx.db,
        actor=ctx.user,
        action="site.delete",
        target_type="site",
        target_id=site.id,
        target_label=site.name,
        before=site_snapshot(site),
    )
    await ctx.db.delete(site)
    await ctx.db.commit()
    return {"deleted": True, "site": _cap(name)}


# --- registry -------------------------------------------------------------

_SITE_PARAM = {
    "type": "object",
    "properties": {
        "site": {"type": "string", "description": "Site name or id"},
    },
    "required": ["site"],
}

_register(
    Tool(
        name="list_sites",
        description="List monitored sites with baseline status, scan cadence and mute state.",
        parameters={"type": "object", "properties": {}},
        executor=_list_sites,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="get_site",
        description="Get details for one site including its latest scan verdict.",
        parameters=_SITE_PARAM,
        executor=_get_site,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="get_status_overview",
        description="Overall status: site count, how many flagged, unacknowledged alerts.",
        parameters={"type": "object", "properties": {}},
        executor=_status_overview,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="list_scans",
        description="Recent scans for a site, newest first.",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "limit": {"type": "integer", "description": "How many scans (max 20)"},
            },
            "required": ["site"],
        },
        executor=_list_scans,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="get_scan_findings",
        description="Per-layer detection scores for a scan (defaults to the site's latest scan).",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "scan_id": {"type": "string", "description": "Optional scan id; omit for latest"},
            },
            "required": ["site"],
        },
        executor=_get_scan_findings,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="explain_incident",
        description="Plain-English explanation of a scan (uses the cached AI summary if present).",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "scan_id": {"type": "string", "description": "Optional scan id; omit for latest"},
            },
            "required": ["site"],
        },
        executor=_explain_incident,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="list_alerts",
        description="Recent alerts across all sites.",
        parameters={
            "type": "object",
            "properties": {
                "unacknowledged_only": {"type": "boolean"},
            },
        },
        executor=_list_alerts,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="run_scan_now",
        description="Queue an immediate scan for a site (requires a ready baseline).",
        parameters=_SITE_PARAM,
        executor=_run_scan_now,
        tier=TIER_SAFE,
        min_role=UserRole.analyst,
    )
)
_register(
    Tool(
        name="acknowledge_alert",
        description="Acknowledge an alert so it stops showing as needing attention.",
        parameters={
            "type": "object",
            "properties": {"alert_id": {"type": "string", "description": "Alert id"}},
            "required": ["alert_id"],
        },
        executor=_acknowledge_alert,
        tier=TIER_SAFE,
        min_role=UserRole.analyst,
    )
)
_register(
    Tool(
        name="mute_site",
        description="Mute alert delivery for a site for N minutes (scans continue; max 7 days).",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "minutes": {"type": "integer", "description": "Minutes to mute (max 10080)"},
            },
            "required": ["site", "minutes"],
        },
        executor=_mute_site,
        tier=TIER_SAFE,
        min_role=UserRole.analyst,
    )
)
_register(
    Tool(
        name="unmute_site",
        description="Unmute a site immediately.",
        parameters=_SITE_PARAM,
        executor=_unmute_site,
        tier=TIER_SAFE,
        min_role=UserRole.analyst,
    )
)
_register(
    Tool(
        name="add_site",
        description="Add a new site to monitor. Starts a baseline capture.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name"},
                "url": {"type": "string", "description": "Full URL including scheme"},
                "allow_private_networks": {
                    "type": "boolean",
                    "description": "Allow private/loopback targets (default false)",
                },
            },
            "required": ["name", "url"],
        },
        executor=_add_site,
        tier=TIER_HIGH_IMPACT,
        min_role=UserRole.analyst,
        summarize=lambda a: f"Add site {(a.get('name') or '').strip()[:60]!r} ({a.get('url', '')})",
    )
)
_register(
    Tool(
        name="rebaseline_site",
        description="Capture a fresh baseline for a site, replacing the current trust anchor.",
        parameters=_SITE_PARAM,
        executor=_rebaseline_site,
        tier=TIER_HIGH_IMPACT,
        min_role=UserRole.analyst,
        summarize=lambda a: f"Re-baseline {a.get('site', '')!r} (resets the anchor)",
    )
)
_register(
    Tool(
        name="set_flag_threshold",
        description="Change a site's flag threshold (0-1). High-impact: requires confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "threshold": {"type": "number", "description": "0.0 - 1.0"},
            },
            "required": ["site", "threshold"],
        },
        executor=_set_flag_threshold,
        tier=TIER_HIGH_IMPACT,
        min_role=UserRole.analyst,
        summarize=lambda a: f"Set flag threshold for {a.get('site', '')!r} to {a.get('threshold')}",
    )
)
_register(
    Tool(
        name="set_scan_interval",
        description="Change a site's scan interval in minutes (clamped to allowed range).",
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "minutes": {"type": "integer", "description": "Scan interval in minutes"},
            },
            "required": ["site", "minutes"],
        },
        executor=_set_scan_interval,
        tier=TIER_HIGH_IMPACT,
        min_role=UserRole.analyst,
        summarize=lambda a: f"Set interval for {a.get('site', '')!r} to {a.get('minutes')} min",
    )
)
_register(
    Tool(
        name="delete_site",
        description="Permanently delete a site and all its scans and alerts.",
        parameters=_SITE_PARAM,
        executor=_delete_site,
        tier=TIER_DESTRUCTIVE,
        min_role=UserRole.analyst,
        summarize=lambda a: f"DELETE {a.get('site', '')!r} and all its history (cannot be undone)",
    )
)
