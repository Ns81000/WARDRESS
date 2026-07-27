"""correctness: partial unique index for in-flight scans + missing perf indexes

Revision ID: g1h2i3j4k5l6
Revises: a7c2e9f31d55
Create Date: 2026-07-24 00:00:00.000000

Partial unique index on scans(site_id) WHERE status IN ('pending','running')
closes the check-then-insert race that allowed duplicate in-flight scans.
The three additional indexes close the missing-index finding from the audit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: str | Sequence[str] | None = "a7c2e9f31d55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Partial unique index: at most one pending/running scan per site.
    # A WHERE clause on a UNIQUE index is a PostgreSQL feature (the target
    # deployment). On other dialects (e.g. SQLite in unit tests, which build
    # the schema via create_all rather than migrations) skip it — a full
    # unique index on site_id would wrongly forbid scan history.
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE UNIQUE INDEX ix_scans_one_inflight_per_site
            ON scans (site_id)
            WHERE status IN ('pending', 'running')
            """
        )
    # Missing perf indexes from the audit (portable across dialects).
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_index(
        "ix_remediation_executions_scan_id", "remediation_executions", ["scan_id"]
    )
    op.create_index("ix_scans_finished_at", "scans", ["finished_at"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_scans_finished_at", table_name="scans")
    op.drop_index(
        "ix_remediation_executions_scan_id", table_name="remediation_executions"
    )
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_scans_one_inflight_per_site", table_name="scans")
