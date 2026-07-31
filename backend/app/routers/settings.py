"""Settings endpoints (§7): SMTP, Telegram, Gemini, Ollama, and
notification channels — each with a test endpoint where §8 demands one.

Stored values are encrypted at rest (app/crypto.py) and never round-trip
to the client: GET responses carry redacted hints ("smtp.ex...", key
prefixes) plus `configured` flags, and PATCH-like semantics let the
client keep a stored secret by omitting the field.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerting import (
    build_telegram_apprise_url,
    build_test_content,
    send_apprise,
    send_email,
    smtp_settings_usable,
)
from app.audit import record_audit
from app.crypto import DecryptionError, decrypt_json, encrypt_json
from app.db import get_db
from app.deps import AdminUser
from app.models import (
    AiProvider,
    AiTaskType,
    ModelCatalogEntry,
    ModelCatalogProvider,
    NotificationChannel,
    NotificationChannelType,
    User,
)
from app.ratelimit import enforce_user_rate_limit
from app.schemas import (
    AiProviderCreate,
    AiProviderOut,
    AiProviderUpdate,
    AiProviderValidateRequest,
    AiTaskAssignmentIn,
    AiTaskAssignmentOut,
    CatalogModelOut,
    CatalogProviderOut,
    GeminiKeyIn,
    GeminiKeyOut,
    GeminiSettingsIn,
    GeminiSettingsOut,
    NotificationChannelCreate,
    NotificationChannelOut,
    NotificationChannelUpdate,
    OllamaModelOut,
    OllamaPullRequest,
    OllamaSettingsIn,
    OllamaSettingsOut,
    SettingsTestResult,
    SmtpSettingsIn,
    SmtpSettingsOut,
    SmtpTestRequest,
    TelegramSettingsIn,
    TelegramSettingsOut,
)
from app.settings_store import (
    SMTP_KEY,
    TELEGRAM_KEY,
    delete_setting,
    load_setting,
    save_setting,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

DB = Annotated[AsyncSession, Depends(get_db)]


def _hint(secret: str, keep: int = 6) -> str:
    """Redacted display hint: first `keep` chars + ellipsis."""
    if not secret:
        return ""
    return secret[:keep] + "..." if len(secret) > keep else "..."


# --- SMTP (§8 email) ---


@router.get("/smtp", response_model=SmtpSettingsOut)
async def get_smtp(user: AdminUser, db: DB) -> SmtpSettingsOut:
    smtp = await load_setting(db, SMTP_KEY)
    if not smtp:
        return SmtpSettingsOut(configured=False)
    return SmtpSettingsOut(
        configured=smtp_settings_usable(smtp),
        host=smtp.get("host"),
        port=smtp.get("port"),
        security=smtp.get("security"),
        username=smtp.get("username"),
        has_password=bool(smtp.get("password")),
        from_addr=smtp.get("from_addr"),
        from_name=smtp.get("from_name"),
    )


@router.put("/smtp", response_model=SmtpSettingsOut)
async def put_smtp(body: SmtpSettingsIn, user: AdminUser, db: DB) -> SmtpSettingsOut:
    existing = await load_setting(db, SMTP_KEY) or {}
    # password=None keeps the stored one; "" clears it (documented in the
    # schema) — so editing the host never silently wipes the credential.
    password = existing.get("password") if body.password is None else body.password
    value = {
        "host": body.host.strip(),
        "port": body.port,
        "security": body.security,
        "username": (body.username or "").strip() or None,
        "password": password or None,
        "from_addr": body.from_addr,
        "from_name": (body.from_name or "").strip() or None,
    }
    record_audit(
        db,
        actor=user,
        action="settings.smtp.update",
        target_type="settings",
        target_id="smtp",
        target_label="SMTP settings",
        after={
            "host": value["host"],
            "port": value["port"],
            "security": value["security"],
            "username": value["username"],
            "has_password": bool(value["password"]),
            "from_addr": value["from_addr"],
            "from_name": value["from_name"],
        },
    )
    await save_setting(db, SMTP_KEY, value)
    return await get_smtp(user, db)


@router.post("/smtp/test", response_model=SettingsTestResult)
async def test_smtp(body: SmtpTestRequest, user: AdminUser, db: DB) -> SettingsTestResult:
    """Send a real test email — the §8 'Send Test Email' button that
    gates Save in the UI. Inline `settings` (the unsaved form values)
    take precedence over the stored row so the test proves the exact
    configuration the user is about to save."""
    stored = await load_setting(db, SMTP_KEY)
    if body.settings is not None:
        smtp = {
            "host": body.settings.host.strip(),
            "port": body.settings.port,
            "security": body.settings.security,
            "username": (body.settings.username or "").strip() or None,
            # Omitted password -> fall back to the stored credential.
            "password": (
                body.settings.password
                if body.settings.password is not None
                else (stored or {}).get("password")
            )
            or None,
            "from_addr": body.settings.from_addr,
            "from_name": (body.settings.from_name or "").strip() or None,
        }
    else:
        smtp = stored
    if not smtp_settings_usable(smtp):
        return SettingsTestResult(ok=False, detail="SMTP is not configured yet — save it first")
    ok, detail = await send_email(smtp, body.to, build_test_content("email"))
    return SettingsTestResult(ok=ok, detail="Test email sent" if ok else detail)


# --- Telegram (§8 bot + tgram:// pushes) ---


async def _acting_user_out(
    db: AsyncSession, acting_user_id: str | None
) -> tuple[str | None, str | None]:
    """Resolve the stored acting-user link to (id, email) for display. A
    stale link (user deleted or deactivated since) reads back as unset so the
    UI shows the assistant is effectively off until it's re-linked."""
    if not acting_user_id:
        return None, None
    try:
        uid = uuid.UUID(acting_user_id)
    except (ValueError, TypeError):
        return None, None
    linked = await db.scalar(select(User).where(User.id == uid, User.is_active.is_(True)))
    if linked is None:
        return None, None
    return str(linked.id), linked.email


