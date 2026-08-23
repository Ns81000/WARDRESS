"""Phase 25 proofs: agent-subsystem Medium findings.

Finding 6.2 — ``resolve_pending`` guarded the pending→confirmed transition
with a plain read-modify-write, so N simultaneous confirms of one card
(double-clicked button, dashboard + Telegram same account) all passed the
status check, each flipped the row to confirmed, and each executed the
frozen args. Concurrency tests drive the real API against real Postgres;
the commit-window shim only guarantees the racers overlap while post-fix
outcomes are arbitrated by the conditional UPDATE's rowcount (Postgres
re-evaluates ``status = 'pending' AND expires_at >= now()`` when a losing
writer's lock wait ends).

Finding 6.3 — ``list_remediation_hooks`` was declared to analysts although
hook configuration is admin-only on every other surface (REST CRUD guards,
dashboard panel); the registry now matches the admin-only boundary.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import engine, guard, tools
from app.agent.tools import ToolError
from app.crypto import encrypt_text
from app.models import (
    AgentActionStatus,
    AgentConversation,
    AgentPendingAction,
    AgentSurface,
    AuditLog,
    RemediationActionType,
    RemediationHook,
    Site,
    SuppressionRule,
    User,
    UserRole,
    utcnow,
)

CANARY_VALUE = "p25-canary-rule"


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee racers overlap: every commit waits, so all participants
    pass their checks before any of them commits."""
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.5)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


# --- shared seeds -----------------------------------------------------------


async def _seed_site(db_factory, *, name: str = "Victim") -> Site:
    async with db_factory() as db:
        site = Site(name=name, url=f"https://{name.lower()}.example.com")
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _seed_conversation(db_factory, user: User) -> uuid.UUID:
    async with db_factory() as db:
        conv = AgentConversation(user_id=user.id, surface=AgentSurface.web)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv.id


async def _seed_rule_action(
    db_factory, user: User, conv_id: uuid.UUID, site_name: str
) -> uuid.UUID:
    """Freeze a create_suppression_rule proposal — an executor with NO
    uniqueness/idempotency backstop, so double-execution is directly
    observable as duplicate rule rows."""
    async with db_factory() as db:
        action = await guard.create_pending(
            db,
            conversation_id=conv_id,
            user=user,
            tool=tools.get_tool("create_suppression_rule"),
            args={"site": site_name, "type": "regex", "value": CANARY_VALUE},
        )
        return action.id


def _race_actions(client, headers, action_id: uuid.UUID, racers: int, verb: str = "confirm"):
    """Barrier-synchronized burst against one pending action; returns the
    gathered coroutine of (status_code, json_body) per racer."""
    barrier = asyncio.Barrier(racers)

    async def racer():
        async with barrier:
            resp = await client.post(f"/api/agent/actions/{action_id}/{verb}", headers=headers)
            return resp.status_code, resp.json()

    return [racer() for _ in range(racers)]


# --- Finding: concurrent confirms double-execute -----------------------------


async def test_concurrent_confirms_single_execution_single_audit(
    client, analyst_user, analyst_headers, db_factory, widen_commit_window
):
    site = await _seed_site(db_factory, name="p25-dbl-exec")
    conv_id = await _seed_conversation(db_factory, analyst_user)
    action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)

    codes_and_bodies = await asyncio.gather(*_race_actions(client, analyst_headers, action_id, 6))
    codes = sorted(code for code, _ in codes_and_bodies)
    # Exactly one winner executes; every loser observes the committed state.
    assert codes == [200] + [409] * 5, codes
    loser_details = {body["detail"] for _, body in codes_and_bodies if _ == 409}
    assert loser_details == {"This action was already confirmed."}

    async with db_factory() as db:
        rules = (
            await db.scalars(select(SuppressionRule).where(SuppressionRule.value == CANARY_VALUE))
        ).all()
        assert len(rules) == 1, f"frozen args executed {len(rules)} times"
        audits = (
            await db.scalars(select(AuditLog).where(AuditLog.action == "suppression_rule.create"))
        ).all()
        assert len(audits) == 1, "exactly one execution audit row"
        action = await db.get(AgentPendingAction, action_id)
        assert action.status == AgentActionStatus.confirmed


