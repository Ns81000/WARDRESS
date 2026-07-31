"""The agent turn loop — one shared core for the web chat and the Telegram bot.

A user turn drives a bounded tool-calling loop against whatever model is
assigned to the ``agent_chat`` task (any tool-capable provider — see
:mod:`app.llm`), through litellm's provider-agnostic ``tools`` parameter:

  1. Build a compact context (system instruction + rolling summary + recent
     transcript) via :mod:`app.agent.context`, as OpenAI-style chat messages.
  2. Call the assigned model through :func:`app.llm.resolve_task` with the
     tools the user's *role* permits — nothing above their permissions is ever
     declared.
  3. For each tool call the model emits: look up the tool, enforce RBAC in code
     (never trust the model), and either
       - execute it now (tier 0/1: reads and safe writes), or
       - freeze it for confirmation (tier >= 2) and stop the loop, surfacing a
         confirmation card the user must approve with a button press.
  4. Feed tool results back and repeat, capped at ``MAX_ITERATIONS`` calls so a
     misbehaving model can't spin.

The loop emits a stream of :class:`AgentEvent` objects. Both surfaces consume
the same events: the web router serialises them as SSE, the Telegram bot folds
them into a single reply. The engine never imports FastAPI or python-telegram-
bot — it is transport-agnostic on purpose.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import context as agent_context
from app.agent.guard import create_pending, needs_confirmation
from app.agent.tools import (
    ToolContext,
    ToolError,
    can_call,
    get_tool,
    tools_for_role,
)
from app.llm import LLMUnavailable, resolve_task
from app.models import (
    AgentConversation,
    AgentMessage,
    AgentMessageRole,
    User,
    utcnow,
)

logger = logging.getLogger(__name__)

# Hard cap on tool round-trips per user turn: a plan+call then a final answer
# is the common case (2); 5 leaves room for a short compositional chain
# (e.g. resolve site -> run scan -> report) without ever letting the model
# loop unbounded.
MAX_ITERATIONS = 5


@dataclass
class AgentEvent:
    """One item in the turn's event stream. `type` drives rendering:
    - text       : assistant prose (delta or whole message)
    - tool       : a tool started/finished (name + friendly label + ok)
    - confirm    : a high-impact action awaits confirmation (card payload)
    - done       : the turn finished (final assistant text)
    - error      : the turn failed (user-safe message)
    """

    type: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.text:
            out["text"] = self.text
        if self.data:
            out["data"] = self.data
        return out


# Friendly labels for the tool activity chip (surface-agnostic copy).
_TOOL_LABELS = {
    "list_sites": "Listing sites",
    "get_site": "Reading site",
    "get_status_overview": "Checking status",
    "list_scans": "Listing scans",
    "get_scan_findings": "Reading findings",
    "list_alerts": "Listing alerts",
    "explain_incident": "Explaining incident",
    "run_scan_now": "Starting a scan",
    "acknowledge_alert": "Acknowledging alert",
    "mute_site": "Muting site",
    "unmute_site": "Unmuting site",
    "add_site": "Adding site",
    "rebaseline_site": "Rebaselining",
    "set_flag_threshold": "Adjusting threshold",
    "set_scan_interval": "Adjusting interval",
    "create_suppression_rule": "Adding suppression rule",
    "list_suppression_rules": "Checking suppression rules",
    "list_remediation_hooks": "Checking remediation hooks",
    "delete_site": "Deleting site",
}


def _tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, name.replace("_", " ").capitalize())


async def _persist_message(
    db: AsyncSession,
    conversation_id: Any,
    role: AgentMessageRole,
    content: str,
    *,
    tool_name: str | None = None,
    tool_payload: dict | None = None,
) -> None:
    db.add(
        AgentMessage(
            conversation_id=conversation_id,
            role=role,
            content=content or "",
            tool_name=tool_name,
            tool_payload=tool_payload,
        )
    )
    await db.commit()


def _assistant_tool_call_message(message: Any) -> dict:
    """Serialise the model's tool-call turn to a plain OpenAI-style assistant
    message so the follow-up request carries the required call ids."""
    calls = []
    for tc in getattr(message, "tool_calls", None) or []:
        calls.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
        )
    return {
        "role": "assistant",
        "content": getattr(message, "content", "") or "",
        "tool_calls": calls,
    }


# Field-level caps applied *before* serialization so the emitted JSON is
# always valid (slicing the serialized string could cut mid-object/string).
_MAX_STR_FIELD = 1000
_MAX_LIST_ITEMS = 50
_MAX_RESULT_CHARS = 4000


def _bound_result(value: Any, _depth: int = 0) -> Any:
    """Recursively clip a tool result's fields (long strings, long lists) so
    it serializes to bounded, *valid* JSON. Truncation happens on the data,
    never on the serialized string."""
    if _depth > 6:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR_FIELD else value[:_MAX_STR_FIELD] + "…"
    if isinstance(value, dict):
        return {k: _bound_result(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        clipped = [_bound_result(v, _depth + 1) for v in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            clipped.append(f"…(+{len(value) - _MAX_LIST_ITEMS} more)")
        return clipped
    return value


def _dump_bounded(obj: Any) -> str:
    """Serialize an already field-bounded object, with a final hard char cap
    as a backstop. The field caps keep this from ever truncating mid-token in
    practice; the outer slice only guards against pathologically wide dicts."""
    text = json.dumps(obj)
    if len(text) <= _MAX_RESULT_CHARS:
        return text
    # Backstop: re-serialize a trimmed marker object so output stays valid JSON.
    return json.dumps({
        "result": {"truncated": True, "note": "result too large to include in full"}
    })


def _tool_result_message(tool_call_id: str, name: str, result: dict) -> dict:
    """One OpenAI-style tool-result message, matched to its call id. The result
    fields are bounded before serialization so the content is always valid
    JSON the model can parse."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": _dump_bounded({"result": _bound_result(result)}),
    }


