"""Playwright-based page capture used by baseline and scan tasks.

Async API throughout — task bodies run under asyncio.run() in the Celery
worker. Every fetch re-validates the target against the SSRF policy
immediately before navigation, and validates the FINAL url after
redirects (a public site redirecting to an internal address is refused).

After the page settles, the capture checks for Cloudflare challenge/
block pages (PROMPT-002 Phase 2): a solvable JS challenge gets a bounded
wait to auto-solve, and a persistent challenge fails the capture with a
user-safe error — challenge HTML is never stored as site content.

Once the page is confirmed real (PROMPT-002 Phase 3), it is auto-scrolled
top-to-bottom so IntersectionObserver/scroll-event lazy content loads,
then waits for the DOM to stabilize before HTML + screenshot are taken
(worker/page_prepare.py). Both helpers never raise, so the capture
failure semantics below are unchanged.
"""

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response, Route, async_playwright

from app.ssrf import SSRFBlockedError, assert_url_allowed
from worker.page_prepare import auto_scroll_page, wait_for_content_stable
from worker.stealth import (
    BROWSER_LAUNCH_ARGS,
    CAPTURE_USER_AGENT,
    CONTEXT_COLOR_SCHEME,
    CONTEXT_LOCALE,
    CONTEXT_TIMEZONE_ID,
    CONTEXT_VIEWPORT,
    MAX_SCROLL_TIME_MS,
    SETTLE_MS,
    apply_stealth,
)

logger = logging.getLogger(__name__)

NAV_TIMEOUT_MS = 60_000
SCREENSHOT_TIMEOUT_MS = 45_000
MAX_HTML_BYTES = 10 * 1024 * 1024  # refuse absurd pages rather than OOM


class FetchError(Exception):
    """Fetch failed for an operational reason (site down, timeout, etc.).
    Message is user-safe and stored on the baseline/scan row."""


@dataclass
class FetchResult:
    html: str
    screenshot: bytes
    final_url: str
    http_status: int | None
    headers: dict[str, str]


# --- Cloudflare challenge detection (PROMPT-002 Phase 2) --------------------
#
# A challenge page must NEVER be stored as capture content: it would sit on
# the baseline/scan row as if it were the real site and poison every later
# comparison. After the page settles we look for Cloudflare's known
# challenge/block markers; when one is present we wait (bounded by the
# navigation budget) for the JS challenge to auto-solve for a real browser,
# re-checking periodically, and fail the capture with a user-safe message
# if the page is still challenged.
CHALLENGE_WAIT_MS = 10_000  # max total auto-solve wait
CHALLENGE_POLL_MS = 1_000  # re-check cadence while waiting

BOT_PROTECTION_ERROR = (
    "Site is behind bot protection that could not be bypassed "
    "(Cloudflare challenge detected)"
)

_CHALLENGE_TITLE_MARKERS = ("just a moment", "attention required")
_CHALLENGE_MARKER_SELECTOR = ".cf-challenge-running, .cf-error-details"

# DOM probe for the two Cloudflare-specific classes. Class selectors only —
# never body text, which legitimately mentions these strings on sites that
# write about (or imitate) challenge pages.
_CHALLENGE_PROBE_JS = (
    "() => ({"
    " title: document.title || '',"
    f" marker: !!document.querySelector('{_CHALLENGE_MARKER_SELECTOR}'),"
    "})"
)


def is_challenge_title(title: str | None) -> bool:
    """True when the page title carries a canonical Cloudflare challenge/
    block marker. Title-only by design: body text is content."""
    lowered = (title or "").strip().lower()
    return any(marker in lowered for marker in _CHALLENGE_TITLE_MARKERS)


