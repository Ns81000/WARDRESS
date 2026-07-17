"""Audit-log read API (§7 /api/audit-log, Phase 5). Admin-only,
paginated, filterable by action prefix / target type / actor. Rows are
immutable — there is deliberately no write/update/delete surface here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import AdminUser
from app.models import AuditLog
from app.schemas import AuditLogOut, AuditLogPage

router = APIRouter(prefix="/api/audit-log", tags=["audit"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=AuditLogPage)
async def list_audit_log(
    admin: AdminUser,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    actor: Annotated[str | None, Query(max_length=320)] = None,
) -> AuditLogPage:
    query = select(AuditLog)
    if action:
        # Prefix match so "site" finds site.create/site.update/site.delete.
        query = query.where(AuditLog.action.startswith(action))
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if actor:
        query = query.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))
    ).all()
    return AuditLogPage(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=int(total or 0),
        offset=offset,
        limit=limit,
    )
