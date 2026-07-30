"""Backend startup bootstrap for the AI layer.

Run from the FastAPI lifespan: migrate legacy AI settings into the new tables
(fast, local — awaited so the AI works on the first request) and refresh the
model catalog from models.dev (network — backgrounded so a slow/absent network
never delays startup; the bundled snapshot covers the offline case). The
Celery beat schedule refreshes the catalog periodically thereafter.
"""

from __future__ import annotations

import logging

from app.db import get_session_factory

logger = logging.getLogger(__name__)


async def bootstrap_migration() -> None:
    """Idempotent one-time legacy->new migration, then fresh-install seeding of
    an enabled local Ollama provider (AI on by default). Never raises."""
    from app.ai_migration import migrate_legacy_ai_settings, seed_default_ollama_provider

    try:
        async with get_session_factory()() as db:
            await migrate_legacy_ai_settings(db)
            await seed_default_ollama_provider(db)
    except Exception:  # noqa: BLE001 — a migration hiccup must not block startup
        logger.exception("Legacy AI settings migration failed")


async def bootstrap_catalog() -> None:
    """Refresh the model catalog (live, else keep existing, else snapshot)."""
    from app.ai_catalog import sync_catalog

    try:
        async with get_session_factory()() as db:
            await sync_catalog(db)
    except Exception:  # noqa: BLE001 — a catalog refresh must never block startup
        logger.exception("Model catalog startup sync failed")
