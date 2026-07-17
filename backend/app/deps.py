"""Authentication + authorization dependencies shared by all routers.

Two credential kinds arrive in the same Bearer header:
- JWT access tokens (interactive dashboard sessions), and
- API keys (`wk_...`, Phase 5) for scripting — routed by prefix, looked
  up by SHA-256, and carrying the owning user's role so RBAC applies
  identically to both.

RBAC (Phase 5, §11): three roles enforced per endpoint.
- admin: everything.
- analyst: sites, scans, suppression rules, alerts/acks, explains,
  reports, bulk import.
- viewer: read-only (GET surfaces only).
Role checks live here as dependency factories so every router states its
requirement declaratively and OpenAPI stays accurate.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys import hash_api_key, looks_like_api_key
from app.db import get_db
from app.models import ApiKey, User, UserRole, ensure_utc, utcnow
from app.ratelimit import enforce_user_rate_limit
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

# Update api_keys.last_used_at at most this often per key — the column
# is a usage indicator, not a per-request access log.
_LAST_USED_RESOLUTION = timedelta(minutes=1)


@dataclass
class AuthContext:
    user: User
    via_api_key: bool


async def _user_from_api_key(db: AsyncSession, credential: str) -> User:
    record = await db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(credential)))
    if record is None or record.revoked_at is not None:
        raise _credentials_error
    user = await db.scalar(select(User).where(User.id == record.user_id))
    if user is None or not user.is_active:
        raise _credentials_error
    now = utcnow()
    last = ensure_utc(record.last_used_at)
    if last is None or last < now - _LAST_USED_RESOLUTION:
        record.last_used_at = now
        await db.commit()
    return user


async def _user_from_jwt(db: AsyncSession, credential: str) -> User:
    payload = decode_access_token(credential)
    if payload is None:
        raise _credentials_error
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise _credentials_error from None
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise _credentials_error
    return user


async def get_auth_context(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthContext:
    if creds is None:
        raise _credentials_error
    if looks_like_api_key(creds.credentials):
        user = await _user_from_api_key(db, creds.credentials)
        ctx = AuthContext(user=user, via_api_key=True)
    else:
        user = await _user_from_jwt(db, creds.credentials)
        ctx = AuthContext(user=user, via_api_key=False)
    # §9 per-user rate limit (the per-IP limit runs in middleware before
    # auth). Raises 429 with Retry-After when exceeded.
    enforce_user_rate_limit(request, str(user.id))
    return ctx


async def get_current_user(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> User:
    return ctx.user


def require_roles(*roles: UserRole):
    """Dependency factory: the authenticated user must hold one of the
    given roles. 403 (not 401) — the credential is valid, the role is
    insufficient — with an actionable message."""

    allowed = set(roles)

    async def check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            names = " or ".join(sorted(r.value for r in allowed))
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires the {names} role",
            )
        return user

    return check


CurrentUser = Annotated[User, Depends(get_current_user)]
# Any authenticated role — reads. Alias kept for readability at call sites.
AnyRoleUser = CurrentUser
# Mutating monitoring work: sites, scans, suppression, acks, explains.
AnalystUser = Annotated[User, Depends(require_roles(UserRole.admin, UserRole.analyst))]
# User management, settings, channels, remediation, audit log.
AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]


async def get_session_auth_context(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Like get_auth_context but refuses API keys. Guards the endpoints
    that manage credentials themselves (API keys, auth/logout): a leaked
    key must not be able to mint or manage other credentials."""
    if ctx.via_api_key:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This endpoint requires an interactive session (API keys cannot manage credentials)",
        )
    return ctx


SessionAuthContext = Annotated[AuthContext, Depends(get_session_auth_context)]
