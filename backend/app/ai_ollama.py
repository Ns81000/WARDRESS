"""Ollama native-API client — local daemon and Ollama Cloud, unified.

litellm handles the actual *completions* (``ollama_chat/``); this module covers
the things litellm does not: live model discovery (``/api/tags``), capability
probing (``/api/show`` — how we learn whether an Ollama model supports tool
calling, since Ollama is not in the models.dev catalog) and streamed model
pulls (``/api/pull``) for the local-download UX.

Auth follows Ollama's docs (verified 2026-07-27): the local daemon needs no
key; Ollama Cloud (``https://ollama.com``) takes an ``Authorization: Bearer``
header and its models carry a ``-cloud``/``:cloud`` marker so the UI can flag
their different privacy/cost profile.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

_DISCOVERY_TIMEOUT = 15
_PULL_TIMEOUT = None  # a pull can take minutes; rely on the stream, not a deadline
OLLAMA_CLOUD_HOST = "https://ollama.com"
# Default endpoint for a local Ollama daemon. In the bundled docker-compose the
# daemon is reachable at the `ollama` service name; a bare host install uses
# localhost. This is a code constant, not an env/setting — the AI layer reads
# nothing from the environment (see app/config.py). An operator running Ollama
# elsewhere sets the base URL per-provider in the Settings UI.
DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"


class OllamaError(Exception):
    """A local/cloud Ollama call failed. Callers surface the message."""


def normalize_base(base_url: str | None) -> str:
    """Native Ollama API base (no trailing slash, no OpenAI-compat ``/v1``)."""
    base = (base_url or DEFAULT_OLLAMA_BASE_URL or "http://localhost:11434").strip()
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base or "http://localhost:11434"


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _is_cloud_model(name: str, *, from_cloud_host: bool) -> bool:
    lowered = name.lower()
    return from_cloud_host or lowered.endswith("-cloud") or lowered.endswith(":cloud")


async def list_models(base_url: str | None, api_key: str | None = None) -> list[dict]:
    """Discover available models via ``/api/tags``. Returns
    ``[{"name", "size", "is_cloud"}]``. Raises OllamaError on failure."""
    base = normalize_base(base_url)
    from_cloud_host = base.rstrip("/") == OLLAMA_CLOUD_HOST
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(f"{base}/api/tags", headers=_headers(api_key))
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaError(f"Could not reach Ollama at {base}: {str(exc)[:160]}") from exc
    out = []
    for m in body.get("models") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model") or ""
        if not name:
            continue
        out.append(
            {
                "name": name,
                "size": m.get("size"),
                "is_cloud": _is_cloud_model(name, from_cloud_host=from_cloud_host),
            }
        )
    return out


async def show_capabilities(
    base_url: str | None, model: str, api_key: str | None = None
) -> list[str]:
    """The model's capability list from ``/api/show`` (e.g. ``["completion",
    "tools"]``). Returns [] when unknown/unreachable — never raises."""
    base = normalize_base(base_url)
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/api/show", json={"model": model}, headers=_headers(api_key)
            )
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Ollama /api/show failed for %s: %s", model, str(exc)[:160])
        return []
    caps = body.get("capabilities")
    return [str(c) for c in caps] if isinstance(caps, list) else []


async def model_supports_tools(
    base_url: str | None, model: str, api_key: str | None = None
) -> bool:
    """Whether an Ollama model supports tool calling (agent-chat gate)."""
    return "tools" in await show_capabilities(base_url, model, api_key)


async def pull_stream(
    base_url: str | None, model: str, api_key: str | None = None
) -> AsyncIterator[dict]:
    """Stream ``/api/pull`` progress as parsed NDJSON dicts
    (``{"status", "total"?, "completed"?, "digest"?}``). Raises OllamaError if
    the stream can't be opened; per-line JSON errors are skipped."""
    base = normalize_base(base_url)
    try:
        async with httpx.AsyncClient(timeout=_PULL_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{base}/api/pull",
                json={"model": model, "stream": True},
                headers=_headers(api_key),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama pull failed: {str(exc)[:160]}") from exc
