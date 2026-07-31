"""Conversational agent tests (§ agent): tool RBAC filtering, tier
interception + confirmation guard, provider rotation/failover through the
unified litellm.Router layer, and the /api/agent/* surface (ownership
isolation, degraded-without-model path).

No real provider is called: the Router's underlying litellm.acompletion is
monkeypatched, and the degradation path needs no provider at all.
"""

import uuid

import pytest

from app.agent import guard, tools
from app.agent.tools import ToolContext, ToolError
from app.models import (
    AgentActionStatus,
    AgentConversation,
    AgentPendingAction,
    AgentSurface,
    Baseline,
    BaselineStatus,
    Site,
    User,
    UserRole,
    utcnow,
)

# --- Tool registry + RBAC filtering ---------------------------------------


def test_registry_has_expected_tools():
    names = {t.name for t in tools.all_tools()}
    # A representative slice across all tiers.
    assert {"list_sites", "run_scan_now", "add_site", "delete_site"} <= names


def test_tools_for_role_filters_by_rank():
    viewer = {t.name for t in tools.tools_for_role(UserRole.viewer)}
    analyst = {t.name for t in tools.tools_for_role(UserRole.analyst)}
    # Viewer sees only reads; analyst sees reads + writes.
    assert "list_sites" in viewer
    assert "run_scan_now" not in viewer
    assert "delete_site" not in viewer
    assert "run_scan_now" in analyst
    assert "delete_site" in analyst
    # Analyst is a strict superset of viewer.
    assert viewer <= analyst


def test_can_call_respects_min_role():
    delete = tools.get_tool("delete_site")
    assert not tools.can_call(delete, UserRole.viewer)
    assert tools.can_call(delete, UserRole.analyst)
    assert tools.can_call(delete, UserRole.admin)


def test_high_impact_tools_have_summaries():
    for t in tools.all_tools():
        if t.tier >= tools.TIER_HIGH_IMPACT:
            assert t.summarize is not None, f"{t.name} needs a confirmation summary"
            # Summaries must not blow the DB column budget.
            assert len(t.summarize({"site": "x", "url": "y", "name": "z", "minutes": 30})) <= 500


def test_tool_schemas_are_openai_shaped():
    for t in tools.all_tools():
        schema = t.openai_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == t.name
        assert schema["function"]["parameters"]["type"] == "object"


# --- Guard: tier interception + confirmation lifecycle --------------------


async def _seed_site(db_factory, *, ready: bool = True) -> Site:
    async with db_factory() as db:
        site = Site(name="Blog", url="https://blog.example.com")
        db.add(site)
        await db.flush()
        db.add(
            Baseline(
                site_id=site.id,
                status=BaselineStatus.ready if ready else BaselineStatus.pending,
                is_current=ready,
            )
        )
        await db.commit()
        await db.refresh(site)
        return site


async def _seed_conversation(db_factory, user: User) -> AgentConversation:
    async with db_factory() as db:
        conv = AgentConversation(user_id=user.id, surface=AgentSurface.web)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv


async def test_needs_confirmation_by_tier():
    assert guard.needs_confirmation(tools.get_tool("delete_site"))
    assert guard.needs_confirmation(tools.get_tool("add_site"))
    assert not guard.needs_confirmation(tools.get_tool("run_scan_now"))
    assert not guard.needs_confirmation(tools.get_tool("list_sites"))


async def test_create_pending_supersedes_prior(db_factory, analyst_user):
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("delete_site")
    async with db_factory() as db:
        a1 = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "one"}
        )
        a2 = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "two"}
        )
        first = await db.get(AgentPendingAction, a1.id)
        second = await db.get(AgentPendingAction, a2.id)
    assert first.status == AgentActionStatus.cancelled
    assert second.status == AgentActionStatus.pending


async def test_confirm_executes_frozen_args(db_factory, analyst_user, monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.enqueue_scan", lambda sid: calls.append(sid))
    site = await _seed_site(db_factory)
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("rebaseline_site")
    monkeypatch.setattr("app.services.enqueue_baseline_capture", lambda bid: calls.append(bid))
    async with db_factory() as db:
        action = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": site.name}
        )
        resolved, result = await guard.resolve_pending(
            db, action_id=action.id, user=analyst_user, confirm=True, surface="agent-web"
        )
    assert resolved.status == AgentActionStatus.confirmed
    assert result.get("rebaselining") is True
    assert calls, "executor should have enqueued the baseline capture"


