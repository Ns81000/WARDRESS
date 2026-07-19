"""agent: conversations, messages, pending actions + gemini key pool

Revision ID: a7c2e9f31d55
Revises: 0a6bd482fe1f
Create Date: 2026-07-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e9f31d55"
down_revision: str | Sequence[str] | None = "0a6bd482fe1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, plain JSON elsewhere — same variant the models use.
_json = sa.JSON().with_variant(JSONB(), "postgresql")

_surface = sa.Enum("web", "telegram", name="agent_surface")
_role = sa.Enum("user", "assistant", "tool", name="agent_message_role")
_action_status = sa.Enum("pending", "confirmed", "cancelled", "expired", name="agent_action_status")


def upgrade() -> None:
    """Upgrade schema."""
    # Conversational agent (§ agent): persisted chat threads shared by the
    # web dashboard and the Telegram bot.
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("surface", _surface, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_conversations_user_id"), "agent_conversations", ["user_id"], unique=False
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", _role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("tool_payload", _json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_messages_conversation_id"),
        "agent_messages",
        ["conversation_id"],
        unique=False,
    )

    # High-impact tool calls frozen for explicit confirmation: the model
    # proposes, the user confirms, the dispatcher executes the stored args
    # verbatim. Expiry bounds how long a proposal stays actionable.
    op.create_table(
        "agent_pending_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("args", _json, nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("status", _action_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_pending_actions_conversation_id"),
        "agent_pending_actions",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_agent_pending_actions_conversation_id"), table_name="agent_pending_actions"
    )
    op.drop_table("agent_pending_actions")
    op.drop_index(op.f("ix_agent_messages_conversation_id"), table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index(op.f("ix_agent_conversations_user_id"), table_name="agent_conversations")
    op.drop_table("agent_conversations")
    # Autogenerate forgets Postgres enum types on downgrade — drop explicitly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="agent_action_status").drop(bind, checkfirst=True)
        sa.Enum(name="agent_message_role").drop(bind, checkfirst=True)
        sa.Enum(name="agent_surface").drop(bind, checkfirst=True)
