"""The agent turn loop — one shared core for the web chat and the Telegram bot.

A user turn drives a bounded Gemini function-calling loop:

  1. Build a compact context (system instruction + rolling summary + recent
     transcript) via :mod:`app.agent.context`.
  2. Call gemini-flash-latest through the multi-key rotation pool
     (:class:`app.llm.KeyPool`) with the tools the user's *role* permits —
     nothing above their permissions is ever declared.
  3. For each function call the model emits: look up the tool, enforce RBAC
     in code (never trust the model), and either
       - execute it now (tier 0/1: reads and safe writes), or
       - freeze it for confirmation (tier >= 2) and stop the loop, surfacing
         a confirmation card the user must approve with a button press.
  4. Feed tool results back and repeat, capped at ``MAX_ITERATIONS`` calls
     so a misbehaving model can't spin.

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
from app.llm import LLMUnavailable, resolve_provider
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


def _gemini_config(tools: list, system_instruction: str):
    """Build the GenerateContentConfig for a tools turn. Automatic function
    calling is disabled so *we* gate every call (RBAC + confirmation); the
    SDK must hand back raw function_call parts instead of executing them."""
    from google.genai import types

    declarations = [t.declaration() for t in tools]
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
    )


def _new_user_content(text: str):
    from google.genai import types

    return types.Content(role="user", parts=[types.Part(text=text)])


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

    provider = await resolve_provider(db)
    if provider is None or provider.kind != "gemini" or provider.pool is None:
        # The agent needs Gemini tool-calling specifically; Ollama has no
        # function-calling contract here. Degrade with a clear message.
        msg = (
            "The assistant needs a Gemini API key. Add one in Settings → AI providers "
            "to chat with Wardress."
        )
        await _persist_message(db, conversation.id, AgentMessageRole.assistant, msg)
        yield AgentEvent("done", msg)
        return

    tools = tools_for_role(user.role)
    system_instruction = agent_context.build_system_instruction(user, surface)
    try:
        config = _gemini_config(tools, system_instruction)
    except ImportError:
        yield AgentEvent("error", "The Gemini SDK is unavailable on the server.")
        return

    # Seed the model contents from the compact transcript, then append the
    # new user turn.
    contents = await agent_context.build_contents(db, conversation, user_message)

    final_text = ""
    for _ in range(MAX_ITERATIONS):
        try:
            response = await provider.pool.call(contents=contents, config=config)
        except LLMUnavailable as exc:
            msg = f"The assistant is unavailable right now: {exc}"
            await _persist_message(db, conversation.id, AgentMessageRole.assistant, msg)
            yield AgentEvent("error", msg)
            return

        calls = list(getattr(response, "function_calls", None) or [])
        if not calls:
            final_text = (getattr(response, "text", None) or "").strip()
            break

        # Record the model's function-call turn verbatim so the follow-up
        # request has the required call/thought signatures.
        model_content = response.candidates[0].content
        contents.append(model_content)

        # Execute (or gate) each requested call, collecting tool responses.
        tool_response_parts = []
        stop_for_confirm = False
        for fc in calls:
            name = fc.name
            args = dict(fc.args or {})
            tool = get_tool(name)
            if tool is None or not can_call(tool, user.role):
                # Unknown tool, or above the user's role: report a refusal to
                # the model as the tool result (it never saw the declaration,
                # but a hallucinated call still gets a clean answer).
                result = {"error": "That action is not available to you."}
                tool_response_parts.append(_function_response(name, result))
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
            await _persist_message(
                db,
                conversation.id,
                AgentMessageRole.tool,
                json.dumps(result)[:2000],
                tool_name=name,
                tool_payload=result if isinstance(result, dict) else None,
            )
            yield AgentEvent("tool", _tool_label(name), {"tool": name, "state": "done", "ok": ok})
            tool_response_parts.append(_function_response(name, result))

        if stop_for_confirm:
            # The turn pauses here; confirming resumes via the confirm endpoint.
            return

        contents.append(_tool_content(tool_response_parts))
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
    await agent_context.maybe_summarize(db, conversation, provider.pool)
    await db.commit()
    yield AgentEvent("done", final_text)


def _function_response(name: str, result: dict):
    from google.genai import types

    return types.Part.from_function_response(name=name, response={"result": result})


def _tool_content(parts: list):
    from google.genai import types

    return types.Content(role="tool", parts=parts)
