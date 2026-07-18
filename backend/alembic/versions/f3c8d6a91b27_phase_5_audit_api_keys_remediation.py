"""phase 5: audit log, api keys, remediation hooks + executions

Revision ID: f3c8d6a91b27
Revises: e9a2b7c15f04
Create Date: 2026-07-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c8d6a91b27"
down_revision: str | Sequence[str] | None = "e9a2b7c15f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, plain JSON elsewhere — same variant the models use.
_json = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    # §6 audit_log: immutable who/what/when rows. before/after snapshots
    # are redacted before they reach the DB (app/audit.py) — no secret
    # values, ever.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("target_label", sa.String(length=256), nullable=True),
        sa.Column("before_json", _json, nullable=True),
        sa.Column("after_json", _json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_target_type"), "audit_log", ["target_type"], unique=False)
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"], unique=False)

    # §6 api_keys: hash-only storage (raw key shown once at creation).
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)

    # §6 remediation_hooks: webhook URL encrypted at rest (URLs routinely
    # embed tokens); manual-confirm default per §9.
    op.create_table(
        "remediation_hooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum(
                "git_rollback",
                "docker_restart",
                "maintenance_page_swap",
                "custom_webhook",
                name="remediation_action_type",
            ),
            nullable=False,
        ),
        sa.Column("trigger_threshold", sa.Float(), nullable=False),
        sa.Column("webhook_url_encrypted", sa.Text(), nullable=False),
        sa.Column("requires_manual_confirm", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remediation_hooks_site_id"), "remediation_hooks", ["site_id"], unique=False
    )

    # The §9 confirm queue: one row per (hook, scan) firing.
    op.create_table(
        "remediation_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hook_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending_confirm",
                "queued",
                "succeeded",
                "failed",
                "dismissed",
                name="remediation_execution_status",
            ),
            nullable=False,
        ),
        sa.Column("hook_name", sa.String(length=200), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hook_id"], ["remediation_hooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remediation_executions_hook_id"),
        "remediation_executions",
        ["hook_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remediation_executions_site_id"),
        "remediation_executions",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "uq_remediation_executions_hook_scan",
        "remediation_executions",
        ["hook_id", "scan_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_remediation_executions_hook_scan", table_name="remediation_executions")
    op.drop_index(op.f("ix_remediation_executions_site_id"), table_name="remediation_executions")
    op.drop_index(op.f("ix_remediation_executions_hook_id"), table_name="remediation_executions")
    op.drop_table("remediation_executions")
    op.drop_index(op.f("ix_remediation_hooks_site_id"), table_name="remediation_hooks")
    op.drop_table("remediation_hooks")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_target_type"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    # Autogenerate forgets Postgres enum types on downgrade — drop explicitly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="remediation_execution_status").drop(bind, checkfirst=True)
        sa.Enum(name="remediation_action_type").drop(bind, checkfirst=True)
