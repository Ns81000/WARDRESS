"""Auth endpoints: login, refresh (rotating), logout (§7, §9).

Refresh tokens travel in an HttpOnly cookie scoped to /api/auth so the
SPA never touches them from JS; the short-lived access token is returned
in the JSON body and held in memory by the frontend.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.models import RefreshToken, User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "wardress_refresh"

# Constant-cost dummy hash so login timing does not reveal whether an
# email exists (verify runs either way).
_DUMMY_HASH = hash_password("wardress-timing-equalizer")


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw_token,
        max_age=settings.refresh_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )


async def _issue_refresh_token(db: AsyncSession, user: User) -> str:
    raw, token_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl),
        )
    )
    return raw


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None:
        verify_password(_DUMMY_HASH, body.password)  # equalize timing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(user.password_hash, body.password) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    raw_refresh = await _issue_refresh_token(db, user)
    await db.commit()
    _set_refresh_cookie(response, raw_refresh)
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        expires_in=settings.access_token_ttl,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    wardress_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not wardress_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")

    token_hash = hash_refresh_token(wardress_refresh)
    record = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    now = datetime.now(UTC)

    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:  # SQLite test backend returns naive datetimes
        expires_at = expires_at.replace(tzinfo=UTC)

    if record.revoked_at is not None or record.replaced_by is not None:
        # Reuse of a rotated/revoked token means the token was stolen —
        # revoke the user's entire refresh-token family (§9 rotation).
        logger.warning("Refresh token reuse detected for user %s", record.user_id)
        for tok in await db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == record.user_id,
                RefreshToken.revoked_at.is_(None),
            )
        ):
            tok.revoked_at = now
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    if expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")

    user = await db.scalar(select(User).where(User.id == record.user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    # Rotate: revoke the presented token, mint a successor.
    raw_new, new_hash = generate_refresh_token()
    successor = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=now + timedelta(seconds=get_settings().refresh_token_ttl),
    )
    db.add(successor)
    await db.flush()  # populate successor.id
    record.revoked_at = now
    record.replaced_by = successor.id
    await db.commit()

    _set_refresh_cookie(response, raw_new)
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        expires_in=settings.access_token_ttl,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    wardress_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if wardress_refresh:
        record = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(wardress_refresh)
            )
        )
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
