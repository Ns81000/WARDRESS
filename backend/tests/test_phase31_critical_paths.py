"""Real coverage for the two safety-critical paths the audit found untested
(Finding: "Two safety-critical code paths have zero test coverage"):

1. The remediation webhook firing path — ``worker/remediation_tasks._fire``
   and its Celery wrapper ``fire_remediation`` — driven against a real local
   HTTP receiver through the real SSRF-pinning transport: entry-contract ids,
   non-firing states, missing prerequisites, redirect/timeout failure mapping,
   and honest terminal rows.

2. The agent engine turn loop — ``app.agent.engine.run_turn`` dispatch,
   refusal, degradation and iteration logic — driven end to end with a
   scripted model standing in ONLY for the LLM boundary (the technique the
   audit itself directs); executors, guard, persistence and the real
   Postgres schema all run for real.

Parts of both paths gained coverage after the audit was filed (atomic-claim
races in Phases 4+5, containment in Phase 11, guard claims and RBAC parity in
Phase 25, SSRF/fetchability/resweep in Phase 26); this module closes the
remaining holes verified by exhaustive grep at Phase 31 time: bad-id/error
wrapper contracts, execution-missing / not-queued-dismissed / prereqs-missing
branches, redirect and timeout mappings, MAX_ITERATIONS exhaustion, empty
message, unconfigured/non-tool model, LLM-unavailable mid-turn, unknown-tool
refusal, malformed tool args, executor-crash containment.
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.agent import engine
from app.agent.tools import get_tool
from app.crypto import encrypt_text
from app.llm import LLMUnavailable
from app.models import (
    AgentConversation,
    AgentMessage,
    AgentMessageRole,
    AgentPendingAction,
    AgentSurface,
    Baseline,
    BaselineStatus,
    RemediationExecution,
    RemediationExecutionStatus,
    RemediationHook,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
)
from worker.remediation_tasks import _fire, fire_remediation

# --- webhook firing path -----------------------------------------------------
# Real receiver: raw asyncio TCP server like test_remediation_claim_race's
# canary, extended with a Location header and a controllable delay so the
# production timeout (constant patched to a fast value — a config knob, not
# logic) maps a genuine transport ReadTimeout.


class _Receiver:
    def __init__(self) -> None:
        self.requests = 0
        self.status_code = 200
        self.delay = 0.0
        self.url = ""


@pytest.fixture
async def receiver():
    r = _Receiver()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        r.requests += 1
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        if r.delay:
            await asyncio.sleep(r.delay)
        body = b"ok"
        extra = "Location: http://127.0.0.1/moved\r\n" if r.status_code == 302 else ""
        head = (
            f"HTTP/1.1 {r.status_code} X\r\n{extra}"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode()
        writer.write(head + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    r.url = f"http://127.0.0.1:{port}/fire"
    try:
        yield r
    finally:
        server.close()
        await server.wait_closed()


async def _seed_firing(db_factory, admin_user, url: str | None = None):
    """A queued (auto-executable) execution whose hook points at a real,
    opted-in loopback receiver — the full legal shape for a firing."""
    async with db_factory() as db:
        site = Site(name="FireTarget", url=f"https://fire-{uuid.uuid4().hex[:8]}.example.com")
        site.created_by = admin_user.id
        db.add(site)
        await db.flush()
        hook = RemediationHook(
            site_id=site.id,
            name="p31-hook",
            action_type="custom_webhook",
            trigger_threshold=0.5,
            webhook_url_encrypted=encrypt_text(url or "http://127.0.0.1:9/fire"),
            allow_private_networks=True,
            requires_manual_confirm=False,
        )
        db.add(hook)
        await db.flush()
        baseline = Baseline(
            site_id=site.id, status=BaselineStatus.ready, is_current=True, content_hash="x"
        )
        db.add(baseline)
        await db.flush()
        scan = Scan(
            site_id=site.id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
        )
        db.add(scan)
        await db.flush()
        ex = RemediationExecution(
            hook_id=hook.id,
            site_id=site.id,
            scan_id=scan.id,
            status=RemediationExecutionStatus.queued,
            hook_name="p31-hook",
            action_type="custom_webhook",
            risk_score=0.9,
        )
        db.add(ex)
        await db.commit()
        await db.refresh(ex)
        return ex, hook


async def _execution_row(db_factory, ex_id):
    async with db_factory() as db:
        return await db.scalar(select(RemediationExecution).where(RemediationExecution.id == ex_id))


async def test_wrapper_rejects_non_uuid_id():
    assert await asyncio.to_thread(fire_remediation, "not-a-uuid") == "bad-id"


async def test_wrapper_swallows_internal_errors_never_propagates(
    db_factory, admin_user, monkeypatch
):
    import worker.remediation_tasks as rt

    ex, _hook = await _seed_firing(db_factory, admin_user)

    @asynccontextmanager
    async def broken_session():
        raise RuntimeError("engine pipe gone")
        yield

    monkeypatch.setattr(rt, "task_session", broken_session)
    # The Celery body runs on a worker thread with no ambient event loop;
    # to_thread reproduces that honestly under pytest-asyncio.
    result = await asyncio.to_thread(fire_remediation, str(ex.id))
    assert result == "error"
    row = await _execution_row(db_factory, ex.id)
    assert row.status is RemediationExecutionStatus.queued


async def test_missing_execution_row_reports_missing():
    assert await _fire(uuid.uuid4()) == "execution-missing"


async def test_dismissed_execution_never_fires(db_factory, admin_user, receiver):
    ex, _hook = await _seed_firing(db_factory, admin_user, receiver.url)
    async with db_factory() as db:
        row = await db.get(RemediationExecution, ex.id)
        row.status = RemediationExecutionStatus.dismissed
        await db.commit()
    assert await _fire(ex.id) == "not-queued-dismissed"
    assert receiver.requests == 0


async def test_hook_deletion_cascades_queued_execution_so_nothing_fires(
    db_factory, admin_user, receiver
):
    """The prereqs-missing arm in _fire is defensive depth only: every
    execution FK (hook/site/scan) is ON DELETE CASCADE (models.py), so a
    persisted execution whose prerequisites are gone cannot exist under
    enforced FKs — the same enforced-FK semantics Phase 1 pinned for
    baselines. Pinned here from the firing side: deleting the hook removes
    the queued execution itself, and firing it reports missing rather than
    POSTing anything."""
    ex, hook = await _seed_firing(db_factory, admin_user, receiver.url)
    async with db_factory() as db:
        await db.execute(text("DELETE FROM remediation_hooks WHERE id = :id"), {"id": str(hook.id)})
        await db.commit()
    assert await _execution_row(db_factory, ex.id) is None
    assert await _fire(ex.id) == "execution-missing"
    assert receiver.requests == 0


async def test_redirect_response_is_not_followed(db_factory, admin_user, receiver):
    receiver.status_code = 302
    ex, _hook = await _seed_firing(db_factory, admin_user, receiver.url)
    assert await _fire(ex.id) == "failed"
    row = await _execution_row(db_factory, ex.id)
    assert row.status is RemediationExecutionStatus.failed
    assert row.detail == "webhook returned HTTP 302"
    assert receiver.requests == 1


async def test_timeout_maps_to_failed_readtimeout_detail(
    db_factory, admin_user, receiver, monkeypatch
):
    import app.remediation as remediation_module

    receiver.delay = 1.0
    monkeypatch.setattr(remediation_module, "WEBHOOK_TIMEOUT_S", 0.2)
    ex, _hook = await _seed_firing(db_factory, admin_user, receiver.url)
    assert await _fire(ex.id) == "failed"
    row = await _execution_row(db_factory, ex.id)
    assert row.status is RemediationExecutionStatus.failed
    assert row.detail == "webhook unreachable: ReadTimeout"


# --- agent engine turn loop ---------------------------------------------------
# Only the LLM boundary is scripted (the audit's own directed technique);
# executors, guard, persistence and Postgres are real.


def _tool_call(cid: str, name: str, args) -> SimpleNamespace:
    raw = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=raw))


def _message(content=None, tool_calls=None) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _response(message) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _ScriptedTask:
    supports_tools = True
    label = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def acompletion(self, *, messages, tools=None, tool_choice=None):
        self.calls.append(messages)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, prompt):
        return "ok"


class _AlwaysToolTask:
    """Complies forever with a harmless tier-0 read call."""

    supports_tools = True
    label = "always-tool"

    def __init__(self):
        self.calls: list[list[dict]] = []

    async def acompletion(self, *, messages, tools=None, tool_choice=None):
        self.calls.append(messages)
        return _response(_message(tool_calls=[_tool_call(f"c{len(self.calls)}", "list_sites", {})]))

    async def generate(self, prompt):
        return "ok"


async def _seed_conversation(db_factory, user) -> uuid.UUID:
    async with db_factory() as db:
        conv = AgentConversation(user_id=user.id, surface=AgentSurface.web)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id


async def _run(db_factory, analyst_user, monkeypatch, conv_id, task, message="hello"):
    async def _resolve(db, name):
        return task

    monkeypatch.setattr(engine, "resolve_task", _resolve)
    async with db_factory() as db:
        conv = await db.get(AgentConversation, conv_id)
        user = await db.get(type(analyst_user), analyst_user.id)
        events = [
            ev.to_dict()
            async for ev in engine.run_turn(
                db, conversation=conv, user=user, user_message=message, surface="agent-web"
            )
        ]
    return events, task


async def _messages(db_factory, conv_id):
    async with db_factory() as db:
        rows = (
            await db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == conv_id))
        ).all()
        for r in rows:
            db.expunge(r)
        return rows


async def _pending_rows(db_factory, conv_id):
    async with db_factory() as db:
        rows = (
            await db.scalars(
                select(AgentPendingAction).where(AgentPendingAction.conversation_id == conv_id)
            )
        ).all()
        for r in rows:
            db.expunge(r)
        return rows


def _done_texts(events):
    return [e["text"] for e in events if e["type"] == "done"]


def _tool_dones(events):
    return [e for e in events if e["type"] == "tool" and e["data"].get("state") == "done"]


def _model_bound_results(task):
    out = []
    for call in task.calls:
        for m in call:
            if m.get("role") == "tool":
                out.append(json.loads(m["content"])["result"])
    return out


async def test_empty_message_errors_without_model_or_persistence(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)

    class _NeverCalled(_ScriptedTask):
        async def acompletion(self, **kwargs):  # pragma: no cover - guard
            pytest.fail("model consulted for an empty message")

    task = _NeverCalled([])
    async with db_factory() as db:
        conv = await db.get(AgentConversation, conv_id)
        user = await db.get(type(analyst_user), analyst_user.id)
        events = [
            ev.to_dict()
            async for ev in engine.run_turn(
                db, conversation=conv, user=user, user_message="   ", surface="agent-web"
            )
        ]
    assert [e["type"] for e in events] == ["error"]
    assert task.calls == []
    assert await _messages(db_factory, conv_id) == []


async def test_no_model_configured_persists_guidance_and_ends_turn(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)

    async def _none(db, name):
        return None

    monkeypatch.setattr(engine, "resolve_task", _none)

    class _NeverCalled(_ScriptedTask):
        async def acompletion(self, **kwargs):  # pragma: no cover - guard
            pytest.fail("model consulted with no model configured")

    task = _NeverCalled([])
    async with db_factory() as db:
        conv = await db.get(AgentConversation, conv_id)
        user = await db.get(type(analyst_user), analyst_user.id)
        events = [
            ev.to_dict()
            async for ev in engine.run_turn(
                db, conversation=conv, user=user, user_message="hi", surface="agent-web"
            )
        ]
    assert _done_texts(events) == [
        "No AI model is configured for the assistant. An admin can assign a "
        "tool-capable model to Agent Chat in Settings \u2192 AI providers."
    ]
    assert task.calls == []
    msgs = await _messages(db_factory, conv_id)
    assert [m.role for m in msgs] == [AgentMessageRole.user, AgentMessageRole.assistant]


async def test_non_tool_model_declines_before_any_model_call(db_factory, analyst_user, monkeypatch):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _ScriptedTask([])

    class _NoTools(_ScriptedTask):
        supports_tools = False

        async def acompletion(self, **kwargs):  # pragma: no cover - guard
            pytest.fail("non-tool model reached the loop")

    task = _NoTools([])
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    assert "doesn't support tool calling" in _done_texts(events)[0]
    assert task.calls == []


async def test_llm_unavailable_mid_turn_yields_error_and_persists(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _ScriptedTask([LLMUnavailable("all keys exhausted")])
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    assert [e["type"] for e in events] == ["error"]
    assert "unavailable right now" in events[0]["text"]
    msgs = await _messages(db_factory, conv_id)
    assert msgs[-1].role is AgentMessageRole.assistant
    assert "unavailable right now" in msgs[-1].content


async def test_unknown_tool_refusal_feeds_back_and_turn_completes(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _ScriptedTask(
        [
            _response(_message(tool_calls=[_tool_call("c1", "totally_bogus_tool", {})])),
            _response(_message(content="All set.")),
        ]
    )
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    assert _tool_dones(events) == []
    assert _done_texts(events) == ["All set."]
    results = _model_bound_results(task)
    assert results[-1] == {"error": "That action is not available to you."}
    assert await _pending_rows(db_factory, conv_id) == []


async def test_malformed_arguments_parse_to_empty_and_execution_continues(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _ScriptedTask(
        [
            _response(_message(tool_calls=[_tool_call("c1", "list_sites", "@@not json{")])),
            _response(_message(content="Done listing.")),
        ]
    )
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    dones = _tool_dones(events)
    assert [d["data"]["tool"] for d in dones] == ["list_sites"]
    assert dones[0]["data"]["ok"] is True
    assert _done_texts(events) == ["Done listing."]
    results = _model_bound_results(task)
    assert "sites" in results[0]


async def test_executor_crash_is_contained_and_never_leaks_internals(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)

    async def boom(ctx, args):
        raise RuntimeError("internal detail: db password hunter2")

    monkeypatch.setattr(get_tool("get_site"), "executor", boom)
    task = _ScriptedTask(
        [
            _response(_message(tool_calls=[_tool_call("c1", "get_site", {"site": "x"})])),
            _response(_message(content="Understood.")),
        ]
    )
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    dones = _tool_dones(events)
    assert dones[0]["data"]["ok"] is False
    assert _model_bound_results(task)[-1] == {"error": "That action failed unexpectedly."}
    assert _done_texts(events) == ["Understood."]
    everything = json.dumps(task.calls) + json.dumps(
        [
            {"content": m.content, "payload": m.tool_payload}
            for m in await _messages(db_factory, conv_id)
        ],
        default=str,
    )
    assert "hunter2" not in everything
    assert "internal detail" not in everything


async def test_toolerror_message_is_surfaced_verbatim_and_turn_completes(
    db_factory, analyst_user, monkeypatch
):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _ScriptedTask(
        [
            _response(
                _message(tool_calls=[_tool_call("c1", "get_site", {"site": "missing-site"})])
            ),
            _response(_message(content="Okay, noted.")),
        ]
    )
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    dones = _tool_dones(events)
    assert dones[0]["data"]["ok"] is False
    fed_back = _model_bound_results(task)[-1]
    assert "error" in fed_back and fed_back["error"]
    assert _done_texts(events) == ["Okay, noted."]


async def test_max_iterations_bound_ends_turn_with_wrapup(db_factory, analyst_user, monkeypatch):
    conv_id = await _seed_conversation(db_factory, analyst_user)
    task = _AlwaysToolTask()
    events, _ = await _run(db_factory, analyst_user, monkeypatch, conv_id, task)
    assert len(task.calls) == engine.MAX_ITERATIONS
    assert len(_tool_dones(events)) == engine.MAX_ITERATIONS
    assert _done_texts(events) == [
        "I did several steps but couldn't wrap up cleanly \u2014 check the dashboard "
        "or try a narrower request."
    ]
    assert await _pending_rows(db_factory, conv_id) == []
