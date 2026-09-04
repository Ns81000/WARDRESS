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

The screenshot is height-capped (PROMPT-002 Phase 4): pages taller than
stealth.MAX_SCREENSHOT_HEIGHT rasterize as a clip of the document's top
MAX_SCREENSHOT_HEIGHT pixels — a shorter but still-valid PNG. Every
capture also returns structured `capture_evidence` (scroll/stability/
screenshot facts plus the informational `capture_quality` label),
persisted on the scan row by worker/scan_tasks.py.

Consent banners are suppressed (PROMPT-002 Phase 5): the common CMP
consent cookies are injected on the context before navigation, and —
once the page is confirmed real, before scrolling — a curated selector
pass clicks the first visible accept/dismiss control
(worker/banner_dismiss.py). Both helpers never raise; banner evidence
rides inside capture_evidence but does not affect capture_quality.

Transient capture failures are retried (PROMPT-002 Phase 6): a
navigation timeout or network-level goto error gets ONE retry after a
short pause, at a reduced navigation timeout, and a challenge that did
not auto-solve gets ONE retry with a longer wait. SSRF refusals and
permanent fetch failures are never retried — they are decisions, not
transient errors. Every attempt builds a fresh browser/context/page
with its own stealth patches, consent cookies and SSRF route guard;
nothing from a failed attempt survives except the retry count, which
rides in capture_evidence.
"""

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response, Route, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.ssrf import SSRFBlockedError, assert_url_allowed
from worker.banner_dismiss import dismiss_banners, inject_consent_cookies
from worker.page_prepare import auto_scroll_page, wait_for_content_stable
from worker.stealth import (
    BANNER_DISMISS_TIMEOUT_MS,
    BROWSER_LAUNCH_ARGS,
    CAPTURE_USER_AGENT,
    CONTEXT_COLOR_SCHEME,
    CONTEXT_LOCALE,
    CONTEXT_TIMEZONE_ID,
    CONTEXT_VIEWPORT,
    MAX_SCREENSHOT_HEIGHT,
    MAX_SCROLL_TIME_MS,
    RETRY_NAV_TIMEOUT_MS,
    RETRY_PAUSE_MS,
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
    # How the capture happened (PROMPT-002 Phase 4): scroll/stability/
    # screenshot evidence plus the informational capture_quality label.
    # None on results from before this field existed — consumers must
    # treat absence as "unknown", never crash on it.
    capture_evidence: dict | None = None


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
# PROMPT-002 Phase 6: an unsolved challenge gets ONE retry with a longer
# wait. Lives beside CHALLENGE_WAIT_MS (the Phase-2 challenge-timing
# family), not in worker/stealth.py's page-preparation section.
CHALLENGE_RETRY_WAIT_MS = 15_000

BOT_PROTECTION_ERROR = (
    "Site is behind bot protection that could not be bypassed "
    "(Cloudflare challenge detected)"
)


class _ChallengeUnsolvedError(FetchError):
    """A challenge was detected and did not auto-solve within the wait
    window. Is-a FetchError with the user-safe BOT_PROTECTION_ERROR
    message (the public contract is unchanged); the subclass exists so
    the Phase-6 retry loop can tell this retryable failure apart from
    permanent FetchErrors."""


class _TransientNavError(Exception):
    """A page.goto failure classified as TRANSIENT (navigation timeout or
    network-level error) — eligible for the Phase-6 retry. Carries the
    short human-readable reason; the original Playwright error is the
    __cause__."""


def _classify_goto_failure(exc: PlaywrightError) -> str | None:
    """Transient classification for a failed page.goto: a short human
    reason when the failure is retryable, None when it is not.

    Retryable: navigation timeouts and network-level net::ERR_* errors
    (DNS blips, refused/reset connections) — the transient failures the
    Phase-6 spec names. NOT retryable: net::ERR_BLOCKED_BY_CLIENT (the
    SSRF route guard's denial — a policy decision, never retried) and
    anything unclassifiable (retrying an unknown failure shape doubles
    the cost of permanent breakage for no expected gain).
    """
    first_line = str(exc).splitlines()[0].lower()
    if "err_blocked_by_client" in first_line or "blockedbyclient" in first_line:
        return None
    if isinstance(exc, PlaywrightTimeoutError):
        return "navigation timeout"
    if "net::err_" in first_line:
        return "network error"
    return None

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
    wait_ms: int = CHALLENGE_WAIT_MS,
) -> None:
    """Detect a Cloudflare challenge after the initial settle and wait for
    it to auto-solve within `wait_ms` (bounded by the navigation budget
    deadline), re-checking at CHALLENGE_POLL_MS. A persistent challenge
    raises _ChallengeUnsolvedError (is-a FetchError) — a hard capture
    failure, never challenge HTML stored as content. Phase 6 passes the
    longer CHALLENGE_RETRY_WAIT_MS on the challenge retry.

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
    remaining_ms = min(wait_ms, int((deadline - time.monotonic()) * 1000))
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
        remaining_ms = min(wait_ms, int((deadline - time.monotonic()) * 1000))

    raise _ChallengeUnsolvedError(BOT_PROTECTION_ERROR)


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


# --- Screenshot height cap + capture evidence (PROMPT-002 Phase 4) ----------

_PAGE_HEIGHT_JS = (
    "() => Math.max("
    "document.body ? document.body.scrollHeight : 0,"
    " document.documentElement ? document.documentElement.scrollHeight : 0)"
)


def _classify_capture_quality(evidence: dict) -> str:
    """`full` / `partial` / `degraded` health label for a completed capture.

    - full: scroll completed, content stable, screenshot not capped.
    - partial: the capture completed but is incomplete — the scroll pass
      hit its time cap (unwalked content may remain), the content never
      stabilized, or the screenshot was height-capped.
    - degraded: a critical capture step failed yet the capture completed —
      here, the page height could not be measured, so the screenshot-cap
      decision (and the capture's completeness) is unknown.

    Informational only: no detection code reads it — it rides inside
    capture_evidence for debugging and operator tooling.
    """
    if evidence.get("actual_height", 0) <= 0:
        return "degraded"
    if (
        evidence.get("capped")
        or evidence.get("screenshot_capped")
        or not evidence.get("stable", False)
    ):
        return "partial"
    return "full"


async def _take_screenshot(page: Page) -> tuple[bytes, dict]:
    """Full-page PNG with a height cap; returns (png, evidence).

    Chromium's full-page raster fails or produces a corrupt image beyond
    ~16384px on many GPUs, and a time-capped scroll walk can leave an
    infinite-scroll page far taller than that. Pages taller than
    stealth.MAX_SCREENSHOT_HEIGHT are captured as a clip of the document's
    top MAX_SCREENSHOT_HEIGHT pixels — a shorter but still-valid PNG, so
    the visual-diff layer only sees a truncated page. The clip runs under
    full_page=True because clip coordinates are PAGE coordinates there:
    verified against Playwright 1.61, full_page=False + clip clamps the
    result to the current viewport instead of the requested region.

    The height probe never fails the capture: a probe error records
    actual_height=0 (capture_quality "degraded") and takes the normal
    full-page screenshot. Screenshot failures themselves still propagate —
    a capture without a screenshot is a failed capture, unchanged.
    """
    evidence: dict = {"screenshot_capped": False, "actual_height": 0}
    try:
        page_height = int(await page.evaluate(_PAGE_HEIGHT_JS) or 0)
    except Exception:  # noqa: BLE001 — evidence gathering must not fail a capture
        logger.debug("Page-height probe failed; height cap not applied", exc_info=True)
        page_height = 0
    evidence["actual_height"] = page_height

    if page_height > MAX_SCREENSHOT_HEIGHT:
        viewport_width = (page.viewport_size or {}).get("width") or CONTEXT_VIEWPORT["width"]
        screenshot = await page.screenshot(
            full_page=True,
            clip={"x": 0, "y": 0, "width": viewport_width, "height": MAX_SCREENSHOT_HEIGHT},
            type="png",
            timeout=SCREENSHOT_TIMEOUT_MS,
        )
        evidence["screenshot_capped"] = True
        return screenshot, evidence
    return (
        await page.screenshot(full_page=True, type="png", timeout=SCREENSHOT_TIMEOUT_MS),
        evidence,
    )


async def fetch_page(url: str, *, allow_private_networks: bool = False) -> FetchResult:
    """Capture `url` (HTML + screenshot + evidence), retrying TRANSIENT
    failures once (PROMPT-002 Phase 6).

    Never retried: SSRF refusals (the top-level gate here, route-guard
    denials, the final-URL recheck — policy decisions) and permanent
    FetchErrors (HTML over budget, anything unclassifiable). Retried
    exactly once, then failed: a goto timeout / network error (after a
    RETRY_PAUSE_MS pause, at the reduced RETRY_NAV_TIMEOUT_MS) and a
    challenge that did not auto-solve (with the longer
    CHALLENGE_RETRY_WAIT_MS). Each attempt is a completely fresh
    browser/context/page; the successful attempt's capture_evidence
    records how many retries preceded it.
    """
    # DNS resolution is blocking — offload like the route guard below
    # (Finding: sync assert_url_allowed inside async functions). The
    # top-level SSRF gate runs before ANY browser work and is never
    # retried: a refusal is a policy decision, not a transient error.
    await asyncio.to_thread(
        assert_url_allowed, url, allow_private_networks=allow_private_networks
    )

    retry_count = 0
    nav_timeout_ms = NAV_TIMEOUT_MS
    challenge_wait_ms = CHALLENGE_WAIT_MS
    try:
        for attempt in (1, 2):
            try:
                return await _capture_attempt(
                    url,
                    allow_private_networks=allow_private_networks,
                    nav_timeout_ms=nav_timeout_ms,
                    challenge_wait_ms=challenge_wait_ms,
                    retry_count=retry_count,
                )
            except _TransientNavError as exc:
                if attempt == 2:
                    raise FetchError(f"Fetch failed: {exc}") from exc
                reason = f"transient navigation failure ({exc})"
                nav_timeout_ms = RETRY_NAV_TIMEOUT_MS
            except _ChallengeUnsolvedError:
                if attempt == 2:
                    raise
                reason = "Cloudflare challenge did not auto-solve within the wait window"
                nav_timeout_ms = RETRY_NAV_TIMEOUT_MS
                challenge_wait_ms = CHALLENGE_RETRY_WAIT_MS
            except FetchError:
                # Any other FetchError is permanent — never retried.
                raise

            # Only reachable when a retry was decided above. Everything
            # attempt-specific lives inside _capture_attempt (fresh
            # browser/context/page, route guard, consent cookies, evidence
            # dicts) — nothing from the failed attempt survives except this
            # loop's bookkeeping, so a retry can never double-count the
            # previous attempt's partial state.
            retry_count = 1
            logger.warning(
                "Capture attempt %d/2 for %s failed (%s); retrying once after %ds pause",
                attempt,
                url,
                reason,
                RETRY_PAUSE_MS // 1000,
            )
            await asyncio.sleep(RETRY_PAUSE_MS / 1000)

        raise FetchError("Fetch failed")  # pragma: no cover — loop always returns/raises
    except SSRFBlockedError:
        raise
    except FetchError:
        raise
    except PlaywrightError as exc:
        # Playwright messages can be long/noisy; keep the first line.
        raise FetchError(f"Fetch failed: {str(exc).splitlines()[0][:500]}") from exc
    except ipaddress.AddressValueError as exc:  # defensive; should not happen
        raise FetchError(f"Fetch failed: {exc}") from exc


async def _capture_attempt(
    url: str,
    *,
    allow_private_networks: bool,
    nav_timeout_ms: int,
    challenge_wait_ms: int,
    retry_count: int,
) -> FetchResult:
    """One full capture attempt (PROMPT-002 Phase 6): a fresh browser,
    context, page, stealth patches, consent cookies and SSRF route guard,
    ending in the assembled FetchResult. Everything is attempt-local, so a
    retried attempt can never double-count the previous attempt's state."""
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
            # Consent cookies BEFORE navigation (PROMPT-002 Phase 5):
            # sites that check cookies first never render their
            # banner. Re-injected on EVERY attempt (Phase 6) — the
            # fresh context starts cookie-empty. Context-level state
            # — no request path, never raises, and the route guard
            # below stays the last word.
            await inject_consent_cookies(context, url)
            page = await context.new_page()
            # SSRF-validate every request the page makes (subresources,
            # XHR/fetch, JS-initiated navigations) — not just the top
            # frame. The guard is PER-PAGE, so a retried attempt's
            # fresh page gets its own guard (Phase 6). "**/*" matches
            # all URLs; the handler fails safe.
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
            # challenged page never extends the attempt beyond
            # nav_timeout_ms + settle.
            nav_deadline = time.monotonic() + nav_timeout_ms / 1000
            try:
                response = await page.goto(url, timeout=nav_timeout_ms, wait_until="load")
            except PlaywrightError as exc:
                # Phase 6: classify BEFORE the generic boundary turns
                # this into a permanent FetchError — only timeout /
                # network-level goto failures are retryable.
                classified = _classify_goto_failure(exc)
                if classified is None:
                    raise
                raise _TransientNavError(
                    f"{classified} ({str(exc).splitlines()[0][:200]})"
                ) from exc
            # Phase 2 contract: the challenge wait is bounded by the
            # REMAINING navigation budget. Phase 6 exception: the
            # challenge RETRY must get its full longer window even if
            # goto consumed most of the reduced budget — extend the
            # deadline to guarantee it. The first attempt keeps the
            # Phase-2 shape exactly.
            challenge_deadline = nav_deadline
            if challenge_wait_ms > CHALLENGE_WAIT_MS:
                challenge_deadline = max(
                    nav_deadline, time.monotonic() + challenge_wait_ms / 1000
                )
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
            # Phase 6 passes the longer CHALLENGE_RETRY_WAIT_MS on the
            # challenge retry.
            await _wait_out_challenge(
                page,
                nav_responses,
                fallback_response=response,
                deadline=challenge_deadline,
                wait_ms=challenge_wait_ms,
            )

            # Consent banner click-dismissal (PROMPT-002 Phase 5) —
            # AFTER the challenge gate (a challenge page must never
            # have its buttons clicked; an auto-solved challenge
            # reloads the real page before we get here) and BEFORE
            # scrolling (a full-page overlay would block the lazy
            # loaders). Page-level interaction only: every request
            # the page makes still flows through the route guard
            # installed above. Never raises; dismiss_banners returns
            # {"dismissed", "selector", "attempts"}.
            banner_evidence = await dismiss_banners(
                page, timeout_ms=BANNER_DISMISS_TIMEOUT_MS
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

            screenshot, screenshot_evidence = await _take_screenshot(page)

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

            # Structured capture evidence (PROMPT-002 Phase 4): the
            # scroll/stability facts the helpers returned, the screenshot
            # cap decision, and the informational health label. Phase 5
            # merges the banner facts in; they deliberately do NOT feed
            # capture_quality — that label grades capture mechanics
            # (scroll/stability/screenshot), not the site's presentation
            # (a banner Wardress could not dismiss is site content, not
            # a capture failure). Debugging metadata only — nothing in
            # detection reads it. Phase 6 adds the retry count (the
            # Phase-7 final assembly expects this exact key name).
            capture_evidence = {
                **scroll_evidence,
                **stability_evidence,
                **screenshot_evidence,
                **banner_evidence,
                "retry_count": retry_count,
                "capture_quality": _classify_capture_quality(
                    {**scroll_evidence, **stability_evidence, **screenshot_evidence}
                ),
            }

            return FetchResult(
                html=html,
                screenshot=screenshot,
                final_url=final_url,
                http_status=http_status,
                headers=headers,
                capture_evidence=capture_evidence,
            )
        finally:
            await browser.close()
