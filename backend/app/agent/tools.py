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

from sqlalchemy import cast, func, select, String
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
    SuppressionRule,
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
    create_suppression_rule,
    list_suppression_rules,
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
_MAX_SUPPRESSION = 30
_NAME_CAP = 120
_VALUE_CAP = 200


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
    # CB-3 / PERF-2: short-id prefix via SQL (no full-table scan).
    if len(ref) >= 4:
        prefix = ref.lower() + "%"
        pref = (
            await ctx.db.scalars(
                select(Site).where(cast(Site.id, String).ilike(prefix)).limit(2)
            )
        ).all()
        if len(pref) == 1:
            return pref[0]
    raise ToolError(f"No site found matching {ref!r}.")


async def _current_baseline(db: AsyncSession, site_id: uuid.UUID) -> Baseline | None:
    return await db.scalar(
        select(Baseline).where(Baseline.site_id == site_id, Baseline.is_current.is_(True))
    )


def _site_brief(
    site: Site, baseline: Baseline | None, suppression_count: int | None = None
) -> dict:
    muted_until = ensure_utc(site.muted_until)
    brief = {
        "id": _sid(site.id),
        "name": _cap(site.name),
        "url": site.url,
        "baseline": baseline.status.value if baseline else "none",
        "auto_scan": site.auto_scan_enabled,
        "interval_min": site.scan_interval_minutes,
        "flag_threshold": site.flag_threshold,
        "muted": muted_until is not None and muted_until > utcnow(),
    }
    if suppression_count is not None:
        brief["suppression_rules"] = suppression_count
    return brief


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
    supp_count = await ctx.db.scalar(
        select(func.count()).select_from(SuppressionRule).where(SuppressionRule.site_id == site.id)
    )
    brief = _site_brief(site, baseline, suppression_count=int(supp_count or 0))
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
    suppression_count = (
        await ctx.db.scalar(select(func.count()).select_from(SuppressionRule)) or 0
    )
    # PERF-1: single-query flagged-site count via correlated subquery instead
    # of the N+1 per-site loop.
    from sqlalchemy import and_
    from sqlalchemy.orm import aliased

    S2 = aliased(Scan)
    latest_sub = (
        select(S2.verdict)
        .where(
            and_(S2.site_id == Site.id, S2.status == ScanStatus.completed)
        )
        .order_by(S2.created_at.desc())
        .limit(1)
        .correlate(Site)
        .scalar_subquery()
    )
    flagged = (
        await ctx.db.scalar(
            select(func.count()).select_from(Site).where(latest_sub == ScanVerdict.flagged)
        )
        or 0
    )
    return {
        "sites_total": int(total),
        "sites_flagged": int(flagged),
        "alerts_unacknowledged": int(unacked),
        "suppression_rule_count": int(suppression_count),
    }


async def _list_scans(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    limit = max(1, min(int(args.get("limit", 5) or 5), _MAX_SCANS))  # CB-6: clamp lower-bound
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


async def _list_suppression_rules(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    rules = await list_suppression_rules(ctx.db, site)
    truncated = len(rules) > _MAX_SUPPRESSION
    out = []
    for rule in rules[:_MAX_SUPPRESSION]:
        out.append({
            "type": rule.type.value,
            "value": _cap(rule.value, _VALUE_CAP),
            "note": _cap(rule.note, 100) if rule.note else None,
        })
    return {
        "site": _cap(site.name),
        "count": len(rules),
        "rules": out,
        "truncated": truncated,
    }


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


async def _create_suppression_rule(ctx: ToolContext, args: dict) -> dict:
    site = await _resolve_site(ctx, args.get("site", ""))
    rule_type = (args.get("type") or "").strip()
    value = (args.get("value") or "").strip()
    note = (args.get("note") or "").strip() or None
    if not rule_type or not value:
        raise ToolError("A suppression rule needs a type and a value.")
    try:
        rule = await create_suppression_rule(
            ctx.db,
            site,
            type=rule_type,
            value=value,
            note=note,
            actor=ctx.user,
            via=ctx.surface,
        )
    except ServiceError as exc:
        raise ToolError(exc.message) from None
    return {
        "created": True,
        "site": _cap(site.name),
        "type": rule.type.value,
        "value": _cap(rule.value, _VALUE_CAP),
    }


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


async def _list_remediation_hooks(ctx: ToolContext, args: dict) -> dict:
    """FEAT-4: Read-only view of remediation hooks for a site. Never
    exposes the decrypted webhook URL — only a hint."""
    from app.models import RemediationHook

    site = await _resolve_site(ctx, args.get("site", ""))
    hooks = (
        await ctx.db.scalars(
            select(RemediationHook)
            .where(RemediationHook.site_id == site.id)
            .order_by(RemediationHook.created_at)
        )
    ).all()
    return {
        "site": _cap(site.name),
        "total": len(hooks),
        "hooks": [
            {
                "id": str(h.id)[:8],
                "name": _cap(h.name, 60),
                "action_type": h.action_type.value,
                "trigger_threshold": round(h.trigger_threshold, 2),
                "is_active": h.is_active,
                "requires_manual_confirm": h.requires_manual_confirm,
            }
            for h in hooks
        ],
    }


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
        name="list_suppression_rules",
        description=(
            "List the false-positive suppression rules configured for a site "
            "(css_selector / regex / bbox exclusions). Returns the true total "
            "count and the rules (list capped)."
        ),
        parameters=_SITE_PARAM,
        executor=_list_suppression_rules,
        tier=TIER_READ,
        min_role=UserRole.viewer,
    )
)
_register(
    Tool(
        name="list_remediation_hooks",
        description=(
            "List remediation hooks (webhook automations) configured for a site. "
            "Shows name, action type, trigger threshold, active/confirm status. "
            "Never reveals the webhook URL."
        ),
        parameters=_SITE_PARAM,
        executor=_list_remediation_hooks,
        tier=TIER_READ,
        min_role=UserRole.analyst,
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
        name="create_suppression_rule",
        description=(
            "Add a false-positive suppression rule to a site so the detection "
            "pipeline ignores an expected dynamic region. type is one of "
            "css_selector, regex, or bbox ('x,y,w,h' fractions). Applies from "
            "the next scan onward."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site name or id"},
                "type": {
                    "type": "string",
                    "enum": ["css_selector", "regex", "bbox"],
                    "description": "Rule kind",
                },
                "value": {
                    "type": "string",
                    "description": "Selector, regex pattern, or 'x,y,w,h' bbox fractions",
                },
                "note": {"type": "string", "description": "Optional human label"},
            },
            "required": ["site", "type", "value"],
        },
        executor=_create_suppression_rule,
        tier=TIER_HIGH_IMPACT,
        min_role=UserRole.analyst,
        summarize=lambda a: (
            f"Add {a.get('type', '')} suppression to {a.get('site', '')!r}: "
            f"{(a.get('value') or '')[:60]!r}"
        ),
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
