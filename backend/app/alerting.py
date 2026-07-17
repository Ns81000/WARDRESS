"""Alert content + channel delivery primitives (§8).

Shared by the worker's delivery task and the API's "send test" endpoints
so a passing test exercises the exact code path a real alert takes.

Two transport families:
- `email` channels render the Jinja2 HTML template (CSS inlined via
  premailer) and send through the user's stored SMTP settings with
  aiosmtplib.
- `telegram` and `apprise_url` channels go through Apprise
  (tgram:// built from the stored bot token + chat id, or the raw
  user-supplied Apprise URL).

Every send returns (ok, detail) instead of raising: the caller decides
whether a failure is a logged delivery row (worker) or an HTTP 502
(settings test button). Nothing in here may crash a scan (rule 6).
"""

import asyncio
import logging
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from premailer import transform

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 20

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class AlertContent:
    """One alert, rendered once, deliverable to any channel type."""

    title: str
    body_text: str
    email_subject: str
    email_html: str


def _risk_pct(risk: float | None) -> str:
    return f"{round((risk or 0.0) * 100)}%"


def build_alert_content(
    *,
    site_name: str,
    site_url: str,
    risk_score: float | None,
    flag_threshold: float,
    top_layers: list[dict],
    scan_id: str,
    site_id: str,
    detected_at: str,
    base_url: str,
) -> AlertContent:
    """Render the alert once for all channels. `top_layers` is a list of
    {"label": ..., "score": ...} rows (highest-scoring layers first)."""
    scan_link = f"{base_url.rstrip('/')}/sites/{site_id}/scans/{scan_id}"
    title = f"Wardress alert: {site_name} flagged at {_risk_pct(risk_score)} risk"

    lines = [
        f"Site: {site_name}",
        f"URL: {site_url}",
        f"Fused risk: {_risk_pct(risk_score)} (threshold {_risk_pct(flag_threshold)})",
        f"Detected: {detected_at}",
    ]
    if top_layers:
        lines.append("Top signals:")
        lines.extend(f"  - {layer['label']}: {_risk_pct(layer['score'])}" for layer in top_layers)
    lines.append(f"Details: {scan_link}")
    body_text = "\n".join(lines)

    html_template = _jinja.get_template("email/alert.html")
    raw_html = html_template.render(
        site_name=site_name,
        site_url=site_url,
        risk_pct=_risk_pct(risk_score),
        threshold_pct=_risk_pct(flag_threshold),
        detected_at=detected_at,
        top_layers=[
            {"label": layer["label"], "pct": _risk_pct(layer["score"])} for layer in top_layers
        ],
        scan_link=scan_link,
    )
    # Inline the CSS for email-client compatibility (§8).
    email_html = transform(raw_html, disable_validation=True)

    return AlertContent(
        title=title,
        body_text=body_text,
        email_subject=title,
        email_html=email_html,
    )


def build_test_content(kind: str) -> AlertContent:
    """A benign self-identifying message for the settings test buttons."""
    title = "Wardress test notification"
    body = (
        f"This is a test message from Wardress ({kind}). "
        "If you can read this, the channel is configured correctly."
    )
    html_template = _jinja.get_template("email/test.html")
    email_html = transform(html_template.render(kind=kind), disable_validation=True)
    return AlertContent(title=title, body_text=body, email_subject=title, email_html=email_html)


# --- SMTP (email channels) ---


def smtp_settings_usable(smtp: dict | None) -> bool:
    return bool(smtp and smtp.get("host") and smtp.get("from_addr"))


