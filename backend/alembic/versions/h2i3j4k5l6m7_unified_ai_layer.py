"""unified AI layer: model catalog + configured providers + task assignments

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-07-27 20:00:00.000000

Schema for the catalog-driven, any-provider AI layer that replaces the
Gemini-pool + single-Ollama design:

- ``model_catalog_providers`` / ``model_catalog`` — reference data synced from
  models.dev (no secrets), refreshed on startup + on a Celery-beat schedule.
- ``ai_providers`` — operator-configured provider instances; keys are
  Fernet-encrypted (app/crypto.py) in ``credentials_encrypted``.
- ``ai_task_assignments`` — which model serves each task, with an optional
  cross-provider fallback.

The one-time data migration of legacy ``app_settings`` ``gemini`` / ``ollama``
rows into these tables runs at application startup (idempotent — see
app/ai_migration.py), not here, so it is unit-testable and can decrypt via the
async crypto helpers with the running app's key.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h2i3j4k5l6m7"
down_revision: str | Sequence[str] | None = "g1h2i3j4k5l6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # models.dev provider metadata (reference data, no secrets).
    op.create_table(
        "model_catalog_providers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("env", sa.JSON(), nullable=False),
        sa.Column("api_base", sa.String(length=512), nullable=True),
        sa.Column("doc", sa.String(length=512), nullable=True),
        sa.Column("npm", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # models.dev model catalog (reference data, no secrets).
    op.create_table(
        "model_catalog",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_calling", sa.Boolean(), nullable=False),
        sa.Column("reasoning", sa.Boolean(), nullable=False),
        sa.Column("cost_input", sa.Float(), nullable=True),
        sa.Column("cost_output", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_catalog_provider_id"), "model_catalog", ["provider_id"], unique=False
    )

    # Operator-configured provider instances; api_keys Fernet-encrypted.
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("validation_detail", sa.String(length=500), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_providers_provider_type"), "ai_providers", ["provider_type"], unique=False
    )

    # One row per AI task (explanation / agent_chat) with optional fallback.
    op.create_table(
        "ai_task_assignments",
        sa.Column(
            "task",
            sa.Enum("explanation", "agent_chat", name="ai_task_type"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.String(length=160), nullable=True),
        sa.Column("fallback_provider_id", sa.Uuid(), nullable=True),
        sa.Column("fallback_model_id", sa.String(length=160), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["fallback_provider_id"], ["ai_providers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("task"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ai_task_assignments")
    op.drop_index(op.f("ix_ai_providers_provider_type"), table_name="ai_providers")
    op.drop_table("ai_providers")
    op.drop_index(op.f("ix_model_catalog_provider_id"), table_name="model_catalog")
    op.drop_table("model_catalog")
    op.drop_table("model_catalog_providers")
    # Postgres keeps the enum type after the table drops; remove it so a
    # re-upgrade can recreate it cleanly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="ai_task_type").drop(bind, checkfirst=True)
