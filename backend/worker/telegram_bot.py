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
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from telegram import Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app.models import (
    Alert,
    Baseline,
    BaselineStatus,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
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
        await send(
            "Wardress connected. This chat is now linked for alerts and commands.\n\n"
            "Commands:\n"
            "/status - overall watch status\n"
            "/sites - monitored sites\n"
            "/scan <name> - scan a site now\n"
            "/ack <alert id> - acknowledge an alert\n"
            "/mute <site> <duration> - mute a site's alerts (e.g. 2h, 45m, 1d)\n"
            "/explain <site> - plain-English summary of the latest incident\n"
            "/help - this list"
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
            await db.commit()
            await send(f"Alerts for {site.name} are unmuted.")
            return
        site.muted_until = datetime.now(UTC) + timedelta(minutes=duration)
        until = site.muted_until.strftime("%Y-%m-%d %H:%M UTC")
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
