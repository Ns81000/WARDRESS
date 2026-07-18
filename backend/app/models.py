"""ORM models — Phase 1 slice of the master prompt §6 schema.

Shape decisions made here are extended, never repainted, in later phases:
- `users.role` is already the §6 enum (admin/analyst/viewer) even though
  Phase 1 only seeds an admin — RBAC enforcement lands in Phase 5.
- `sites.allow_private_networks` is the §9 per-site SSRF opt-in from day one.
- `scans.layer_scores` is a JSON dict that layer 1 populates now and
  layers 2-9 extend in Phase 2 without a schema change.

Types are dialect-portable on purpose: JSONB/UUID on Postgres, JSON/CHAR
on SQLite so the unit-test suite can run against aiosqlite without a
running Postgres.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB in Postgres, plain JSON elsewhere (tests on aiosqlite).
JSONDict = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize a DB datetime to aware-UTC. The SQLite test backend
    returns naive datetimes; Postgres returns aware ones — comparisons
    against datetime.now(UTC) must work identically on both."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class Base(DeclarativeBase):
    type_annotation_map = {
        dict: JSONDict,
        uuid.UUID: Uuid(as_uuid=True),
    }


class UserRole(enum.StrEnum):
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class ScanStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ScanVerdict(enum.StrEnum):
    clean = "clean"
    changed = "changed"  # differences found, fused risk below the site threshold
    flagged = "flagged"  # fused risk at/above the site threshold — needs attention
    error = "error"


class BaselineStatus(enum.StrEnum):
    pending = "pending"
    capturing = "capturing"
    ready = "ready"
    failed = "failed"


class SuppressionRuleType(enum.StrEnum):
    css_selector = "css_selector"
    regex = "regex"
    bbox = "bbox"


class NotificationChannelType(enum.StrEnum):
    """§6 notification_channels.type. `email` sends through the stored
    SMTP settings; `telegram` builds an Apprise tgram:// URL from the
    stored bot token + chat ID; `apprise_url` is a raw user-supplied
    Apprise URL (Discord/Slack/ntfy/webhook/...)."""

    email = "email"
    telegram = "telegram"
    apprise_url = "apprise_url"


class AlertDeliveryStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"  # logged and visible in the UI — never crashes a scan
    skipped = "skipped"  # e.g. site muted, channel disabled


class RemediationActionType(enum.StrEnum):
    """§6 remediation_hooks.action_type — a label describing what the
    webhook does on the receiving end. Wardress always just POSTs the
    incident payload; the label drives UI copy and the receiver's own
    dispatch, never different client-side behavior."""

    git_rollback = "git_rollback"
    docker_restart = "docker_restart"
    maintenance_page_swap = "maintenance_page_swap"
    custom_webhook = "custom_webhook"


class RemediationExecutionStatus(enum.StrEnum):
    """Lifecycle of one remediation firing (§9: manual-confirm default).
    pending_confirm sits in the dashboard confirm queue; auto-execute
    hooks (explicit per-hook opt-in) skip straight to queued."""

    pending_confirm = "pending_confirm"
    queued = "queued"  # confirmed (or auto) — waiting on the worker
    succeeded = "succeeded"
    failed = "failed"  # webhook unreachable/non-2xx — visible, never affects scans
    dismissed = "dismissed"  # operator rejected the pending confirmation


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    """Store enum *values* (lowercase strings), not Python member names."""
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), default=UserRole.admin)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Server-side record of issued refresh tokens so rotation and revocation
    are enforceable (§9). Only a SHA-256 of the token is stored — a DB leak
    must not yield usable tokens."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # When the session this token belongs to originally logged in. Carried
    # unchanged across rotations so successor expiry can be capped at
    # session_started_at + max_session_ttl (no infinitely-sliding sessions).
    # NULL on pre-upgrade rows: treated as created_at.
    session_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set when this token is rotated, pointing at its successor — makes
    # token-reuse detection possible (reuse of a rotated token means theft).
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2048))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # §9 SSRF opt-in: private/loopback/link-local targets are refused unless
    # the user explicitly enables this per site.
    allow_private_networks: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- Phase 2: per-site detection/scheduling knobs (§5, §11) ---
    # Fused risk score at or above this flags the scan (0-1, default 0.5).
    flag_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    # Recurring scans (Celery Beat). `scan_interval_minutes` is the user's
    # chosen base cadence; `current_interval_minutes` is what the adaptive
    # scheduler is actually using right now (tightens after a change,
    # relaxes back toward base while stable); `next_scan_at` is the due
    # time the dispatcher polls on.
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    current_interval_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    next_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    # --- Phase 4: alerting state ---
    # Muted sites still scan and store findings; only alert *delivery* is
    # suppressed (recorded as skipped, visible in the UI). Set via the
    # Telegram bot's /mute or the dashboard.
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    baselines: Mapped[list["Baseline"]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )
    scans: Mapped[list["Scan"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    suppression_rules: Mapped[list["SuppressionRule"]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_sites_url", "url"),)


class SuppressionRule(Base):
    """§5/§6 false-positive suppression: a per-site exclusion the detection
    pipeline honors. Three kinds (`type`):
    - css_selector — DOM subtrees the text/structure layers ignore
    - regex — dynamic text patterns excluded from text comparison
    - bbox — a screenshot region the visual layer masks, stored as
      normalized fractions "x,y,w,h" of the full-page capture (resolution-
      independent: the same rule applies to any later capture size)
    `value` is validated at the API boundary (parseable regex, sane
    selector, in-range bbox) — the worker treats stored rules as trusted
    but still fails safe per rule if one turns out unusable."""

    __tablename__ = "suppression_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[SuppressionRuleType] = mapped_column(
        _enum(SuppressionRuleType, "suppression_rule_type")
    )
    value: Mapped[str] = mapped_column(String(1024))
    # Optional human label ("cookie banner", "visitor counter").
    note: Mapped[str | None] = mapped_column(String(200), default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    site: Mapped[Site] = relationship(back_populates="suppression_rules")


class NotificationChannel(Base):
    """§6 notification_channels: one alert destination. `config` is a
    Fernet-encrypted JSON blob (app/crypto.py) — an Apprise URL, or the
    telegram chat reference — because Apprise URLs embed credentials
    (webhook tokens, SMTP passwords) and must never sit in plaintext.

    `site_id` NULL = global channel (alerts for every site); set = only
    that site's alerts (§8 "configurable per site or globally")."""

    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), default=None, index=True
    )
    type: Mapped[NotificationChannelType] = mapped_column(
        _enum(NotificationChannelType, "notification_channel_type")
    )
    # Human label ("Ops Discord", "On-call email").
    name: Mapped[str] = mapped_column(String(200))
    config_encrypted: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """Singleton config blobs keyed by name ("smtp", "telegram", "gemini",
    "ollama"). Values are Fernet-encrypted JSON — every one of these
    holds a credential or sits next to one."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    """§6 alerts: one row per flagged scan. Delivery attempts live in
    alert_deliveries; acknowledgement (dashboard or bot /ack) here."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True, unique=True
    )
    risk_score: Mapped[float | None] = mapped_column(Float, default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # "dashboard" | "telegram" — where the ack came from.
    acknowledged_via: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class AlertDelivery(Base):
    """One delivery attempt of one alert to one channel. Failures are
    recorded here (status=failed + detail) and surfaced in the UI —
    a broken channel must be visible, and must never crash a scan."""

    __tablename__ = "alert_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="SET NULL"), default=None
    )
    # Denormalized so a deleted channel's history stays readable.
    channel_name: Mapped[str] = mapped_column(String(200))
    channel_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[AlertDeliveryStatus] = mapped_column(
        _enum(AlertDeliveryStatus, "alert_delivery_status"),
        default=AlertDeliveryStatus.pending,
    )
    # User-safe failure/skip reason ("SMTP authentication failed", "site
    # muted until ..."), never a raw traceback or a credential.
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    alert: Mapped[Alert] = relationship(back_populates="deliveries")


