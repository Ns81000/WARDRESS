"""Regression tests for the unified litellm.Router LLM layer (formerly the
Gemini KeyPool). The implementation changed — the *behaviour* under test did
not: multi-key rotation, rate-limit failover, cross-provider fallback, and the
silent-degradation contract (LLMUnavailable / None), all exercised against the
real litellm Router with the underlying completion call mocked.
"""

import litellm
import pytest
from litellm import RateLimitError
from litellm.types.utils import Choices, Message, ModelResponse

from app.ai_catalog import litellm_model_string
from app.ai_config import create_provider, set_assignment
from app.llm import (
    LLMUnavailable,
    _deployments,
    _litellm_api_base,
    clear_router_cache,
    provider_api_keys,
    resolve_task,
)
from app.models import AiTaskType


def _ok_response(content: str = "ok") -> ModelResponse:
    return ModelResponse(choices=[Choices(message=Message(content=content))])


async def _make_task(db, *, provider_type, keys, model, base_url=None, task=AiTaskType.explanation):
    provider = await create_provider(
        db, label=provider_type, provider_type=provider_type, api_keys=keys, base_url=base_url
    )
    await set_assignment(db, task=task, provider_id=provider.id, model_id=model)
    await db.commit()
    return provider


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_router_cache()
    yield
    clear_router_cache()


# --- Provider-type -> litellm model string mapping -----------------------


def test_model_string_mapping() -> None:
    # models.dev "google" is litellm "gemini/"
    assert litellm_model_string("google", "gemini-flash-latest") == "gemini/gemini-flash-latest"
    # ollama uses the tool-capable chat API prefix
    assert litellm_model_string("ollama", "llama3.1") == "ollama_chat/llama3.1"
    # a generic custom endpoint rides litellm's openai shim
    assert litellm_model_string("openai_compatible", "my-model") == "openai/my-model"
    # identity for aligned providers
    assert litellm_model_string("groq", "llama-3.1-70b") == "groq/llama-3.1-70b"


def test_ollama_base_strips_v1(db_factory) -> None:
    from app.models import AiProvider

    p = AiProvider(label="o", provider_type="ollama", base_url="http://ollama:11434/v1")
    assert _litellm_api_base(p) == "http://ollama:11434"


# --- Credential handling + redaction -------------------------------------


async def test_provider_keys_roundtrip_and_hint(db_factory) -> None:
    async with db_factory() as db:
        provider = await create_provider(
            db,
            label="g",
            provider_type="google",
            api_keys=["AIzaSECRET123", "AIzaSECOND456"],
            base_url=None,
        )
        await db.commit()
        keys = provider_api_keys(provider)
        assert keys == ["AIzaSECRET123", "AIzaSECOND456"]
        from app.ai_config import key_hints

        hints = key_hints(provider)
        assert all("SECRET" not in h and "SECOND" not in h for h in hints)
        assert hints[0].startswith("AIzaSE")


# --- Multi-key rotation: N keys -> N Router deployments ------------------


async def test_multi_key_creates_multiple_deployments(db_factory) -> None:
    async with db_factory() as db:
        provider = await create_provider(
            db, label="g", provider_type="google", api_keys=["k1", "k2", "k3"], base_url=None
        )
        await db.commit()
        deps = _deployments(provider, "gemini-flash-latest", "primary")
        assert len(deps) == 3
        assert all(d["model_name"] == "primary" for d in deps)
        assert {d["litellm_params"]["api_key"] for d in deps} == {"k1", "k2", "k3"}


# --- Degradation: unconfigured -> None -----------------------------------


async def test_resolve_task_none_when_unconfigured(db_factory) -> None:
    async with db_factory() as db:
        assert await resolve_task(db, "explanation") is None


async def test_resolve_task_none_when_provider_disabled(db_factory) -> None:
    async with db_factory() as db:
        provider = await _make_task(
            db, provider_type="google", keys=["k1"], model="gemini-flash-latest"
        )
        provider.enabled = False
        await db.commit()
        clear_router_cache()
        assert await resolve_task(db, "explanation") is None