@router.get("/telegram", response_model=TelegramSettingsOut)
async def get_telegram(user: AdminUser, db: DB) -> TelegramSettingsOut:
    tg = await load_setting(db, TELEGRAM_KEY)
    if not tg or not tg.get("bot_token"):
        return TelegramSettingsOut(configured=False)
    acting_id, acting_email = await _acting_user_out(db, tg.get("acting_user_id"))
    return TelegramSettingsOut(
        configured=True,
        token_hint=_hint(tg["bot_token"], keep=10),
        chat_id=tg.get("chat_id"),
        chat_captured_at=tg.get("chat_captured_at"),
        acting_user_id=acting_id,
        acting_user_email=acting_email,
    )


@router.put("/telegram", response_model=TelegramSettingsOut)
async def put_telegram(body: TelegramSettingsIn, user: AdminUser, db: DB) -> TelegramSettingsOut:
    existing = await load_setting(db, TELEGRAM_KEY) or {}
    if body.bot_token is None:
        token = existing.get("bot_token") or ""
    else:
        token = body.bot_token
    if not token:
        record_audit(
            db,
            actor=user,
            action="settings.telegram.update",
            target_type="settings",
            target_id="telegram",
            target_label="Telegram settings",
            after={"configured": False},
        )
        await delete_setting(db, TELEGRAM_KEY)
        return TelegramSettingsOut(configured=False)
    value = dict(existing)
    if token != existing.get("bot_token"):
        # New bot -> the old chat capture belongs to the old bot.
        value.pop("chat_id", None)
        value.pop("chat_captured_at", None)
    value["bot_token"] = token
    # acting_user_id: None keeps the stored link, "" clears it, a value sets it
    # (validated to a live user so the assistant can never run under a stale or
    # deactivated identity).
    if body.acting_user_id is not None:
        linked_id = body.acting_user_id.strip()
        if not linked_id:
            value.pop("acting_user_id", None)
        else:
            try:
                uid = uuid.UUID(linked_id)
            except (ValueError, TypeError):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "That is not a valid user id"
                ) from None
            linked = await db.scalar(select(User).where(User.id == uid, User.is_active.is_(True)))
            if linked is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "No active user with that id"
                )
            value["acting_user_id"] = str(linked.id)
    record_audit(
        db,
        actor=user,
        action="settings.telegram.update",
        target_type="settings",
        target_id="telegram",
        target_label="Telegram settings",
        after={
            "configured": True,
            "token_changed": token != existing.get("bot_token"),
            "acting_user_id": value.get("acting_user_id"),
        },
    )
    await save_setting(db, TELEGRAM_KEY, value)
    return await get_telegram(user, db)


