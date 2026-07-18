"""Pydantic request/response schemas for the API surface."""

import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import (
    AlertDeliveryStatus,
    BaselineStatus,
    NotificationChannelType,
    RemediationActionType,
    RemediationExecutionStatus,
    ScanStatus,
    ScanVerdict,
    SuppressionRuleType,
    UserRole,
)

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
    # Alert mute (Phase 4): minutes from now; 0 unmutes. Scans continue,
    # only alert delivery is skipped (and recorded as skipped).
    mute_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)


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
    muted_until: datetime | None
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
    # Cached "Explain this incident" output (§8), if generated.
    explanation: str | None = None
    explanation_provider: str | None = None
    explanation_at: datetime | None = None


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


# --- Phase 4: notification channels (§6/§8) ---

# Apprise service URL schemes surfaced in the UI. Any Apprise URL is
# accepted (that's the point of Apprise); this list only powers helper
# text and the `kind` label stored with the channel.
_APPRISE_URL_MAX = 1024


class NotificationChannelCreate(BaseModel):
    type: NotificationChannelType
    name: str = Field(min_length=1, max_length=200)
    site_id: uuid.UUID | None = None
    # email channels: the recipient address.
    to: str | None = Field(default=None, max_length=320)
    # apprise_url channels: the service URL (discord://, slack://,
    # ntfy://, tgram://, json:// webhook, mailto://, ...).
    url: str | None = Field(default=None, max_length=_APPRISE_URL_MAX)
    # Optional display label of the service kind ("discord", "ntfy", ...).
    kind: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    def validate_for_type(self) -> dict:
        """Returns the config dict to encrypt, or raises ValueError."""
        if self.type is NotificationChannelType.email:
            to = (self.to or "").strip()
            if not to or "@" not in to:
                raise ValueError("email channels need a valid recipient address")
            return {"to": to}
        if self.type is NotificationChannelType.telegram:
            # Chat ID comes from the global telegram settings (auto-
            # captured by /start); nothing channel-specific to store.
            return {}
        # apprise_url
        url = (self.url or "").strip()
        if not url:
            raise ValueError("a service URL is required")
        if "://" not in url:
            raise ValueError("the service URL must look like scheme://... (an Apprise URL)")
        # Reject URLs Apprise itself can't parse, with the same library
        # the delivery path uses — a channel that saves must be sendable.
        import apprise

        if not apprise.Apprise().add(url):
            raise ValueError(
                "Apprise does not recognize this service URL — check the scheme and format"
            )
        return {"url": url, "kind": (self.kind or "").strip() or "apprise"}


class NotificationChannelOut(BaseModel):
    """Channel metadata only — the stored config is encrypted and never
    round-trips to the client. `target_hint` is a redacted display hint
    ("ops@ex...", "discord://...") built at read time."""

    id: uuid.UUID
    type: NotificationChannelType
    name: str
    site_id: uuid.UUID | None
    is_active: bool
    target_hint: str
    created_at: datetime


class NotificationChannelUpdate(BaseModel):
    is_active: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)


# --- Phase 4: settings blobs (§7 /api/settings/*) ---


class SmtpSettingsIn(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: str = Field(default="starttls", pattern="^(starttls|tls|none)$")
    username: str | None = Field(default=None, max_length=320)
    # None means "keep the stored password" on update; empty string clears.
    password: str | None = Field(default=None, max_length=1024)
    from_addr: str = Field(min_length=3, max_length=320)
    from_name: str | None = Field(default=None, max_length=200)

    @field_validator("from_addr")
    @classmethod
    def from_addr_shape(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v:
            raise ValueError("from address must be an email address")
        return v


class SmtpSettingsOut(BaseModel):
    configured: bool
    host: str | None = None
    port: int | None = None
    security: str | None = None
    username: str | None = None
    has_password: bool = False
    from_addr: str | None = None
    from_name: str | None = None


class SmtpTestRequest(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    # Optional inline settings: §8's "Send Test Email" button gates the
    # Save action, so the test must exercise the *form's* values before
    # anything is persisted. Omitted -> test the stored settings. An
    # omitted password inside inline settings falls back to the stored
    # one, so editing the host doesn't force retyping the credential.
    settings: SmtpSettingsIn | None = None

    @field_validator("to")
    @classmethod
    def to_shape(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v:
            raise ValueError("recipient must be an email address")
        return v


class TelegramSettingsIn(BaseModel):
    # None keeps the stored token; empty string clears the configuration.
    bot_token: str | None = Field(default=None, max_length=256)

    @field_validator("bot_token")
    @classmethod
    def token_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and not re.match(r"^\d+:[\w-]+$", v):
            raise ValueError(
                "that does not look like a bot token (expected '<digits>:<secret>' from BotFather)"
            )
        return v


class TelegramSettingsOut(BaseModel):
    configured: bool
    token_hint: str | None = None  # "1234567890:AAAA..." redacted
    chat_id: str | None = None  # captured by /start; shown so the user knows it worked
    chat_captured_at: str | None = None


class GeminiSettingsIn(BaseModel):
    # None keeps the stored key; empty string clears.
    api_key: str | None = Field(default=None, max_length=256)
    enabled: bool = True


class GeminiSettingsOut(BaseModel):
    configured: bool
    enabled: bool = False
    key_hint: str | None = None
    model: str = "gemini-flash-latest"


class OllamaSettingsIn(BaseModel):
    enabled: bool = False
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)


class OllamaSettingsOut(BaseModel):
    configured: bool
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None


class SettingsTestResult(BaseModel):
    ok: bool
    detail: str


# --- Phase 4: alerts (§6/§7) ---


class AlertDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID | None
    channel_name: str
    channel_type: str
    status: AlertDeliveryStatus
    detail: str | None
    created_at: datetime
    finished_at: datetime | None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    scan_id: uuid.UUID
    risk_score: float | None
    acknowledged_at: datetime | None
    acknowledged_via: str | None
    created_at: datetime


class AlertDetailOut(AlertOut):
    site_name: str | None = None
    deliveries: list[AlertDeliveryOut] = []


class AlertPage(BaseModel):
    items: list[AlertDetailOut]
    total: int
    offset: int
    limit: int


class ExplainResponse(BaseModel):
    explanation: str
    provider: str
    generated_at: datetime
    cached: bool


# --- Phase 5: user management (§7 /api/users, admin-only) ---


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=1024)
    role: UserRole = UserRole.viewer

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) < 3:
            raise ValueError("a valid email address is required")
        return v


class UserUpdate(BaseModel):
    """Admin patch: role, active flag, or a password reset. All optional."""

    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=1024)


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


