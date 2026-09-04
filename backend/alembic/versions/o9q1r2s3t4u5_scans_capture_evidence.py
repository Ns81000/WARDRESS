"""scans.capture_evidence: capture-side evidence JSON (PROMPT-002 Phase 4)

Revision ID: o9q1r2s3t4u5
Revises: n8p9q1r2s3t4
Create Date: 2026-09-04 00:00:00.000000

Nullable JSON (JSONB on Postgres, mirroring the baselines.capture_meta
idiom) storing how a scan's page was captured: the scroll/stability
evidence from worker/page_prepare.py, the screenshot height-cap decision,
and the informational capture_quality label. Debugging metadata only —
nothing in the detection pipeline reads it (per-layer data stays in
scans.layer_scores / scan_findings).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "o9q1r2s3t4u5"
down_revision: str | Sequence[str] | None = "n8p9q1r2s3t4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column(
            "capture_evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("scans", "capture_evidence")