class Baseline(Base):
    """A trusted capture of a site. A site can have many baselines over time
    (rebaseline after a legitimate change); exactly one is current."""

    __tablename__ = "baselines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[BaselineStatus] = mapped_column(
        _enum(BaselineStatus, "baseline_status"), default=BaselineStatus.pending
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    html_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    # Response metadata captured alongside (final URL after redirects,
    # status code, selected headers) — later layers extend this dict.
    capture_meta: Mapped[dict | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    site: Mapped[Site] = relationship(back_populates="baselines")

    # DB-enforced invariant: at most one current baseline per site, even
    # under concurrent capture tasks. Partial index works on both Postgres
    # and SQLite (each dialect needs its own `where` kwarg).
    __table_args__ = (
        Index(
            "uq_baselines_one_current_per_site",
            "site_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("baselines.id", ondelete="SET NULL")
    )
    status: Mapped[ScanStatus] = mapped_column(
        _enum(ScanStatus, "scan_status"), default=ScanStatus.pending
    )
    verdict: Mapped[ScanVerdict | None] = mapped_column(
        _enum(ScanVerdict, "scan_verdict"), default=None
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    html_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    # Per-layer results: {"layer1_hash": {"score": 1.0, "evidence": {...}}}.
    # Kept as the compact summary the scan table reads; the full per-layer
    # evidence for UI drilldown lives in scan_findings rows (§5).
    layer_scores: Mapped[dict | None] = mapped_column(default=None)
    # Fused risk score from layer 9 (0-1). Own indexed column — the
    # dashboard filters and thresholds on it (never buried in JSON).
    risk_score: Mapped[float | None] = mapped_column(Float, default=None, index=True)
    # Phase 4 "Explain this incident" (§8): plain-English summary from
    # Gemini/Ollama, generated on demand and cached here (one explanation
    # per scan; regenerating overwrites).
    explanation: Mapped[str | None] = mapped_column(Text, default=None)
    explanation_provider: Mapped[str | None] = mapped_column(String(32), default=None)
    explanation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    site: Mapped[Site] = relationship(back_populates="scans")
    baseline: Mapped[Baseline | None] = relationship()
    findings: Mapped[list["ScanFinding"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_scans_site_created", "site_id", "created_at"),)


class ScanFinding(Base):
    """One detection layer's result for one scan (§5): the layer's score
    plus its full evidence dict for UI drilldown — never just a bare
    number. Skipped layers get a row too (`skipped=True` + the reason in
    evidence) so the pipeline's gating decisions stay auditable."""

    __tablename__ = "scan_findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    # 1-9 per the §5 layer table.
    layer: Mapped[int] = mapped_column(SmallInteger)
    # Stable machine key, e.g. "layer2_dom_structure".
    layer_key: Mapped[str] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float, default=None)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    # Matched keywords, diff snippets, new-link lists, header diffs, or
    # {"reason": ...} when skipped.
    evidence: Mapped[dict | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scan: Mapped[Scan] = relationship(back_populates="findings")

    __table_args__ = (
        # One row per layer per scan — a redelivered task must upsert,
        # never duplicate.
        Index("uq_scan_findings_scan_layer", "scan_id", "layer", unique=True),
    )


class AuditLog(Base):
    """§6 audit_log: who changed what, when (Phase 5). Every config
    change, baseline reset, suppression-rule change, settings/channel
    edit, ack, mute, and user-management action writes a row here.

    `actor_email` is denormalized so history stays readable after a user
    is deleted. before/after snapshots NEVER contain secret values —
    writers redact before calling record_audit (app/audit.py), and the
    helper drops known-sensitive keys as a second line of defense.
    Rows are immutable: no update/delete API exists, by design."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_email: Mapped[str | None] = mapped_column(String(320), default=None)
    # Stable machine key, e.g. "site.create", "settings.smtp.update",
    # "user.deactivate", "alert.ack" — filterable in the UI.
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # Human display label for the target ("blog", "SMTP settings") so the
    # log stays readable after the target row is deleted.
    target_label: Mapped[str | None] = mapped_column(String(256), default=None)
    before_json: Mapped[dict | None] = mapped_column(default=None)
    after_json: Mapped[dict | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class ApiKey(Base):
    """§6 api_keys: per-user keys for scripting against the REST API.
    The raw key is shown exactly once at creation; only its SHA-256 is
    stored (same rationale as refresh tokens — a DB leak yields nothing
    usable). Requests authenticated by key carry the owning user's role,
    so RBAC applies identically. A revoked or deactivated-owner key fails
    with 401 and can never break anything else (rule 6)."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # First characters of the raw key ("wk_ab12cd34"), for list display.
    key_prefix: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class RemediationHook(Base):
    """§6 remediation_hooks: an outbound webhook fired when one of the
    site's scans is flagged at/above trigger_threshold. Manual-confirm by
    default (§9): the firing parks in the confirm queue until an operator
    approves it; auto_execute is an explicit, clearly-labeled per-hook
    opt-in. The webhook URL is Fernet-encrypted at rest — remediation
    endpoints routinely embed tokens in their URLs."""

    __tablename__ = "remediation_hooks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    action_type: Mapped[RemediationActionType] = mapped_column(
        _enum(RemediationActionType, "remediation_action_type")
    )
    # Fires when scan risk_score >= trigger_threshold (and the scan is
    # flagged). Defaults to the site's own flag threshold semantics.
    trigger_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    webhook_url_encrypted: Mapped[str] = mapped_column(Text)
    requires_manual_confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RemediationExecution(Base):
    """One firing of one remediation hook for one flagged scan — the
    §9 confirm queue's row. Unique per (hook, scan): acks_late scan
    redelivery must never queue the same remediation twice."""

    __tablename__ = "remediation_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("remediation_hooks.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    status: Mapped[RemediationExecutionStatus] = mapped_column(
        _enum(RemediationExecutionStatus, "remediation_execution_status"),
        default=RemediationExecutionStatus.pending_confirm,
    )
    # Denormalized display fields so history survives hook edits/deletes.
    hook_name: Mapped[str] = mapped_column(String(200))
    action_type: Mapped[str] = mapped_column(String(32))
    risk_score: Mapped[float | None] = mapped_column(Float, default=None)
    # User-safe outcome ("HTTP 200", "connection refused"), never a
    # traceback or the webhook URL (it may embed credentials).
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("uq_remediation_executions_hook_scan", "hook_id", "scan_id", unique=True),
    )
