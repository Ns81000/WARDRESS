"""Model catalog synced from models.dev, plus the models.dev-id -> litellm
mapping every provider call depends on.

The catalog (``https://models.dev/catalog.json``) is reference data — no
secrets. It is refreshed on backend startup and on a Celery-beat schedule
(worker/beat_tasks.py). A normalized offline snapshot is bundled in the repo
(``app/data/models_dev_catalog.json``) so a network-less install still has a
catalog; a successful live fetch opportunistically rewrites that snapshot.

One parser (:func:`normalize_catalog`) turns the raw models.dev payload into
the compact records we store; the bundled snapshot is already in that compact
shape, so :func:`load_snapshot` skips normalization. Both feed one idempotent
upsert (:func:`upsert_catalog`).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCatalogEntry, ModelCatalogProvider

logger = logging.getLogger(__name__)

CATALOG_URL = "https://models.dev/catalog.json"
_SNAPSHOT_PATH = Path(__file__).parent / "data" / "models_dev_catalog.json"
_FETCH_TIMEOUT = 20

# models.dev provider id -> litellm provider prefix. Identity for the vast
# majority (openai, groq, openrouter, cerebras, mistral, xai, deepseek,
# anthropic, deepinfra, ...); this map only records the handful where the two
# registries disagree. This is reference data, NOT per-provider feature logic —
# a generic provider needs no code, only a catalog entry + a user key.
PROVIDER_LITELLM_PREFIX: dict[str, str] = {
    "google": "gemini",  # models.dev "google" == Google AI Studio == litellm "gemini/"
    "google-vertex": "vertex_ai",
    "google-vertex-anthropic": "vertex_ai",
    "cloudflare-workers-ai": "cloudflare",
    "amazon-bedrock": "bedrock",
    "azure": "azure",
}

# Sentinel provider types that are not models.dev providers.
OLLAMA_TYPE = "ollama"
OPENAI_COMPATIBLE_TYPE = "openai_compatible"


def litellm_model_string(provider_type: str, model_id: str) -> str:
    """The ``<prefix>/<model>`` string litellm routes on, for a configured
    provider. Ollama uses the tool-capable chat API prefix; a generic
    OpenAI-compatible endpoint routes through litellm's ``openai/`` shim with
    a custom ``api_base``."""
    if provider_type == OLLAMA_TYPE:
        return f"ollama_chat/{model_id}"
    if provider_type == OPENAI_COMPATIBLE_TYPE:
        return f"openai/{model_id}"
    prefix = PROVIDER_LITELLM_PREFIX.get(provider_type, provider_type)
    return f"{prefix}/{model_id}"


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def normalize_catalog(raw: dict) -> dict:
    """Turn the raw models.dev ``catalog.json`` ({providers, models}) into our
    compact snapshot shape: ``{"providers": [...], "models": [...]}``. Reads
    every model from each provider's own ``models`` dict (the richest source),
    not the top-level flattened list."""
    providers_raw = raw.get("providers") or {}
    out_providers: list[dict] = []
    out_models: list[dict] = []
    for pid, pdata in providers_raw.items():
        if not isinstance(pdata, dict):
            continue
        out_providers.append(
            {
                "id": pid,
                "name": pdata.get("name") or pid,
                "env": pdata.get("env") or [],
                "api_base": pdata.get("api"),
                "doc": pdata.get("doc"),
                "npm": pdata.get("npm"),
            }
        )
        for mid, mdata in (pdata.get("models") or {}).items():
            if not isinstance(mdata, dict):
                continue
            limit = mdata.get("limit") or {}
            cost = mdata.get("cost") or {}
            out_models.append(
                {
                    "id": f"{pid}/{mid}",
                    "provider_id": pid,
                    "model_id": mid,
                    "display_name": mdata.get("name") or mid,
                    "context_window": _int(limit.get("context")),
                    "max_output_tokens": _int(limit.get("output")),
                    "tool_calling": bool(mdata.get("tool_call")),
                    "reasoning": bool(mdata.get("reasoning")),
                    "cost_input": _num(cost.get("input")),
                    "cost_output": _num(cost.get("output")),
                }
            )
    return {"providers": out_providers, "models": out_models}


def load_snapshot() -> dict | None:
    """The bundled compact snapshot ({providers, models}), or None if missing
    / unreadable. Never raises — a broken snapshot must not block startup."""
    try:
        with _SNAPSHOT_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "models" in data and "providers" in data:
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Bundled model catalog snapshot unavailable: %s", exc)
    return None


def _write_snapshot(compact: dict) -> None:
    """Opportunistically refresh the bundled snapshot after a live fetch.
    Best-effort — a read-only filesystem must not fail the sync."""
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generated_at": datetime.now(UTC).isoformat(), **compact}
        with _SNAPSHOT_PATH.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), sort_keys=True)
    except OSError as exc:
        logger.info("Could not refresh bundled catalog snapshot: %s", exc)


async def fetch_live_catalog(client: httpx.AsyncClient | None = None) -> dict | None:
    """Fetch + normalize the live models.dev catalog, or None on any failure
    (network, non-2xx, malformed). Never raises."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_FETCH_TIMEOUT)
    try:
        resp = await client.get(CATALOG_URL)
        resp.raise_for_status()
        return normalize_catalog(resp.json())
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Live models.dev catalog fetch failed: %s", str(exc)[:200])
        return None
    finally:
        if owns:
            await client.aclose()