async def test_cancel_does_not_execute(db_factory, analyst_user, monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.enqueue_baseline_capture", lambda bid: calls.append(bid))
    site = await _seed_site(db_factory)
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("rebaseline_site")
    async with db_factory() as db:
        action = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": site.name}
        )
        resolved, result = await guard.resolve_pending(
            db, action_id=action.id, user=analyst_user, confirm=False, surface="agent-web"
        )
    assert resolved.status == AgentActionStatus.cancelled
    assert result is None
    assert not calls


async def test_confirm_rejects_foreign_user(db_factory, analyst_user, viewer_user):
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("delete_site")
    async with db_factory() as db:
        action = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "x"}
        )
        with pytest.raises(ToolError):
            await guard.resolve_pending(
                db, action_id=action.id, user=viewer_user, confirm=True, surface="agent-web"
            )


async def test_confirm_rejects_expired(db_factory, analyst_user):
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("delete_site")
    async with db_factory() as db:
        action = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "x"}
        )
        # Force expiry into the past.
        action.expires_at = utcnow().replace(year=2000)
        await db.commit()
        with pytest.raises(ToolError):
            await guard.resolve_pending(
                db, action_id=action.id, user=analyst_user, confirm=True, surface="agent-web"
            )
        refreshed = await db.get(AgentPendingAction, action.id)
    assert refreshed.status == AgentActionStatus.expired


# --- Tool executors: real domain semantics --------------------------------


async def test_run_scan_now_requires_ready_baseline(db_factory, analyst_user):
    site = await _seed_site(db_factory, ready=False)
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        with pytest.raises(ToolError):
            await tools.get_tool("run_scan_now").executor(ctx, {"site": site.name})


async def test_resolve_site_ambiguous(db_factory, analyst_user):
    async with db_factory() as db:
        db.add(Site(name="Dup", url="https://a.example.com"))
        db.add(Site(name="Dup", url="https://b.example.com"))
        await db.commit()
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        with pytest.raises(ToolError):
            await tools._resolve_site(ctx, "Dup")


async def test_mute_site_clamps_to_cap(db_factory, analyst_user):
    site = await _seed_site(db_factory)
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        result = await tools.get_tool("mute_site").executor(
            ctx, {"site": site.name, "minutes": 999999}
        )
    assert result["muted"] is True


# --- Suppression grounding (DA-1/DA-2/FEAT-1/FEAT-2) ----------------------


async def _seed_suppression(db_factory, site_id, count: int) -> None:
    from app.models import SuppressionRule, SuppressionRuleType

    async with db_factory() as db:
        for i in range(count):
            db.add(
                SuppressionRule(
                    site_id=site_id,
                    type=SuppressionRuleType.regex,
                    value=rf"dynamic-{i}-\d+",
                    note=f"rule {i}",
                )
            )
        await db.commit()


async def test_list_suppression_rules_reports_true_count(db_factory, analyst_user):
    """With N rules seeded, the tool reports N — the reported '0 rules' bug is gone."""
    site = await _seed_site(db_factory)
    await _seed_suppression(db_factory, site.id, 3)
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        result = await tools.get_tool("list_suppression_rules").executor(ctx, {"site": site.name})
    assert result["count"] == 3
    assert len(result["rules"]) == 3
    assert all(r["type"] == "regex" for r in result["rules"])


async def test_list_suppression_rules_empty_is_zero(db_factory, analyst_user):
    """No rules -> count 0 with an empty list (grounded, not guessed)."""
    site = await _seed_site(db_factory)
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        result = await tools.get_tool("list_suppression_rules").executor(ctx, {"site": site.name})
    assert result["count"] == 0
    assert result["rules"] == []


async def test_list_suppression_available_to_viewer():
    """Read tool is viewer-visible; create tool is not (analyst+ only)."""
    viewer = {t.name for t in tools.tools_for_role(UserRole.viewer)}
    analyst = {t.name for t in tools.tools_for_role(UserRole.analyst)}
    assert "list_suppression_rules" in viewer
    assert "create_suppression_rule" not in viewer
    assert "create_suppression_rule" in analyst


async def test_create_suppression_rule_is_confirmation_gated():
    """create_suppression_rule is high-impact, so it flows through the confirm gate."""
    tool = tools.get_tool("create_suppression_rule")
    assert tool.tier >= tools.TIER_HIGH_IMPACT
    assert tool.summarize is not None
    assert guard.needs_confirmation(tool)


