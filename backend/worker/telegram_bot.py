"""Wardress interactive Telegram bot (§8) — python-telegram-bot v22.

Runs as the dedicated `telegram-bot` container (Phase 0 decision).
Commands: /start /status /sites /scan <name> /ack <id> /mute <site>
<duration> /help. Deliberately small: quick pull-based status checks and
simple acknowledgements — the dashboard is the real UI, and outbound
alert pushes go through Apprise tgram://, not this bot.

Lifecycle: the outer loop reads the bot token from the encrypted DB
settings row (Settings screen; TELEGRAM_BOT_TOKEN env is a bootstrap
fallback) and (re)starts polling whenever the token changes. A missing
token idles politely; a revoked token logs and retries on a backoff —
the container never crash-loops, and nothing here can affect scanning.

Access control: the bot only answers the chat captured in Settings. The
first /start after configuring a fresh token captures that chat ID
(shown in the Settings screen as confirmation); any other chat gets a
refusal. One bot, one owner — this is a single-operator tool.
"""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agent.engine import run_turn
from app.agent.guard import resolve_pending
from app.agent.tools import ToolError
from app.audit import record_audit
from app.models import (
    AgentConversation,
    AgentSurface,
    Alert,
    Baseline,
    BaselineStatus,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
    User,
)
from app.scanning import is_stale
from app.settings_store import TELEGRAM_KEY, load_setting, save_setting
from worker.celery_app import celery_app
from worker.db import task_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx logs every polling request at INFO — keep the container log usable.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("wardress.telegram")

TOKEN_POLL_SECONDS = 60
ERROR_BACKOFF_SECONDS = 60

_VERDICT_MARKS = {
    ScanVerdict.clean: "OK",
    ScanVerdict.changed: "CHANGED",
    ScanVerdict.flagged: "FLAGGED",
    ScanVerdict.error: "ERROR",
}


async def _load_bot_settings() -> dict:
    """Current telegram settings dict (may be empty). Env token is only a
    bootstrap fallback for installs that pre-seeded .env."""
    try:
        async with task_session() as db:
            stored = await load_setting(db, TELEGRAM_KEY) or {}
    except Exception:
        log.exception("Could not read telegram settings from the DB")
        stored = {}
    if not stored.get("bot_token"):
        env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if env_token:
            stored = {**stored, "bot_token": env_token}
    return stored


