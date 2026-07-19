"""Confirm-before-execute guard for high-impact agent actions.

Tier >= TIER_HIGH_IMPACT tool calls are never executed inline. The
dispatcher freezes the proposed call (tool + args, verbatim) into an
`agent_pending_actions` row and surfaces a confirmation card. When the
user confirms — a button press, never model output — the stored args are
executed exactly as frozen. RBAC, ownership and expiry are re-checked at
confirm time, so a stale card or a role change between propose and
confirm fails closed.

One pending action per conversation: proposing a new one supersedes
(cancels) the old — a chat can't accumulate an approval backlog.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import (
    TIER_HIGH_IMPACT,
    Tool,
    ToolContext,
    ToolError,
    can_call,
    get_tool,
)
from app.models import (
    AgentActionStatus,
    AgentPendingAction,
    User,
    ensure_utc,
    utcnow,
)

PENDING_TTL = timedelta(minutes=10)


def needs_confirmation(tool: Tool) -> bool:
    return tool.tier >= TIER_HIGH_IMPACT


async def create_pending(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user: User,
    tool: Tool,
    args: dict,
) -> AgentPendingAction:
    """Freeze a proposed high-impact call, superseding any prior pending
    action in this conversation. Commits."""
    prior = (
        await db.scalars(
            select(AgentPendingAction).where(
                AgentPendingAction.conversation_id == conversation_id,
                AgentPendingAction.status == AgentActionStatus.pending,
            )
        )
    ).all()
    for row in prior:
        row.status = AgentActionStatus.cancelled
        row.resolved_at = utcnow()
    summary = tool.summarize(args) if tool.summarize else f"{tool.name}({args})"
    action = AgentPendingAction(
        conversation_id=conversation_id,
        user_id=user.id,
        tool=tool.name,
        args=args,
        summary=summary[:500],
        expires_at=utcnow() + PENDING_TTL,
    )
    db.add(action)
    await db.commit()
    return action


async def resolve_pending(
    db: AsyncSession,
    *,
    action_id: uuid.UUID,
    user: User,
    confirm: bool,
    surface: str,
) -> tuple[AgentPendingAction, dict | None]:
    """Confirm or cancel a pending action. On confirm, executes the frozen
    args and returns (action, result). Raises ToolError with a user-safe
    message on any refusal (missing, foreign, expired, role change)."""
    action = await db.scalar(select(AgentPendingAction).where(AgentPendingAction.id == action_id))
    if action is None:
        raise ToolError("That action no longer exists.")
    if action.user_id != user.id:
        # Ownership is strict: the confirmer must be the proposer.
        raise ToolError("This confirmation belongs to a different user.")
    if action.status != AgentActionStatus.pending:
        raise ToolError(f"This action was already {action.status.value}.")
    expires = ensure_utc(action.expires_at)
    if expires is not None and expires < utcnow():
        action.status = AgentActionStatus.expired
        action.resolved_at = utcnow()
        await db.commit()
        raise ToolError("This action expired — ask again if you still want it.")

    if not confirm:
        action.status = AgentActionStatus.cancelled
        action.resolved_at = utcnow()
        await db.commit()
        return action, None

    tool = get_tool(action.tool)
    if tool is None:
        raise ToolError("This action's tool is no longer available.")
    if not can_call(tool, user.role):
        raise ToolError("Your role no longer permits this action.")

    # Mark confirmed before executing so a crash can't leave a re-runnable
    # pending row; the executor's own commit persists the actual change.
    action.status = AgentActionStatus.confirmed
    action.resolved_at = utcnow()
    await db.commit()

    ctx = ToolContext(db=db, user=user, surface=surface)
    result = await tool.executor(ctx, dict(action.args or {}))
    return action, result


async def expire_stale(db: AsyncSession) -> int:
    """Best-effort janitor: flip expired pending rows. Returns count."""
    stale = (
        await db.scalars(
            select(AgentPendingAction).where(
                AgentPendingAction.status == AgentActionStatus.pending,
                AgentPendingAction.expires_at < utcnow(),
            )
        )
    ).all()
    for row in stale:
        row.status = AgentActionStatus.expired
        row.resolved_at = utcnow()
    if stale:
        await db.commit()
    return len(stale)