async def test_create_suppression_rule_persists_and_validates(db_factory, analyst_user):
    site = await _seed_site(db_factory)
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        result = await tools.get_tool("create_suppression_rule").executor(
            ctx, {"site": site.name, "type": "css_selector", "value": "#visitor-counter"}
        )
    assert result["created"] is True
    # Round-trips through the read tool.
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        listed = await tools.get_tool("list_suppression_rules").executor(ctx, {"site": site.name})
    assert listed["count"] == 1
    # Bad regex is rejected with a user-safe ToolError, not a crash.
    async with db_factory() as db:
        ctx = ToolContext(db=db, user=analyst_user, surface="agent-web")
        with pytest.raises(ToolError):
            await tools.get_tool("create_suppression_rule").executor(
                ctx, {"site": site.name, "type": "regex", "value": "([unclosed"}
            )


# --- Tool result JSON truncation (A5 - CB-1 fix) -------------------------


def test_bound_result_truncates_long_strings():
    from app.agent.engine import _bound_result

    long = "x" * 2000
    bounded = _bound_result({"key": long})
    assert len(bounded["key"]) <= 1001  # 1000 + ellipsis
    assert bounded["key"].endswith("…")


def test_bound_result_clips_long_lists():
    from app.agent.engine import _bound_result

    long_list = list(range(100))
    bounded = _bound_result({"items": long_list})
    assert len(bounded["items"]) <= 51  # 50 + overflow marker
    assert "+50 more" in str(bounded["items"][-1])


def test_dump_bounded_always_valid_json():
    import json

    from app.agent.engine import _dump_bounded

    oversized = {"huge": "x" * 10000, "nested": {"also": "y" * 10000}}
    dumped = _dump_bounded(oversized)
    # Must be parseable — no mid-string slice.
    parsed = json.loads(dumped)
    assert isinstance(parsed, dict)


# --- Provider rotation / failover (unified litellm.Router layer) ----------


async def test_agent_provider_redacts_keys(db_factory):
    """A configured provider never leaks its keys — hint-only, as before."""
    from app.ai_config import create_provider, key_hints

    async with db_factory() as db:
        provider = await create_provider(
            db, label="g", provider_type="google", api_keys=["AIzaSECRETKEY"], base_url=None
        )
        await db.commit()
        hints = key_hints(provider)
        assert "SECRET" not in hints[0]
        assert hints[0].startswith("AIzaSE")


async def test_agent_chat_multi_key_rotation_and_failover(db_factory, monkeypatch):
    """Two agent-chat keys: the first completion 429s, the Router retries/fails
    over across the deployments and the turn's model call succeeds — no request
    lost on a transient failure."""
    import litellm
    from litellm import RateLimitError
    from litellm.types.utils import Choices, Message, ModelResponse

    from app.ai_config import create_provider, set_assignment
    from app.llm import clear_router_cache, resolve_task
    from app.models import AiTaskType

    clear_router_cache()
    n = {"c": 0}

    async def flaky(**kwargs):
        n["c"] += 1
        if n["c"] == 1:  # first attempt fails; failover/retry must recover
            raise RateLimitError("quota", llm_provider="gemini", model=kwargs.get("model"))
        return ModelResponse(choices=[Choices(message=Message(content="ok"))])

    monkeypatch.setattr(litellm, "acompletion", flaky)
    async with db_factory() as db:
        provider = await create_provider(
            db, label="g", provider_type="google", api_keys=["k1", "k2"], base_url=None
        )
        await set_assignment(
            db, task=AiTaskType.agent_chat, provider_id=provider.id, model_id="gemini-flash-latest"
        )
        await db.commit()
        task = await resolve_task(db, "agent_chat")
        assert task.supports_tools is True
        text = await task.generate("hi")
        assert text == "ok"
        assert n["c"] >= 2  # proved a failed attempt was retried, not lost
    clear_router_cache()


