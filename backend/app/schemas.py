"""Pydantic request/response schemas for the Phase 1 API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import BaselineStatus, ScanStatus, ScanVerdict, UserRole

# --- Auth ---


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type label, not a secret
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    created_at: datetime


# --- Sites ---


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    allow_private_networks: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("url")
    @classmethod
    def http_only(cls, v: HttpUrl) -> HttpUrl:
        # HttpUrl already restricts to http/https; belt-and-braces since
        # this string later reaches Playwright.
        if v.scheme not in ("http", "https"):
            raise ValueError("only http and https URLs can be monitored")
        return v


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    allow_private_networks: bool
    is_active: bool
    created_at: datetime


class SiteDetailOut(SiteOut):
    """Site plus its current-baseline summary for the detail page."""

    baseline_status: BaselineStatus | None = None
    baseline_captured_at: datetime | None = None
    baseline_error: str | None = None


# --- Baselines / scans ---


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    status: BaselineStatus
    is_current: bool
    content_hash: str | None
    error: str | None
    created_at: datetime
    captured_at: datetime | None


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    baseline_id: uuid.UUID | None
    status: ScanStatus
    verdict: ScanVerdict | None
    content_hash: str | None
    layer_scores: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
