"""baselines: partial unique index for in-flight captures (+ duplicate repair)

Revision ID: k5l6m7n8p9q1
Revises: j4k5l6m7n8p9
Create Date: 2026-08-23 00:00:00.000000

Baselines had no in-flight uniqueness backstop (unlike scans, which have
had one since g1h2i3j4k5l6): concurrent rebaselines all passed the
check-then-insert window and each enqueued a full capture of the same
site. This revision adds the missing arbiter:

    CREATE UNIQUE INDEX uq_baselines_one_inflight_per_site
    ON baselines (site_id)
    WHERE status IN ('pending', 'capturing')

Pre-existing duplicate in-flight rows (litter from exactly that race,
e.g. rows stuck pending after a worker crash) would make the index
unbuildable, so they are repaired first: per site, the earliest-created
in-flight row is kept and every later one is marked failed as superseded.
Duplicates ARE the defect being repaired — each twin ran its own capture
and fought over the current-baseline anchor — and the keeper's task still
completes normally afterwards.

The downgrade drops the index; repaired rows stay failed (history is not
rewritten backwards).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "k5l6m7n8p9q1"
down_revision: str | Sequence[str] | None = "j4k5l6m7n8p9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REPAIR_SQL = """
UPDATE baselines b
SET status = 'failed',
    error = 'Capture never completed — superseded by a newer capture '
            '(duplicate repaired during upgrade)'
FROM baselines keeper
WHERE b.site_id = keeper.site_id
  AND b.status IN ('pending', 'capturing')
  AND keeper.status IN ('pending', 'capturing')
  AND (keeper.created_at, keeper.id) < (b.created_at, b.id)
"""

_CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX uq_baselines_one_inflight_per_site
ON baselines (site_id)
WHERE status IN ('pending', 'capturing')
"""


def upgrade() -> None:
    bind = op.get_bind()
    # A WHERE clause on a UNIQUE index is a PostgreSQL feature (the target
    # deployment). On other dialects skip it — a full unique index on
    # site_id would wrongly forbid baseline history.
    if bind.dialect.name == "postgresql":
        op.execute(_REPAIR_SQL)
        op.execute(_CREATE_INDEX_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("uq_baselines_one_inflight_per_site", table_name="baselines")
