"""Service layer for the unified AI provider configuration.

Shared by the Settings API (new provider/task endpoints and the deprecated
Gemini/Ollama adapters) and the one-time legacy migration, so credential
encryption, secret redaction, the tool-calling gate and audit-shaped
before/after snapshots live in exactly one place.

Credentials are Fernet-encrypted at rest via app/crypto.py (identical to the
existing app_settings pattern) as ``{"api_keys": [...]}``; secrets never leave
the backend — callers get key *hints* only.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_catalog import OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE, model_supports_tools
from app.crypto import DecryptionError, decrypt_json, encrypt_json
from app.llm import _key_hint, clear_router_cache, provider_api_keys
from app.models import AiProvider, AiTaskAssignment, AiTaskType, ModelCatalogEntry
from app.ssrf import SSRFBlockedError, assert_url_allowed


class ProviderConfigError(ValueError):
    """A provider config is invalid (e.g. an SSRF-blocked base_url). Message
    is user-safe; the settings router maps it to a 422."""


async def validate_base_url(base_url: str | None, provider_type: str) -> None:
    """Reject a provider ``base_url`` that would enable SSRF.

    Requires an http/https scheme and a resolvable host, then runs the shared
    SSRF policy (``app/ssrf.assert_url_allowed``) to block loopback / private /
    link-local / cloud-metadata targets. Local providers legitimately point at
    private hosts (a local Ollama at ``localhost:11434``), so the
    private-network allowance is gated on the provider *type* — only the local
    provider kinds (Ollama / OpenAI-compatible) may resolve to internal
    addresses; hosted providers may not. The DNS-resolving check runs in a
    thread so it never blocks the event loop.
    """
    if base_url is None:
        return
    url = base_url.strip()
    if not url:
        return
    allow_private = provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE)
    try:
        await asyncio.to_thread(
            assert_url_allowed, url, allow_private_networks=allow_private
        )
    except SSRFBlockedError as exc:
        raise ProviderConfigError(str(exc)) from None

# Kept in sync with the frontend AI settings card.
MAX_KEYS_PER_PROVIDER = 10


def encrypt_keys(keys: list[str]) -> str | None:
    """Fernet-encrypt a provider's API keys, or None when there are none."""
    cleaned = [k.strip() for k in keys if isinstance(k, str) and k.strip()]
    return encrypt_json({"api_keys": cleaned}) if cleaned else None


def key_hints(provider: AiProvider) -> list[str]:
    """Redacted hints for each stored key (never the secret)."""
    return [_key_hint(k) for k in provider_api_keys(provider)]


def _keys_unreadable(provider: AiProvider) -> bool:
    """ERR-4: True when credentials are stored but can't be decrypted (e.g.
    after a Fernet key rotation). The UI should prompt a re-save."""
    if not provider.credentials_encrypted:
        return False
    try:
        decrypt_json(provider.credentials_encrypted)
        return False
    except DecryptionError:
        return True


def provider_out(provider: AiProvider) -> dict:
    """Redacted provider view for API responses — no secrets, hint-only."""
    hints = key_hints(provider)
    return {
        "id": str(provider.id),
        "label": provider.label,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "enabled": provider.enabled,
        "key_count": len(hints),
        "key_hints": hints,
        "keys_unreadable": _keys_unreadable(provider),
        "validation_status": provider.validation_status,
        "validation_detail": provider.validation_detail,
        "validated_at": provider.validated_at.isoformat() if provider.validated_at else None,
    }


async def list_providers(db: AsyncSession) -> list[AiProvider]:
    rows = await db.scalars(select(AiProvider).order_by(AiProvider.created_at))
    return list(rows)


async def get_provider(db: AsyncSession, provider_id: uuid.UUID) -> AiProvider | None:
    return await db.scalar(select(AiProvider).where(AiProvider.id == provider_id))


async def create_provider(
    db: AsyncSession,
    *,
    label: str,
    provider_type: str,
    api_keys: list[str] | None,
    base_url: str | None,
    validate_url: bool = True,
) -> AiProvider:
    # validate_url=False is used only by the one-time legacy migration, whose
    # base_url comes from already-trusted stored config (and may be a Docker
    # service hostname that doesn't resolve at migration time). User-facing
    # create/update always validate.
    if validate_url:
        await validate_base_url(base_url, provider_type)
    provider = AiProvider(
        label=label.strip() or provider_type,
        provider_type=provider_type,
        credentials_encrypted=encrypt_keys(api_keys or []),
        base_url=(base_url or "").strip() or None,
        enabled=True,
        validation_status="unknown",
    )
    db.add(provider)
    await db.flush()
    return provider