@router.post("/telegram/test", response_model=SettingsTestResult)
async def test_telegram(user: AdminUser, db: DB) -> SettingsTestResult:
    """Send a test message via Apprise tgram:// to the captured chat."""
    tg = await load_setting(db, TELEGRAM_KEY)
    if not tg or not tg.get("bot_token"):
        return SettingsTestResult(ok=False, detail="Telegram bot token is not configured yet")
    if not tg.get("chat_id"):
        return SettingsTestResult(
            ok=False,
            detail="No chat captured yet — open your bot in Telegram and send /start",
        )
    url = build_telegram_apprise_url(tg["bot_token"], tg["chat_id"])
    ok, detail = await send_apprise(url, build_test_content("telegram"), kind="telegram")
    return SettingsTestResult(ok=ok, detail="Test message sent" if ok else detail)


# --- Unified AI provider layer (§8: catalog-driven, any-provider) --------
#
# The real configuration lives in ai_providers / ai_task_assignments (see
# app/ai_config.py + app/llm.py). The /gemini and /ollama endpoints below are
# thin, DEPRECATED adapters kept so older clients keep working through a
# deprecation window; they mutate the same new tables. Removal plan: drop them
# one minor release after the frontend ships the new AI settings UI (which uses
# the /api/settings/ai/* endpoints exclusively).

from app.ai_config import (  # noqa: E402 — grouped with the AI section it serves
    ProviderConfigError,
    create_provider,
    delete_provider,
    get_provider,
    key_hints,
    list_providers,
    provider_out,
    resolve_tool_capability,
    set_assignment,
    update_provider,
)
from app.ai_config import (  # noqa: E402
    assignment_out as _assignment_out,
)
from app.ai_config import (  # noqa: E402
    get_assignment as _get_assignment,
)

_SENTINEL_PROVIDER_TYPES = {"ollama", "openai_compatible"}


async def _provider_type_is_valid(db: DB, provider_type: str) -> bool:
    if provider_type in _SENTINEL_PROVIDER_TYPES:
        return True
    return (
        await db.scalar(
            select(ModelCatalogProvider.id).where(ModelCatalogProvider.id == provider_type)
        )
        is not None
    )


