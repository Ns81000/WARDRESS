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

from sqlalchemy import select, update
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
    message on any refusal (missing, foreign, expired, role change).

    The pending→confirmed/cancelled transition is claimed atomically with a
    conditional UPDATE whose rowcount is the arbiter (same primitive as
    refresh-token rotation and the remediation confirm queue): K simultaneous
    confirms of one card — double-click, dashboard + Telegram same account —
    would each pass a plain status read and each execute the frozen args.
    Postgres re-evaluates the WHERE when a losing writer's lock wait ends, so
    exactly one request wins; every loser observes the winner's state."""
    action = await db.scalar(select(AgentPendingAction).where(AgentPendingAction.id == action_id))
    if action is None:
        raise ToolError("That action no longer exists.")
    if action.user_id != user.id:
        # Ownership is strict: the confirmer must be the proposer.
        raise ToolError("This confirmation belongs to a different user.")

    if confirm:
        # Re-check availability and RBAC *before* claiming so a refused
        # confirm leaves the card pending exactly as before — a role change
        # between propose and confirm must not burn the action.
        tool = get_tool(action.tool)
        if tool is None:
            raise ToolError("This action's tool is no longer available.")
        if not can_call(tool, user.role):
            raise ToolError("Your role no longer permits this action.")

    now = utcnow()
    target = AgentActionStatus.confirmed if confirm else AgentActionStatus.cancelled
    claim = await db.execute(
        update(AgentPendingAction)
        .where(
            AgentPendingAction.id == action_id,
            AgentPendingAction.status == AgentActionStatus.pending,
            # Expired cards settle as expired below, never confirm/cancel.
            AgentPendingAction.expires_at >= now,
        )
        .values(status=target, resolved_at=now)
    )
    if claim.rowcount == 0:
        # Lost the race or the clock passed expiry. Refresh to observe the
        # committed winner state before answering.
        await db.refresh(action)
        if action.status == AgentActionStatus.pending:
            # Still pending ⇒ only the expiry predicate failed: settle it as
            # expired (conditional again, so racing expirers stay coherent).
            await db.execute(
                update(AgentPendingAction)
                .where(
                    AgentPendingAction.id == action_id,
                    AgentPendingAction.status == AgentActionStatus.pending,
                )
                .values(status=AgentActionStatus.expired, resolved_at=utcnow())
            )
            await db.commit()
            raise ToolError("This action expired — ask again if you still want it.")
        raise ToolError(f"This action was already {action.status.value}.")

    # Mark confirmed/cancelled before executing so a crash can't leave a
    # re-runnable pending row; the executor's own commit persists the actual
    # change.
    await db.commit()
    await db.refresh(action)

    if not confirm:
        return action, None

    ctx = ToolContext(db=db, user=user, surface=surface)
    result = await tool.executor(ctx, dict(action.args or {}))
    return action, result


async def expire_stale(db: AsyncSession) -> int:
    """Best-effort janitor: flip expired pending rows. Returns count.

    One conditional UPDATE rather than select-then-mutate: the status
    predicate is re-evaluated at write time, so an action confirmed or
    cancelled in between can never be overwritten to expired."""
    result = await db.execute(
        update(AgentPendingAction)
        .where(
            AgentPendingAction.status == AgentActionStatus.pending,
            AgentPendingAction.expires_at < utcnow(),
        )
        .values(status=AgentActionStatus.expired, resolved_at=utcnow())
    )
    await db.commit()
    return result.rowcount
