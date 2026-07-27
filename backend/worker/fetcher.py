"""Playwright-based page capture used by baseline and scan tasks.

Async API throughout — task bodies run under asyncio.run() in the Celery
worker. Every fetch re-validates the target against the SSRF policy
immediately before navigation, and validates the FINAL url after
redirects (a public site redirecting to an internal address is refused).
"""

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Route, async_playwright

from app.ssrf import SSRFBlockedError, assert_url_allowed

logger = logging.getLogger(__name__)

NAV_TIMEOUT_MS = 45_000
SCREENSHOT_TIMEOUT_MS = 30_000
SETTLE_MS = 2_000  # post-load pause for late JS DOM writes
MAX_HTML_BYTES = 10 * 1024 * 1024  # refuse absurd pages rather than OOM

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Wardress/0.1 SiteMonitor"


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
    assert_url_allowed(url, allow_private_networks=allow_private_networks)

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1366, "height": 900},
                    ignore_https_errors=False,
                )
                page = await context.new_page()
                # SSRF-validate every request the page makes (subresources,
                # XHR/fetch, JS-initiated navigations) — not just the top
                # frame. "**/*" matches all URLs; the handler fails safe.
                await page.route(
                    "**/*", _make_ssrf_route_guard(allow_private_networks)
                )
                # wait_until="load" (not "networkidle": Playwright's docs
                # discourage it, and any page with long-polling/beacons
                # never goes idle -> guaranteed timeout). A short settle
                # window lets late JS DOM writes land before capture.
                response = await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
                await page.wait_for_timeout(SETTLE_MS)
                final_url = page.url

                # Redirect landed on a different host? Re-run the SSRF check
                # on where we actually ended up.
                if _hostnames_differ(url, final_url):
                    assert_url_allowed(final_url, allow_private_networks=allow_private_networks)

                html = await page.content()
                if len(html.encode("utf-8", errors="replace")) > MAX_HTML_BYTES:
                    raise FetchError(
                        f"Page HTML exceeds the {MAX_HTML_BYTES // (1024 * 1024)} MB limit"
                    )

                screenshot = await page.screenshot(
                    full_page=True, type="png", timeout=SCREENSHOT_TIMEOUT_MS
                )

                headers: dict[str, str] = {}
                http_status: int | None = None
                if response is not None:
                    http_status = response.status
                    # Keep a curated subset now; layer 6 (Phase 2) captures more.
                    for k in ("content-type", "server", "last-modified", "etag"):
                        v = response.headers.get(k)
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
