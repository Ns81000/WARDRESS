"""Remediation webhook delivery (Celery task, §9).

Firing runs in its own task, never in the scan body — a broken or slow
webhook must never block or crash a scan (rule 6). The task decrypts the
hook URL, POSTs the incident payload, and records the outcome on the
execution row (succeeded/failed + a user-safe detail). Idempotent: it
only acts on rows still in `queued`, so acks_late redelivery cannot
double-fire.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.models import (
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    Site,
    utcnow,
)
from app.remediation import build_remediation_payload, decrypt_hook_url, post_webhook
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

        payload = build_remediation_payload(site, scan, hook)
        ok, detail = await post_webhook(url, payload)
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