def looks_like_challenge_page(
    *,
    title: str | None = None,
    has_challenge_marker: bool = False,
    http_status: int | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    """OR-combined Cloudflare indicators: canonical challenge title, the
    cf-challenge-running/cf-error-details classes in the DOM, or a 403
    response carrying a cf-ray header."""
    if has_challenge_marker or is_challenge_title(title):
        return True
    if http_status == 403 and headers:
        return "cf-ray" in {k.lower() for k in headers}
    return False


async def _challenge_markers(page: Page) -> dict:
    """DOM challenge markers for the CURRENT document. Degrades to
    not-a-challenge on any evaluate failure (page closed or navigating
    mid-check) — ambiguous detection must never fail the capture."""
    try:
        return await page.evaluate(_CHALLENGE_PROBE_JS)
    except Exception:  # noqa: BLE001 — any evaluate failure is not-a-challenge
        logger.debug("Challenge marker probe failed", exc_info=True)
        return {"title": "", "marker": False}


def _latest_nav(
    nav_responses: list[Response], fallback: Response | None
) -> tuple[int | None, dict[str, str]]:
    """Status + header map of the most recent main-frame navigation
    response (the challenge reload makes the goto response stale)."""
    latest = nav_responses[-1] if nav_responses else fallback
    if latest is None:
        return None, {}
    return latest.status, {k.lower(): v for k, v in latest.headers.items()}


async def _wait_out_challenge(
    page: Page,
    nav_responses: list[Response],
    *,
    fallback_response: Response | None,
    deadline: float,
) -> None:
    """Detect a Cloudflare challenge after the initial settle and wait for
    it to auto-solve within the navigation budget, re-checking at
    CHALLENGE_POLL_MS. A persistent challenge raises FetchError — a hard
    capture failure, never challenge HTML stored as content.

    Every re-check combines the CURRENT document's markers with the latest
    main-frame response: a challenge that solves reloads the page, and
    nav_responses then carries the fresh (real-page) response, while the
    goto fallback only ever serves when response tracking found nothing."""
    http_status, headers = _latest_nav(nav_responses, fallback_response)
    markers = await _challenge_markers(page)
    if not looks_like_challenge_page(
        title=markers.get("title"),
        has_challenge_marker=bool(markers.get("marker")),
        http_status=http_status,
        headers=headers,
    ):
        return

    logger.info("Cloudflare challenge detected; waiting for auto-solve")
    remaining_ms = min(CHALLENGE_WAIT_MS, int((deadline - time.monotonic()) * 1000))
    while remaining_ms > 0:
        await page.wait_for_timeout(min(CHALLENGE_POLL_MS, remaining_ms))
        markers = await _challenge_markers(page)
        http_status, headers = _latest_nav(nav_responses, fallback_response)
        if not looks_like_challenge_page(
            title=markers.get("title"),
            has_challenge_marker=bool(markers.get("marker")),
            http_status=http_status,
            headers=headers,
        ):
            logger.info("Cloudflare challenge cleared during wait")
            return
        remaining_ms = min(CHALLENGE_WAIT_MS, int((deadline - time.monotonic()) * 1000))

    raise FetchError(BOT_PROTECTION_ERROR)


def _hostnames_differ(url_a: str, url_b: str) -> bool:
    return (urlparse(url_a).hostname or "") != (urlparse(url_b).hostname or "")


def _make_ssrf_route_guard(allow_private_networks: bool):
    """Build a Playwright route handler that SSRF-validates every request
    the page initiates (subresources, XHR/fetch, JS-initiated navigations),
    closing the gap where only the top-level + final URL were checked.

    Fail-safe: a request whose target is a blocked/internal address is
    aborted; http(s) requests that pass are allowed; non-http(s) schemes
    (data:, blob:, about:) are allowed through unchanged (they touch no
    network). An unexpected error in the guard aborts the single request
    rather than allowing it (deny on doubt) and never crashes the scan.

    A per-fetch verdict cache keyed by scheme+host avoids re-resolving DNS
    for every asset from the same origin.
    """
    verdict_cache: dict[str, bool] = {}

    async def _handler(route: Route) -> None:
        request_url = route.request.url
        try:
            scheme = (urlparse(request_url).scheme or "").lower()
            if scheme not in ("http", "https"):
                # data:/blob:/about: etc. — inline, no network egress.
                await route.continue_()
                return
            host = (urlparse(request_url).hostname or "").lower()
            cache_key = f"{scheme}://{host}"
            allowed = verdict_cache.get(cache_key)
            if allowed is None:
                try:
                    # DNS resolution is blocking — offload to a thread so it
                    # can't stall the event loop under a burst of requests.
                    await asyncio.to_thread(
                        assert_url_allowed,
                        request_url,
                        allow_private_networks=allow_private_networks,
                    )
                    allowed = True
                except SSRFBlockedError:
                    allowed = False
                verdict_cache[cache_key] = allowed
            if allowed:
                await route.continue_()
            else:
                logger.info("Blocked SSRF subresource request to %s", request_url)
                await route.abort("blockedbyclient")
        except Exception:
            # Deny on any unexpected error; never let the guard crash the
            # capture. abort() itself can race a closed page — swallow that.
            try:
                await route.abort("blockedbyclient")
            except Exception:  # noqa: BLE001
                logger.debug("route.abort() raised after page close", exc_info=True)

    return _handler


async def fetch_page(url: str, *, allow_private_networks: bool = False) -> FetchResult:
    # DNS resolution is blocking — offload like the route guard below
    # (Finding: sync assert_url_allowed inside async functions).
    await asyncio.to_thread(assert_url_allowed, url, allow_private_networks=allow_private_networks)

    try:
        async with async_playwright() as pw:
            # Blink's AutomationControlled feature is the single loudest
            # "this is a bot" signal Chromium ships; disable it at launch
            # (worker/stealth.py owns the capture's browser shape).
            browser = await pw.chromium.launch(
                headless=True, args=BROWSER_LAUNCH_ARGS
            )
            try:
                context = await browser.new_context(
                    user_agent=CAPTURE_USER_AGENT,
                    locale=CONTEXT_LOCALE,
                    timezone_id=CONTEXT_TIMEZONE_ID,
                    color_scheme=CONTEXT_COLOR_SCHEME,
                    viewport=CONTEXT_VIEWPORT,
                    ignore_https_errors=False,
                )
                # Stealth patches (init scripts) BEFORE any page exists and
                # BEFORE the route guard: the guard must be the last word on
                # every request the stealthed page makes (PROMPT-002 rule 11).
                await apply_stealth(context)
                page = await context.new_page()
                # SSRF-validate every request the page makes (subresources,
                # XHR/fetch, JS-initiated navigations) — not just the top
                # frame. "**/*" matches all URLs; the handler fails safe.
                await page.route("**/*", _make_ssrf_route_guard(allow_private_networks))
                # Track every main-frame navigation response: a challenge that
                # auto-solves reloads the page, and the capture must record
                # the REAL response (status/headers), not the challenge's.
                nav_responses: list[Response] = []

                def _track_nav(resp: Response) -> None:
                    try:
                        if resp.request.is_navigation_request() and resp.frame == page.main_frame:
                            nav_responses.append(resp)
                    except Exception:  # noqa: BLE001 — tracking must never break a fetch
                        logger.debug("Navigation-response tracking skipped", exc_info=True)

                page.on("response", _track_nav)
                # wait_until="load" (not "networkidle": Playwright's docs
                # discourage it, and any page with long-polling/beacons
                # never goes idle -> guaranteed timeout). A bounded settle
                # window (stealth.SETTLE_MS) lets late JS DOM writes land
                # before capture. The challenge auto-solve wait is bounded
                # by the remaining navigation budget (deadline below), so a
                # challenged page never extends the capture beyond
                # NAV_TIMEOUT_MS + settle.
                challenge_deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
                response = await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
                await page.wait_for_timeout(SETTLE_MS)
                final_url = page.url

                # Redirect landed on a different host? Re-run the SSRF check
                # on where we actually ended up.
                if _hostnames_differ(url, final_url):
                    # Offloaded like every other direct check (the route
                    # guard above sets the precedent): resolution is
                    # blocking and must not stall the loop.
                    await asyncio.to_thread(
                        assert_url_allowed,
                        final_url,
                        allow_private_networks=allow_private_networks,
                    )

                # Cloudflare challenge page? Wait out a solvable one, or fail
                # the capture hard (rule: never store challenge HTML).
                await _wait_out_challenge(
                    page,
                    nav_responses,
                    fallback_response=response,
                    deadline=challenge_deadline,
                )

                # Page confirmed real (PROMPT-002 Phase 3): scroll it so
                # IntersectionObserver/scroll-event lazy content below the
                # fold loads, then wait for the DOM to stop churning before
                # capture. The challenge checks ran ABOVE, on the settled
                # DOM — a challenge page is never scrolled, and a challenge
                # that auto-solved via reload left a fresh page for this
                # pass. Both helpers never raise (a failed scroll must not
                # fail a capture), and every request the lazy loaders fire
                # still goes through the SSRF route guard installed above.
                scroll_evidence = await auto_scroll_page(
                    page, max_scroll_time_ms=MAX_SCROLL_TIME_MS
                )
                stability_evidence = await wait_for_content_stable(page)
                logger.debug(
                    "Capture page preparation: scroll=%s stability=%s",
                    scroll_evidence,
                    stability_evidence,
                )

                html = await page.content()
                if len(html.encode("utf-8", errors="replace")) > MAX_HTML_BYTES:
                    raise FetchError(
                        f"Page HTML exceeds the {MAX_HTML_BYTES // (1024 * 1024)} MB limit"
                    )

                screenshot = await page.screenshot(
                    full_page=True, type="png", timeout=SCREENSHOT_TIMEOUT_MS
                )

                # The latest main-frame response, not goto's: the challenge
                # reload path re-navigates (403 challenge -> 200 real page).
                latest = nav_responses[-1] if nav_responses else response
                headers: dict[str, str] = {}
                http_status: int | None = None
                if latest is not None:
                    http_status = latest.status
                    # Keep a curated subset now; layer 6 (Phase 2) captures more.
                    for k in ("content-type", "server", "last-modified", "etag"):
                        v = latest.headers.get(k)
                        if v is not None:
                            headers[k] = v

                return FetchResult(
                    html=html,
                    screenshot=screenshot,
                    final_url=final_url,
                    http_status=http_status,
                    headers=headers,
                )
            finally:
                await browser.close()
    except SSRFBlockedError:
        raise
    except FetchError:
        raise
    except PlaywrightError as exc:
        # Playwright messages can be long/noisy; keep the first line.
        raise FetchError(f"Fetch failed: {str(exc).splitlines()[0][:500]}") from exc
    except ipaddress.AddressValueError as exc:  # defensive; should not happen
        raise FetchError(f"Fetch failed: {exc}") from exc
