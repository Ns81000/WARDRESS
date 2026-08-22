"""sites.url uniqueness: dedupe existing twins, then a unique index

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-08-23 00:00:00.000000

sites.url had only a plain (non-unique) index, so duplicate sites for the
same URL could be created — sequentially via single-site create (which
never checked) and concurrently via bulk import (whose snapshot-read dedup
has no DB backstop). This revision repairs data created before the
constraint existed and enforces uniqueness from then on:

1. Duplicate rows are removed, keeping exactly one site per URL — the one
   with the smallest (created_at, id), i.e. the earliest-created. The
   removed twins' dependent history (baselines/scans/alerts/…) cascades.
   Duplicates ARE the defect being repaired: each twin ran its own scan
   schedule and doubled alerting/remediation for the same target.
2. The old non-unique ix_sites_url is replaced by unique uq_sites_url.
   The unique index covers the same lookups, so nothing is lost.

The downgrade restores the non-unique index; it cannot resurrect deleted
duplicate rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: str | Sequence[str] | None = "h2i3j4k5l6m7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Repair phase: collapse any pre-existing duplicates down to one row per
    # URL before the unique index can be built. Row comparison keeps the
    # minimal (created_at, id) — deterministic even for same-timestamp ties.
    op.execute(
        """
        DELETE FROM sites s
        USING sites keeper
        WHERE s.url = keeper.url
          AND (s.created_at, s.id) > (keeper.created_at, keeper.id)
        """
    )
    op.drop_index("ix_sites_url", table_name="sites")
    op.create_index("uq_sites_url", "sites", ["url"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_sites_url", table_name="sites")
    op.create_index("ix_sites_url", "sites", ["url"], unique=False)
