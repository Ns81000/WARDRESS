"""site_icons: opt-in favicon resolver cache

Revision ID: n8p9q1r2s3t4
Revises: m7n8p9q1r2s3
Create Date: 2026-08-26 00:00:00.000000

One cached favicon per site (site_id is the PK and a CASCADE FK to
sites). Rows appear only while the operator keeps the opt-in resolver
enabled; deleting a site removes its icon row with it. The toggle itself
lives in app_settings (encrypted JSON blob, key "favicon") — no schema
change needed for it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n8p9q1r2s3t4"
down_revision: str | Sequence[str] | None = "m7n8p9q1r2s3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_icons",
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=200), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id"),
    )


def downgrade() -> None:
    op.drop_table("site_icons")
