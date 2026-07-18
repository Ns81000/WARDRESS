"""auth: add session_started_at for absolute session lifetime

Revision ID: 0a6bd482fe1f
Revises: f3c8d6a91b27
Create Date: 2026-07-18 17:47:58.696985

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a6bd482fe1f'
down_revision: Union[str, Sequence[str], None] = 'f3c8d6a91b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "refresh_tokens",
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("refresh_tokens", "session_started_at")
