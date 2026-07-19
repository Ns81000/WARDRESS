"""Conversational agent endpoints (§ agent): /api/agent/*.

The message endpoint streams the turn as Server-Sent Events over a plain
StreamingResponse — no websocket infra, fits the async stack natively.
Event wire shape (one JSON object per `data:` line):
  {"type": "tool" | "confirm" | "done" | "error", "text": ..., "data": {...}}

Auth: any authenticated role can chat (the tool registry itself filters
what each role can do); conversations are strictly per-user — user A can
never read or continue user B's thread. Confirm/cancel re-validates
ownership, RBAC, and expiry in the guard.
"""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.engine import AgentEvent, run_turn
from app.agent.guard import resolve_pending
from app.agent.tools import ToolError
from app.db import get_db
from app.deps import CurrentUser
from app.models import (
    AgentActionStatus,
    AgentConversation,
    AgentMessage,
    AgentPendingAction,
    AgentSurface,
    User,
)
from app.schemas import (
    AgentConversationDetailOut,
    AgentConversationOut,
    AgentMessageIn,
    AgentMessageOut,
    AgentPendingActionOut,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

DB = Annotated[AsyncSession, Depends(get_db)]

_MAX_CONVERSATIONS = 50


async def _own_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user: User
) -> AgentConversation:
    conversation = await db.scalar(
        select(AgentConversation).where(AgentConversation.id == conversation_id)
    )
    if conversation is None or conversation.user_id != user.id:
        # 404 (not 403) for foreign threads: their existence is not leaked.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[AgentConversationOut])
async def list_conversations(user: CurrentUser, db: DB) -> list[AgentConversationOut]:
    rows = (
        await db.scalars(
            select(AgentConversation)
            .where(AgentConversation.user_id == user.id)
            .order_by(AgentConversation.updated_at.desc())
            .limit(_MAX_CONVERSATIONS)
        )
    ).all()
    return [AgentConversationOut.model_validate(r) for r in rows]


@router.post(
    "/conversations", response_model=AgentConversationOut, status_code=status.HTTP_201_CREATED
)
async def create_conversation(user: CurrentUser, db: DB) -> AgentConversationOut:
    conversation = AgentConversation(user_id=user.id, surface=AgentSurface.web)
    db.add(conversation)
    await db.commit()
    return AgentConversationOut.model_validate(conversation)


@router.get("/conversations/{conversation_id}", response_model=AgentConversationDetailOut)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, db: DB
) -> AgentConversationDetailOut:
    conversation = await _own_conversation(db, conversation_id, user)
    messages = (
        await db.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .order_by(AgentMessage.created_at)
        )
    ).all()
    pending = await db.scalar(
        select(AgentPendingAction).where(
            AgentPendingAction.conversation_id == conversation.id,
            AgentPendingAction.status == AgentActionStatus.pending,
        )
    )
    return AgentConversationDetailOut(
        **AgentConversationOut.model_validate(conversation).model_dump(),
        messages=[AgentMessageOut.model_validate(m) for m in messages],
        pending_action=AgentPendingActionOut.model_validate(pending) if pending else None,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DB) -> None:
    conversation = await _own_conversation(db, conversation_id, user)
    await db.delete(conversation)
    await db.commit()


def _sse(event: AgentEvent) -> str:
    return f"data: {json.dumps(event.to_dict())}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: AgentMessageIn,
    user: CurrentUser,
    db: DB,
) -> StreamingResponse:
    """One user turn, streamed as SSE. The generator commits as it goes, so
    a dropped connection still leaves a coherent transcript."""
    conversation = await _own_conversation(db, conversation_id, user)

    async def stream():
        try:
            async for event in run_turn(
                db,
                conversation=conversation,
                user=user,
                user_message=body.message,
                surface="agent-web",
            ):
                yield _sse(event)
        except Exception:  # noqa: BLE001 — the stream must end with an event
            yield _sse(AgentEvent("error", "The assistant hit an unexpected error."))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/actions/{action_id}/confirm")
async def confirm_action(action_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Execute a frozen high-impact action. The guard re-checks ownership,
    RBAC and expiry; the stored args run verbatim."""
    try:
        action, result = await resolve_pending(
            db, action_id=action_id, user=user, confirm=True, surface="agent-web"
        )
    except ToolError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"status": action.status.value, "result": result}


@router.post("/actions/{action_id}/cancel")
async def cancel_action(action_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    try:
        action, _ = await resolve_pending(
            db, action_id=action_id, user=user, confirm=False, surface="agent-web"
        )
    except ToolError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return {"status": action.status.value}
