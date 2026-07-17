"""Pydantic request/response schemas for the API surface."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import BaselineStatus, ScanStatus, ScanVerdict, SuppressionRuleType, UserRole

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
    # §5 fused-risk threshold and §11 recurring-scan cadence.
    flag_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    auto_scan_enabled: bool = True
    scan_interval_minutes: int = Field(default=60, ge=5, le=24 * 60)

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


class SiteUpdate(BaseModel):
    """Patchable per-site detection/scheduling settings. All optional —
    only provided fields change."""

    flag_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_scan_enabled: bool | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=5, le=24 * 60)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    allow_private_networks: bool
    is_active: bool
    flag_threshold: float
    auto_scan_enabled: bool
    scan_interval_minutes: int
    current_interval_minutes: int | None
    next_scan_at: datetime | None
    created_at: datetime


class SiteDetailOut(SiteOut):
    """Site plus its current-baseline summary for the detail page."""

    baseline_id: uuid.UUID | None = None
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
    risk_score: float | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ScanFindingOut(BaseModel):
    """One layer's §5 result: score + full evidence for UI drilldown."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    layer: int
    layer_key: str
    score: float | None
    skipped: bool
    evidence: dict | None


class ScanDetailOut(ScanOut):
    findings: list[ScanFindingOut] = []


class ScanPage(BaseModel):
    """Paginated scan history (offset/limit) — powers the incident
    timeline, which needs older history than the latest-50 slice."""

    items: list[ScanOut]
    total: int
    offset: int
    limit: int


# --- Suppression rules (§5 false-positive suppression, §6 schema) ---

# A bbox is stored as "x,y,w,h" fractions (0-1) of the baseline capture
# the user drew on; the visual layer anchors the mask to the baseline's
# pixel geometry so it stays over the same content when a later capture
# is taller or shorter.
_BBOX_RE = re.compile(r"^(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$")

# CSS selectors reach lxml's cssselect translator in the worker; keep the
# grammar to what it supports and reject obvious non-selectors early.
_CSS_SELECTOR_MAX = 512


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse and validate a normalized bbox string. Raises ValueError."""
    m = _BBOX_RE.match(value.strip())
    if not m:
        raise ValueError("bbox must be 'x,y,w,h' with numeric fractions")
    x, y, w, h = (float(g) for g in m.groups())
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("bbox origin must be within the image (0-1 fractions)")
    if w <= 0.0 or h <= 0.0:
        raise ValueError("bbox width and height must be positive")
    if x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
        raise ValueError("bbox must not extend past the image edge")
    return x, y, w, h


class SuppressionRuleCreate(BaseModel):
    type: SuppressionRuleType
    value: str = Field(min_length=1, max_length=1024)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note")
    @classmethod
    def strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value must not be blank")
        return v

    def validate_for_type(self) -> None:
        """Per-type value validation — called by the router so the error
        surfaces as a clean 422 with an actionable message."""
        if self.type is SuppressionRuleType.regex:
            try:
                re.compile(self.value)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}") from None
        elif self.type is SuppressionRuleType.bbox:
            parse_bbox(self.value)  # raises ValueError with a clear message
        elif self.type is SuppressionRuleType.css_selector:
            if len(self.value) > _CSS_SELECTOR_MAX:
                raise ValueError("selector too long")
            # Validate with the same translator the worker uses, so a rule
            # that saves is a rule that applies.
            from lxml.cssselect import CSSSelector, SelectorError

            try:
                CSSSelector(self.value)
            except SelectorError as exc:
                raise ValueError(f"invalid CSS selector: {exc}") from None


class SuppressionRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    type: SuppressionRuleType
    value: str
    note: str | None
    created_at: datetime
