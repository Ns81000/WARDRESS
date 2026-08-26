"""Opt-in site favicon resolver (Phase 27 residual-risk follow-up).

Default OFF: sites pages render local letter avatars and nothing leaves
the deployment (the Phase 27 privacy property — target confidentiality —
is the default). When an admin enables ``favicon_resolution_enabled``,
``GET /api/sites/{site_id}/icon`` fetches the monitored site's favicon
**once** through our own backend, caches it in the ``site_icons`` table,
and serves those bytes to authenticated dashboard clients.

Security posture:
- The hostname comes from the stored site URL, never from request input.
- Every outbound URL passes ``app.ssrf.assert_url_allowed`` before any
  request; redirects are followed manually with a small hop cap and each
  hop is re-gated (redirect-to-internal is the classic bypass).
- Only raster image formats are accepted, enforced by magic-byte sniffing.
  SVG is deliberately rejected: serving attacker-controlled markup from
  the monitored origin as an image resource keeps <img> XSS-safety but
  adds no value over raster favicons, and refusing it keeps every stored
  byte provably a bitmap (mirrors the artifact router's untrusted-content
  conservatism).
- Downloads are size-capped (64 KiB) so a hostile server cannot exhaust
  memory.
- Failures store only a type-level detail string — never the fetched URL
  or its credentials (Phase 26 redaction discipline).
- robots.txt is deliberately not consulted: fetching /favicon.ico is
  standard browser behavior for any page a user visits, not crawling,
  and the operator has opted in to exactly this request.

Concurrency: two operators loading the dashboard simultaneously for a
never-fetched site must not double-fetch (thundering herd against a dead
site on every dashboard render). Exactly one request wins an atomic
claim — the repo's established primitive: a conditional UPDATE whose
rowcount arbitrates (refresh-token rotation, remediation confirm queue,
alert acks) plus the unique site_id constraint arbitrating the first-ever
insert — and losers poll briefly for the winner's row before falling back
to a graceful 404 (cosmetic: the frontend renders the letter avatar).

Test seam: tests monkeypatch :func:`fetch_outcome_for_site` (the only
network-touching function) to keep the suite hermetic (Phase 30).
"""

import asyncio
import re
import time as _time
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Site, SiteIcon
from app.settings_store import load_setting

FAVICON_SETTING_KEY = "favicon"