async def upsert_catalog(db: AsyncSession, compact: dict) -> tuple[int, int]:
    """Replace the catalog tables with the compact snapshot's contents.
    Idempotent full refresh (the catalog is small and models come and go, so a
    replace is simpler and safer than a diff). Returns (providers, models)."""
    providers = compact.get("providers") or []
    models = compact.get("models") or []
    if not models:
        logger.warning("Refusing to upsert an empty model catalog")
        return (0, 0)
    now = datetime.now(UTC)
    await db.execute(delete(ModelCatalogEntry))
    await db.execute(delete(ModelCatalogProvider))
    db.add_all(
        [
            ModelCatalogProvider(
                id=p["id"],
                name=p["name"],
                env=p.get("env") or [],
                api_base=p.get("api_base"),
                doc=p.get("doc"),
                npm=p.get("npm"),
                updated_at=now,
            )
            for p in providers
        ]
    )
    db.add_all(
        [
            ModelCatalogEntry(
                id=m["id"],
                provider_id=m["provider_id"],
                model_id=m["model_id"],
                display_name=m["display_name"],
                context_window=m.get("context_window"),
                max_output_tokens=m.get("max_output_tokens"),
                tool_calling=bool(m.get("tool_calling")),
                reasoning=bool(m.get("reasoning")),
                cost_input=m.get("cost_input"),
                cost_output=m.get("cost_output"),
                updated_at=now,
            )
            for m in models
        ]
    )
    await db.commit()
    return (len(providers), len(models))


async def sync_catalog(db: AsyncSession, *, allow_snapshot_fallback: bool = True) -> dict:
    """Refresh the catalog: try live models.dev first (and refresh the bundled
    snapshot on success); fall back to the bundled snapshot only if the tables
    are still empty. Returns a small status dict for logs/observability. Never
    raises — a catalog refresh failure must never break startup or a scan."""
    live = await fetch_live_catalog()
    if live is not None:
        providers, models = await upsert_catalog(db, live)
        _write_snapshot(live)
        logger.info("Model catalog synced from models.dev: %d models", models)
        return {"source": "live", "providers": providers, "models": models}

    existing = await db.scalar(select(ModelCatalogEntry.id).limit(1))
    if existing is not None:
        logger.info("Live catalog fetch failed; keeping existing catalog")
        return {"source": "existing", "providers": 0, "models": 0}

    if allow_snapshot_fallback:
        snapshot = load_snapshot()
        if snapshot is not None:
            providers, models = await upsert_catalog(db, snapshot)
            logger.info("Model catalog seeded from bundled snapshot: %d models", models)
            return {"source": "snapshot", "providers": providers, "models": models}

    logger.warning("Model catalog could not be synced (no network, no snapshot)")
    return {"source": "none", "providers": 0, "models": 0}


async def model_supports_tools(db: AsyncSession, catalog_id: str) -> bool | None:
    """Whether a catalog model (``provider/model``) supports tool calling.
    None when the model is not in the catalog (caller decides the default)."""
    row = await db.scalar(
        select(ModelCatalogEntry.tool_calling).where(ModelCatalogEntry.id == catalog_id)
    )
    return bool(row) if row is not None else None
