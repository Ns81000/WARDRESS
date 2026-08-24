"""Remediation webhooks (§6 remediation_hooks, §9) — shared logic.

A flagged scan can fire outbound webhooks so external tooling can react
(roll back a deploy, restart a container, swap in a maintenance page).
The master-prompt safety rules are absolute here:

- **Manual-confirm by default.** A hook with requires_manual_confirm=True
  (the default) parks its firing in the dashboard confirm queue as
  `pending_confirm`; nothing is POSTed until an operator approves. Auto-
  execute is an explicit, per-hook opt-in and is labeled as such.
- **A persistent incident cannot flap a hook forever.** Auto firings are
  cooldown-bounded (AUTO_FIRE_COOLDOWN_MINUTES): while the window is
  hot, new auto firings land in the confirm queue instead of POSTing
  unattended at the tightened scan cadence.
- **A broken hook never affects scanning (rule 6).** Creating the
execution rows is best-effort inside the scan task; the POST itself
runs in a *separate* Celery task, never in the scan body. Any failure
is a `failed` row with a user-safe detail — visible, never fatal.
- **Webhook targets obey the SSRF discipline.** URLs are validated by
`assert_url_allowed` at create/update (refusing loopback/RFC1918/
link-local receivers unless the hook opts in via
`allow_private_networks`) and every fire connects through the
DNS-pinning transport, so a target can't pass validation and then
resolve privately.

Wardress always POSTs the same JSON incident payload; the action_type is
a label the receiver uses to decide what to actually do. The webhook URL
is Fernet-encrypted at rest (URLs routinely embed tokens).
"""

import logging
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import DecryptionError, decrypt_text
from app.models import (
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    Site,
    utcnow,
)
from app.ssrf import SSRFBlockedError
from app.ssrf_transport import SSRFPinningTransport

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_S = 20.0

# A persistent incident re-flags every scan, and adaptive cadence tightens to
# base/4 (floored at MIN_INTERVAL_MINUTES = 5) — so without a brake an
# auto-execute hook fires its destructive webhook up to ~12 times per hour
# for as long as the incident lasts (a restart/rollback loop that can itself
# prevent recovery). This cooldown caps the flap: within the window after a
# hook has actually gone out — any outcome counts; hammering a receiver that
# is down is the same harm — a new AUTO firing is downgraded to the confirm
# queue instead of executing unattended. Manual-confirm hooks are never
# affected: their rows always park for a human anyway. Dismissed rows don't
# count either: the operator explicitly rejected that firing.
AUTO_FIRE_COOLDOWN_MINUTES = 30


def build_remediation_payload(site: Site, scan: Scan, hook: RemediationHook) -> dict:
    """The JSON body POSTed to the webhook. Contains incident facts and a
    dashboard link — never a secret."""
    base = get_settings().public_base_url.rstrip("/")
    return {
        "event": "wardress.remediation",
        "action_type": hook.action_type.value,
        "hook_name": hook.name,
        "site": {"id": str(site.id), "name": site.name, "url": site.url},
        "scan": {
            "id": str(scan.id),
            "risk_score": scan.risk_score,
            "verdict": scan.verdict.value if scan.verdict else None,
            "detected_at": (scan.finished_at or scan.created_at).isoformat(),
        },
        "dashboard_url": f"{base}/sites/{site.id}/scans/{scan.id}",
    }


