"""API-key management (§6/§7 /api/api-keys, Phase 5).

Per-user keys for scripting against the REST API. The raw key is shown
exactly once, at creation. Keys are managed only from an interactive
session (SessionAuthContext) — a leaked key must not be able to mint more
keys. A key inherits its owner's role, so RBAC applies to key-driven
requests identically (enforced in app/deps.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys import generate_api_key
from app.audit import record_audit
from app.db import get_db
from app.deps import SessionAuthContext
from app.models import ApiKey, utcnow
from app.schemas import ApiKeyCreate, ApiKeyCreatedOut, ApiKeyOut

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(ctx: SessionAuthContext, db: DB) -> list[ApiKeyOut]:
    keys = (
        await db.scalars(
            select(ApiKey).where(ApiKey.user_id == ctx.user.id).order_by(ApiKey.created_at.desc())
        )
    ).all()
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: ApiKeyCreate, ctx: SessionAuthContext, db: DB) -> ApiKeyCreatedOut:
    raw, key_hash, prefix = generate_api_key()
    key = ApiKey(user_id=ctx.user.id, key_hash=key_hash, key_prefix=prefix, label=body.label)
    db.add(key)
    await db.flush()
    record_audit(
        db,
        actor=ctx.user,
        action="api_key.create",
        target_type="api_key",
        target_id=key.id,
        target_label=body.label,
        after={"label": body.label, "key_prefix": prefix},
    )
    await db.commit()
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(key).model_dump(), key=raw)


@router.delete("/{key_id}", response_model=ApiKeyOut)
async def revoke_api_key(key_id: uuid.UUID, ctx: SessionAuthContext, db: DB) -> ApiKeyOut:
    """Revoke (don't delete): the row stays so the audit trail and
    last-used history remain, and the hash can never be re-issued."""
    key = await db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == ctx.user.id)
    )
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        record_audit(
            db,
            actor=ctx.user,
            action="api_key.revoke",
            target_type="api_key",
            target_id=key.id,
            target_label=key.label,
        )
        await db.commit()
    return ApiKeyOut.model_validate(key)
