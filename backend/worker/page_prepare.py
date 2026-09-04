"""Page-preparation utilities for the Playwright capture (PROMPT-002 Phase 3).

A `full_page=True` screenshot renders the document at its full height, but
content below the fold often is not THERE yet: IntersectionObserver
callbacks and scroll-event lazy loaders only fire when elements actually
enter the viewport, and a short settle window is not enough for heavy JS
sites that keep writing to the DOM long after `load`.

`auto_scroll_page()` walks the page top-to-bottom in overlapping
viewport-height steps so lazy content triggers and loads; after it,
`wait_for_content_stable()` waits for the DOM to stop churning before the
capture takes its HTML + screenshot.

Contracts:
- Neither function EVER raises: a failed scroll must never fail a
  capture, which proceeds with whatever content is available.
- Both return evidence dicts (logged by fetcher.py and persisted as
  capture evidence on the scan row — worker/scan_tasks.py).
- No network policy here: every request the page makes while scrolling
  (lazy images, XHR) goes through the SSRF route guard the caller
  installed — scrolling itself only calls scrollBy/scrollTo, never
  navigates, so it creates no new request paths.
"""

import logging
import time

from playwright.async_api import Page

from worker.stealth import (
    CONTENT_STABLE_POLL_MS,
    CONTENT_STABLE_TIMEOUT_MS,
    MAX_SCROLL_TIME_MS,
    SCROLL_STEP_PAUSE_MS,
)

logger = logging.getLogger(__name__)

# 80% of the viewport per step: consecutive steps overlap, so an element
# entering the viewport gradually reliably fires IntersectionObserver
# (a single jump-to-bottom would not).
SCROLL_STEP_FRACTION = 0.8

# Two consecutive steps/polls without growth before the page counts as
# fully loaded / stable.
_STABLE_STEPS_NEEDED = 2

_HEIGHT_PROBE_JS = (
    "() => ({"
    " scroll_height: Math.max("
    "   document.body ? document.body.scrollHeight : 0,"
    "   document.documentElement ? document.documentElement.scrollHeight : 0),"
    " viewport_height: window.innerHeight,"
    " scroll_y: window.scrollY"
    "})"
)
_SCROLL_BY_JS = "(dy) => { window.scrollBy(0, dy); }"
_SCROLL_TOP_JS = "() => { window.scrollTo(0, 0); }"
_CONTENT_LENGTH_JS = "() => (document.body ? document.body.innerHTML.length : 0)"


async def auto_scroll_page(
    page: Page,
    *,
    max_scroll_time_ms: int = MAX_SCROLL_TIME_MS,
    step_pause_ms: int = SCROLL_STEP_PAUSE_MS,
) -> dict:
    """Scroll the page from its current position to the bottom in
    viewport-sized steps, pausing at each step so lazy content fires,
    then return to the top (the screenshot must start from the top).

    Stops when the page has been scrolled to the bottom AND its height
    has stopped growing for two consecutive steps (lazy loaders near the
    bottom have fired), when the page provably cannot scroll further, or
    at the hard `max_scroll_time_ms` cap — infinite-scroll sites never
    stall a capture.

    Returns evidence: `{"scroll_steps": N, "initial_height": H0,
    "final_height": H1, "capped": bool, "scroll_time_ms": T}`. Never
    raises: any failure (JS error, closed page) is logged and the caller
    continues with whatever content is available.
    """
    evidence: dict = {
        "scroll_steps": 0,
        "initial_height": 0,
        "final_height": 0,
        "capped": False,
        "scroll_time_ms": 0,
    }
    start = time.monotonic()
    try:
        probe = await page.evaluate(_HEIGHT_PROBE_JS)
        initial_height = int(probe.get("scroll_height") or 0)
        viewport_height = int(probe.get("viewport_height") or 0)
        evidence["initial_height"] = initial_height
        evidence["final_height"] = initial_height

        # Nothing scrollable: no below-fold content can hide anywhere.
        if initial_height <= viewport_height:
            return evidence

        deadline = start + max_scroll_time_ms / 1000
        last_height = initial_height
        last_scroll_y = int(probe.get("scroll_y") or 0)
        stable_steps = 0
        while True:
            if time.monotonic() >= deadline:
                evidence["capped"] = True
                break
            step_px = max(1, int(viewport_height * SCROLL_STEP_FRACTION))
            await page.evaluate(_SCROLL_BY_JS, step_px)
            evidence["scroll_steps"] += 1
            await page.wait_for_timeout(step_pause_ms)
            probe = await page.evaluate(_HEIGHT_PROBE_JS)
            height = int(probe.get("scroll_height") or 0)
            scroll_y = int(probe.get("scroll_y") or 0)
            evidence["final_height"] = height

            stable_steps = stable_steps + 1 if height <= last_height else 0
            at_bottom = scroll_y + viewport_height >= height
            stalled = scroll_y == last_scroll_y and height <= last_height
            last_height = height
            last_scroll_y = scroll_y
            if stable_steps >= _STABLE_STEPS_NEEDED and (at_bottom or stalled):
                break
    except Exception:  # noqa: BLE001 — scrolling must never fail a capture
        logger.debug("Auto-scroll degraded; capture continues as-is", exc_info=True)
    finally:
        evidence["scroll_time_ms"] = int((time.monotonic() - start) * 1000)
        if evidence["scroll_steps"] > 0:
            # The screenshot must capture from the top of the page.
            try:
                await page.evaluate(_SCROLL_TOP_JS)
            except Exception:  # noqa: BLE001 — best-effort return to top
                logger.debug("Scroll-back-to-top failed", exc_info=True)
    return evidence


async def wait_for_content_stable(
    page: Page,
    *,
    timeout_ms: int = CONTENT_STABLE_TIMEOUT_MS,
    poll_ms: int = CONTENT_STABLE_POLL_MS,
) -> dict:
    """Poll `document.body.innerHTML`'s length every `poll_ms` until it
    stops changing for two consecutive polls (the DOM has stopped
    churning after the scroll pass) or `timeout_ms` elapses.

    Returns evidence: `{"stable": bool, "polls": N, "final_length": L}`.
    Never raises: a failing probe is logged and reported as unstable.
    """
    evidence: dict = {"stable": False, "polls": 0, "final_length": 0}
    try:
        deadline = time.monotonic() + timeout_ms / 1000
        last_length: int | None = None
        unchanged_polls = 0
        while True:
            evidence["polls"] += 1
            length = int(await page.evaluate(_CONTENT_LENGTH_JS) or 0)
            evidence["final_length"] = length
            unchanged_polls = unchanged_polls + 1 if length == last_length else 0
            last_length = length
            if unchanged_polls >= _STABLE_STEPS_NEEDED:
                evidence["stable"] = True
                return evidence
            if time.monotonic() >= deadline:
                return evidence
            await page.wait_for_timeout(poll_ms)
    except Exception:  # noqa: BLE001 — stability probing must never fail a capture
        logger.debug("Content-stability probe degraded; capture continues", exc_info=True)
        return evidence