# --- Phase 5: API keys (§6 api_keys) ---


class ApiKeyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label must not be blank")
        return v


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    """Creation response only: the single time the raw key is revealed."""

    key: str


# --- Phase 5: audit log (§6/§7) ---


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    target_label: str | None
    before_json: dict | None
    after_json: dict | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    offset: int
    limit: int


# --- Phase 5: bulk site import (§7 /api/sites/bulk-import) ---

# The frontend reads the chosen CSV client-side and posts its text, so
# the API needs no multipart parser (and no new dependency). Caps keep a
# pathological upload from becoming a memory problem.
BULK_IMPORT_MAX_CSV_BYTES = 512 * 1024
BULK_IMPORT_MAX_ROWS = 500


class BulkImportRequest(BaseModel):
    """Exactly one source: inline CSV text, or a sitemap URL to crawl."""

    csv_text: str | None = Field(default=None, max_length=BULK_IMPORT_MAX_CSV_BYTES)
    sitemap_url: str | None = Field(default=None, max_length=2048)
    # Applied to every created site (same defaults as single-site create).
    allow_private_networks: bool = False
    auto_scan_enabled: bool = True
    scan_interval_minutes: int = Field(default=60, ge=5, le=24 * 60)

    def validate_source(self) -> None:
        if bool(self.csv_text) == bool(self.sitemap_url):
            raise ValueError("provide either csv_text or sitemap_url (exactly one)")


class BulkImportRowResult(BaseModel):
    """Per-row outcome — imports are never all-or-nothing (§11)."""

    row: int
    url: str
    name: str | None
    status: str  # created | skipped | error
    detail: str | None = None
    site_id: uuid.UUID | None = None


class BulkImportResult(BaseModel):
    total_rows: int
    created: int
    skipped: int
    errors: int
    results: list[BulkImportRowResult]


# --- Phase 5: remediation hooks (§6/§9) ---


class RemediationHookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    action_type: RemediationActionType
    webhook_url: str = Field(min_length=1, max_length=2048)
    trigger_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # §9: manual confirm is the default; auto-execute is an explicit,
    # clearly-labeled opt-in surfaced as its own toggle in the UI.
    requires_manual_confirm: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("webhook_url")
    @classmethod
    def url_shape(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("webhook_url must be an http(s) URL")
        return v


class RemediationHookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    webhook_url: str | None = Field(default=None, min_length=1, max_length=2048)
    trigger_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_manual_confirm: bool | None = None
    is_active: bool | None = None

    @field_validator("webhook_url")
    @classmethod
    def url_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("webhook_url must be an http(s) URL")
        return v


class RemediationHookOut(BaseModel):
    """Hook metadata. The stored webhook URL is encrypted and never
    round-trips whole — `url_hint` is a redacted display form."""

    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    action_type: RemediationActionType
    trigger_threshold: float
    requires_manual_confirm: bool
    is_active: bool
    url_hint: str
    created_at: datetime


class RemediationExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hook_id: uuid.UUID
    site_id: uuid.UUID
    scan_id: uuid.UUID
    status: RemediationExecutionStatus
    hook_name: str
    action_type: str
    risk_score: float | None
    detail: str | None
    confirmed_at: datetime | None
    executed_at: datetime | None
    created_at: datetime
    site_name: str | None = None


class RemediationExecutionPage(BaseModel):
    items: list[RemediationExecutionOut]
    total: int
    offset: int
    limit: int


# --- Phase 5: operational health (§7 /api/health) ---


class HealthComponent(BaseModel):
    """One monitored component. status: ok | degraded | down | unknown;
    detail is always user-safe."""

    status: str
    detail: str | None = None


class HealthDetails(BaseModel):
    status: str
    uptime_seconds: int
    queue_depth: int | None
    db_size_bytes: int | None
    sites_total: int
    scans_last_24h: int
    avg_scan_seconds: float | None
    last_scan_at: datetime | None
    last_dispatch_tick_at: datetime | None
    components: dict[str, HealthComponent]