# Outbound-fetch budget per resolution attempt: /favicon.ico first, then
# ONE homepage GET for link discovery (+ its icon download if different).
_MAX_REDIRECT_HOPS = 3
_MAX_ICON_BYTES = 64 * 1024
_MAX_HOME_HTML_BYTES = 256 * 1024
_TIMEOUT_SECONDS = 5.0
_NEGATIVE_CACHE_TTL = timedelta(hours=24)
_STALE_OK_REFRESH = timedelta(days=30)
_CLAIM_WAIT_SECONDS = 8.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def sniffed_content_type(body: bytes) -> str | None:
    """Content type by magic bytes. The stored/served content type always
    comes from HERE, never from the remote Content-Type header (servers
    lie; error pages get served as image/png all too often)."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"GIF87a") or body.startswith(b"GIF89a"):
        return "image/gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    return None


class FetchOutcome:
    __slots__ = ("ok", "body", "content_type", "source_url", "detail")

    def __init__(
        self,
        ok: bool,
        body: bytes = b"",
        content_type: str = "",
        source_url: str = "",
        detail: str = "",
    ) -> None:
        self.ok = ok
        self.body = body
        self.content_type = content_type
        self.source_url = source_url
        self.detail = detail


async def _gate_url(url: str, allow_private_networks: bool) -> None:
    from app.ssrf import SSRFBlockedError, assert_url_allowed

    try:
        assert_url_allowed(url, allow_private_networks=allow_private_networks)
    except SSRFBlockedError:
        raise


async def _fetch_with_gates(
    client: httpx.AsyncClient,
    url: str,
    *,
    allow_private_networks: bool,
    max_bytes: int,
) -> tuple[bytes | None, str]:
    """GET one gated URL, following redirects MANUALLY with a small hop cap
    and re-validation of every hop's URL before the request (an open
    redirect onto an internal host must die at the hop, not after the
    fetch). Returns ``(body_or_None, final_content_type)``."""
    hops = 0
    while True:
        await _gate_url(url, allow_private_networks)
        resp = await client.get(url)
        if resp.is_redirect:
            location = resp.headers.get("location", "")
            if not location:
                return None, ""
            nxt = urljoin(url, location)
            scheme = nxt.split(":", 1)[0].lower()
            if scheme not in ("http", "https"):
                return None, ""
            hops += 1
            if hops > _MAX_REDIRECT_HOPS:
                return None, ""
            url = nxt
            continue
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if resp.status_code != 200:
            return None, ctype
        body = resp.content[: max_bytes + 1]
        return body, ctype


def extract_icon_href(html: bytes | None) -> str | None:
    """First <link> whose rel mentions 'icon' (shortcut icon,
    apple-touch-icon included), tolerant of malformed markup."""
    if not html:
        return None
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover — decode with errors= never raises
        return None
    lower = text.lower()
    idx = 0
    while True:
        start = lower.find("<link", idx)
        if start == -1:
            return None
        end = lower.find(">", start)
        if end == -1:
            return None
        tag_lower = lower[start : end + 1]
        m_rel = re.search(r'rel=["\']([^"\']+)["\']', tag_lower)
        if m_rel and "icon" in m_rel.group(1):
            m_href = re.search(r'href=["\']([^"\']+)["\']', tag_lower)
            if m_href and m_href.group(1):
                return m_href.group(1)
        idx = end + 1


async def attempt_favicon_fetch(site: Site) -> FetchOutcome:
    """The real network path. Two-request budget:
    https://host/favicon.ico first; failing that, one homepage GET to
    discover a declared icon, resolved against the base URL (absolute URLs
    pass through; scheme-relative handled by urljoin) and gated+fetched
    like any other hop."""
    from app.ssrf import SSRFBlockedError

    base = site.url.rstrip("/")
    allow_private = bool(site.allow_private_networks)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT_SECONDS), follow_redirects=False
    ) as client:
        primary = f"{base}/favicon.ico"
        try:
            body, _ctype = await _fetch_with_gates(
                client, primary, allow_private_networks=allow_private, max_bytes=_MAX_ICON_BYTES
            )
            sniffed = sniffed_content_type(body) if body else None
            if body is not None and len(body) <= _MAX_ICON_BYTES and sniffed:
                return FetchOutcome(True, body, sniffed, primary)
        except SSRFBlockedError:
            raise
        except (httpx.HTTPError, OSError, ValueError):
            pass  # unreachable/timeout/bad URL — fall through to discovery

        try:
            homepage_body, _ = await _fetch_with_gates(
                client,
                site.url,
                allow_private_networks=allow_private,
                max_bytes=_MAX_HOME_HTML_BYTES,
            )
            icon_ref = extract_icon_href(homepage_body)
            if not icon_ref or homepage_body is None:
                raise _NoIconRef()
            resolved = urljoin(f"{site.url}/", icon_ref)
            body, _ctype = await _fetch_with_gates(
                client, resolved, allow_private_networks=allow_private, max_bytes=_MAX_ICON_BYTES
            )
            sniffed = sniffed_content_type(body) if body else None
            if body is not None and len(body) <= _MAX_ICON_BYTES and sniffed:
                return FetchOutcome(True, body, sniffed, resolved)
        except SSRFBlockedError:
            raise
        except (_NoIconRef, httpx.HTTPError, OSError, ValueError):
            pass

    return FetchOutcome(False, detail="unreachable-or-not-an-image")


class _NoIconRef(Exception):
    """Homepage carried no discoverable icon link."""


async def fetch_outcome_for_site(site: Site) -> FetchOutcome:
    """Network seam for tests: monkeypatch THIS in test modules (it is the
    only outbound-reaching symbol resolve_site_icon depends on), keeping
    the suite hermetic per Phase 30."""
    return await attempt_favicon_fetch(site)


async def get_favicon_enabled(db: AsyncSession) -> bool:
    stored = await load_setting(db, FAVICON_SETTING_KEY)
    return bool(stored and stored.get("enabled"))


async def _wait_for_winner(db: AsyncSession, site_id, deadline_s: float):
    """Poll briefly for a concurrent resolver to finish; serve whatever
    landed, else None (the caller answers 404 → letter-avatar fallback).
    Commit before each poll so this session's read snapshot ends and the
    next SELECT starts a new transaction that can observe the winner's
    committed row (polling inside one long-lived transaction would keep
    re-reading the stale pre-fetch snapshot forever)."""
    deadline = _time.monotonic() + deadline_s
    while _time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        await db.commit()  # end the open transaction -> fresh snapshot
        db.expire_all()
        fresh = await db.scalar(select(SiteIcon).where(SiteIcon.site_id == site_id))
        if fresh is not None and fresh.claimed_at is None:
            return fresh
    return None


async def resolve_site_icon(db: AsyncSession, site: Site) -> tuple[SiteIcon | None, bool]:
    """Cache-first resolution returning ``(row_or_None, fetched_now)``.

    Cache states:
    - ok row younger than 30 days → serve (no network).
    - failed row inside its 24h negative-cache window → 404 (no network;
      prevents refetch storms against dead sites on every dashboard load).
    - no row / expired failure / stale-ok → ONE claim-arbitrated fetch.

    The atomic claim uses the repo's conditional-UPDATE primitive:
    ``claimed_at IS NULL -> claimed_at = now()`` with rowcount as the
    arbiter. The first-ever insert races on site_id's unique constraint
    instead (INSERT ... catch IntegrityError); both losers converge to the
    same brief poll-and-fallback path.
    """
    now = _utcnow()
    row = await db.scalar(select(SiteIcon).where(SiteIcon.site_id == site.id))

    if row is not None:
        if row.status == "ok":
            if now - _as_aware(row.fetched_at) <= _STALE_OK_REFRESH:
                return row, False
        else:
            if _as_aware(row.retry_after) > now:
                return row, False

    claim_token = now
    working_row = None
    if row is not None:
        claimed = await db.execute(
            update(SiteIcon)
            .where(SiteIcon.site_id == site.id, SiteIcon.claimed_at.is_(None))
            .values(claimed_at=claim_token)
        )
        await db.commit()
        if claimed.rowcount == 0:
            loser_wait = await _wait_for_winner(db, site.id, _CLAIM_WAIT_SECONDS)
            return loser_wait, False
        working_row = await db.scalar(select(SiteIcon).where(SiteIcon.site_id == site.id))
    else:
        candidate = SiteIcon(
            site_id=site.id,
            status="failed",
            data=b"",
            content_type="",
            source_url=None,
            detail="pending",
            fetched_at=now,
            retry_after=now,
            claimed_at=claim_token,
        )
        db.add(candidate)
        try:
            await db.commit()
            working_row = candidate
        except Exception:
            # Lost the unique-constraint insert race to a concurrent request.
            await db.rollback()
            loser_wait = await _wait_for_winner(db, site.id, _CLAIM_WAIT_SECONDS)
            return loser_wait, False

    try:
        outcome = await fetch_outcome_for_site(site)
    except Exception:
        outcome = FetchOutcome(False, detail="resolver-error")

    now = _utcnow()
    if outcome.ok:
        # Enforce the size cap AND the raster contract at the cache boundary:
        # the fetch seam is also where a hostile server's oversize body or
        # mislabeled non-image payload (HTML error page as image/png) gets
        # refused. Only magic-byte-verified rasters may be stored.
        sniffed = sniffed_content_type(outcome.body) if outcome.body else None
        if not outcome.body or len(outcome.body) > _MAX_ICON_BYTES or sniffed is None:
            working_row.status = "failed"
            working_row.data = b""
            working_row.content_type = ""
            working_row.source_url = None
            working_row.detail = "not-a-raster-image" if sniffed is None else "oversize-or-empty"
            working_row.fetched_at = now
            working_row.retry_after = now + _NEGATIVE_CACHE_TTL
        else:
            working_row.status = "ok"
            working_row.data = outcome.body
            # Serve the sniffed type, never the remote header's claim.
            working_row.content_type = sniffed
            working_row.source_url = outcome.source_url
            working_row.detail = None
            working_row.fetched_at = now
            working_row.retry_after = now
    else:
        working_row.status = "failed"
        working_row.data = b""
        working_row.content_type = ""
        working_row.source_url = None
        working_row.detail = outcome.detail
        working_row.fetched_at = now
        working_row.retry_after = now + _NEGATIVE_CACHE_TTL
    working_row.claimed_at = None
    await db.commit()
    await db.refresh(working_row)
    return working_row, True
