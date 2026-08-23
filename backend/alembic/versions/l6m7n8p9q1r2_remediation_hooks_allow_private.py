"""remediation_hooks: per-hook private-network opt-in for webhook targets

Revision ID: l6m7n8p9q1r2
Revises: k5l6m7n8p9q1
Create Date: 2026-08-23 00:00:00.000000

Hook URLs previously bypassed the codebase's entire SSRF discipline:
creation accepted loopback/RFC1918/link-local/metadata targets and the
worker POSTed to them unpinned. Hooks now validate through the same gate
as every other outbound fetch, with an explicit per-hook opt-in mirroring
`sites.allow_private_networks` for deployments whose receivers genuinely
live on internal networks (the default stays deny).

Existing rows keep working unchanged only if their targets are global;
internal-target hooks saved before this column existed will refuse at
fire time with a blocked-address detail until re-saved with the opt-in —
fail-closed by design. The downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l6m7n8p9q1r2"
down_revision: str | Sequence[str] | None = "k5l6m7n8p9q1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remediation_hooks",
        sa.Column(
            "allow_private_networks",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("remediation_hooks", "allow_private_networks")