# --- Rate-limit failover: a request is never lost while a key has capacity -


async def test_failover_recovers_from_rate_limit(db_factory, monkeypatch) -> None:
    async with db_factory() as db:
        await _make_task(db, provider_type="google", keys=["k1", "k2"], model="gemini-flash-latest")
        n = {"c": 0}

        async def flaky(**kwargs):
            n["c"] += 1
            if n["c"] == 1:
                raise RateLimitError("quota", llm_provider="gemini", model=kwargs.get("model"))
            return _ok_response("recovered")

        monkeypatch.setattr(litellm, "acompletion", flaky)
        task = await resolve_task(db, "explanation")
        text = await task.generate("hi")
        assert text == "recovered"
        assert n["c"] >= 2  # first attempt failed, retried, succeeded


# --- All keys failing -> LLMUnavailable (silent-degradation contract) -----


async def test_all_keys_failing_raises_llm_unavailable(db_factory, monkeypatch) -> None:
    async with db_factory() as db:
        await _make_task(db, provider_type="google", keys=["k1", "k2"], model="gemini-flash-latest")

        async def always_fail(**kwargs):
            raise RateLimitError("quota", llm_provider="gemini", model=kwargs.get("model"))

        monkeypatch.setattr(litellm, "acompletion", always_fail)
        task = await resolve_task(db, "explanation")
        with pytest.raises(LLMUnavailable):
            await task.generate("hi")


async def test_empty_response_raises(db_factory, monkeypatch) -> None:
    async with db_factory() as db:
        await _make_task(db, provider_type="google", keys=["k1"], model="gemini-flash-latest")

        async def empty(**kwargs):
            return _ok_response("")

        monkeypatch.setattr(litellm, "acompletion", empty)
        task = await resolve_task(db, "explanation")
        with pytest.raises(LLMUnavailable):
            await task.generate("hi")


# --- Cross-provider fallback (Router fallbacks) --------------------------


async def test_cross_provider_fallback(db_factory, monkeypatch) -> None:
    async with db_factory() as db:
        primary = await create_provider(
            db, label="p", provider_type="google", api_keys=["pk"], base_url=None
        )
        fallback = await create_provider(
            db, label="f", provider_type="groq", api_keys=["fk"], base_url=None
        )
        await set_assignment(
            db,
            task=AiTaskType.explanation,
            provider_id=primary.id,
            model_id="gemini-flash-latest",
            fallback_provider_id=fallback.id,
            fallback_model_id="llama-3.1-70b",
        )
        await db.commit()

        async def only_groq_ok(**kwargs):
            if "groq/" in (kwargs.get("model") or ""):
                return _ok_response("from-fallback")
            raise RateLimitError("quota", llm_provider="gemini", model=kwargs.get("model"))

        monkeypatch.setattr(litellm, "acompletion", only_groq_ok)
        task = await resolve_task(db, "explanation")
        text = await task.generate("hi")
        assert text == "from-fallback"


# --- Router cache concurrency safety (A2 - CON-1/CON-2 fix) --------------


async def test_concurrent_resolve_task_safe(db_factory, monkeypatch) -> None:
    """Multiple concurrent resolve_task calls for the same sig use a shared
    Router without race-corrupting the cache (CON-1 fix)."""
    import asyncio

    async with db_factory() as db:
        await _make_task(db, provider_type="google", keys=["k1"], model="gemini-flash-latest")

        async def ok_response(**kwargs):
            await asyncio.sleep(0.01)  # simulate network delay
            return _ok_response("concurrent-ok")

        monkeypatch.setattr(litellm, "acompletion", ok_response)

        # Fire 10 concurrent resolves — all should succeed and share the cache entry.
        tasks_resolved = await asyncio.gather(
            *[resolve_task(db, "explanation") for _ in range(10)]
        )
        assert all(t is not None and t.task == "explanation" for t in tasks_resolved)
        # All resolved objects share the same signature (hence the same Router).
        sigs = {t._sig for t in tasks_resolved if t}
        assert len(sigs) == 1
