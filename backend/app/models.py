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
