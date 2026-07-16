"""Playwright-based page capture used by baseline and scan tasks.

Async API throughout — task bodies run under asyncio.run() in the Celery
worker. Every fetch re-validates the target against the SSRF policy
immediately before navigation, and validates the FINAL url after
redirects (a public site redirecting to an internal address is refused).
"""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.ssrf import SSRFBlockedError, assert_url_allowed

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
