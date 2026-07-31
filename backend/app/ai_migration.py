"""One-time migration + fresh-install seeding for the unified AI layer.

Two startup responsibilities, both idempotent and both safe to call on every
boot:

1. **Legacy migration** — pre-existing installs stored AI config as encrypted
   ``app_settings`` rows: a ``gemini`` row (legacy single-key ``{api_key}`` *or*
   the pool ``{keys:[...]}`` shape) and an ``ollama`` row. ``migrate_legacy_ai_settings``
   moves that into the new ``ai_providers`` / ``ai_task_assignments`` tables with
   no data loss, then leaves the legacy rows in place (the deprecated
   ``/api/settings/gemini`` adapters read/write the new tables — the legacy rows
   are no longer the source of truth). There is **no** env-var path: the AI layer
   reads nothing from the environment; keys/endpoints live only in the DB/UI.

2. **Fresh-install seed** — ``seed_default_ollama_provider`` creates an *enabled*
   local Ollama provider so AI is "on by default": the operator only has to start
   the Ollama container and download a model (both surfaced in the Settings UI),
   with no key and no ``.env`` edit. Gated by a one-time sentinel so a provider
   the operator later deletes is never silently resurrected.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_config import create_provider
from app.ai_ollama import DEFAULT_OLLAMA_BASE_URL
from app.models import AiProvider, AiTaskType
from app.settings_store import GEMINI_KEY, OLLAMA_KEY, load_setting, save_setting

logger = logging.getLogger(__name__)

# The migrated Gemini model. gemini-flash-latest is tool-capable, so a
# migrated Gemini provider can serve both explanation and agent chat.
_DEFAULT_GEMINI_MODEL = "gemini-flash-latest"

# Sentinel app_settings row: marks that fresh-install AI seeding has already
# run once, so we never resurrect a provider the operator deleted on purpose.
AI_SEED_KEY = "ai_seed_done"


def _legacy_gemini_keys(g: dict | None) -> list[str]:
    """Extract API keys from either legacy Gemini shape."""
    if not g or not g.get("enabled", True):
        return []
    keys = g.get("keys")
    if isinstance(keys, list):
        return [k["api_key"] for k in keys if isinstance(k, dict) and k.get("api_key")]
    if g.get("api_key"):
        return [g["api_key"]]
    return []


async def migrate_legacy_ai_settings(db: AsyncSession) -> dict:
    """Move legacy ``app_settings`` AI rows into the new tables. Returns a small
    status dict. Idempotent (no-ops once any ``ai_providers`` row exists); never
    raises fatally — a migration hiccup must not block startup."""
    from app.ai_config import set_assignment

    if await db.scalar(select(AiProvider.id).limit(1)) is not None:
        return {"migrated": False, "reason": "providers already configured"}

    created: list[str] = []

    # --- Gemini (legacy app_settings row only; no env path) ---
    g = await load_setting(db, GEMINI_KEY)
    gemini_keys = _legacy_gemini_keys(g)
    gemini_provider = None
    if gemini_keys:
        gemini_provider = await create_provider(
            db,
            label="Gemini (migrated)",
            provider_type="google",
            api_keys=gemini_keys,
            base_url=None,
        )
        await set_assignment(
            db,
            task=AiTaskType.explanation,
            provider_id=gemini_provider.id,
            model_id=_DEFAULT_GEMINI_MODEL,
        )
        await set_assignment(
            db,
            task=AiTaskType.agent_chat,
            provider_id=gemini_provider.id,
            model_id=_DEFAULT_GEMINI_MODEL,
        )
        created.append("gemini")

    # --- Ollama (legacy app_settings row only; no env path) ---
    o = await load_setting(db, OLLAMA_KEY)
    if o and o.get("enabled") and o.get("model"):
        ollama_provider = await create_provider(
            db,
            label="Ollama (migrated)",
            provider_type="ollama",
            api_keys=[],
            base_url=o.get("base_url") or DEFAULT_OLLAMA_BASE_URL,
            validate_url=False,  # trusted stored config; Docker hostname may not resolve
        )
        # The old design preferred Gemini for explanation when both existed and
        # never used Ollama for the agent (no function-calling contract). Keep
        # that: Ollama takes explanation only if Gemini didn't, and is left out
        # of agent chat (the operator can opt a tool-capable Ollama model in).
        if gemini_provider is None:
            await set_assignment(
                db,
                task=AiTaskType.explanation,
                provider_id=ollama_provider.id,
                model_id=o["model"],
            )
        created.append("ollama")

    await db.commit()
    if created:
        logger.info("Migrated legacy AI settings into provider layer: %s", ", ".join(created))
    return {"migrated": bool(created), "created": created}


async def seed_default_ollama_provider(db: AsyncSession) -> dict:
    """Fresh-install seed: create an *enabled* local Ollama provider so AI is on
    by default. Runs at most once ever (guarded by the ``ai_seed_done`` sentinel),
    and never when the install already has any provider (e.g. a legacy migration
    just ran, or the operator configured one). No model is assigned yet — there is
    nothing downloaded on a fresh box — so the operator starts the Ollama container
    and pulls a model from the UI, then ticks it onto a task. Never raises."""
    if await load_setting(db, AI_SEED_KEY) is not None:
        return {"seeded": False, "reason": "already seeded once"}

    if await db.scalar(select(AiProvider.id).limit(1)) is not None:
        # An install with existing config (legacy-migrated or operator-created):
        # mark seeding done so we don't add a competing default later.
        await save_setting(db, AI_SEED_KEY, {"done": True})
        return {"seeded": False, "reason": "providers already exist"}

    await create_provider(
        db,
        label="Ollama (local)",
        provider_type="ollama",
        api_keys=[],
        base_url=DEFAULT_OLLAMA_BASE_URL,
        validate_url=False,  # default localhost; Docker hostname may not resolve
    )
    await db.commit()
    await save_setting(db, AI_SEED_KEY, {"done": True})
    logger.info("Seeded default local Ollama provider (AI on by default)")
    return {"seeded": True}