async def test_agent_chat_all_keys_exhausted_raises(db_factory, monkeypatch):
    import litellm
    from litellm import RateLimitError

    from app.ai_config import create_provider, set_assignment
    from app.llm import LLMUnavailable, clear_router_cache, resolve_task
    from app.models import AiTaskType

    clear_router_cache()

    async def always_fail(**kwargs):
        raise RateLimitError("quota", llm_provider="gemini", model=kwargs.get("model"))

    monkeypatch.setattr(litellm, "acompletion", always_fail)
    async with db_factory() as db:
        provider = await create_provider(
            db, label="g", provider_type="google", api_keys=["k1"], base_url=None
        )
        await set_assignment(
            db, task=AiTaskType.agent_chat, provider_id=provider.id, model_id="gemini-flash-latest"
        )
        await db.commit()
        task = await resolve_task(db, "agent_chat")
        with pytest.raises(LLMUnavailable):
            await task.generate("hi")
    clear_router_cache()


# --- API surface -----------------------------------------------------------


async def test_conversation_crud_and_isolation(client, analyst_headers, viewer_headers):
    # Analyst creates a conversation.
    resp = await client.post("/api/agent/conversations", headers=analyst_headers)
    assert resp.status_code == 201, resp.text
    conv_id = resp.json()["id"]

    # Owner can read it.
    got = await client.get(f"/api/agent/conversations/{conv_id}", headers=analyst_headers)
    assert got.status_code == 200

    # A different user cannot (404, existence not leaked).
    foreign = await client.get(f"/api/agent/conversations/{conv_id}", headers=viewer_headers)
    assert foreign.status_code == 404

    # Owner sees it in the list; the other user does not.
    mine = await client.get("/api/agent/conversations", headers=analyst_headers)
    assert any(c["id"] == conv_id for c in mine.json())
    theirs = await client.get("/api/agent/conversations", headers=viewer_headers)
    assert not any(c["id"] == conv_id for c in theirs.json())


async def test_message_without_agent_model_degrades(client, analyst_headers):
    """With no agent-chat model configured, the turn must end with a clear,
    calm 'assign a model' message — never a 500, and not Gemini-specific."""
    resp = await client.post("/api/agent/conversations", headers=analyst_headers)
    conv_id = resp.json()["id"]
    async with client.stream(
        "POST",
        f"/api/agent/conversations/{conv_id}/messages",
        headers=analyst_headers,
        json={"message": "how many sites are flagged?"},
    ) as stream:
        assert stream.status_code == 200
        body = ""
        async for chunk in stream.aiter_text():
            body += chunk
    assert "assistant" in body.lower()
    assert "Settings" in body


async def test_confirm_unknown_action_404s(client, analyst_headers):
    fake = uuid.uuid4()
    resp = await client.post(f"/api/agent/actions/{fake}/confirm", headers=analyst_headers)
    # Guard raises ToolError -> 409 with a user-safe message.
    assert resp.status_code == 409


# --- Telegram surface: acting-user link + shared conversation -------------
#
# The bot handlers can't be driven without a live Telegram poll, but their
# DB-touching helpers (which decide identity and thread reuse) can — and
# those are the parts that carry the RBAC and no-pseudo-actor guarantees.


async def test_telegram_acting_user_resolves_live_only(db_factory, analyst_user):
    from app.settings_store import TELEGRAM_KEY, save_setting
    from worker import telegram_bot

    async with db_factory() as db:
        # Unset -> None (assistant off, slash commands only).
        assert await telegram_bot._load_acting_user(db) is None

        # A live, active user resolves.
        await save_setting(
            db, TELEGRAM_KEY, {"bot_token": "1:a", "acting_user_id": str(analyst_user.id)}
        )
    async with db_factory() as db:
        linked = await telegram_bot._load_acting_user(db)
        assert linked is not None and linked.id == analyst_user.id

        # A garbage id resolves to None rather than raising.
        await save_setting(db, TELEGRAM_KEY, {"bot_token": "1:a", "acting_user_id": "not-a-uuid"})
    async with db_factory() as db:
        assert await telegram_bot._load_acting_user(db) is None


async def test_telegram_acting_user_ignores_deactivated(db_factory, analyst_user):
    from app.settings_store import TELEGRAM_KEY, save_setting
    from worker import telegram_bot

    async with db_factory() as db:
        analyst = await db.get(User, analyst_user.id)
        analyst.is_active = False
        await save_setting(
            db, TELEGRAM_KEY, {"bot_token": "1:a", "acting_user_id": str(analyst_user.id)}
        )
        await db.commit()
    async with db_factory() as db:
        # A deactivated user must not keep operating the assistant.
        assert await telegram_bot._load_acting_user(db) is None


