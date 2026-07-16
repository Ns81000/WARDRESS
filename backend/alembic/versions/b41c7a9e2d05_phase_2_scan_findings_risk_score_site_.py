"""phase 2: scan_findings, scans.risk_score, site scheduling/threshold, flagged verdict

Revision ID: b41c7a9e2d05
Revises: 76f6f5dcf922
Create Date: 2026-07-16 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b41c7a9e2d05"
down_revision: str | Sequence[str] | None = "76f6f5dcf922"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # --- scans.verdict gains the 'flagged' value (risk >= site threshold).
    # Postgres enums need an explicit ALTER TYPE; SQLite stores VARCHAR and
    # needs nothing (the test suite builds schema via create_all anyway).
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE scan_verdict ADD VALUE IF NOT EXISTS 'flagged'")

    # --- per-site detection/scheduling knobs (server_default backfills
    # existing rows, matching the ORM defaults in app/models.py).
    op.add_column(
        "sites",
        sa.Column("flag_threshold", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "sites",
        sa.Column("auto_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "sites",
        sa.Column("scan_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "sites",
        sa.Column("current_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_sites_next_scan_at"), "sites", ["next_scan_at"], unique=False)

    # --- fused risk score: own indexed column (dashboard filters on it).
    op.add_column("scans", sa.Column("risk_score", sa.Float(), nullable=True))
    op.create_index(op.f("ix_scans_risk_score"), "scans", ["risk_score"], unique=False)

    # --- scan_findings: one row per layer per scan, full evidence for
    # UI drilldown (§5) — skipped layers get a row with the reason too.
    op.create_table(
        "scan_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.SmallInteger(), nullable=False),
        sa.Column("layer_key", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scan_findings_scan_id"), "scan_findings", ["scan_id"], unique=False)
    op.create_index(
        "uq_scan_findings_scan_layer", "scan_findings", ["scan_id", "layer"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("uq_scan_findings_scan_layer", table_name="scan_findings")
    op.drop_index(op.f("ix_scan_findings_scan_id"), table_name="scan_findings")
    op.drop_table("scan_findings")

    op.drop_index(op.f("ix_scans_risk_score"), table_name="scans")
    op.drop_column("scans", "risk_score")

    op.drop_index(op.f("ix_sites_next_scan_at"), table_name="sites")
    op.drop_column("sites", "next_scan_at")
    op.drop_column("sites", "current_interval_minutes")
    op.drop_column("sites", "scan_interval_minutes")
    op.drop_column("sites", "auto_scan_enabled")
    op.drop_column("sites", "flag_threshold")

    if bind.dialect.name == "postgresql":
        # Postgres cannot drop a single enum value: rewrite affected rows,
        # then rebuild the type without 'flagged'.
        op.execute("UPDATE scans SET verdict = 'changed' WHERE verdict = 'flagged'")
        op.execute("ALTER TYPE scan_verdict RENAME TO scan_verdict_old")
        op.execute("CREATE TYPE scan_verdict AS ENUM ('clean', 'changed', 'error')")
        op.execute(
            "ALTER TABLE scans ALTER COLUMN verdict TYPE scan_verdict "
            "USING verdict::text::scan_verdict"
        )
        op.execute("DROP TYPE scan_verdict_old")
