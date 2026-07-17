"""User management (§7 /api/users, admin-only — Phase 5 RBAC).

Create/list/update/deactivate users and assign roles. Deletion is
deliberately deactivation-first: audit history and created_by references
stay meaningful. Hard delete exists for cleanup of never-used accounts.
Every action writes an audit row; password hashes and passwords never
appear in responses or audit snapshots.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_db
from app.deps import AdminUser
from app.models import RefreshToken, User, UserRole, utcnow
from app.schemas import UserAdminOut, UserCreate, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

DB = Annotated[AsyncSession, Depends(get_db)]


def _snapshot(user: User) -> dict:
    return {"email": user.email, "role": user.role.value, "is_active": user.is_active}


async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _revoke_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Deactivation/role change must cut live sessions off at the next
    refresh — revoke the whole outstanding token family."""
    now = utcnow()
    for tok in await db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    ):
        tok.revoked_at = now


@router.get("", response_model=list[UserAdminOut])
async def list_users(admin: AdminUser, db: DB) -> list[UserAdminOut]:
    users = (await db.scalars(select(User).order_by(User.created_at))).all()
    return [UserAdminOut.model_validate(u) for u in users]


@router.post("", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, admin: AdminUser, db: DB) -> UserAdminOut:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    record_audit(
        db,
        actor=admin,
        action="user.create",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        after=_snapshot(user),
    )
    await db.commit()
    return UserAdminOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: AdminUser, db: DB
) -> UserAdminOut:
    user = await _get_user_or_404(db, user_id)
    before = _snapshot(user)

    if body.role is not None and body.role != user.role:
        # An admin demoting themselves could lock the instance out of
        # user management entirely — require another admin to do it.
        if user.id == admin.id and body.role is not UserRole.admin:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You cannot change your own role — ask another admin",
            )
        user.role = body.role
        # Role rides in the access token; cut sessions so the change
        # takes effect at the next refresh, not in 15 minutes maybe.
        await _revoke_refresh_tokens(db, user.id)

    if body.is_active is not None and body.is_active != user.is_active:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You cannot deactivate your own account — ask another admin",
            )
        if not body.is_active:
            active_admins = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.admin, User.is_active.is_(True), User.id != user.id)
            )
            if user.role is UserRole.admin and not (active_admins or 0):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Cannot deactivate the last active admin",
                )
            await _revoke_refresh_tokens(db, user.id)
        user.is_active = body.is_active

    if body.password is not None:
        user.password_hash = hash_password(body.password)
        await _revoke_refresh_tokens(db, user.id)

    record_audit(
        db,
        actor=admin,
        action="user.update",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        before=before,
        after={**_snapshot(user), **({"password": "[reset]"} if body.password else {})},
    )
    await db.commit()
    return UserAdminOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, admin: AdminUser, db: DB) -> None:
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot delete your own account — ask another admin"
        )
    if user.role is UserRole.admin and user.is_active:
        active_admins = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.admin, User.is_active.is_(True), User.id != user.id)
        )
        if not (active_admins or 0):
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete the last active admin")
    record_audit(
        db,
        actor=admin,
        action="user.delete",
        target_type="user",
        target_id=user.id,
        target_label=user.email,
        before=_snapshot(user),
    )
    await db.delete(user)
    await db.commit()