async def test_confirm_cancel_race_single_winner(
    client, analyst_user, analyst_headers, db_factory, widen_commit_window
):
    """Cross-endpoint race: whichever intent claims the row first wins, and
    the loser must observe it — a cancel can never be overwritten into an
    execution (and vice versa)."""
    site = await _seed_site(db_factory, name="p25-cc-race")
    conv_id = await _seed_conversation(db_factory, analyst_user)

    outcomes = set()
    for round_idx in range(4):
        action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)
        results = await asyncio.gather(
            *_race_actions(client, analyst_headers, action_id, 1, verb="confirm"),
            *_race_actions(client, analyst_headers, action_id, 1, verb="cancel"),
        )
        codes = sorted(code for code, _ in results)
        assert codes == [200, 409], (round_idx, results)
        async with db_factory() as db:
            action = await db.get(AgentPendingAction, action_id)
            rules = (
                await db.scalars(
                    select(SuppressionRule).where(SuppressionRule.value == CANARY_VALUE)
                )
            ).all()
        # Execution happened iff the confirm won.
        assert (len(rules) == round_idx + 1) == (action.status == AgentActionStatus.confirmed)
        outcomes.add(action.status)
    assert outcomes <= {AgentActionStatus.confirmed, AgentActionStatus.cancelled}


async def test_sequential_lifecycle_guards_unchanged(
    client, analyst_user, analyst_headers, db_factory
):
    """Behavior preservation (true before and after): settled cards refuse
    re-resolution with the historical message shapes."""
    site = await _seed_site(db_factory, name="p25-seq")
    conv_id = await _seed_conversation(db_factory, analyst_user)

    action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)
    first = await client.post(f"/api/agent/actions/{action_id}/confirm", headers=analyst_headers)
    assert first.status_code == 200
    second = await client.post(f"/api/agent/actions/{action_id}/confirm", headers=analyst_headers)
    assert second.status_code == 409
    assert second.json()["detail"] == "This action was already confirmed."
    third = await client.post(f"/api/agent/actions/{action_id}/cancel", headers=analyst_headers)
    assert third.status_code == 409
    assert third.json()["detail"] == "This action was already confirmed."

    action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)
    cancelled = await client.post(f"/api/agent/actions/{action_id}/cancel", headers=analyst_headers)
    assert cancelled.status_code == 200
    late_confirm = await client.post(
        f"/api/agent/actions/{action_id}/confirm", headers=analyst_headers
    )
    assert late_confirm.status_code == 409
    assert late_confirm.json()["detail"] == "This action was already cancelled."


