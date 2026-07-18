"""Settings endpoints (§7): SMTP, Telegram, Gemini, Ollama, and
notification channels — each with a test endpoint where §8 demands one.

Stored values are encrypted at rest (app/crypto.py) and never round-trip
to the client: GET responses carry redacted hints ("smtp.ex...", key
prefixes) plus `configured` flags, and PATCH-like semantics let the
client keep a stored secret by omitting the field.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.config import get_settings
from app.crypto import DecryptionError, decrypt_json, encrypt_json
from app.db import get_db
from app.deps import AdminUser
from app.models import NotificationChannel, NotificationChannelType
from app.schemas import (
    GeminiSettingsIn,
    GeminiSettingsOut,
    NotificationChannelCreate,
    NotificationChannelOut,
    NotificationChannelUpdate,
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
    GEMINI_KEY,
    OLLAMA_KEY,
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


@router.get("/telegram", response_model=TelegramSettingsOut)
async def get_telegram(user: AdminUser, db: DB) -> TelegramSettingsOut:
    tg = await load_setting(db, TELEGRAM_KEY)
    if not tg or not tg.get("bot_token"):
        return TelegramSettingsOut(configured=False)
    return TelegramSettingsOut(
        configured=True,
        token_hint=_hint(tg["bot_token"], keep=10),
        chat_id=tg.get("chat_id"),
        chat_captured_at=tg.get("chat_captured_at"),
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
    record_audit(
        db,
        actor=user,
        action="settings.telegram.update",
        target_type="settings",
        target_id="telegram",
        target_label="Telegram settings",
        after={"configured": True, "token_changed": token != existing.get("bot_token")},
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


# --- Gemini (§8 optional cloud intelligence) ---


@router.get("/gemini", response_model=GeminiSettingsOut)
async def get_gemini(user: AdminUser, db: DB) -> GeminiSettingsOut:
    g = await load_setting(db, GEMINI_KEY)
    if not g or not g.get("api_key"):
        return GeminiSettingsOut(configured=False, model=get_settings().gemini_model)
    return GeminiSettingsOut(
        configured=True,
        enabled=bool(g.get("enabled", True)),
        key_hint=_hint(g["api_key"]),
        model=get_settings().gemini_model,
    )


@router.put("/gemini", response_model=GeminiSettingsOut)
async def put_gemini(body: GeminiSettingsIn, user: AdminUser, db: DB) -> GeminiSettingsOut:
    existing = await load_setting(db, GEMINI_KEY) or {}
    key = existing.get("api_key", "") if body.api_key is None else body.api_key.strip()
    if not key:
        record_audit(
            db,
            actor=user,
            action="settings.gemini.update",
            target_type="settings",
            target_id="gemini",
            target_label="Gemini settings",
            after={"configured": False},
        )
        await delete_setting(db, GEMINI_KEY)
        return GeminiSettingsOut(configured=False, model=get_settings().gemini_model)
    record_audit(
        db,
        actor=user,
        action="settings.gemini.update",
        target_type="settings",
        target_id="gemini",
        target_label="Gemini settings",
        after={"configured": True, "enabled": body.enabled},
    )
    await save_setting(db, GEMINI_KEY, {"api_key": key, "enabled": body.enabled})
    return await get_gemini(user, db)


@router.post("/gemini/test", response_model=SettingsTestResult)
async def test_gemini(user: AdminUser, db: DB) -> SettingsTestResult:
    """One cheap gemini-flash-latest call to confirm the stored key works
    (§7). Uses the same client module the worker's escalation uses."""
    g = await load_setting(db, GEMINI_KEY)
    if not g or not g.get("api_key"):
        return SettingsTestResult(ok=False, detail="Gemini API key is not configured yet")
    from app.llm import gemini_test_call

    ok, detail = await gemini_test_call(g["api_key"])
    return SettingsTestResult(ok=ok, detail=detail)


# --- Ollama (§8 optional local LLM) ---


@router.get("/ollama", response_model=OllamaSettingsOut)
async def get_ollama(user: AdminUser, db: DB) -> OllamaSettingsOut:
    o = await load_setting(db, OLLAMA_KEY)
    if not o:
        return OllamaSettingsOut(configured=False, base_url=get_settings().ollama_base_url)
    return OllamaSettingsOut(
        configured=True,
        enabled=bool(o.get("enabled")),
        base_url=o.get("base_url") or get_settings().ollama_base_url,
        model=o.get("model"),
    )


@router.put("/ollama", response_model=OllamaSettingsOut)
async def put_ollama(body: OllamaSettingsIn, user: AdminUser, db: DB) -> OllamaSettingsOut:
    value = {
        "enabled": body.enabled,
        "base_url": (body.base_url or "").strip() or get_settings().ollama_base_url,
        "model": (body.model or "").strip() or None,
    }
    record_audit(
        db,
        actor=user,
        action="settings.ollama.update",
        target_type="settings",
        target_id="ollama",
        target_label="Ollama settings",
        after={"enabled": value["enabled"], "base_url": value["base_url"], "model": value["model"]},
    )
    await save_setting(db, OLLAMA_KEY, value)
    return await get_ollama(user, db)


@router.post("/ollama/test", response_model=SettingsTestResult)
async def test_ollama(user: AdminUser, db: DB) -> SettingsTestResult:
    o = await load_setting(db, OLLAMA_KEY)
    if not o or not o.get("enabled"):
        return SettingsTestResult(ok=False, detail="Ollama is not enabled yet — save it first")
    from app.llm import ollama_test_call

    ok, detail = await ollama_test_call(
        o.get("base_url") or get_settings().ollama_base_url, o.get("model")
    )
    return SettingsTestResult(ok=ok, detail=detail)


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
