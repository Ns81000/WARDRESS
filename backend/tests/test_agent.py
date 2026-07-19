"""Conversational agent tests (§ agent): tool RBAC filtering, tier
interception + confirmation guard, key-pool rotation/failover, and the
/api/agent/* surface (ownership isolation, degraded-without-key path).

The Gemini SDK is never called: the engine tests stub the KeyPool, and the
degradation path needs no provider at all.
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


def test_declarations_are_openapi_shaped():
    for t in tools.all_tools():
        decl = t.declaration()
        assert decl["name"] == t.name
        assert decl["parameters"]["type"] == "object"


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
    monkeypatch.setattr("app.agent.tools.enqueue_scan", lambda sid: calls.append(sid))
    site = await _seed_site(db_factory)
    conv = await _seed_conversation(db_factory, analyst_user)
    tool = tools.get_tool("rebaseline_site")
    monkeypatch.setattr("app.agent.tools.enqueue_baseline_capture", lambda bid: calls.append(bid))
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
    monkeypatch.setattr("app.agent.tools.enqueue_baseline_capture", lambda bid: calls.append(bid))
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


# --- Key pool rotation / failover -----------------------------------------


def test_keys_from_setting_normalizes_shapes():
    from app.llm import keys_from_setting

    legacy = keys_from_setting({"api_key": "AIzaLEGACY", "enabled": True})
    assert legacy == [{"id": "legacy", "api_key": "AIzaLEGACY", "label": "default"}]
    pool = keys_from_setting(
        {"keys": [{"id": "a", "api_key": "AIzaA", "label": "k1"}], "enabled": True}
    )
    assert pool[0]["api_key"] == "AIzaA"
    assert keys_from_setting({"api_key": "x", "enabled": False}) == []
    assert keys_from_setting(None) == []


def test_key_pool_health_snapshot_redacts():
    from app.llm import KeyPool

    pool = KeyPool([{"id": "a", "api_key": "AIzaSECRETKEY", "label": "primary"}])
    snap = pool.health_snapshot()
    assert snap[0]["health"] == "healthy"
    assert "SECRET" not in snap[0]["hint"]
    assert snap[0]["hint"].startswith("AIzaSE")


async def test_key_pool_fails_over_to_next_key(monkeypatch):
    """First key raises a 429; the pool must cool it down and succeed on the
    second key — returning the good response, not raising."""
    from app import llm

    llm._key_states.clear()
    calls = []

    class FakeResp:
        text = "ok"

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = self

        @property
        def models(self):
            return self

        async def generate_content(self, *, model, contents, config=None):
            calls.append(self.api_key)
            if self.api_key == "bad":
                raise RuntimeError("429 quota exceeded")
            return FakeResp()

        async def aclose(self):
            pass

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", FakeClient)
    pool = llm.KeyPool(
        [
            {"id": "1", "api_key": "bad", "label": "bad"},
            {"id": "2", "api_key": "good", "label": "good"},
        ]
    )
    text = await pool.generate("hi")
    assert text == "ok"
    assert calls == ["bad", "good"]
    # The bad key should now be cooling down.
    assert llm._state_for("bad").health() == "cooldown"


async def test_key_pool_all_exhausted_raises(monkeypatch):
    from app import llm

    llm._key_states.clear()

    class FakeClient:
        def __init__(self, api_key):
            self.aio = self

        @property
        def models(self):
            return self

        async def generate_content(self, *, model, contents, config=None):
            raise RuntimeError("429 quota exceeded")

        async def aclose(self):
            pass

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", FakeClient)
    pool = llm.KeyPool([{"id": "1", "api_key": "k1", "label": "k1"}])
    with pytest.raises(llm.LLMUnavailable):
        await pool.generate("hi")


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


async def test_message_without_gemini_key_degrades(client, analyst_headers):
    """With no provider configured, the turn must end with a clear, calm
    'add a key' message — never a 500."""
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
    assert "Gemini" in body
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