async def _require_provider(db: DB, provider_id: str) -> AiProvider:
    try:
        pid = uuid.UUID(provider_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found") from None
    provider = await get_provider(db, pid)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    return provider


# --- Legacy Gemini adapters (DEPRECATED) ---------------------------------

_LEGACY_GEMINI_MODEL = "gemini-flash-latest"


async def _legacy_google_provider(db: DB) -> AiProvider | None:
    return await db.scalar(
        select(AiProvider)
        .where(AiProvider.provider_type == "google")
        .order_by(AiProvider.created_at)
    )


async def _ensure_task_assigned(db: DB, provider: AiProvider, model: str) -> None:
    """Point any *unset* task at this provider, preserving the old "add a key
    and the AI just works" behaviour. gemini-flash-latest is tool-capable, so
    both explanation and agent_chat are eligible."""
    for task in (AiTaskType.explanation, AiTaskType.agent_chat):
        current = await _get_assignment(db, task)
        if current is None or current.provider_id is None:
            await set_assignment(db, task=task, provider_id=provider.id, model_id=model)


def _gemini_out_from_provider(provider: AiProvider | None) -> GeminiSettingsOut:
    if provider is None:
        return GeminiSettingsOut(configured=False, model=_LEGACY_GEMINI_MODEL)
    hints = key_hints(provider)
    keys = [
        GeminiKeyOut(id=str(i), label="", hint=h, health="healthy", used_today=0, daily_budget=0)
        for i, h in enumerate(hints)
    ]
    return GeminiSettingsOut(
        configured=bool(hints),
        enabled=provider.enabled and bool(hints),
        key_hint=hints[0] if hints else None,
        model=_LEGACY_GEMINI_MODEL,
        keys=keys,
    )


@router.get("/gemini", response_model=GeminiSettingsOut, deprecated=True)
async def get_gemini(user: AdminUser, db: DB) -> GeminiSettingsOut:
    return _gemini_out_from_provider(await _legacy_google_provider(db))


@router.put("/gemini", response_model=GeminiSettingsOut, deprecated=True)
async def put_gemini(body: GeminiSettingsIn, user: AdminUser, db: DB) -> GeminiSettingsOut:
    """DEPRECATED single-key setter. Prefer POST /api/settings/ai/providers."""
    from app.llm import provider_api_keys

    provider = await _legacy_google_provider(db)
    if body.api_key is not None:
        key = body.api_key.strip()
        if not key:
            if provider is not None:
                await delete_provider(db, provider)
            record_audit(
                db,
                actor=user,
                action="settings.gemini.update",
                target_type="settings",
                target_id="gemini",
                target_label="Gemini settings",
                after={"configured": False},
            )
            await db.commit()
            return GeminiSettingsOut(configured=False, model=_LEGACY_GEMINI_MODEL)
        if provider is None:
            provider = await create_provider(
                db, label="Gemini", provider_type="google", api_keys=[key], base_url=None
            )
        else:
            await update_provider(db, provider, api_keys=[key])
    if provider is not None:
        await update_provider(db, provider, enabled=body.enabled)
        if body.enabled and provider_api_keys(provider):
            await _ensure_task_assigned(db, provider, _LEGACY_GEMINI_MODEL)
    record_audit(
        db,
        actor=user,
        action="settings.gemini.update",
        target_type="settings",
        target_id="gemini",
        target_label="Gemini settings",
        after={"configured": provider is not None, "enabled": body.enabled},
    )
    await db.commit()
    return _gemini_out_from_provider(provider)


@router.post(
    "/gemini/keys",
    response_model=GeminiSettingsOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def add_gemini_key(body: GeminiKeyIn, user: AdminUser, db: DB) -> GeminiSettingsOut:
    """DEPRECATED. Add one key to the Gemini provider's rotation pool."""
    from app.llm import provider_api_keys

    provider = await _legacy_google_provider(db)
    existing = provider_api_keys(provider) if provider else []
    key = body.api_key.strip()
    if key in existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "That key is already in the pool")
    if len(existing) >= 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Key pool is capped at 10 keys")
    if provider is None:
        provider = await create_provider(
            db, label="Gemini", provider_type="google", api_keys=[key], base_url=None
        )
    else:
        await update_provider(db, provider, api_keys=[*existing, key])
    await _ensure_task_assigned(db, provider, _LEGACY_GEMINI_MODEL)
    record_audit(
        db,
        actor=user,
        action="settings.gemini.key_add",
        target_type="settings",
        target_id="gemini",
        target_label="Gemini key pool",
        after={"pool_size": len(provider_api_keys(provider))},
    )
    await db.commit()
    return _gemini_out_from_provider(provider)


@router.delete("/gemini/keys/{key_id}", response_model=GeminiSettingsOut, deprecated=True)
async def remove_gemini_key(key_id: str, user: AdminUser, db: DB) -> GeminiSettingsOut:
    """DEPRECATED. Remove one key (identified by its list index)."""
    from app.llm import provider_api_keys

    provider = await _legacy_google_provider(db)
    existing = provider_api_keys(provider) if provider else []
    try:
        idx = int(key_id)
        remaining = [k for i, k in enumerate(existing) if i != idx]
    except ValueError:
        remaining = existing
    if provider is None or len(remaining) == len(existing):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found in the pool")
    record_audit(
        db,
        actor=user,
        action="settings.gemini.key_remove",
        target_type="settings",
        target_id="gemini",
        target_label="Gemini key pool",
        after={"pool_size": len(remaining)},
    )
    if remaining:
        await update_provider(db, provider, api_keys=remaining)
    else:
        await delete_provider(db, provider)
        provider = None
    await db.commit()
    return _gemini_out_from_provider(provider)


@router.post("/gemini/test", response_model=SettingsTestResult, deprecated=True)
async def test_gemini(user: AdminUser, db: DB) -> SettingsTestResult:
    """DEPRECATED. One cheap live call through the Gemini provider."""
    from app.llm import validate_provider_call

    provider = await _legacy_google_provider(db)
    if provider is None or not key_hints(provider):
        return SettingsTestResult(ok=False, detail="No Gemini API keys configured yet")
    ok, detail = await validate_provider_call(provider, _LEGACY_GEMINI_MODEL)
    return SettingsTestResult(ok=ok, detail=detail)


# --- Legacy Ollama adapters (DEPRECATED) ---------------------------------

from app.ai_ollama import DEFAULT_OLLAMA_BASE_URL  # noqa: E402


async def _legacy_ollama_provider(db: DB) -> AiProvider | None:
    return await db.scalar(
        select(AiProvider)
        .where(AiProvider.provider_type == "ollama")
        .order_by(AiProvider.created_at)
    )


@router.get("/ollama", response_model=OllamaSettingsOut, deprecated=True)
async def get_ollama(user: AdminUser, db: DB) -> OllamaSettingsOut:
    provider = await _legacy_ollama_provider(db)
    assignment = await _get_assignment(db, AiTaskType.explanation)
    model = (
        assignment.model_id
        if assignment and provider and assignment.provider_id == provider.id
        else None
    )
    if provider is None:
        return OllamaSettingsOut(configured=False, base_url=DEFAULT_OLLAMA_BASE_URL)
    return OllamaSettingsOut(
        configured=True,
        enabled=provider.enabled,
        base_url=provider.base_url or DEFAULT_OLLAMA_BASE_URL,
        model=model,
    )


@router.put("/ollama", response_model=OllamaSettingsOut, deprecated=True)
async def put_ollama(body: OllamaSettingsIn, user: AdminUser, db: DB) -> OllamaSettingsOut:
    """DEPRECATED. Prefer POST /api/settings/ai/providers with type 'ollama'."""
    provider = await _legacy_ollama_provider(db)
    base = (body.base_url or "").strip() or DEFAULT_OLLAMA_BASE_URL
    model = (body.model or "").strip() or None
    if provider is None:
        provider = await create_provider(
            db, label="Ollama", provider_type="ollama", api_keys=[], base_url=base,
            validate_url=False,  # Docker hostname may not resolve outside Docker
        )
    else:
        await update_provider(db, provider, base_url=base, enabled=body.enabled)
    if body.enabled and model:
        # Ollama drives explanation only (agent chat needs a tool-capable model
        # the operator opts in explicitly through the new UI).
        current = await _get_assignment(db, AiTaskType.explanation)
        if current is None or current.provider_id is None or current.provider_id == provider.id:
            await set_assignment(
                db, task=AiTaskType.explanation, provider_id=provider.id, model_id=model
            )
    record_audit(
        db,
        actor=user,
        action="settings.ollama.update",
        target_type="settings",
        target_id="ollama",
        target_label="Ollama settings",
        after={"enabled": body.enabled, "base_url": base, "model": model},
    )
    await db.commit()
    return await get_ollama(user, db)


@router.post("/ollama/test", response_model=SettingsTestResult, deprecated=True)
async def test_ollama(user: AdminUser, db: DB) -> SettingsTestResult:
    """DEPRECATED. Live call through the Ollama provider's explanation model."""
    from app.llm import validate_provider_call

    provider = await _legacy_ollama_provider(db)
    assignment = await _get_assignment(db, AiTaskType.explanation)
    if provider is None or not provider.enabled:
        return SettingsTestResult(ok=False, detail="Ollama is not enabled yet — save it first")
    if assignment is None or assignment.provider_id != provider.id or not assignment.model_id:
        return SettingsTestResult(ok=False, detail="No Ollama model configured yet")
    ok, detail = await validate_provider_call(provider, assignment.model_id)
    return SettingsTestResult(ok=ok, detail=detail)


# --- New unified AI settings API (/api/settings/ai/*) --------------------

ai_router = APIRouter(prefix="/api/settings/ai", tags=["settings", "ai"])


@ai_router.get("/catalog/providers", response_model=list[CatalogProviderOut])
async def list_catalog_providers(user: AdminUser, db: DB) -> list[CatalogProviderOut]:
    """The models.dev provider catalog (searchable add-provider dropdown), with
    the two non-catalog entries (Ollama, custom OpenAI-compatible) prepended."""
    rows = await db.scalars(
        select(ModelCatalogProvider).order_by(ModelCatalogProvider.name)
    )
    out = [
        CatalogProviderOut(id="ollama", name="Ollama"),
        CatalogProviderOut(id="openai_compatible", name="Custom (OpenAI-compatible)"),
    ]
    out += [
        CatalogProviderOut(id=r.id, name=r.name, env=r.env or [], api_base=r.api_base, doc=r.doc)
        for r in rows
        if r.id not in ("ollama", "ollama-cloud", "ollama_cloud")
    ]
    return out


@ai_router.get("/catalog/models", response_model=list[CatalogModelOut])
async def list_catalog_models(
    user: AdminUser,
    db: DB,
    provider_id: str | None = None,
    tools_only: bool = False,
) -> list[CatalogModelOut]:
    q = select(ModelCatalogEntry)
    if provider_id:
        q = q.where(ModelCatalogEntry.provider_id == provider_id)
    if tools_only:
        q = q.where(ModelCatalogEntry.tool_calling.is_(True))
    rows = await db.scalars(q.order_by(ModelCatalogEntry.display_name))
    return [
        CatalogModelOut(
            id=r.id,
            provider_id=r.provider_id,
            model_id=r.model_id,
            display_name=r.display_name,
            context_window=r.context_window,
            max_output_tokens=r.max_output_tokens,
            tool_calling=r.tool_calling,
            reasoning=r.reasoning,
            cost_input=r.cost_input,
            cost_output=r.cost_output,
        )
        for r in rows
    ]


@ai_router.get("/providers", response_model=list[AiProviderOut])
async def list_ai_providers(user: AdminUser, db: DB) -> list[AiProviderOut]:
    return [AiProviderOut(**provider_out(p)) for p in await list_providers(db)]


@ai_router.post(
    "/providers", response_model=AiProviderOut, status_code=status.HTTP_201_CREATED
)
async def create_ai_provider(
    body: AiProviderCreate, user: AdminUser, db: DB
) -> AiProviderOut:
    if not await _provider_type_is_valid(db, body.provider_type):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown provider type '{body.provider_type}'",
        )
    if body.provider_type == "openai_compatible" and not (body.base_url or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A custom OpenAI-compatible provider requires a base URL",
        )
    try:
        provider = await create_provider(
            db,
            label=body.label,
            provider_type=body.provider_type,
            api_keys=body.api_keys,
            base_url=body.base_url,
        )
    except ProviderConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    record_audit(
        db,
        actor=user,
        action="settings.ai.provider_create",
        target_type="ai_provider",
        target_id=str(provider.id),
        target_label=provider.label,
        after={"provider_type": provider.provider_type, "key_count": len(body.api_keys)},
    )
    await db.commit()
    return AiProviderOut(**provider_out(provider))


