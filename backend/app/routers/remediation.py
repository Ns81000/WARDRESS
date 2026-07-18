"""Remediation hooks + confirm queue API (§6/§9, Phase 5).

Hook configuration is admin-only (it points Wardress at infrastructure
that can roll deployments back). The confirm queue is analyst-or-admin:
confirming a remediation is incident response, same tier as acking an
alert. Every configuration change and every confirm/dismiss writes an
audit row. The stored webhook URL never round-trips — list responses
carry a redacted hint only.
"""

import uuid
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.crypto import encrypt_text
from app.db import get_db
from app.deps import AdminUser, AnalystUser, CurrentUser
from app.models import (
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Site,
    utcnow,
)
from app.remediation import decrypt_hook_url
from app.scanning import is_stale
from app.schemas import (
    RemediationExecutionOut,
    RemediationExecutionPage,
    RemediationHookCreate,
    RemediationHookOut,
    RemediationHookUpdate,
)
from app.tasks import enqueue_remediation

router = APIRouter(prefix="/api", tags=["remediation"])

DB = Annotated[AsyncSession, Depends(get_db)]


def _url_hint(hook: RemediationHook) -> str:
    url = decrypt_hook_url(hook)
    if url is None:
        return "(unreadable — re-save this hook)"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname or ''}/..."


def _hook_out(hook: RemediationHook) -> RemediationHookOut:
    return RemediationHookOut(
        id=hook.id,
        site_id=hook.site_id,
        name=hook.name,
        action_type=hook.action_type,
        trigger_threshold=hook.trigger_threshold,
        requires_manual_confirm=hook.requires_manual_confirm,
        is_active=hook.is_active,
        url_hint=_url_hint(hook),
        created_at=hook.created_at,
    )


def _hook_snapshot(hook: RemediationHook) -> dict:
    return {
        "name": hook.name,
        "action_type": hook.action_type.value,
        "trigger_threshold": hook.trigger_threshold,
        "requires_manual_confirm": hook.requires_manual_confirm,
        "is_active": hook.is_active,
    }


async def _get_site_or_404(db: AsyncSession, site_id: uuid.UUID) -> Site:
    site = await db.scalar(select(Site).where(Site.id == site_id))
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


# --- Hook CRUD (admin) ---


@router.get("/sites/{site_id}/remediation-hooks", response_model=list[RemediationHookOut])
async def list_hooks(site_id: uuid.UUID, admin: AdminUser, db: DB) -> list[RemediationHookOut]:
    await _get_site_or_404(db, site_id)
    hooks = (
        await db.scalars(
            select(RemediationHook)
            .where(RemediationHook.site_id == site_id)
            .order_by(RemediationHook.created_at)
        )
    ).all()
    return [_hook_out(h) for h in hooks]


@router.post(
    "/sites/{site_id}/remediation-hooks",
    response_model=RemediationHookOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_hook(
    site_id: uuid.UUID, body: RemediationHookCreate, admin: AdminUser, db: DB
) -> RemediationHookOut:
    site = await _get_site_or_404(db, site_id)
    hook = RemediationHook(
        site_id=site.id,
        name=body.name,
        action_type=body.action_type,
        trigger_threshold=body.trigger_threshold,
        webhook_url_encrypted=encrypt_text(body.webhook_url),
        requires_manual_confirm=body.requires_manual_confirm,
        created_by=admin.id,
    )
    db.add(hook)
    await db.flush()
    record_audit(
        db,
        actor=admin,
        action="remediation_hook.create",
        target_type="remediation_hook",
        target_id=hook.id,
        target_label=f"{site.name}: {hook.name}",
        after=_hook_snapshot(hook),
    )
    await db.commit()
    return _hook_out(hook)


@router.patch("/sites/{site_id}/remediation-hooks/{hook_id}", response_model=RemediationHookOut)
async def update_hook(
    site_id: uuid.UUID,
    hook_id: uuid.UUID,
    body: RemediationHookUpdate,
    admin: AdminUser,
    db: DB,
) -> RemediationHookOut:
    site = await _get_site_or_404(db, site_id)
    hook = await db.scalar(
        select(RemediationHook).where(
            RemediationHook.id == hook_id, RemediationHook.site_id == site_id
        )
    )
    if hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Remediation hook not found")
    before = _hook_snapshot(hook)
    if body.name is not None:
        hook.name = body.name.strip()
    if body.webhook_url is not None:
        hook.webhook_url_encrypted = encrypt_text(body.webhook_url)
    if body.trigger_threshold is not None:
        hook.trigger_threshold = body.trigger_threshold
    if body.requires_manual_confirm is not None:
        hook.requires_manual_confirm = body.requires_manual_confirm
    if body.is_active is not None:
        hook.is_active = body.is_active
    record_audit(
        db,
        actor=admin,
        action="remediation_hook.update",
        target_type="remediation_hook",
        target_id=hook.id,
        target_label=f"{site.name}: {hook.name}",
        before=before,
        after={
            **_hook_snapshot(hook),
            **({"webhook_url": "[updated]"} if body.webhook_url is not None else {}),
        },
    )
    await db.commit()
    return _hook_out(hook)


@router.delete(
    "/sites/{site_id}/remediation-hooks/{hook_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_hook(site_id: uuid.UUID, hook_id: uuid.UUID, admin: AdminUser, db: DB) -> None:
    site = await _get_site_or_404(db, site_id)
    hook = await db.scalar(
        select(RemediationHook).where(
            RemediationHook.id == hook_id, RemediationHook.site_id == site_id
        )
    )
    if hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Remediation hook not found")
    record_audit(
        db,
        actor=admin,
        action="remediation_hook.delete",
        target_type="remediation_hook",
        target_id=hook.id,
        target_label=f"{site.name}: {hook.name}",
        before=_hook_snapshot(hook),
    )
    await db.delete(hook)
    await db.commit()


# --- Confirm queue (analyst or admin) ---


async def _execution_page(
    db: AsyncSession, query, offset: int, limit: int
) -> RemediationExecutionPage:
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(RemediationExecution.created_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    site_ids = {r.site_id for r in rows}
    names: dict[uuid.UUID, str] = {}
    if site_ids:
        pairs = (await db.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids)))).all()
        names = {p[0]: p[1] for p in pairs}
    return RemediationExecutionPage(
        items=[
            RemediationExecutionOut(
                **RemediationExecutionOut.model_validate(r).model_dump(exclude={"site_name"}),
                site_name=names.get(r.site_id),
            )
            for r in rows
        ],
        total=int(total or 0),
        offset=offset,
        limit=limit,
    )


