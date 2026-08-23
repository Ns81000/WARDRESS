"""Remediation webhook delivery (Celery task, §9).

Firing runs in its own task, never in the scan body — a broken or slow
webhook must never block or crash a scan (rule 6). The task decrypts the
hook URL, POSTs the incident payload through the SSRF-pinning transport
(honoring the hook's private-network opt-in), and records the outcome on
the execution row (succeeded/failed + a user-safe detail). Every attempt
terminates in a written outcome — a delivery-path crash marks the row
failed rather than leaving it queued for the resweep to re-enqueue
forever. Delivery is claimed atomically before the POST — `executed_at`
is stamped by exactly one concurrent message while the row stays
`queued`, reclaimable once the stamp goes stale — so neither acks_late
redelivery nor duplicate queue messages can double-fire.
"""

import asyncio
import logging
import uuid

from sqlalchemy import or_, select, update

from app.models import (
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    Site,
    utcnow,
)
from app.remediation import build_remediation_payload, decrypt_hook_url, post_webhook
from app.scanning import STALE_INFLIGHT
from worker.celery_app import celery_app
from worker.db import task_session

logger = logging.getLogger(__name__)


async def _fire(execution_id: uuid.UUID) -> str:
    async with task_session() as db:
        execution = await db.scalar(
            select(RemediationExecution).where(RemediationExecution.id == execution_id)
        )
        if execution is None:
            return "execution-missing"
        if execution.status is not RemediationExecutionStatus.queued:
            # Only queued rows fire — guards redelivery and dismissed rows.
            return f"not-queued-{execution.status.value}"

        # Claim the delivery atomically: the conditional UPDATE's rowcount is
        # the arbiter between concurrent messages (Postgres re-evaluates the
        # predicate when the lock wait ends), so exactly one POSTs. The claim
        # stamps executed_at while the row stays queued: a crash mid-fire is
        # still recoverable — fresh duplicates skip, and once the stamp ages
        # past STALE_INFLIGHT the resweep's next message can reclaim.
        now = utcnow()
        claim = await db.execute(
            update(RemediationExecution)
            .where(
                RemediationExecution.id == execution_id,
                RemediationExecution.status == RemediationExecutionStatus.queued,
                or_(
                    RemediationExecution.executed_at.is_(None),
                    RemediationExecution.executed_at < now - STALE_INFLIGHT,
                ),
            )
            .values(executed_at=now)
        )
        if claim.rowcount == 0:
            return "not-claimed"
        await db.commit()

        hook = await db.scalar(
            select(RemediationHook).where(RemediationHook.id == execution.hook_id)
        )
        site = await db.scalar(select(Site).where(Site.id == execution.site_id))
        scan = await db.scalar(select(Scan).where(Scan.id == execution.scan_id))
        if hook is None or site is None or scan is None:
            execution.status = RemediationExecutionStatus.failed
            execution.detail = "hook, site, or scan no longer exists"
            execution.executed_at = utcnow()
            await db.commit()
            return "prereqs-missing"

        url = decrypt_hook_url(hook)
        if url is None:
            execution.status = RemediationExecutionStatus.failed
            execution.detail = "webhook URL could not be decrypted — re-save the hook"
            execution.executed_at = utcnow()
            await db.commit()
            return "url-undecryptable"

        try:
            payload = build_remediation_payload(site, scan, hook)
            ok, detail = await post_webhook(
                url, payload, allow_private_networks=hook.allow_private_networks
            )
        except Exception:
            # Terminal-state guarantee: a crash here (payload build bug,
            # unexpected transport error) must never leave the row stuck
            # `queued` with the resweep re-enqueueing it forever. The row
            # records an honest failed outcome; post_webhook itself never
            # raises, so this is defense in depth.
            logger.exception("Remediation %s delivery crashed", execution.id)
            ok, detail = False, "delivery failed unexpectedly"
        execution.status = (
            RemediationExecutionStatus.succeeded if ok else RemediationExecutionStatus.failed
        )
        execution.detail = detail
        execution.executed_at = utcnow()
        await db.commit()
        logger.info(
            "Remediation %s (%s) -> %s: %s",
            execution.id,
            execution.action_type,
            execution.status.value,
            detail,
        )
        return execution.status.value


@celery_app.task(name="wardress.fire_remediation")
def fire_remediation(execution_id: str) -> str:
    """POST one confirmed/auto remediation webhook. Failures are rows,
    not exceptions — this task never propagates into scan state."""
    try:
        parsed = uuid.UUID(execution_id)
    except ValueError:
        logger.error("fire_remediation got a non-UUID id: %r", execution_id)
        return "bad-id"
    try:
        return asyncio.run(_fire(parsed))
    except Exception:
        logger.exception("Unexpected error firing remediation %s", execution_id)
        return "error"