@ai_router.patch("/providers/{provider_id}", response_model=AiProviderOut)
async def update_ai_provider(
    provider_id: str, body: AiProviderUpdate, user: AdminUser, db: DB
) -> AiProviderOut:
    provider = await _require_provider(db, provider_id)
    try:
        await update_provider(
            db,
            provider,
            label=body.label,
            api_keys=body.api_keys,
            base_url=body.base_url,
            enabled=body.enabled,
        )
    except ProviderConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    record_audit(
        db,
        actor=user,
        action="settings.ai.provider_update",
        target_type="ai_provider",
        target_id=str(provider.id),
        target_label=provider.label,
        after={"enabled": provider.enabled, "keys_changed": body.api_keys is not None},
    )
    await db.commit()
    return AiProviderOut(**provider_out(provider))


@ai_router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_provider(provider_id: str, user: AdminUser, db: DB) -> None:
    provider = await _require_provider(db, provider_id)
    label = provider.label
    await delete_provider(db, provider)
    record_audit(
        db,
        actor=user,
        action="settings.ai.provider_delete",
        target_type="ai_provider",
        target_id=provider_id,
        target_label=label,
        after={"deleted": True},
    )
    await db.commit()


@ai_router.post("/providers/{provider_id}/validate", response_model=SettingsTestResult)
async def validate_ai_provider(
    provider_id: str,
    body: AiProviderValidateRequest,
    user: AdminUser,
    db: DB,
    request: Request,
) -> SettingsTestResult:
    """A real, cheap completion to confirm the provider+model works; the result
    is persisted on the provider so the UI can show ok/failed state.

    Rate-limited per user: this makes a live outbound call, so an admin can't
    spam it to burn provider quota or probe internal endpoints."""
    from datetime import UTC, datetime

    from app.llm import validate_provider_call

    enforce_user_rate_limit(request, str(user.id))
    provider = await _require_provider(db, provider_id)
    ok, detail = await validate_provider_call(provider, body.model_id)
    provider.validation_status = "ok" if ok else "failed"
    provider.validation_detail = detail[:500]
    provider.validated_at = datetime.now(UTC)
    record_audit(
        db,
        actor=user,
        action="settings.ai.provider_validate",
        target_type="ai_provider",
        target_id=str(provider.id),
        target_label=provider.label,
        after={"ok": ok, "model": body.model_id},
    )
    await db.commit()
    return SettingsTestResult(ok=ok, detail=detail)