async def send_email(smtp: dict, to_addr: str, content: AlertContent) -> tuple[bool, str]:
    """Send through the user's SMTP settings. Returns (ok, detail); the
    detail on failure is user-safe (no credentials, no tracebacks)."""
    if not smtp_settings_usable(smtp):
        return False, "SMTP is not configured (host and from address are required)"

    message = EmailMessage()
    from_name = (smtp.get("from_name") or "Wardress").strip()
    message["From"] = formataddr((from_name, smtp["from_addr"]))
    message["To"] = to_addr
    message["Subject"] = content.email_subject
    message.set_content(content.body_text)
    message.add_alternative(content.email_html, subtype="html")

    security = (smtp.get("security") or "starttls").lower()
    port = int(smtp.get("port") or (465 if security == "tls" else 587))
    kwargs: dict = {
        "hostname": smtp["host"],
        "port": port,
        "timeout": SEND_TIMEOUT_SECONDS,
    }
    if security == "tls":
        kwargs["use_tls"] = True
    elif security == "none":
        # Opt out of the automatic STARTTLS upgrade only when the user
        # explicitly chose an unencrypted server (e.g. a LAN relay).
        kwargs["start_tls"] = False
    if smtp.get("username"):
        kwargs["username"] = smtp["username"]
        kwargs["password"] = smtp.get("password") or ""

    try:
        await aiosmtplib.send(message, **kwargs)
        return True, "sent"
    except aiosmtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed — check the username/password (app password?)"
    except aiosmtplib.SMTPConnectError:
        return False, f"Could not connect to SMTP server {smtp['host']}:{port}"
    except aiosmtplib.SMTPException as exc:
        return False, f"SMTP error: {type(exc).__name__}"
    except (TimeoutError, OSError):
        return False, f"SMTP server {smtp['host']}:{port} is unreachable or timed out"
    except Exception as exc:  # never let a send crash the caller
        logger.exception("Unexpected SMTP failure")
        return False, f"Unexpected email failure: {type(exc).__name__}"


# --- Apprise (telegram + apprise_url channels) ---


def build_telegram_apprise_url(bot_token: str, chat_id: str) -> str:
    """Outbound Telegram pushes use Apprise's tgram:// support (§8) —
    the interactive bot container is a separate concern."""
    return f"tgram://{bot_token}/{chat_id}/"


def _redact_apprise_failure(kind: str) -> str:
    # Apprise logs specifics itself; the stored URL embeds credentials so
    # the user-facing detail must never echo it back.
    return (
        f"The {kind} notification service rejected the message or was unreachable — "
        "check the service URL and its credentials"
    )


async def send_apprise(url: str, content: AlertContent, *, kind: str) -> tuple[bool, str]:
    """Send one notification to one Apprise URL. Returns (ok, detail)."""
    try:
        import apprise

        apobj = apprise.Apprise()
        if not apobj.add(url):
            return False, f"The {kind} service URL is not a valid Apprise URL"
        ok = await asyncio.wait_for(
            apobj.async_notify(title=content.title, body=content.body_text),
            timeout=SEND_TIMEOUT_SECONDS * 2,
        )
        if ok:
            return True, "sent"
        return False, _redact_apprise_failure(kind)
    except TimeoutError:
        return False, f"The {kind} notification service timed out"
    except Exception as exc:  # never let a send crash the caller
        logger.exception("Unexpected Apprise failure")
        return False, f"Unexpected notification failure: {type(exc).__name__}"


# --- Channel-level dispatch (one channel, any type) ---


async def deliver_to_channel(
    channel_type: str,
    config: dict,
    content: AlertContent,
    *,
    smtp: dict | None,
    telegram: dict | None,
) -> tuple[bool, str]:
    """Route one rendered alert to one channel config. `smtp`/`telegram`
    are the decrypted global settings dicts (or None when unconfigured)."""
    if channel_type == "email":
        to_addr = (config.get("to") or "").strip()
        if not to_addr:
            return False, "Email channel has no recipient address"
        if not smtp_settings_usable(smtp):
            return False, "SMTP is not configured — set it up in Settings first"
        return await send_email(smtp, to_addr, content)

    if channel_type == "telegram":
        token = ((telegram or {}).get("bot_token") or "").strip()
        chat_id = (config.get("chat_id") or (telegram or {}).get("chat_id") or "").strip()
        if not token:
            return False, "Telegram bot token is not configured — set it up in Settings first"
        if not chat_id:
            return False, "Telegram chat ID is not captured yet — send /start to your bot"
        return await send_apprise(
            build_telegram_apprise_url(token, chat_id), content, kind="telegram"
        )

    if channel_type == "apprise_url":
        url = (config.get("url") or "").strip()
        if not url:
            return False, "Channel has no service URL"
        return await send_apprise(url, content, kind=config.get("kind") or "apprise")

    return False, f"Unknown channel type: {channel_type}"
