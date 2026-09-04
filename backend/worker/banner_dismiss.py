"""Consent/cookie banner suppression for Playwright captures (PROMPT-002
Phase 5).

Every capture uses a fresh browser context — no persisted cookies — so
every capture of a consent-gated site hits the first-visit banner: it
obscures page content in the screenshot, a full-page overlay blocks the
scroll pass's lazy loading, and its DOM elements churn between captures.
This module removes the banner two ways:

1. `inject_consent_cookies(context, url)` — BEFORE navigation, set the
   well-known CMP consent cookies (OneTrust, Cookiebot, CookieYes, IAB
   TCF v2, ...) so banners that check cookies first never appear.
   Cookies are materialized at runtime, scheme-aware:
   `url=f"{scheme}://{host}"` (explicit ports preserved, never a bare
   `"domain": ""`), and Secure-flagged entries are set ONLY for https
   targets (Chromium refuses Secure cookies on http:).
2. `dismiss_banners(page)` — after the page is confirmed real (challenge
   gate passed) but BEFORE the scroll pass, try the curated selector
   list and click the first visible accept/dismiss control. Consent
   iframes (Quantcast, Sourcepoint, Usercentrics) are covered by
   iterating `page.frames()`; Playwright's CSS engine pierces open
   shadow DOM, which covers the Usercentrics host.

Contracts (mirroring worker/page_prepare.py):
- Neither function EVER raises: a failed injection or dismissal is a
  degraded capture, not a failed one.
- `dismiss_banners` returns evidence
  `{"dismissed": bool, "selector": str | None, "attempts": int}`.
- No network policy here: injection is context-level state and clicking
  is page-level interaction — neither creates a new request path, and
  every request the page makes during dismissal still flows through the
  SSRF route guard the caller installed (fetcher._make_ssrf_route_guard).
"""

import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus, urlparse

from playwright.async_api import BrowserContext, ElementHandle, Page

from worker.stealth import BANNER_DISMISS_TIMEOUT_MS

logger = logging.getLogger(__name__)

# A click that hasn't completed within this window has almost certainly
# failed (element detached mid-animation as the banner closes); the loop
# moves on to the next selector rather than burning the whole budget.
_CLICK_TIMEOUT_MS = 1_000
# Post-click pause so the banner's removal starts landing before the
# scroll pass measures the page (best-effort, guarded).
_POST_CLICK_SETTLE_MS = 250

# --- Curated consent cookies ------------------------------------------------
#
# Top CMP cookies by market share. Presence is what suppresses the banner
# on most CMPs (they render only when no consent record exists); values
# mirror each CMP's real "everything accepted / banner dismissed" shape.