def _parse_tool_args(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def run_turn(
    db: AsyncSession,
    *,
    conversation: AgentConversation,
    user: User,
    user_message: str,
    surface: str,
) -> AsyncIterator[AgentEvent]:
    """Drive one user turn to completion, yielding events as it goes.

    `surface` is the audit 'via' tag ("agent-web" | "agent-telegram"). The
    caller has already loaded/created the conversation and verified the user
    owns it. This function persists the user message, the assistant turns, and
    any tool results, and commits as it goes so a dropped connection leaves a
    coherent transcript."""
    user_message = (user_message or "").strip()
    if not user_message:
        yield AgentEvent("error", "Say something and I'll help.")
        return

    await _persist_message(db, conversation.id, AgentMessageRole.user, user_message)

    task = await resolve_task(db, "agent_chat")
    if task is None:
        # No model assigned to the assistant. Provider-agnostic message: any
        # tool-capable model on any provider works — not Gemini specifically.
        msg = (
            "No AI model is configured for the assistant. An admin can assign a "
            "tool-capable model to Agent Chat in Settings → AI providers."
        )
        await _persist_message(db, conversation.id, AgentMessageRole.assistant, msg)
        yield AgentEvent("done", msg)
        return
    if not task.supports_tools:
        # Defence in depth: the config API refuses to assign a non-tool model
        # to agent chat, but never let a stale/edge config attempt tool calls.
        msg = (
            "The model assigned to the assistant doesn't support tool calling. "
            "Assign a tool-capable model to Agent Chat in Settings → AI providers."
        )
        await _persist_message(db, conversation.id, AgentMessageRole.assistant, msg)
        yield AgentEvent("done", msg)
        return

    tools = tools_for_role(user.role)
    openai_tools = [t.openai_tool() for t in tools]
    system_instruction = agent_context.build_system_instruction(user, surface)

    # Seed messages: system rules + the compact transcript + new user turn.
    messages: list[dict] = [{"role": "system", "content": system_instruction}]
    messages += await agent_context.build_contents(db, conversation, user_message)

    final_text = ""
    for _ in range(MAX_ITERATIONS):
        try:
            response = await task.acompletion(
                messages=messages, tools=openai_tools, tool_choice="auto"
            )
        except LLMUnavailable as exc:
            msg = f"The assistant is unavailable right now: {exc}"
            await _persist_message(db, conversation.id, AgentMessageRole.assistant, msg)
            yield AgentEvent("error", msg)
            return

        message = response.choices[0].message
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        if not tool_calls:
            final_text = (getattr(message, "content", None) or "").strip()
            break

        # Record the model's tool-call turn verbatim so the follow-up request
        # carries the required call ids.
        assistant_msg = _assistant_tool_call_message(message)
        messages.append(assistant_msg)
        # CB-2: persist the assistant tool-call turn so the transcript is
        # complete.  context.build_contents skips tool rows; this is an
        # assistant row with tool_name/tool_payload metadata for replay.
        first_call = tool_calls[0].function.name if tool_calls else None
        await _persist_message(
            db,
            conversation.id,
            AgentMessageRole.assistant,
            getattr(message, "content", "") or "",
            tool_name=first_call,
            tool_payload={
                "tool_calls": [
                    {"name": tc.function.name, "args": _parse_tool_args(tc.function.arguments)}
                    for tc in tool_calls
                ]
            },
        )

        stop_for_confirm = False
        for tc in tool_calls:
            name = tc.function.name
            args = _parse_tool_args(tc.function.arguments)
            tool = get_tool(name)
            if tool is None or not can_call(tool, user.role):
                # Unknown tool, or above the user's role: report a refusal to
                # the model as the tool result (it never saw the declaration,
                # but a hallucinated call still gets a clean answer).
                result = {"error": "That action is not available to you."}
                messages.append(_tool_result_message(tc.id, name, result))
                continue

            if needs_confirmation(tool):
                action = await create_pending(
                    db,
                    conversation_id=conversation.id,
                    user=user,
                    tool=tool,
                    args=args,
                )
                await _persist_message(
                    db,
                    conversation.id,
                    AgentMessageRole.assistant,
                    action.summary or "",
                    tool_name=name,
                    tool_payload={"pending_action_id": str(action.id)},
                )
                yield AgentEvent(
                    "confirm",
                    action.summary or _tool_label(name),
                    {
                        "action_id": str(action.id),
                        "tool": name,
                        "summary": action.summary,
                        "destructive": tool.tier >= 3,
                    },
                )
                stop_for_confirm = True
                break

            yield AgentEvent("tool", _tool_label(name), {"tool": name, "state": "start"})
            try:
                result = await tool.executor(ToolContext(db=db, user=user, surface=surface), args)
                ok = True
            except ToolError as exc:
                result = {"error": str(exc)}
                ok = False
            except Exception:  # noqa: BLE001 — never leak internals to the model
                logger.exception("Agent tool %r crashed", name)
                result = {"error": "That action failed unexpectedly."}
                ok = False
            bounded_result = _bound_result(result)
            await _persist_message(
                db,
                conversation.id,
                AgentMessageRole.tool,
                _dump_bounded(bounded_result),
                tool_name=name,
                tool_payload=bounded_result if isinstance(bounded_result, dict) else None,
            )
            yield AgentEvent("tool", _tool_label(name), {"tool": name, "state": "done", "ok": ok})
            messages.append(_tool_result_message(tc.id, name, result))

        if stop_for_confirm:
            # The turn pauses here; confirming resumes via the confirm endpoint.
            return
    else:
        # Loop exhausted without a plain-text answer.
        final_text = (
            "I did several steps but couldn't wrap up cleanly — check the dashboard "
            "or try a narrower request."
        )

    if not final_text:
        final_text = "Done."
    await _persist_message(db, conversation.id, AgentMessageRole.assistant, final_text)
    conversation.updated_at = utcnow()
    await agent_context.maybe_title(db, conversation, user_message)
    # Collapse aged-out turns into the rolling summary once the window
    # overflows — token-efficiency without losing continuity. Best-effort:
    # a failed summary keeps the prior one and never breaks the turn.
    await agent_context.maybe_summarize(db, conversation, task)
    await db.commit()
    yield AgentEvent("done", final_text)