@ai_router.get("/providers/{provider_id}/ollama-models", response_model=list[OllamaModelOut])
async def list_ollama_models(provider_id: str, user: AdminUser, db: DB) -> list[OllamaModelOut]:
    from app.ai_ollama import OllamaError, list_models
    from app.llm import provider_api_keys

    provider = await _require_provider(db, provider_id)
    if provider.provider_type != "ollama":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not an Ollama provider")
    keys = provider_api_keys(provider)
    try:
        models = await list_models(provider.base_url, keys[0] if keys else None)
    except OllamaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    return [OllamaModelOut(**m) for m in models]


@ai_router.get("/assignments", response_model=list[AiTaskAssignmentOut])
async def get_assignments(user: AdminUser, db: DB) -> list[AiTaskAssignmentOut]:
    return [
        AiTaskAssignmentOut(**await _assignment_out(db, task))
        for task in (AiTaskType.explanation, AiTaskType.agent_chat)
    ]


@ai_router.put("/assignments/{task}", response_model=AiTaskAssignmentOut)
async def put_assignment(
    task: str, body: AiTaskAssignmentIn, user: AdminUser, db: DB
) -> AiTaskAssignmentOut:
    try:
        task_type = AiTaskType(task)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task") from None

    provider = None
    if body.provider_id:
        provider = await _require_provider(db, body.provider_id)
    if body.provider_id and not body.model_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A model is required")

    # Tool-calling gate: a non-tool model can never back agent chat.
    if task_type == AiTaskType.agent_chat and provider is not None and body.model_id:
        capable = await resolve_tool_capability(db, provider, body.model_id)
        if capable is False:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{body.model_id} does not support tool calling, so it can't back agent chat",
            )

    fb_provider_id = None
    if body.fallback_provider_id:
        fb = await _require_provider(db, body.fallback_provider_id)
        fb_provider_id = fb.id
    await set_assignment(
        db,
        task=task_type,
        provider_id=provider.id if provider else None,
        model_id=body.model_id,
        fallback_provider_id=fb_provider_id,
        fallback_model_id=body.fallback_model_id,
    )
    record_audit(
        db,
        actor=user,
        action="settings.ai.assign",
        target_type="ai_task",
        target_id=task,
        target_label=f"AI task: {task}",
        after={"provider_id": body.provider_id, "model_id": body.model_id},
    )
    await db.commit()
    return AiTaskAssignmentOut(**await _assignment_out(db, task_type))