def _onetrust_alert_box_closed_value() -> str:
    """OneTrust's OptanonAlertBoxClosed carries the dismissal timestamp
    in its `YYYY.M.D+HH:MM:SS` shape."""
    now = datetime.now(UTC)
    return (
        f"{now.year}.{now.month}.{now.day}"
        f"+{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    )


def _cookiebot_value() -> str:
    """Cookiebot's CookieConsent stamp (URL-encoded JSON-ish, runtime utc)."""
    utc_ms = int(datetime.now(UTC).timestamp() * 1000)
    return (
        "{stamp:%27-1%27,necessary:true,preferences:true,statistics:true,"
        f"marketing:true,method:5,ver:1,utc:{utc_ms},region:%27us%27}}"
    )


def _onetrust_consent_value() -> str:
    """OneTrust's OptanonConsent record. The datestamp mirrors the real
    CMP's `Wkd Mon DD YYYY HH:MM:SS GMT:0000` shape but is stamped at
    runtime (URL-encoded: spaces as `+`, colons as `%3A`) like the
    sibling OptanonAlertBoxClosed value."""
    now = datetime.now(UTC)
    datestamp = quote_plus(f"{now:%a} {now:%b} {now.day:02d} {now.year} {now:%H:%M:%S} GMT:0000")
    return (
        f"isGpcEnabled=0&datestamp={datestamp}"
        "&version=202401.1.0&hosts=&consentIds=&interactionCount=1"
    )


CONSENT_COOKIES: list[dict] = [
    # OneTrust — "often Secure" (the spec's named case): only set on https.
    {
        "name": "OptanonAlertBoxClosed",
        "value_fn": _onetrust_alert_box_closed_value,
        "secure_when_https": True,
    },
    {
        "name": "OptanonConsent",
        "value_fn": _onetrust_consent_value,
        "secure_when_https": True,
    },
    # Cookiebot (Usercentrics Cookiebot)
    {"name": "CookieConsent", "value_fn": _cookiebot_value, "secure_when_https": True},
    # CookieYes (current + legacy key)
    {
        "name": "cookieyes-consent",
        "value": (
            '{"necessary":true,"functional":true,"analytics":true,'
            '"performance":true,"advertisement":true}'
        ),
    },
    {
        "name": "cky-consent",
        "value": (
            '{"necessary":true,"functional":true,"analytics":true,'
            '"performance":true,"advertisement":true}'
        ),
    },
    # IAB TCF v2 consent string (Didomi, Sourcepoint, ... read this key)
    {
        "name": "euconsent-v2",
        "value": (
            "CQJl0AAQJl0AAAHABBENAzCsAPAAAAAAAAAAiQAAAAAAAAAAAAAAAAAAAA.YAAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        ),
        "secure_when_https": True,
    },
    # Didomi
    {
        "name": "didomi_token",
        "value": (
            "eyJ2ZXJzaW9uIjoxLCJjcmVhdGVkQXQiOiIyMDI2LTAxLTAxVDAwOjAwOjAwLjAwMFoi"
            "LCJ1cGRhdGVkQXQiOiIyMDI2LTAxLTAxVDAwOjAwOjAwLjAwMFoifQ"
        ),
    },
    # Cookie Script
    {
        "name": "CookieScriptConsent",
        "value": (
            '{"consentid":"wardress-consent","categories":{"necessary":true,'
            '"functional":true,"analytics":true,"marketing":true},'
            '"action":"accept"}'
        ),
    },
    # Klaro!
    {
        "name": "klaro",
        "value": (
            '{"accepted":["necessary","functional","analytics","marketing"],'
            '"declined":[],"modified":"2026-01-01T00:00:00.000Z"}'
        ),
    },
    # Complianz (GDPR Cookie Consent)
    {"name": "cmplz_consented_services", "value": "W10="},
    # Borlabs Cookie
    {
        "name": "borlabs-cookie",
        "value": (
            '{"status":true,"essential":[],"statistics":[],"marketing":[],'
            '"consents":{"essential":true,"statistics":true,"marketing":true}}'
        ),
    },
    # Osano
    {
        "name": "osano_consentmanager",
        "value": (
            '{"essential":true,"analytics":true,"marketing":true,'
            '"storage":true,"version":"1.0"}'
        ),
    },
    # tarteaucitron.js
    {
        "name": "tarteaucitron",
        "value": "!necessary=true!functional=true!analytics=true!marketing=true",
    },
]

# --- Curated dismiss selectors ----------------------------------------------
#
# Ordered CMP-specific first: the first VISIBLE match is clicked, so the
# broad generic patterns at the end only ever fire when no known CMP
# control matched. Playwright's CSS engine pierces open shadow DOM (the
# Usercentrics host) and supports selector lists (the combined wait).

DISMISS_SELECTORS: list[str] = [
    # OneTrust
    "#onetrust-accept-btn-handler",
    ".onetrust-close-btn-handler",
    # Cookiebot
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    # CookieYes
    ".cky-btn-accept",
    "#cookie_action_accept",
    # CookieConsent (orestbida, generic CMP)
    ".cc-accept-all",
    ".cc-btn.cc-allow",
    ".cc-btn.cc-dismiss",
    # Complianz
    ".cmplz-btn.cmplz-accept",
    # Borlabs
    ".brlbs-btn-accept-all",
    # Cookie Script
    "#CookieScriptUserPreferenceAccept",
    # Klaro!
    ".klaro .cm-btn-success",
    # tarteaucitron
    "#tarteaucitronAcceptAll",
    # Osano
    ".osano-cm-accept-all",
    # Didomi
    "#didomi-notice-agree-button",
    # Quantcast Choice (also renders in consent iframes)
    ".fc-cta-consent",
    # Sourcepoint
    "#sp-cc-accept",
    # Usercentrics (open shadow root — pierced by Playwright's CSS engine)
    "#usercentrics-root button[data-testid='uc-accept-all-button']",
    # iubenda
    ".iubenda-cs-accept-btn",
    # TrustArc
    "#truste-consent-button",
    # Generic / accessible banners
    "[data-testid='cookie-policy-dialog-accept-button']",
    "button[aria-label*='Accept']",
    "button[aria-label*='accept']",
    "button[aria-label*='Agree']",
    ".cmp-accept-all",
    "#accept-cookies",
    "#acceptCookies",
    ".js-cookie-accept",
    ".cookie-accept",
]


# --- Cookie materialization --------------------------------------------------


def _cookie_url_target(url: str) -> tuple[str, str] | None:
    """(scheme, host-part) for a cookie's scheme-aware `url` attribute.

    The host part keeps an explicit port and brackets IPv6 literals;
    returns None for anything that cannot carry cookies (non-http(s)
    scheme, missing host, unparseable URL).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    scheme = (parsed.scheme or "").lower()
    hostname = parsed.hostname or ""
    if scheme not in ("http", "https") or not hostname:
        return None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return scheme, (f"{hostname}:{port}" if port else hostname)


def materialize_consent_cookies(url: str) -> list[dict]:
    """Build the runtime cookie list for one target: scheme-aware `url`
    per cookie (explicit ports preserved, never a bare `"domain": ""`),
    runtime-generated values, and Secure flags only on https targets."""
    target = _cookie_url_target(url)
    if target is None:
        return []
    scheme, host_part = target
    cookies: list[dict] = []
    for entry in CONSENT_COOKIES:
        value = entry["value_fn"]() if "value_fn" in entry else entry["value"]
        cookie: dict = {
            "name": entry["name"],
            "value": value,
            "url": f"{scheme}://{host_part}",
        }
        if entry.get("secure_when_https") and scheme == "https":
            cookie["secure"] = True
        cookies.append(cookie)
    return cookies


async def inject_consent_cookies(context: BrowserContext, url: str) -> list[str]:
    """Set the common CMP consent cookies on a fresh context BEFORE
    navigation so first-visit banners never render.

    Returns the list of cookie names injected (empty when the target
    cannot carry cookies or the injection failed). Never raises — a
    failed injection is a banner that may appear, not a failed capture.
    """
    try:
        cookies = materialize_consent_cookies(url)
        if not cookies:
            logger.debug("Consent-cookie injection skipped for %r", url)
            return []
        await context.add_cookies(cookies)
        names = [c["name"] for c in cookies]
        logger.debug("Injected %d consent cookies before navigation", len(names))
        return names
    except Exception:  # noqa: BLE001 — injection must never fail a capture
        logger.debug("Consent-cookie injection degraded; capture continues", exc_info=True)
        return []


# --- Click dismissal ---------------------------------------------------------


async def _clickable_in_viewport(el: ElementHandle, page: Page) -> bool:
    """True when the element has a bounding box intersecting the viewport
    — a banner control hidden off-screen must not be clicked."""
    try:
        box = await el.bounding_box()
    except Exception:  # noqa: BLE001 — detached mid-check: not clickable
        return False
    if box is None:
        return False
    viewport = page.viewport_size or {}
    vw = viewport.get("width") or 0
    vh = viewport.get("height") or 0
    if vw <= 0 or vh <= 0:
        # Unknown viewport: fall back to visibility alone.
        return True
    return (
        box["x"] < vw
        and box["y"] < vh
        and box["x"] + box["width"] > 0
        and box["y"] + box["height"] > 0
    )


def _frames(page: Page) -> list:
    """Main frame first, then child frames (consent iframes included)."""
    return [page.main_frame, *(f for f in page.frames if f is not page.main_frame)]


async def _find_and_click(page: Page, frames: list, evidence: dict) -> bool:
    """One pass over every frame × selector; clicks the first visible,
    in-viewport match. Records `attempts` and mutates `evidence` on
    success. Never raises."""
    for frame in frames:
        for selector in DISMISS_SELECTORS:
            evidence["attempts"] += 1
            try:
                el = await frame.query_selector(selector)
            except Exception:  # noqa: BLE001 — a broken frame is skipped
                logger.debug("Banner query failed in frame %s", frame.url, exc_info=True)
                continue
            if el is None or not await el.is_visible():
                continue
            if not await _clickable_in_viewport(el, page):
                continue
            try:
                await el.click(timeout=_CLICK_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 — try the next selector
                logger.debug("Banner click failed for %s", selector, exc_info=True)
                continue
            evidence["dismissed"] = True
            evidence["selector"] = selector
            logger.info("Dismissed consent banner via %s", selector)
            return True
    return False


async def _post_click_settle(page: Page) -> None:
    try:
        await page.wait_for_timeout(_POST_CLICK_SETTLE_MS)
    except Exception:  # noqa: BLE001 — best-effort pause
        logger.debug("Post-dismissal settle skipped", exc_info=True)


async def dismiss_banners(page: Page, *, timeout_ms: int = BANNER_DISMISS_TIMEOUT_MS) -> dict:
    """Attempt to click dismiss/accept buttons on cookie banners.

    Tries each curated selector across the main frame and every consent
    iframe and clicks the first visible match. Banners are almost always
    in the DOM after the capture's settle window, so the first pass is
    instant; when nothing matched, ONE combined-selector wait consumes
    the remaining budget for a late-rendering banner before a final
    pass. The total time spent is bounded by `timeout_ms`.

    Returns evidence: `{"dismissed": bool, "selector": str | None,
    "attempts": int}`. Never raises — a failed dismissal is not a
    capture failure.
    """
    evidence: dict = {"dismissed": False, "selector": None, "attempts": 0}
    try:
        frames = _frames(page)
        if await _find_and_click(page, frames, evidence):
            await _post_click_settle(page)
            return evidence

        deadline = time.monotonic() + timeout_ms / 1000
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return evidence
        combined = ",".join(DISMISS_SELECTORS)
        try:
            await page.wait_for_selector(combined, state="visible", timeout=remaining_ms)
        except Exception:  # noqa: BLE001 — timeout/no match: nothing to click
            return evidence
        if await _find_and_click(page, frames, evidence):
            await _post_click_settle(page)
    except Exception:  # noqa: BLE001 — dismissal must never fail a capture
        logger.debug("Banner dismissal degraded; capture continues as-is", exc_info=True)
    return evidence
