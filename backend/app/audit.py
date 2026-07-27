"""Audit-log write path (§6 audit_log, Phase 5).

Every config change, baseline reset, suppression-rule change,
settings/channel edit, ack, mute, remediation action, and
user-management action records who/what/when here. Rules:

- **Never secret values.** Callers pass already-redacted snapshots, and
  `_redact` drops known-sensitive keys as a second line of defense.
- **Best-effort by design.** `record_audit` adds the row to the caller's
  session so it commits atomically with the change itself; if the write
  cannot be built (serialization surprise), it logs and returns — an
  audit hiccup must never fail the user's action (rule 6).
- Rows are immutable: there is no update/delete API for audit_log.
"""

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

logger = logging.getLogger(__name__)

# Keys whose values must never reach an audit row, regardless of caller
# discipline. Checked as case-insensitive substrings of the key name.
# Deliberately NOT bare "url": a monitored site's URL is legitimate audit
# content — webhook/Apprise URLs (which embed credentials) are matched by
# their specific key names.
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "key_hash",
    "webhook_url",
    "apprise",
    "service_url",
    "config",  # encrypted channel configs
)

_MAX_VALUE_CHARS = 500
_MAX_KEYS = 40
# Bound recursion so a pathologically nested snapshot can't blow the stack
# or the audit-write budget. Beyond this depth we stringify+cap the branch.
_MAX_DEPTH = 6


def _key_is_sensitive(key: Any) -> bool:
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _scrub_userinfo(text: str) -> str:
    """Strip `user:pass@` credentials embedded in a URL-shaped value.

    A monitored site URL is legitimate audit content, but a webhook/Apprise
    URL carrying `https://user:token@host/…` would leak the secret through a
    non-sensitive key. Replace any `//user:pass@` authority with `//[redacted]@`.
    """
    if "://" not in text or "@" not in text:
        return text
    return re.sub(r"(://)[^/@\s]+@", r"\1[redacted]@", text)


def _redact_value(value: Any, depth: int) -> Any:
    """Recursively scrub a single value: drop sensitive keys at any depth,
    strip URL userinfo, and stringify+cap scalars. Depth-bounded."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        if depth >= _MAX_DEPTH:
            return _cap_text(str(value))
        return {
            str(k): ("[redacted]" if _key_is_sensitive(k) else _redact_value(v, depth + 1))
            for k, v in list(value.items())[:_MAX_KEYS]
        }
    if isinstance(value, (list, tuple)):
        if depth >= _MAX_DEPTH:
            return _cap_text(str(value))
        return [_redact_value(v, depth + 1) for v in list(value)[:_MAX_KEYS]]
    return _cap_text(_scrub_userinfo(str(value)))


def _cap_text(text: str) -> str:
    return text[:_MAX_VALUE_CHARS] + ("…" if len(text) > _MAX_VALUE_CHARS else "")


def _redact(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Defensive scrub: drop sensitive keys (at any nesting depth), strip
    URL userinfo, stringify+cap odd values, bounded in depth/breadth."""
    if snapshot is None:
        return None
    result = _redact_value(snapshot, 0)
    # _redact_value on a dict returns a dict; narrow the type for callers.
    return result if isinstance(result, dict) else {"value": result}


def record_audit(
    db: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str | None = None,
    target_label: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor_label: str | None = None,
) -> None:
    """Queue an audit row on the caller's session (commits with it).

    Synchronous on purpose: it only stages the row; the caller's own
    commit persists change + audit atomically. Never raises.
    `actor_label` names non-user actors (e.g. the Telegram bot) in the
    display slot when `actor` is None.
    """
    try:
        db.add(
            AuditLog(
                actor_id=actor.id if actor is not None else None,
                actor_email=actor.email if actor is not None else actor_label,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                target_label=(target_label or None),
                before_json=_redact(before),
                after_json=_redact(after),
            )
        )
    except Exception:  # pragma: no cover — defensive only
        logger.exception("Could not stage audit row for action %r", action)