@ai_router.post("/ollama/pull")
async def pull_ollama_model(body: OllamaPullRequest, user: AdminUser, db: DB) -> StreamingResponse:
    """Stream an Ollama model download (`/api/pull`) to the client as SSE with
    live progress. Local-download UX only — unrelated to cloud models."""
    import json as _json

    from app.ai_ollama import OllamaError, pull_stream
    from app.llm import provider_api_keys

    base_url = body.base_url
    api_key = None
    target_id = "ollama"
    target_label = "Ollama model pull"

    if body.provider_id:
        try:
            provider = await _require_provider(db, body.provider_id)
            if provider.provider_type == "ollama":
                keys = provider_api_keys(provider)
                base_url = provider.base_url or base_url
                api_key = keys[0] if keys else None
                target_id = str(provider.id)
                target_label = provider.label
        except Exception:
            pass

    model = body.model
    record_audit(
        db,
        actor=user,
        action="settings.ai.ollama_pull",
        target_type="ai_provider",
        target_id=target_id,
        target_label=target_label,
        after={"model": model},
    )
    await db.commit()

    async def _events():
        try:
            async for chunk in pull_stream(base_url, model, api_key):
                yield f"data: {_json.dumps(chunk)}\n\n"
            yield f"data: {_json.dumps({'status': 'success', 'done': True})}\n\n"
        except OllamaError as exc:
            yield f"data: {_json.dumps({'status': 'error', 'error': str(exc), 'done': True})}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")


# --- Notification channels (§6/§8) ---

channels_router = APIRouter(prefix="/api/notification-channels", tags=["notifications"])