async def test_expired_action_settles_expired_and_never_executes(
    client, analyst_user, analyst_headers, db_factory
):
    """Behavior preservation (true before and after): an expired card never
    executes; confirming it settles the row as expired."""
    site = await _seed_site(db_factory, name="p25-expired")
    conv_id = await _seed_conversation(db_factory, analyst_user)
    action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)

    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
        action.expires_at = utcnow().replace(year=2000)
        await db.commit()

    resp = await client.post(f"/api/agent/actions/{action_id}/confirm", headers=analyst_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This action expired — ask again if you still want it."

    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
        assert action.status == AgentActionStatus.expired
        rules = (
            await db.scalars(select(SuppressionRule).where(SuppressionRule.value == CANARY_VALUE))
        ).all()
    assert not rules


async def test_racing_confirms_of_one_expired_action_settle_it_once(
    client, analyst_user, analyst_headers, db_factory, widen_commit_window
):
    site = await _seed_site(db_factory, name="p25-expired-race")
    conv_id = await _seed_conversation(db_factory, analyst_user)
    action_id = await _seed_rule_action(db_factory, analyst_user, conv_id, site.name)

    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
        action.expires_at = utcnow().replace(year=2000)
        await db.commit()

    bodies = await asyncio.gather(*_race_actions(client, analyst_headers, action_id, 4))
    assert all(code == 409 for code, _ in bodies)
    details = {body["detail"] for _, body in bodies}
    # Every loser reports a coherent expired/settled answer — never success.
    assert details <= {
        "This action expired — ask again if you still want it.",
        "This action was already expired.",
    }
    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
        assert action.status == AgentActionStatus.expired


async def test_role_refusal_leaves_the_card_pending(db_factory, analyst_user):
    """A confirm refused on RBAC (role change between propose and confirm)
    must not burn the action: availability/RBAC are re-checked before the
    claim, so the card stays pending exactly as before. The refusal message
    proves the RBAC check ran before any execution attempt (a mis-ordered
    claim would burn the row and the executor would fail with a different,
    domain-level error)."""
    conv_id = await _seed_conversation(db_factory, analyst_user)
    async with db_factory() as db:
        action = await guard.create_pending(
            db,
            conversation_id=conv_id,
            user=analyst_user,
            tool=tools.get_tool("delete_site"),
            args={"site": "whatever"},
        )
        action_id = action.id

    async with db_factory() as db:
        user = await db.get(User, analyst_user.id)
        user.role = UserRole.viewer
        with pytest.raises(ToolError, match="role no longer permits"):
            await guard.resolve_pending(
                db, action_id=action_id, user=user, confirm=True, surface="agent-web"
            )

    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
    assert action.status == AgentActionStatus.pending


async def test_executor_failure_after_claim_is_terminal_not_rerunnable(
    client, analyst_user, analyst_headers, db_factory
):
    """Documented honesty bound (unchanged by this fix): an executor failure
    after a won claim leaves the row confirmed — visible as a 409 to the
    caller, never re-runnable, never silently absorbed."""
    site = await _seed_site(db_factory, name="p25-burn")
    conv_id = await _seed_conversation(db_factory, analyst_user)
    async with db_factory() as db:
        action = await guard.create_pending(
            db,
            conversation_id=conv_id,
            user=analyst_user,
            tool=tools.get_tool("add_site"),
            args={"name": "Twin", "url": site.url},
        )
        action_id = action.id

    resp = await client.post(f"/api/agent/actions/{action_id}/confirm", headers=analyst_headers)
    assert resp.status_code == 409  # duplicate-URL conflict raised by the executor

    async with db_factory() as db:
        action = await db.get(AgentPendingAction, action_id)
        twins = (await db.scalars(select(Site).where(Site.url == site.url))).all()
    assert action.status == AgentActionStatus.confirmed
    assert len(twins) == 1


async def test_expire_stale_flips_only_still_pending_expired_rows(db_factory, analyst_user):
    """Janitor guard: non-pending rows are never touched (their transitions
    are claimed atomically elsewhere), and the returned count is the number
    actually flipped. Two conversations are used because create_pending
    supersedes any prior pending action within ONE conversation."""
    conv_a = await _seed_conversation(db_factory, analyst_user)
    conv_b = await _seed_conversation(db_factory, analyst_user)
    async with db_factory() as db:
        fresh = await guard.create_pending(
            db,
            conversation_id=conv_a,
            user=analyst_user,
            tool=tools.get_tool("delete_site"),
            args={"site": "current"},
        )
        settled = await guard.create_pending(
            db,
            conversation_id=conv_b,
            user=analyst_user,
            tool=tools.get_tool("delete_site"),
            args={"site": "already-done"},
        )
        settled.status = AgentActionStatus.cancelled
        await db.commit()
        overdue = await guard.create_pending(
            db,
            conversation_id=conv_b,
            user=analyst_user,
            tool=tools.get_tool("delete_site"),
            args={"site": "old"},
        )
        overdue.expires_at = utcnow().replace(year=2000)
        await db.commit()
        fresh_id, cancelled_id, overdue_id = fresh.id, settled.id, overdue.id

    async with db_factory() as db:
        count = await guard.expire_stale(db)
    assert count == 1

    async with db_factory() as db:
        assert (await db.get(AgentPendingAction, overdue_id)).status == AgentActionStatus.expired
        assert (await db.get(AgentPendingAction, fresh_id)).status == AgentActionStatus.pending
        assert (
            await db.get(AgentPendingAction, cancelled_id)
        ).status == AgentActionStatus.cancelled

    async with db_factory() as db:
        again = await guard.expire_stale(db)
    assert again == 0


# --- Finding: list_remediation_hooks exposed below the admin boundary -------


async def _seed_hook(db_factory, site: Site, admin: User) -> None:
    async with db_factory() as db:
        db.add(
            RemediationHook(
                site_id=site.id,
                name="restore-page",
                action_type=RemediationActionType.custom_webhook,
                trigger_threshold=0.7,
                webhook_url_encrypted=encrypt_text("https://hooks.internal.example/run"),
                created_by=admin.id,
            )
        )
        await db.commit()


async def test_hooks_tool_min_role_matches_rest_admin_only():
    hook_tool = tools.get_tool("list_remediation_hooks")
    assert hook_tool.min_role == UserRole.admin, (
        "hook posture data is admin-only on every other surface "
        "(AdminUser guards on all REST hook routes); the agent declaration must match"
    )


async def test_analyst_declarations_exclude_hooks_admin_keeps_them():
    analyst = {t.name for t in tools.tools_for_role(UserRole.analyst)}
    admin = {t.name for t in tools.tools_for_role(UserRole.admin)}
    assert "list_remediation_hooks" not in analyst
    assert "list_remediation_hooks" in admin


async def test_dispatcher_refuses_analyst_hooks_call_and_returns_no_config(
    db_factory, analyst_user, admin_user, monkeypatch
):
    """End to end through the real turn loop: a scripted model emitting
    list_remediation_hooks for an analyst gets the refusal result fed back;
    no hook configuration ever enters model context."""
    site = await _seed_site(db_factory, name="Hooked")
    await _seed_hook(db_factory, site, admin_user)
    conv_id = await _seed_conversation(db_factory, analyst_user)

    calls_holder: list[list[dict]] = []

    class _ScriptedTask:
        supports_tools = True
        label = "scripted"

        def __init__(self, script):
            self.script = list(script)

        async def acompletion(self, *, messages, tools=None, tool_choice=None):
            calls_holder.append(messages)
            return self.script.pop(0)

        async def generate(self, prompt):
            return "ok"

    script = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="c1",
                                function=SimpleNamespace(
                                    name="list_remediation_hooks",
                                    arguments=json.dumps({"site": "Hooked"}),
                                ),
                            )
                        ],
                    )
                )
            ]
        ),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Done."))]),
    ]
    task = _ScriptedTask(script)

    async def _resolve(db, name):
        return task

    monkeypatch.setattr(engine, "resolve_task", _resolve)

    async with db_factory() as db:
        conv = await db.get(AgentConversation, conv_id)
        user = await db.get(type(analyst_user), analyst_user.id)
        events = [
            ev.to_dict()
            async for ev in engine.run_turn(
                db, conversation=conv, user=user, user_message="any hooks?", surface="agent-web"
            )
        ]

    # The tool never executed: no done event, and the refusal came back as data.
    done_tools = [
        e["data"]["tool"]
        for e in events
        if e["type"] == "tool" and e["data"].get("state") == "done"
    ]
    assert "list_remediation_hooks" not in done_tools
    tool_messages = [m for call in calls_holder for m in call if m.get("role") == "tool"]
    assert tool_messages, "refusal must be fed back to the model as the tool result"
    refusal = json.loads(tool_messages[0]["content"])
    assert refusal["result"] == {"error": "That action is not available to you."}
    blob = json.dumps(calls_holder)
    for leaked in ("restore-page", "custom_webhook", "trigger_threshold"):
        assert leaked not in blob, f"hook configuration leaked into model context: {leaked}"


async def test_rest_hook_surface_parity_admin_ok_analyst_forbidden(
    client, analyst_headers, auth_headers, db_factory, admin_user
):
    """Parity pin: the REST boundary this tool now mirrors is unchanged."""
    site = await _seed_site(db_factory, name="p25-parity")
    await _seed_hook(db_factory, site, admin_user)
    denied = await client.get(f"/api/sites/{site.id}/remediation-hooks", headers=analyst_headers)
    allowed = await client.get(f"/api/sites/{site.id}/remediation-hooks", headers=auth_headers)
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert [h["name"] for h in allowed.json()] == ["restore-page"]
