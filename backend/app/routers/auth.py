"""Auth endpoints: login, refresh (rotating), logout (§7, §9).

Refresh tokens travel in an HttpOnly cookie scoped to /api/auth so the
SPA never touches them from JS; the short-lived access token is returned
in the JSON body and held in memory by the frontend.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.models import RefreshToken, User, ensure_utc
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
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


def _capped_expiry(now: datetime, session_started_at: datetime) -> datetime:
    """Refresh-TTL expiry, but never past the absolute session ceiling."""
    settings = get_settings()
    sliding = now + timedelta(seconds=settings.refresh_token_ttl)
    absolute = session_started_at + timedelta(seconds=settings.max_session_ttl)
    return min(sliding, absolute)


async def _issue_refresh_token(db: AsyncSession, user: User) -> str:
    raw, token_hash = generate_refresh_token()
    now = datetime.now(UTC)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            session_started_at=now,
            expires_at=_capped_expiry(now, now),
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

    # Transparently upgrade the stored hash if Argon2 parameters have moved
    # on since this password was last set (only on a verified-correct login).
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

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

    if record.replaced_by is not None:
        # Reuse of a *rotated* token means the token was stolen (the
        # legitimate client holds the successor) — revoke the user's entire
        # refresh-token family (§9 rotation).
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

    if record.revoked_at is not None:
        # Revoked but never rotated (logout, admin reset, or a deactivation
        # sweep). Replaying it — a browser retry or a stale tab — is not
        # evidence of theft, so reject this one token without escalating to a
        # family-wide revocation that would sign every device out.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    if expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")

    user = await db.scalar(select(User).where(User.id == record.user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    # Rotate: revoke the presented token, mint a successor. The successor
    # inherits the session's original login time so its expiry stays capped
    # at the absolute session ceiling (no infinitely-sliding 7-day windows).
    session_started_at = ensure_utc(record.session_started_at) or ensure_utc(record.created_at)
    successor_expiry = _capped_expiry(now, session_started_at)
    if successor_expiry <= now:
        # The absolute session lifetime is exhausted — no successor.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, log in again")
    raw_new, new_hash = generate_refresh_token()
    successor = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        session_started_at=session_started_at,
        expires_at=successor_expiry,
    )
    db.add(successor)
    await db.flush()  # populate successor.id

    # Claim the presented token atomically: only the request whose
    # conditional UPDATE actually flips revoked_at (rowcount == 1) may mint a
    # successor. A second concurrent refresh presenting the same cookie reads
    # the row while still unrevoked, races here, and its UPDATE matches zero
    # rows — so it is treated as reuse (theft) rather than silently issuing a
    # second live successor from one presented token.
    claim = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == record.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.replaced_by.is_(None),
        )
        .values(revoked_at=now, replaced_by=successor.id)
    )
    if claim.rowcount == 0:
        # Lost the rotation race (or the token was revoked between the read
        # and here): discard our just-minted successor and apply the same
        # reuse response the revoked/replaced branch above uses.
        await db.rollback()
        logger.warning("Refresh token reuse detected for user %s", record.user_id)
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == record.user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

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
    # Mirror the attributes used at set time so strict user agents accept the
    # deletion (a cookie is matched for removal by name+path+secure+samesite).
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/api/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
