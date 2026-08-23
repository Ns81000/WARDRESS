"""users: per-account failed-login counter and lockout deadline

Revision ID: j4k5l6m7n8p9
Revises: i3j4k5l6m7n8
Create Date: 2026-08-23 00:00:00.000000

Login previously had no per-account defense: the only brake on password
guessing was the generic per-IP window shared with all API traffic, and
failed attempts left no trace in the audit log. These columns give the
login handler a persisted place to count consecutive failures and to
store when a locked account unlocks again:

- failed_login_attempts: incremented atomically on every failed attempt,
  reset to 0 by any successful login.
- locked_until: set once the counter crosses the lockout threshold, with
  an escalating duration; NULL means the account is not locked.

Existing rows start unlocked with a zeroed counter (server_default), so
the migration is additive and needs no data repair. The downgrade drops
both columns; any in-flight lockout is forgotten with them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j4k5l6m7n8p9"
down_revision: str | Sequence[str] | None = "i3j4k5l6m7n8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