async def create_executions_for_flagged_scan(db: AsyncSession, scan: Scan) -> list[uuid.UUID]:
    """For a flagged scan, create one RemediationExecution per active hook
    whose trigger_threshold is met. Returns the ids of executions that are
    ready to fire immediately (auto-execute hooks); manual-confirm hooks
    are left in the confirm queue. An auto firing within
    AUTO_FIRE_COOLDOWN_MINUTES of the hook's last outbound attempt lands
    in the confirm queue too — visible, human-gated, never silently
    dropped. Idempotent under acks_late redelivery via the unique
    (hook_id, scan_id) index. Never raises."""
    ready: list[uuid.UUID] = []
    try:
        hooks = (
            await db.scalars(
                select(RemediationHook).where(
                    RemediationHook.site_id == scan.site_id,
                    RemediationHook.is_active.is_(True),
                )
            )
        ).all()
        risk = scan.risk_score or 0.0
        for hook in hooks:
            if risk < hook.trigger_threshold:
                continue
            existing = await db.scalar(
                select(RemediationExecution).where(
                    RemediationExecution.hook_id == hook.id,
                    RemediationExecution.scan_id == scan.id,
                )
            )
            if existing is not None:
                if existing.status is RemediationExecutionStatus.queued:
                    ready.append(existing.id)
                continue
            auto = not hook.requires_manual_confirm
            cooled = False
            if auto:
                last_attempt_at = await db.scalar(
                    select(func.max(RemediationExecution.created_at)).where(
                        RemediationExecution.hook_id == hook.id,
                        RemediationExecution.status.in_(
                            [
                                RemediationExecutionStatus.queued,
                                RemediationExecutionStatus.succeeded,
                                RemediationExecutionStatus.failed,
                            ]
                        ),
                    )
                )
                cooled = last_attempt_at is not None and last_attempt_at > utcnow() - timedelta(
                    minutes=AUTO_FIRE_COOLDOWN_MINUTES
                )
            status = (
                RemediationExecutionStatus.pending_confirm
                if (cooled or not auto)
                else RemediationExecutionStatus.queued
            )
            execution = RemediationExecution(
                hook_id=hook.id,
                site_id=scan.site_id,
                scan_id=scan.id,
                status=status,
                hook_name=hook.name,
                action_type=hook.action_type.value,
                risk_score=scan.risk_score,
                detail=(
                    f"auto-fire held by the {AUTO_FIRE_COOLDOWN_MINUTES}-min cooldown"
                    if cooled
                    else None
                ),
            )
            db.add(execution)
            await db.flush()
            if status is RemediationExecutionStatus.queued:
                ready.append(execution.id)
        await db.commit()
    except Exception:
        logger.exception("Could not create remediation executions for scan %s", scan.id)
        try:
            await db.rollback()
        except Exception:  # noqa: S110 — best-effort
            pass
    return ready


async def post_webhook(
    url: str, payload: dict, *, allow_private_networks: bool = False
) -> tuple[bool, str]:
    """POST the incident payload. Returns (ok, user-safe detail). Never
    raises; the URL is never echoed into the detail (it may embed a
    credential). The connection is pinned like every other outbound fetch:
    the transport resolves the host, validates every resolved address
    against the SSRF policy (honoring the hook's private-network opt-in),
    and connects to a validated IP — no second resolution to race."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(WEBHOOK_TIMEOUT_S),
            transport=SSRFPinningTransport(allow_private_networks=allow_private_networks),
        ) as client:
            resp = await client.post(url, json=payload)
        if 200 <= resp.status_code < 300:
            return True, f"HTTP {resp.status_code}"
        return False, f"webhook returned HTTP {resp.status_code}"
    except SSRFBlockedError as exc:
        # Messages carry host/resolved-address material only — never the
        # full URL — so they are safe to surface.
        return False, f"webhook target refused: {exc}"
    except httpx.HTTPError as exc:
        return False, f"webhook unreachable: {type(exc).__name__}"
    except Exception as exc:
        # Contract repair: any other failure class (e.g. httpx.InvalidURL
        # from a legacy unfetchable URL) must land here as a failed row,
        # never escape to wedge the execution in `queued` forever.
        logger.warning("Webhook POST failed unexpectedly: %s", type(exc).__name__)
        return False, f"webhook error: {type(exc).__name__}"


def decrypt_hook_url(hook: RemediationHook) -> str | None:
    try:
        return decrypt_text(hook.webhook_url_encrypted)
    except DecryptionError:
        return None