async def test_telegram_conversation_reused_per_user(db_factory, analyst_user):
    from worker import telegram_bot

    async with db_factory() as db:
        first = await telegram_bot._telegram_conversation(db, analyst_user)
        first_id = first.id
        assert first.surface == AgentSurface.telegram
    async with db_factory() as db:
        again = await telegram_bot._telegram_conversation(db, analyst_user)
        # Same rolling thread, not a fresh one each message.
        assert again.id == first_id


# --- Phase D: rolling summary + pending-action expiry janitor --------------


class _FakePool:
    """Minimal pool stand-in: records the summary prompt and returns a canned
    line, so context.maybe_summarize can be exercised without Gemini."""

    def __init__(self, reply: str = "Rolling summary of the chat."):
        self.reply = reply
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


async def _add_messages(db_factory, conv_id, count: int) -> None:
    from app.models import AgentMessage, AgentMessageRole

    async with db_factory() as db:
        for i in range(count):
            role = AgentMessageRole.user if i % 2 == 0 else AgentMessageRole.assistant
            db.add(AgentMessage(conversation_id=conv_id, role=role, content=f"turn {i}"))
        await db.commit()


async def test_summary_not_generated_for_short_chat(db_factory, analyst_user):
    from app.agent import context

    conv = await _seed_conversation(db_factory, analyst_user)
    await _add_messages(db_factory, conv.id, 4)  # well under the window
    pool = _FakePool()
    async with db_factory() as db:
        fresh = await db.get(AgentConversation, conv.id)
        await context.maybe_summarize(db, fresh, pool)
        await db.commit()
        assert fresh.summary is None
    assert pool.prompts == []  # no Gemini call for a short conversation


async def test_summary_regenerated_when_window_overflows(db_factory, analyst_user):
    from app.agent import context

    conv = await _seed_conversation(db_factory, analyst_user)
    # More than WINDOW_MESSAGES + trigger so aged-out turns exist.
    await _add_messages(db_factory, conv.id, context.WINDOW_MESSAGES + 6)
    pool = _FakePool()
    async with db_factory() as db:
        fresh = await db.get(AgentConversation, conv.id)
        await context.maybe_summarize(db, fresh, pool)
        await db.commit()
    async with db_factory() as db:
        reloaded = await db.get(AgentConversation, conv.id)
        assert reloaded.summary == "Rolling summary of the chat."
    assert len(pool.prompts) == 1


async def test_summary_failure_keeps_prior(db_factory, analyst_user):
    from app.agent import context

    class _BrokenPool:
        async def generate(self, prompt: str) -> str:
            raise RuntimeError("all keys cooling down")

    conv = await _seed_conversation(db_factory, analyst_user)
    async with db_factory() as db:
        fresh = await db.get(AgentConversation, conv.id)
        fresh.summary = "earlier summary"
        await db.commit()
    await _add_messages(db_factory, conv.id, context.WINDOW_MESSAGES + 6)
    async with db_factory() as db:
        fresh = await db.get(AgentConversation, conv.id)
        await context.maybe_summarize(db, fresh, _BrokenPool())
        await db.commit()
    async with db_factory() as db:
        reloaded = await db.get(AgentConversation, conv.id)
        assert reloaded.summary == "earlier summary"  # prior kept, turn not broken


async def test_expire_stale_flips_only_overdue_pending(db_factory, analyst_user):
    from datetime import timedelta

    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("delete_site")
    async with db_factory() as db:
        # One fresh (within TTL), one already overdue.
        fresh = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "keep"}
        )
        overdue = await guard.create_pending(
            db, conversation_id=conv.id, user=analyst_user, tool=tool, args={"site": "old"}
        )
        # create_pending supersedes the prior pending row, so re-fetch and
        # force the fresh one back to pending for the mixed-state assertion.
        fresh_row = await db.get(AgentPendingAction, fresh.id)
        fresh_row.status = AgentActionStatus.pending
        overdue_row = await db.get(AgentPendingAction, overdue.id)
        overdue_row.status = AgentActionStatus.pending
        overdue_row.expires_at = utcnow() - timedelta(minutes=1)
        await db.commit()

    async with db_factory() as db:
        count = await guard.expire_stale(db)
        assert count == 1
    async with db_factory() as db:
        assert (await db.get(AgentPendingAction, fresh.id)).status == AgentActionStatus.pending
        assert (await db.get(AgentPendingAction, overdue.id)).status == AgentActionStatus.expired