def _target_hint(channel: NotificationChannel) -> str:
    """Redacted 'where does this go' label for the channel list."""
    try:
        config = decrypt_json(channel.config_encrypted)
    except DecryptionError:
        return "(configuration unreadable — re-save this channel)"
    if channel.type is NotificationChannelType.email:
        return config.get("to") or ""
    if channel.type is NotificationChannelType.telegram:
        return "captured chat"
    url = config.get("url") or ""
    scheme = url.split("://", 1)[0] if "://" in url else "url"
    return f"{scheme}://..."


def _channel_out(channel: NotificationChannel) -> NotificationChannelOut:
    return NotificationChannelOut(
        id=channel.id,
        type=channel.type,
        name=channel.name,
        site_id=channel.site_id,
        is_active=channel.is_active,
        target_hint=_target_hint(channel),
        created_at=channel.created_at,
    )


@channels_router.get("", response_model=list[NotificationChannelOut])
async def list_channels(user: AdminUser, db: DB) -> list[NotificationChannelOut]:
    channels = (
        await db.scalars(select(NotificationChannel).order_by(NotificationChannel.created_at))
    ).all()
    return [_channel_out(c) for c in channels]


@channels_router.post(
    "", response_model=NotificationChannelOut, status_code=status.HTTP_201_CREATED
)
async def create_channel(
    body: NotificationChannelCreate, user: AdminUser, db: DB
) -> NotificationChannelOut:
    try:
        config = body.validate_for_type()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if body.site_id is not None:
        from app.models import Site

        site = await db.scalar(select(Site).where(Site.id == body.site_id))
        if site is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    channel = NotificationChannel(
        user_id=user.id,
        site_id=body.site_id,
        type=body.type,
        name=body.name,
        config_encrypted=encrypt_json(config),
    )
    db.add(channel)
    await db.flush()
    record_audit(
        db,
        actor=user,
        action="channel.create",
        target_type="notification_channel",
        target_id=channel.id,
        target_label=channel.name,
        after={
            "type": channel.type.value,
            "name": channel.name,
            "site_id": str(body.site_id) if body.site_id else None,
            "target_hint": _target_hint(channel),
        },
    )
    await db.commit()
    return _channel_out(channel)


@channels_router.patch("/{channel_id}", response_model=NotificationChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    user: AdminUser,
    db: DB,
) -> NotificationChannelOut:
    channel = await db.scalar(
        select(NotificationChannel).where(NotificationChannel.id == channel_id)
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    before = {"name": channel.name, "is_active": channel.is_active}
    if body.is_active is not None:
        channel.is_active = body.is_active
    if body.name is not None:
        channel.name = body.name.strip()
    record_audit(
        db,
        actor=user,
        action="channel.update",
        target_type="notification_channel",
        target_id=channel.id,
        target_label=channel.name,
        before=before,
        after={"name": channel.name, "is_active": channel.is_active},
    )
    await db.commit()
    return _channel_out(channel)


@channels_router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: uuid.UUID, user: AdminUser, db: DB) -> None:
    channel = await db.scalar(
        select(NotificationChannel).where(NotificationChannel.id == channel_id)
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    record_audit(
        db,
        actor=user,
        action="channel.delete",
        target_type="notification_channel",
        target_id=channel.id,
        target_label=channel.name,
        before={"type": channel.type.value, "name": channel.name},
    )
    await db.delete(channel)
    await db.commit()


@channels_router.post("/{channel_id}/test", response_model=SettingsTestResult)
async def test_channel(channel_id: uuid.UUID, user: AdminUser, db: DB) -> SettingsTestResult:
    """Send a test notification through one stored channel — the same
    delivery path a real alert takes."""
    channel = await db.scalar(
        select(NotificationChannel).where(NotificationChannel.id == channel_id)
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    try:
        config = decrypt_json(channel.config_encrypted)
    except DecryptionError:
        return SettingsTestResult(
            ok=False, detail="Channel configuration could not be decrypted — re-save the channel"
        )
    from app.alerting import deliver_to_channel

    smtp = await load_setting(db, SMTP_KEY)
    telegram = await load_setting(db, TELEGRAM_KEY)
    ok, detail = await deliver_to_channel(
        channel.type.value,
        config,
        build_test_content(channel.type.value),
        smtp=smtp,
        telegram=telegram,
    )
    return SettingsTestResult(ok=ok, detail="Test notification sent" if ok else detail)
