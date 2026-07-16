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
    ForeignKey,
    Index,
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
    changed = "changed"
    error = "error"


class BaselineStatus(enum.StrEnum):
    pending = "pending"
    capturing = "capturing"
    ready = "ready"
    failed = "failed"


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    baselines: Mapped[list["Baseline"]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )
    scans: Mapped[list["Scan"]] = relationship(back_populates="site", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_sites_url", "url"),)


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
    # Layers 2-9 add keys in Phase 2; the fused risk score gets its own
    # column then (needs indexing/thresholding, not burying in JSON).
    layer_scores: Mapped[dict | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    site: Mapped[Site] = relationship(back_populates="scans")
    baseline: Mapped[Baseline | None] = relationship()

    __table_args__ = (Index("ix_scans_site_created", "site_id", "created_at"),)
