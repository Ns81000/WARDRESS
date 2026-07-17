"""phase 3: suppression_rules (css_selector / regex / bbox exclusions per site)

Revision ID: d7e3a1c40f88
Revises: b41c7a9e2d05
Create Date: 2026-07-16 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e3a1c40f88"
down_revision: str | Sequence[str] | None = "b41c7a9e2d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # §6 suppression_rules: per-site false-positive exclusions the
    # detection pipeline honors (§5 — a real point-and-click UI feature).
    # Enum values are the StrEnum *values*, matching app/models.py.
    op.create_table(
        "suppression_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("css_selector", "regex", "bbox", name="suppression_rule_type"),
            nullable=False,
        ),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_suppression_rules_site_id"), "suppression_rules", ["site_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_suppression_rules_site_id"), table_name="suppression_rules")
    op.drop_table("suppression_rules")
    # Autogenerate forgets Postgres enum types on downgrade — drop explicitly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="suppression_rule_type").drop(bind, checkfirst=True)
