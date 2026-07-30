"""Tests for the legacy->new AI settings migration, Ollama (local + cloud)
configuration, and live provider validation.
"""

import litellm
from litellm.types.utils import Choices, Message, ModelResponse

from app.ai_config import create_provider
from app.ai_migration import migrate_legacy_ai_settings, seed_default_ollama_provider
from app.llm import _deployments, _litellm_api_base, validate_provider_call
from app.models import AiProvider, AiTaskType
from app.settings_store import GEMINI_KEY, OLLAMA_KEY, save_setting


async def _providers(db):
    from sqlalchemy import select

    return list(await db.scalars(select(AiProvider)))


async def _assignment(db, task):
    from app.ai_config import get_assignment

    return await get_assignment(db, task)


# --- Legacy Gemini migration (both shapes) -------------------------------


async def test_migrate_legacy_pool_shape(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(
            db,
            GEMINI_KEY,
            {
                "enabled": True,
                "keys": [{"id": "1", "api_key": "AIzaK1"}, {"id": "2", "api_key": "AIzaK2"}],
            },
        )
        result = await migrate_legacy_ai_settings(db)
        assert result["migrated"] is True and "gemini" in result["created"]
        providers = await _providers(db)
        assert len(providers) == 1
        assert providers[0].provider_type == "google"
        from app.llm import provider_api_keys

        assert provider_api_keys(providers[0]) == ["AIzaK1", "AIzaK2"]
        # gemini-flash-latest is tool-capable -> both tasks assigned
        expl = await _assignment(db, AiTaskType.explanation)
        agent = await _assignment(db, AiTaskType.agent_chat)
        assert expl.provider_id == providers[0].id
        assert agent.provider_id == providers[0].id


async def test_migrate_legacy_single_key_shape(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(db, GEMINI_KEY, {"enabled": True, "api_key": "AIzaLEGACY"})
        await migrate_legacy_ai_settings(db)
        from app.llm import provider_api_keys

        providers = await _providers(db)
        assert provider_api_keys(providers[0]) == ["AIzaLEGACY"]


async def test_migration_is_idempotent(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(db, GEMINI_KEY, {"enabled": True, "api_key": "AIzaX"})
        await migrate_legacy_ai_settings(db)
        second = await migrate_legacy_ai_settings(db)
        assert second["migrated"] is False
        assert len(await _providers(db)) == 1


async def test_migrate_ollama_only_takes_explanation(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(
            db,
            OLLAMA_KEY,
            {"enabled": True, "base_url": "http://ollama:11434/v1", "model": "llama3.1"},
        )
        await migrate_legacy_ai_settings(db)
        providers = await _providers(db)
        assert providers[0].provider_type == "ollama"
        expl = await _assignment(db, AiTaskType.explanation)
        agent = await _assignment(db, AiTaskType.agent_chat)
        assert expl.provider_id == providers[0].id
        # Ollama is not auto-assigned to agent chat (no tool contract assumed)
        assert agent is None or agent.provider_id is None


async def test_migrate_gemini_preferred_over_ollama_for_explanation(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(db, GEMINI_KEY, {"enabled": True, "api_key": "AIzaX"})
        await save_setting(db, OLLAMA_KEY, {"enabled": True, "model": "llama3.1"})
        await migrate_legacy_ai_settings(db)
        expl = await _assignment(db, AiTaskType.explanation)
        providers = {p.provider_type: p for p in await _providers(db)}
        assert expl.provider_id == providers["google"].id


# --- Fresh-install seed: AI on by default via a local Ollama provider -----


async def test_fresh_install_seeds_enabled_local_ollama(db_factory) -> None:
    async with db_factory() as db:
        # Nothing configured, nothing migrated -> seed one enabled Ollama provider.
        await migrate_legacy_ai_settings(db)
        result = await seed_default_ollama_provider(db)
        assert result["seeded"] is True
        providers = await _providers(db)
        assert len(providers) == 1
        assert providers[0].provider_type == "ollama"
        assert providers[0].enabled is True
        assert providers[0].base_url == "http://ollama:11434"


async def test_seed_is_one_time_even_after_provider_deleted(db_factory) -> None:
    """The seed must not resurrect a provider the operator deleted on purpose."""
    async with db_factory() as db:
        await seed_default_ollama_provider(db)
        # Operator deletes the seeded provider.
        for p in await _providers(db):
            await db.delete(p)
        await db.commit()
        # A later boot must NOT re-seed (sentinel remembers it already ran).
        second = await seed_default_ollama_provider(db)
        assert second["seeded"] is False
        assert await _providers(db) == []


async def test_seed_skipped_when_migration_created_a_provider(db_factory) -> None:
    async with db_factory() as db:
        await save_setting(db, GEMINI_KEY, {"enabled": True, "api_key": "AIzaX"})
        await migrate_legacy_ai_settings(db)
        result = await seed_default_ollama_provider(db)
        assert result["seeded"] is False
        # Only the migrated Gemini provider exists — no competing Ollama default.
        types = sorted(p.provider_type for p in await _providers(db))
        assert types == ["google"]


# --- Ollama cloud configuration ------------------------------------------


def test_ollama_cloud_deployment_carries_bearer_key() -> None:
    """A cloud Ollama provider (base https://ollama.com + key) must produce a
    deployment litellm turns into an Authorization: Bearer call to /api/chat."""
    p = AiProvider(
        label="cloud",
        provider_type="ollama",
        base_url="https://ollama.com",
    )
    assert _litellm_api_base(p) == "https://ollama.com"


async def test_ollama_cloud_key_flows_into_deployment(db_factory) -> None:
    async with db_factory() as db:
        p = await create_provider(
            db,
            label="cloud",
            provider_type="ollama",
            api_keys=["ollama-cloud-key"],
            base_url="https://ollama.com",
        )
        await db.commit()
        deps = _deployments(p, "gpt-oss:120b", "primary")
        assert deps[0]["litellm_params"]["model"] == "ollama_chat/gpt-oss:120b"
        assert deps[0]["litellm_params"]["api_key"] == "ollama-cloud-key"
        assert deps[0]["litellm_params"]["api_base"] == "https://ollama.com"


# --- Tool-capability of a resolved task (agent-chat gate) ----------------


def test_supports_tools_trusts_gate_for_ollama_and_custom() -> None:
    """Regression: litellm's static registry returns False for ollama_chat/* and
    custom openai/* models, which would wrongly block a tool-capable Ollama model
    from agent chat even after the assignment gate approved it. The resolver must
    trust the gate for these provider types (capability was probed at assignment)."""
    from app.llm import _supports_tools

    assert _supports_tools("ollama", "ollama_chat/qwen2.5-coder:latest") is True
    assert _supports_tools("openai_compatible", "openai/some-model") is True
    # A catalog provider still defers to litellm's registry.
    assert _supports_tools("google", "gemini/gemini-flash-latest") is True
    assert _supports_tools("google", "gemini/totally-unknown-model") is False


# --- Live provider validation --------------------------------------------


async def test_validate_provider_ok(db_factory, monkeypatch) -> None:
    async def ok(**kwargs):
        return ModelResponse(choices=[Choices(message=Message(content="ok"))])

    monkeypatch.setattr(litellm, "acompletion", ok)
    async with db_factory() as db:
        p = await create_provider(
            db, label="g", provider_type="google", api_keys=["k"], base_url=None
        )
        await db.commit()
        ok_result, detail = await validate_provider_call(p, "gemini-flash-latest")
        assert ok_result is True


async def test_validate_provider_failure_is_reported(db_factory, monkeypatch) -> None:
    from litellm import AuthenticationError

    async def bad(**kwargs):
        raise AuthenticationError("bad key", llm_provider="gemini", model=kwargs.get("model"))

    monkeypatch.setattr(litellm, "acompletion", bad)
    async with db_factory() as db:
        p = await create_provider(
            db, label="g", provider_type="google", api_keys=["k"], base_url=None
        )
        await db.commit()
        ok_result, detail = await validate_provider_call(p, "gemini-flash-latest")
        assert ok_result is False
        assert detail  # a human message, not empty
