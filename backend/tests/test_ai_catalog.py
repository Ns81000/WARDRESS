"""Tests for the catalog-driven AI config: models.dev catalog parsing/sync,
the bundled offline snapshot, provider validation, task assignment + the
tool-capability gate, the legacy->new migration, and Ollama config.
"""


from app.ai_catalog import (
    load_snapshot,
    normalize_catalog,
    sync_catalog,
    upsert_catalog,
)
from app.ai_config import (
    create_provider,
    get_assignment,
    provider_out,
    resolve_tool_capability,
    set_assignment,
)
from app.models import AiTaskType, ModelCatalogEntry

# A tiny slice of the real models.dev payload shape.
_RAW = {
    "providers": {
        "openai": {
            "id": "openai",
            "name": "OpenAI",
            "env": ["OPENAI_API_KEY"],
            "api": None,
            "doc": "https://platform.openai.com",
            "npm": "@ai-sdk/openai",
            "models": {
                "gpt-4o-mini": {
                    "id": "gpt-4o-mini",
                    "name": "GPT-4o mini",
                    "reasoning": False,
                    "tool_call": True,
                    "limit": {"context": 128000, "output": 16384},
                    "cost": {"input": 0.15, "output": 0.6},
                },
                "text-embed": {
                    "id": "text-embed",
                    "name": "Embedding",
                    "tool_call": False,
                    "reasoning": False,
                    "limit": {"context": 8192},
                },
            },
        }
    },
    "models": {},
}


def test_normalize_catalog_shape() -> None:
    compact = normalize_catalog(_RAW)
    assert {p["id"] for p in compact["providers"]} == {"openai"}
    ids = {m["id"]: m for m in compact["models"]}
    assert "openai/gpt-4o-mini" in ids
    m = ids["openai/gpt-4o-mini"]
    assert m["tool_calling"] is True
    assert m["context_window"] == 128000
    assert m["max_output_tokens"] == 16384
    assert m["cost_input"] == 0.15
    # A model without cost/output still normalizes (None, not a crash)
    assert ids["openai/text-embed"]["cost_input"] is None
    assert ids["openai/text-embed"]["max_output_tokens"] is None


def test_bundled_snapshot_exists_and_is_wellformed() -> None:
    snap = load_snapshot()
    assert snap is not None, "bundled offline snapshot must ship in the repo"
    assert len(snap["models"]) > 100
    # gemini-flash-latest (used by the legacy migration) must be present + tool-capable
    gemini = [m for m in snap["models"] if m["id"] == "google/gemini-flash-latest"]
    assert gemini and gemini[0]["tool_calling"] is True


async def test_upsert_and_query_catalog(db_factory) -> None:
    async with db_factory() as db:
        providers, models = await upsert_catalog(db, normalize_catalog(_RAW))
        assert providers == 1 and models == 2
        # Idempotent: a second upsert replaces, doesn't duplicate
        await upsert_catalog(db, normalize_catalog(_RAW))
        from sqlalchemy import func, select

        count = await db.scalar(select(func.count()).select_from(ModelCatalogEntry))
        assert count == 2


async def test_upsert_refuses_empty(db_factory) -> None:
    async with db_factory() as db:
        await upsert_catalog(db, normalize_catalog(_RAW))
        # An empty catalog must not wipe an existing one
        providers, models = await upsert_catalog(db, {"providers": [], "models": []})
        assert (providers, models) == (0, 0)
        from sqlalchemy import func, select

        assert await db.scalar(select(func.count()).select_from(ModelCatalogEntry)) == 2


async def test_sync_falls_back_to_snapshot(db_factory, monkeypatch) -> None:
    async def no_network(*a, **k):
        return None

    monkeypatch.setattr("app.ai_catalog.fetch_live_catalog", no_network)
    async with db_factory() as db:
        result = await sync_catalog(db)
        assert result["source"] == "snapshot"
        assert result["models"] > 100


# --- Provider redaction + tool-capability gate ---------------------------


async def test_provider_out_redacts_secrets(db_factory) -> None:
    async with db_factory() as db:
        p = await create_provider(
            db, label="OpenAI", provider_type="openai", api_keys=["sk-SUPERSECRET"], base_url=None
        )
        await db.commit()
        out = provider_out(p)
        blob = str(out)
        assert "SUPERSECRET" not in blob
        assert out["key_count"] == 1
        assert out["key_hints"]


async def test_tool_capability_gate_from_catalog(db_factory) -> None:
    async with db_factory() as db:
        await upsert_catalog(db, normalize_catalog(_RAW))
        p = await create_provider(
            db, label="OpenAI", provider_type="openai", api_keys=["sk"], base_url=None
        )
        await db.commit()
        assert await resolve_tool_capability(db, p, "gpt-4o-mini") is True
        assert await resolve_tool_capability(db, p, "text-embed") is False
        # Unknown model -> None (unknown, caller decides)
        assert await resolve_tool_capability(db, p, "nonexistent") is None


async def test_openai_compatible_capability_is_trusted(db_factory) -> None:
    async with db_factory() as db:
        p = await create_provider(
            db,
            label="Custom",
            provider_type="openai_compatible",
            api_keys=["sk"],
            base_url="https://example.com/v1",
        )
        await db.commit()
        # We can't know -> None (not blocked)
        assert await resolve_tool_capability(db, p, "whatever") is None


# --- Assignment ----------------------------------------------------------


async def test_set_and_get_assignment(db_factory) -> None:
    async with db_factory() as db:
        p = await create_provider(
            db, label="OpenAI", provider_type="openai", api_keys=["sk"], base_url=None
        )
        await set_assignment(
            db, task=AiTaskType.agent_chat, provider_id=p.id, model_id="gpt-4o-mini"
        )
        await db.commit()
        row = await get_assignment(db, "agent_chat")
        assert row is not None
        assert row.provider_id == p.id
        assert row.model_id == "gpt-4o-mini"