async def update_provider(
    db: AsyncSession,
    provider: AiProvider,
    *,
    label: str | None = None,
    api_keys: list[str] | None = None,
    base_url: str | None = None,
    enabled: bool | None = None,
) -> AiProvider:
    """Patch-style update. ``api_keys=None`` keeps the stored keys; ``[]``
    clears them; a list replaces them (the "None keeps stored secret" rule the
    rest of Settings follows)."""
    if label is not None:
        provider.label = label.strip() or provider.label
    if base_url is not None:
        await validate_base_url(base_url, provider.provider_type)
        provider.base_url = base_url.strip() or None
    if enabled is not None:
        provider.enabled = enabled
    if api_keys is not None:
        provider.credentials_encrypted = encrypt_keys(api_keys)
        # New keys invalidate the last validation result.
        provider.validation_status = "unknown"
        provider.validation_detail = None
        provider.validated_at = None
    clear_router_cache()
    return provider


async def delete_provider(db: AsyncSession, provider: AiProvider) -> None:
    await db.delete(provider)
    clear_router_cache()


# --- Task assignment ------------------------------------------------------


async def get_assignment(db: AsyncSession, task: str | AiTaskType) -> AiTaskAssignment | None:
    value = task.value if isinstance(task, AiTaskType) else str(task)
    return await db.scalar(select(AiTaskAssignment).where(AiTaskAssignment.task == value))


async def set_assignment(
    db: AsyncSession,
    *,
    task: str | AiTaskType,
    provider_id: uuid.UUID | None,
    model_id: str | None,
    fallback_provider_id: uuid.UUID | None = None,
    fallback_model_id: str | None = None,
) -> AiTaskAssignment:
    value = AiTaskType(task) if not isinstance(task, AiTaskType) else task
    row = await get_assignment(db, value)
    if row is None:
        row = AiTaskAssignment(task=value)
        db.add(row)
    row.provider_id = provider_id
    row.model_id = model_id
    row.fallback_provider_id = fallback_provider_id
    row.fallback_model_id = fallback_model_id
    clear_router_cache()
    return row


async def assignment_out(db: AsyncSession, task: str | AiTaskType) -> dict:
    row = await get_assignment(db, task)
    value = task.value if isinstance(task, AiTaskType) else str(task)
    if row is None:
        return {
            "task": value,
            "provider_id": None,
            "model_id": None,
            "fallback_provider_id": None,
            "fallback_model_id": None,
        }
    return {
        "task": value,
        "provider_id": str(row.provider_id) if row.provider_id else None,
        "model_id": row.model_id,
        "fallback_provider_id": str(row.fallback_provider_id)
        if row.fallback_provider_id
        else None,
        "fallback_model_id": row.fallback_model_id,
    }


# --- Tool-calling gate (agent-chat eligibility) --------------------------


async def resolve_tool_capability(
    db: AsyncSession, provider: AiProvider, model_id: str
) -> bool | None:
    """Whether (provider, model) supports tool calling — the agent-chat gate.
    None means "unknown" (caller decides). For catalog providers this is the
    catalog flag; Ollama is probed live via /api/show; a generic
    OpenAI-compatible endpoint is trusted (we can't know, so we don't block)."""
    if provider.provider_type == OLLAMA_TYPE:
        from app.ai_ollama import model_supports_tools as ollama_supports_tools

        keys = provider_api_keys(provider)
        key = keys[0] if keys else None
        try:
            return await ollama_supports_tools(provider.base_url, model_id, key)
        except Exception:  # noqa: BLE001 — probe failure -> unknown, don't block
            return None
    if provider.provider_type == OPENAI_COMPATIBLE_TYPE:
        return None  # unknown; trusted
    catalog_id = f"{provider.provider_type}/{model_id}"
    return await model_supports_tools(db, catalog_id)


def catalog_supports_tools_sync(entry: ModelCatalogEntry | None) -> bool:
    return bool(entry and entry.tool_calling)


def decrypt_provider_blob(provider: AiProvider) -> dict[str, Any]:
    """Full decrypted credential blob (migration/debug only — never returned
    to a client). {} when keyless or undecryptable."""
    if not provider.credentials_encrypted:
        return {}
    try:
        return decrypt_json(provider.credentials_encrypted)
    except DecryptionError:
        return {}