@router.get("/remediation/executions", response_model=RemediationExecutionPage)
async def list_executions(
    user: CurrentUser,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    pending_only: bool = False,
) -> RemediationExecutionPage:
    query = select(RemediationExecution)
    if pending_only:
        query = query.where(
            RemediationExecution.status == RemediationExecutionStatus.pending_confirm
        )
    return await _execution_page(db, query, offset, limit)


@router.post(
    "/remediation/executions/{execution_id}/confirm",
    response_model=RemediationExecutionOut,
)
async def confirm_execution(
    execution_id: uuid.UUID, user: AnalystUser, db: DB
) -> RemediationExecutionOut:
    execution = await db.scalar(
        select(RemediationExecution).where(RemediationExecution.id == execution_id)
    )
    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Remediation execution not found")
    # A row can be re-confirmed if a previous confirm's enqueue was lost
    # and the worker never picked it up (same stale-row philosophy as
    # scans — nothing may stick in an in-flight state forever).
    stale_queued = (
        execution.status is RemediationExecutionStatus.queued
        and execution.confirmed_at is not None
        and is_stale(execution.confirmed_at)
    )
    if execution.status is not RemediationExecutionStatus.pending_confirm and not stale_queued:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This remediation is already {execution.status.value.replace('_', ' ')}",
        )
    execution.status = RemediationExecutionStatus.queued
    execution.confirmed_by = user.id
    execution.confirmed_at = utcnow()
    record_audit(
        db,
        actor=user,
        action="remediation.confirm",
        target_type="remediation_execution",
        target_id=execution.id,
        target_label=execution.hook_name,
        after={"status": "queued", "risk_score": execution.risk_score},
    )
    await db.commit()
    try:
        enqueue_remediation(execution.id)
    except HTTPException:
        # Task queue down: put the row back in the confirm queue so the
        # operator can retry once the queue is back — never stuck.
        execution.status = RemediationExecutionStatus.pending_confirm
        execution.detail = "task queue unavailable — confirm again shortly"
        await db.commit()
        raise
    site = await db.scalar(select(Site).where(Site.id == execution.site_id))
    out = RemediationExecutionOut.model_validate(execution)
    return RemediationExecutionOut(
        **out.model_dump(exclude={"site_name"}), site_name=site.name if site else None
    )


@router.post(
    "/remediation/executions/{execution_id}/dismiss",
    response_model=RemediationExecutionOut,
)
async def dismiss_execution(
    execution_id: uuid.UUID, user: AnalystUser, db: DB
) -> RemediationExecutionOut:
    execution = await db.scalar(
        select(RemediationExecution).where(RemediationExecution.id == execution_id)
    )
    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Remediation execution not found")
    if execution.status is not RemediationExecutionStatus.pending_confirm:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This remediation is already {execution.status.value.replace('_', ' ')}",
        )
    execution.status = RemediationExecutionStatus.dismissed
    execution.confirmed_by = user.id
    execution.confirmed_at = utcnow()
    execution.detail = "Dismissed by operator"
    record_audit(
        db,
        actor=user,
        action="remediation.dismiss",
        target_type="remediation_execution",
        target_id=execution.id,
        target_label=execution.hook_name,
        after={"status": "dismissed"},
    )
    await db.commit()
    site = await db.scalar(select(Site).where(Site.id == execution.site_id))
    out = RemediationExecutionOut.model_validate(execution)
    return RemediationExecutionOut(
        **out.model_dump(exclude={"site_name"}), site_name=site.name if site else None
    )