async def _capture_chat(chat_id: int) -> bool:
    """Persist the chat ID on first /start. Returns False when a
    different chat is already captured (refuse — one owner)."""
    async with task_session() as db:
        stored = await load_setting(db, TELEGRAM_KEY) or {}
        existing = str(stored.get("chat_id") or "")
        if existing and existing != str(chat_id):
            return False
        if not existing:
            stored["chat_id"] = str(chat_id)
            stored["chat_captured_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            if not stored.get("bot_token"):
                # Env-token bootstrap: persist so the Settings screen and
                # Apprise pushes see the same configuration.
                env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                if env_token:
                    stored["bot_token"] = env_token
            await save_setting(db, TELEGRAM_KEY, stored)
        return True


async def _authorized(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    async with task_session() as db:
        stored = await load_setting(db, TELEGRAM_KEY) or {}
    captured = str(stored.get("chat_id") or "")
    return bool(captured) and captured == str(update.effective_chat.id)


def _reply(update: Update):
    """The bot replies in plain text only — no markdown parsing surprises
    from site names, no emoji (product rule)."""

    async def send(text: str) -> None:
        if update.effective_chat is not None and update.get_bot() is not None:
            await update.get_bot().send_message(chat_id=update.effective_chat.id, text=text)

    return send


def _guarded(handler):
    """Wrap a command handler with chat authorization + crash isolation:
    a handler exception must answer the user, not kill the poller."""

    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        send = _reply(update)
        try:
            if not await _authorized(update):
                await send(
                    "This bot is linked to a different chat (or none yet). "
                    "Send /start from the owner's chat after configuring the token in Settings."
                )
                return
            await handler(update, context, send)
        except Exception:
            log.exception("Command handler failed")
            try:
                await send("Something went wrong handling that command — see the bot logs.")
            except TelegramError:
                pass

    return wrapped


# --- Commands ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    send = _reply(update)
    try:
        if update.effective_chat is None:
            return
        ok = await _capture_chat(update.effective_chat.id)
        if not ok:
            await send("This bot is already linked to another chat.")
            return
        # Attach the quick-action menu on connect; the buttons just send plain
        # text that flows through the same assistant turn as anything typed.
        await update.get_bot().send_message(
            chat_id=update.effective_chat.id,
            text=(
                "Wardress connected. This chat is now linked for alerts and commands.\n\n"
                "Ask in plain language (e.g. 'scan the blog now', 'what needs attention?') "
                "once an admin links an 'acts as' user in Settings, or use the commands:\n"
                "/status - overall watch status\n"
                "/sites - monitored sites\n"
                "/scan <name> - scan a site now\n"
                "/ack <alert id> - acknowledge an alert\n"
                "/mute <site> <duration> - mute a site's alerts (e.g. 2h, 45m, 1d)\n"
                "/explain <site> - plain-English summary of the latest incident\n"
                "/help - this list"
            ),
            reply_markup=_quick_action_keyboard(),
        )
    except Exception:
        log.exception("/start failed")


async def cmd_help(update, context, send) -> None:
    await send(
        "Wardress commands:\n"
        "/status - overall watch status\n"
        "/sites - monitored sites and their last verdicts\n"
        "/scan <name> - run a scan now (name can be a unique prefix)\n"
        "/ack <alert id> - acknowledge an alert (id prefix works)\n"
        "/mute <site> <duration> - mute alerts, e.g. /mute blog 2h (0 unmutes)\n"
        "/explain <site> - plain-English summary of the latest incident\n"
        "/help - this list"
    )


async def cmd_status(update, context, send) -> None:
    async with task_session() as db:
        total_sites = await db.scalar(select(func.count()).select_from(Site)) or 0
        running = (
            await db.scalar(
                select(func.count())
                .select_from(Scan)
                .where(Scan.status.in_([ScanStatus.pending, ScanStatus.running]))
            )
            or 0
        )
        unacked = (
            await db.scalar(
                select(func.count()).select_from(Alert).where(Alert.acknowledged_at.is_(None))
            )
            or 0
        )
        flagged_sites = (
            await db.scalars(
                select(Site)
                .join(Alert, Alert.site_id == Site.id)
                .where(Alert.acknowledged_at.is_(None))
                .distinct()
            )
        ).all()
    lines = [
        "Wardress status",
        f"Sites monitored: {total_sites}",
        f"Scans in flight: {running}",
        f"Unacknowledged alerts: {unacked}",
    ]
    if flagged_sites:
        lines.append("Needs attention: " + ", ".join(s.name for s in flagged_sites[:10]))
    await send("\n".join(lines))


async def cmd_sites(update, context, send) -> None:
    async with task_session() as db:
        sites = (await db.scalars(select(Site).order_by(Site.name))).all()
        if not sites:
            await send("No sites are being monitored yet. Add one in the dashboard.")
            return
        lines = []
        for site in sites[:30]:
            last = await db.scalar(
                select(Scan)
                .where(Scan.site_id == site.id, Scan.verdict.is_not(None))
                .order_by(Scan.created_at.desc())
                .limit(1)
            )
            mark = _VERDICT_MARKS.get(last.verdict, "-") if last else "no scans yet"
            muted = ""
            if site.muted_until and site.muted_until > datetime.now(UTC):
                muted = f" (muted until {site.muted_until.strftime('%H:%M UTC')})"
            lines.append(f"{site.name}: {mark}{muted}")
        if len(sites) > 30:
            lines.append(f"...and {len(sites) - 30} more (see the dashboard)")
    await send("\n".join(lines))


async def _find_site(db, name: str) -> tuple[Site | None, str | None]:
    """Site by exact name, else unique case-insensitive prefix. Returns
    (site, error_message)."""
    sites = (await db.scalars(select(Site))).all()
    exact = [s for s in sites if s.name.lower() == name.lower()]
    if len(exact) == 1:
        return exact[0], None
    prefix = [s for s in sites if s.name.lower().startswith(name.lower())]
    if len(prefix) == 1:
        return prefix[0], None
    if not prefix:
        return None, f"No site matches '{name}'. /sites lists them."
    names = ", ".join(s.name for s in prefix[:5])
    return None, f"'{name}' is ambiguous: {names}"


async def cmd_scan(update, context, send) -> None:
    name = " ".join(context.args or []).strip()
    if not name:
        await send("Usage: /scan <site name>")
        return
    async with task_session() as db:
        site, err = await _find_site(db, name)
        if site is None:
            await send(err)
            return
        # Same semantics as the API's scan-now endpoint.
        baseline = await db.scalar(
            select(Baseline).where(
                Baseline.site_id == site.id,
                Baseline.is_current.is_(True),
                Baseline.status == BaselineStatus.ready,
            )
        )
        if baseline is None:
            await send(f"{site.name} has no ready baseline yet — capture one in the dashboard.")
            return
        in_flight = await db.scalar(
            select(Scan).where(
                Scan.site_id == site.id,
                Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
            )
        )
        if in_flight is not None:
            if is_stale(in_flight.created_at):
                in_flight.status = ScanStatus.failed
                in_flight.verdict = ScanVerdict.error
                in_flight.error = "Scan never completed — superseded by a new scan"
                in_flight.finished_at = datetime.now(UTC)
            else:
                await send(f"A scan of {site.name} is already in progress.")
                return
        scan = Scan(site_id=site.id, baseline_id=baseline.id, status=ScanStatus.pending)
        db.add(scan)
        await db.commit()
        scan_id = scan.id
        site_name = site.name
    try:
        await asyncio.to_thread(celery_app.send_task, "wardress.run_scan", args=[str(scan_id)])
    except Exception:
        log.exception("Could not enqueue scan from bot")
        await send("Could not reach the task queue — try again shortly.")
        return
    await send(f"Scan of {site_name} started. I'll stay quiet; check /status or the dashboard.")


async def cmd_ack(update, context, send) -> None:
    raw = " ".join(context.args or []).strip().lower()
    if not raw:
        await send("Usage: /ack <alert id> (a unique prefix works)")
        return
    async with task_session() as db:
        alerts = (
            await db.scalars(
                select(Alert)
                .where(Alert.acknowledged_at.is_(None))
                .order_by(Alert.created_at.desc())
            )
        ).all()
        matches = [a for a in alerts if str(a.id).lower().startswith(raw)]
        if not matches:
            await send(f"No unacknowledged alert matches '{raw}'.")
            return
        if len(matches) > 1:
            await send(f"'{raw}' matches {len(matches)} alerts — use more characters.")
            return
        alert = matches[0]
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_via = "telegram"
        record_audit(
            db,
            actor=None,
            actor_label="telegram-bot",
            action="alert.acknowledge",
            target_type="alert",
            target_id=alert.id,
            target_label=f"Alert {str(alert.id)[:8]}",
            after={"risk_score": alert.risk_score, "via": "telegram"},
        )
        await db.commit()
        site = await db.scalar(select(Site).where(Site.id == alert.site_id))
        site_name = site.name if site else "unknown site"
    await send(f"Acknowledged alert {str(alert.id)[:8]} for {site_name}.")


def parse_duration_minutes(raw: str) -> int | None:
    """'45m' / '2h' / '1d' / plain minutes -> minutes; None on nonsense.
    0 is valid (unmute). Capped at 7 days like the API."""
    raw = raw.strip().lower()
    factor = 1
    if raw.endswith("m"):
        raw = raw[:-1]
    elif raw.endswith("h"):
        raw, factor = raw[:-1], 60
    elif raw.endswith("d"):
        raw, factor = raw[:-1], 60 * 24
    if not raw.isdigit():
        return None
    minutes = int(raw) * factor
    return min(minutes, 7 * 24 * 60)


async def cmd_mute(update, context, send) -> None:
    args = list(context.args or [])
    if len(args) < 2:
        await send("Usage: /mute <site> <duration> — e.g. /mute blog 2h (0 unmutes)")
        return
    duration = parse_duration_minutes(args[-1])
    if duration is None:
        await send(f"'{args[-1]}' is not a duration I understand (try 45m, 2h, 1d, or 0).")
        return
    name = " ".join(args[:-1]).strip()
    async with task_session() as db:
        site, err = await _find_site(db, name)
        if site is None:
            await send(err)
            return
        if duration == 0:
            site.muted_until = None
            record_audit(
                db,
                actor=None,
                actor_label="telegram-bot",
                action="site.mute",
                target_type="site",
                target_id=site.id,
                target_label=site.name,
                after={"muted_until": None, "via": "telegram"},
            )
            await db.commit()
            await send(f"Alerts for {site.name} are unmuted.")
            return
        site.muted_until = datetime.now(UTC) + timedelta(minutes=duration)
        until = site.muted_until.strftime("%Y-%m-%d %H:%M UTC")
        record_audit(
            db,
            actor=None,
            actor_label="telegram-bot",
            action="site.mute",
            target_type="site",
            target_id=site.id,
            target_label=site.name,
            after={"muted_until": until, "via": "telegram"},
        )
        await db.commit()
        await send(
            f"Alerts for {site.name} muted until {until}. "
            "Scans keep running; skipped deliveries stay visible in the dashboard."
        )


async def cmd_explain(update, context, send) -> None:
    """§8 'Explain this incident' from the bot: /explain <site> explains
    that site's most recent flagged (else most recent completed) scan
    via the same cached path as the dashboard button."""
    from app.explain import ExplainError, explain_scan

    name = " ".join(context.args or []).strip()
    if not name:
        await send("Usage: /explain <site name>")
        return
    async with task_session() as db:
        site, err = await _find_site(db, name)
        if site is None:
            await send(err)
            return
        scan = await db.scalar(
            select(Scan)
            .where(Scan.site_id == site.id, Scan.verdict == ScanVerdict.flagged)
            .order_by(Scan.created_at.desc())
            .limit(1)
        )
        if scan is None:
            scan = await db.scalar(
                select(Scan)
                .where(Scan.site_id == site.id, Scan.verdict.is_not(None))
                .order_by(Scan.created_at.desc())
                .limit(1)
            )
        if scan is None:
            await send(f"{site.name} has no completed scans yet.")
            return
        try:
            result = await explain_scan(db, scan.id)
        except ExplainError as exc:
            await send(str(exc))
            return
        site_name = site.name
    await send(f"{site_name} — latest incident explained:\n\n{result['explanation']}")


# --- Conversational assistant (shared agent core) ---
#
# Free text (anything that is not a slash command) is routed through the
# same run_turn engine the web surface uses. The bot acts as a real RBAC
# user — the "acts as" link configured in Settings — so tool permissions
# and audit actors are the operator's, never a pseudo-actor free pass. If
# no user is linked, the assistant is off and only slash commands answer.

_QUICK_ACTIONS = [["Status", "Sites"], ["Unacknowledged alerts", "Help"]]


def _quick_action_keyboard() -> ReplyKeyboardMarkup:
    """A persistent button menu for the common asks. The buttons send plain
    text that flows through the same assistant turn as anything typed."""
    return ReplyKeyboardMarkup(_QUICK_ACTIONS, resize_keyboard=True)


async def _load_acting_user(db) -> User | None:
    """The RBAC user the assistant acts as (Settings 'acts as' link). A
    stale link (user deleted/deactivated) resolves to None — the assistant
    then declines rather than running with stale permissions."""
    stored = await load_setting(db, TELEGRAM_KEY) or {}
    raw = stored.get("acting_user_id")
    if not raw:
        return None
    try:
        uid = uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None
    return await db.scalar(select(User).where(User.id == uid, User.is_active.is_(True)))


async def _telegram_conversation(db, user: User) -> AgentConversation:
    """Reuse this user's most recent Telegram thread, else open one. One
    rolling thread per operator keeps context without unbounded growth."""
    conversation = await db.scalar(
        select(AgentConversation)
        .where(
            AgentConversation.user_id == user.id,
            AgentConversation.surface == AgentSurface.telegram,
        )
        .order_by(AgentConversation.updated_at.desc())
        .limit(1)
    )
    if conversation is None:
        conversation = AgentConversation(user_id=user.id, surface=AgentSurface.telegram)
        db.add(conversation)
        await db.commit()
    return conversation


def _confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    """Inline Confirm/Cancel buttons for a high-impact pending action. The
    callback_data carries the action id the guard re-validates on tap."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"confirm:{action_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel:{action_id}"),
            ]
        ]
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route free text through the agent core. Chat authorization mirrors the
    slash commands; a handler crash answers the user, never kills the poller."""
    send = _reply(update)
    try:
        if not await _authorized(update):
            await send(
                "This bot is linked to a different chat (or none yet). "
                "Send /start from the owner's chat after configuring the token in Settings."
            )
            return
        text = (update.message.text if update.message else "") or ""
        text = text.strip()
        if not text:
            return
        async with task_session() as db:
            user = await _load_acting_user(db)
            if user is None:
                await send(
                    "The assistant is not linked to a Wardress user yet. An admin can set "
                    "'acts as' in Settings > Telegram to enable natural-language requests. "
                    "The slash commands (/status, /sites, /scan, ...) still work."
                )
                return
            conversation = await _telegram_conversation(db, user)
            confirm_shown = False
            final_text = ""
            async for event in run_turn(
                db,
                conversation=conversation,
                user=user,
                user_message=text,
                surface="agent-telegram",
            ):
                if event.type == "confirm":
                    action_id = event.data.get("action_id")
                    summary = event.text or "Confirm this action?"
                    if action_id:
                        await update.get_bot().send_message(
                            chat_id=update.effective_chat.id,
                            text=summary,
                            reply_markup=_confirm_keyboard(action_id),
                        )
                        confirm_shown = True
                elif event.type in ("done", "error"):
                    final_text = event.text or final_text
            if final_text and not confirm_shown:
                await send(final_text)
            elif final_text and confirm_shown:
                # The prose (if any) came before the confirm card; send it too.
                await send(final_text)
    except Exception:
        log.exception("Assistant message handler failed")
        try:
            await send("Something went wrong handling that — see the bot logs.")
        except TelegramError:
            pass


async def on_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve an inline Confirm/Cancel tap. The guard re-checks ownership,
    RBAC and expiry against the acting user before running frozen args."""
    query = update.callback_query
    if query is None:
        return
    try:
        await query.answer()
        if not await _authorized(update):
            await query.edit_message_text("This chat is not linked — action ignored.")
            return
        data = query.data or ""
        verb, _, raw_id = data.partition(":")
        if verb not in ("confirm", "cancel") or not raw_id:
            return
        try:
            action_id = uuid.UUID(raw_id)
        except (ValueError, TypeError):
            await query.edit_message_text("That action reference is invalid.")
            return
        async with task_session() as db:
            user = await _load_acting_user(db)
            if user is None:
                await query.edit_message_text(
                    "The assistant is no longer linked to a user — action cancelled."
                )
                return
            try:
                action, result = await resolve_pending(
                    db,
                    action_id=action_id,
                    user=user,
                    confirm=(verb == "confirm"),
                    surface="agent-telegram",
                )
            except ToolError as exc:
                await query.edit_message_text(str(exc))
                return
        if verb == "cancel":
            await query.edit_message_text("Action cancelled.")
        elif isinstance(result, dict) and result.get("error"):
            await query.edit_message_text(f"Action failed: {result['error']}")
        else:
            await query.edit_message_text("Action confirmed and carried out.")
    except Exception:
        log.exception("Confirm callback failed")
        try:
            await query.edit_message_text("Something went wrong resolving that action.")
        except TelegramError:
            pass


# --- Lifecycle ---


def build_application(token: str):
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", _guarded(cmd_help)))
    application.add_handler(CommandHandler("status", _guarded(cmd_status)))
    application.add_handler(CommandHandler("sites", _guarded(cmd_sites)))
    application.add_handler(CommandHandler("scan", _guarded(cmd_scan)))
    application.add_handler(CommandHandler("ack", _guarded(cmd_ack)))
    application.add_handler(CommandHandler("mute", _guarded(cmd_mute)))
    application.add_handler(CommandHandler("explain", _guarded(cmd_explain)))
    application.add_handler(
        CallbackQueryHandler(on_confirm_callback, pattern=r"^(confirm|cancel):")
    )
    # Free text (not a command) flows through the shared agent core. Kept last
    # so it never shadows the slash commands above.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return application


async def _run_until_token_changes(token: str) -> None:
    """Manual PTB lifecycle (initialize/start/start_polling) instead of
    run_polling(): the bot must also watch the DB for a token change from
    the Settings screen and restart itself — run_polling owns the loop
    and only stops on process signals."""
    application = build_application(token)
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    log.info("Bot polling started")
    try:
        while True:
            await asyncio.sleep(TOKEN_POLL_SECONDS)
            current = (await _load_bot_settings()).get("bot_token", "")
            if current != token:
                log.info("Bot token changed in Settings — restarting with the new token")
                return
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        log.info("Bot polling stopped")


async def _main() -> None:
    while True:
        settings = await _load_bot_settings()
        token = settings.get("bot_token", "")
        if not token:
            log.info("No bot token configured — idle. Set it in Settings (or .env).")
            await asyncio.sleep(TOKEN_POLL_SECONDS)
            continue
        try:
            await _run_until_token_changes(token)
        except InvalidToken:
            log.warning(
                "Telegram rejected the bot token (revoked or mistyped) — "
                "retrying in %ss; update it in Settings",
                ERROR_BACKOFF_SECONDS,
            )
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
        except TelegramError as exc:
            log.warning("Telegram API trouble (%s) — retrying in %ss", exc, ERROR_BACKOFF_SECONDS)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
        except Exception:
            log.exception("Unexpected bot failure — retrying in %ss", ERROR_BACKOFF_SECONDS)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
