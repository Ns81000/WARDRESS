"""Page-preparation tests (PROMPT-002 Phase 3).

Unit tests drive `worker/page_prepare.py` through a minimal scripted
Page double (no browser): incremental scroll, growth/stall detection,
the hard time cap, and the never-raise degradation paths. Integration
tests use the hermetic local ThreadingHTTPServer + real-Chromium-skip
pattern from test_stealth.py / test_cloudflare_detection.py and prove
the capture-level behavior: a scroll-event lazy page only reveals its
below-fold marker through the new auto-scroll pass.

FAILED-before proofs are embedded: the pre-Phase-3 fetch_page never
scrolled, so lazy below-fold content was missing from every capture,
and neither page_prepare function existed at all.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

import worker.fetcher as fetcher_mod
from worker.fetcher import BROWSER_LAUNCH_ARGS, fetch_page
from worker.page_prepare import auto_scroll_page, wait_for_content_stable

# --- scripted Page double (no browser) ---------------------------------------


class ScriptedPage:
    """Implements just the page_prepare surface: evaluate() dispatching on
    the probe JS and wait_for_timeout() (instant)."""

    def __init__(
        self,
        *,
        scroll_height: int,
        viewport_height: int,
        growth=None,
        fail_js: str | None = None,
    ):
        self.scroll_height = scroll_height
        self.viewport_height = viewport_height
        self.scroll_y = 0
        self.growth = growth  # callable(steps_so_far) -> extra px, or None
        self.fail_js = fail_js  # evaluate raises when the JS contains this
        self.scroll_steps = 0
        self.scrolled_to_top = False
        self.max_scroll_y = 0
        self.last_step: int | None = None
        self.waits_ms: list[int] = []
        self.content_length = 42

    async def evaluate(self, js, arg=None):
        if self.fail_js and self.fail_js in js:
            raise RuntimeError("simulated page JS failure")
        if "scroll_height" in js:
            return {
                "scroll_height": self.scroll_height,
                "viewport_height": self.viewport_height,
                "scroll_y": self.scroll_y,
            }
        if "scrollBy" in js:
            self.scroll_steps += 1
            self.last_step = arg
            bottom = max(0, self.scroll_height - self.viewport_height)
            self.scroll_y = min(self.scroll_y + arg, bottom)
            self.max_scroll_y = max(self.max_scroll_y, self.scroll_y)
            if self.growth is not None:
                self.scroll_height += self.growth(self.scroll_steps)
            return None
        if "scrollTo" in js:
            self.scrolled_to_top = True
            self.scroll_y = 0
            return None
        if "innerHTML" in js:
            return self.content_length
        raise AssertionError(f"unexpected JS probe: {js[:60]}")

    async def wait_for_timeout(self, ms: int) -> None:
        self.waits_ms.append(ms)


# --- unit tests: auto_scroll_page ---------------------------------------------


async def test_auto_scroll_walks_growing_page_to_the_bottom() -> None:
    """Lazy sections grow the page while scrolling: the walk must continue
    past the initial height, stop only once at the bottom with a stable
    height, and return to the top."""

    def grow(steps: int) -> int:
        return 1000 if steps <= 2 else 0  # two lazy sections, then stable

    page = ScriptedPage(scroll_height=3000, viewport_height=1000, growth=grow)
    evidence = await auto_scroll_page(page)

    assert evidence["initial_height"] == 3000
    assert evidence["final_height"] == 5000
    assert evidence["capped"] is False
    assert evidence["scroll_steps"] > 0
    assert page.max_scroll_y >= 5000 - 1000  # reached the (grown) bottom
    assert page.scrolled_to_top is True
    assert page.scroll_y == 0  # back at the top for the screenshot
    assert evidence["scroll_time_ms"] >= 0
    # every step paused for lazy content to fire
    assert page.waits_ms == [300] * evidence["scroll_steps"]


async def test_auto_scroll_time_caps_infinite_page() -> None:
    """Infinite-scroll behavior: a page that grows forever must stop at the
    hard time cap with capped=True, never hang the capture."""
    page = ScriptedPage(
        scroll_height=2000,
        viewport_height=1000,
        growth=lambda steps: 50_000,
    )
    evidence = await auto_scroll_page(page, max_scroll_time_ms=250, step_pause_ms=10)

    assert evidence["capped"] is True
    assert evidence["scroll_steps"] > 0
    assert evidence["initial_height"] == 2000
    assert evidence["final_height"] > evidence["initial_height"]
    assert evidence["scroll_time_ms"] >= 250


async def test_auto_scroll_survives_js_errors() -> None:
    """Never-raise contract: a page whose JS throws mid-probe degrades to
    a no-scroll capture with partial evidence, both for the initial height
    probe and for the scroll step itself."""
    probe_fail = ScriptedPage(scroll_height=3000, viewport_height=1000, fail_js="scroll_height")
    evidence = await auto_scroll_page(probe_fail)
    assert evidence["scroll_steps"] == 0
    assert evidence["initial_height"] == 0
    assert evidence["final_height"] == 0
    assert evidence["capped"] is False
    assert "scroll_time_ms" in evidence

    scroll_fail = ScriptedPage(scroll_height=3000, viewport_height=1000, fail_js="scrollBy")
    evidence = await auto_scroll_page(scroll_fail)
    assert evidence["scroll_steps"] == 0
    assert evidence["initial_height"] == 3000
    assert evidence["final_height"] == 3000
    assert evidence["capped"] is False
    assert scroll_fail.scrolled_to_top is False  # never scrolled, no return-to-top


async def test_auto_scroll_skips_unscrollable_page() -> None:
    """scrollHeight <= viewport: no scrollable content, no steps, no waits."""
    page = ScriptedPage(scroll_height=1000, viewport_height=1000)
    evidence = await auto_scroll_page(page)

    assert evidence["scroll_steps"] == 0
    assert evidence["initial_height"] == 1000
    assert evidence["final_height"] == 1000
    assert evidence["capped"] is False
    assert page.scroll_steps == 0
    assert page.waits_ms == []


async def test_auto_scroll_step_overlaps_viewport() -> None:
    """The step must be a fraction (0.8) of the viewport, not a full jump:
    overlap is what makes IntersectionObserver fire reliably."""
    page = ScriptedPage(scroll_height=50_000, viewport_height=1000)
    await auto_scroll_page(page, max_scroll_time_ms=10_000)
    assert page.scroll_steps > 0
    assert page.last_step == 800  # 0.8 * 1000: overlapping steps
    assert page.scrolled_to_top is True


# --- unit tests: wait_for_content_stable --------------------------------------


async def test_wait_for_content_stable_stabilizes_after_three_polls() -> None:
    """A constant DOM needs 2 consecutive unchanged polls: poll 1 baseline,
    polls 2+3 unchanged -> stable=True at exactly 3 polls."""
    page = ScriptedPage(scroll_height=0, viewport_height=0)
    evidence = await wait_for_content_stable(page, timeout_ms=5_000, poll_ms=10)

    assert evidence["stable"] is True
    assert evidence["polls"] == 3
    assert evidence["final_length"] == 42


async def test_wait_for_content_stable_times_out_on_churning_page() -> None:
    """A DOM that keeps growing (timestamps, tickers) must exhaust the
    timeout and report stable=False with the last observed length."""

    def churn() -> None:
        page.content_length += 7

    page = ScriptedPage(scroll_height=0, viewport_height=0)
    original = page.evaluate

    async def evaluating(js, arg=None):
        if "innerHTML" in js:
            churn()
        return await original(js, arg)

    page.evaluate = evaluating  # type: ignore[method-assign]
    evidence = await wait_for_content_stable(page, timeout_ms=200, poll_ms=10)

    assert evidence["stable"] is False
    assert evidence["polls"] > 2
    assert evidence["final_length"] > 42


async def test_wait_for_content_stable_survives_probe_failure() -> None:
    """Never-raise contract: a failing content probe reports unstable with
    whatever was known, instead of failing the capture."""
    page = ScriptedPage(scroll_height=0, viewport_height=0, fail_js="innerHTML")
    evidence = await wait_for_content_stable(page, timeout_ms=1_000, poll_ms=10)

    assert evidence["stable"] is False
    assert evidence["polls"] == 1
    assert evidence["final_length"] == 0


# --- hermetic local capture target -------------------------------------------


def _routes_handler() -> tuple[type[BaseHTTPRequestHandler], dict]:
    routes: dict[str, tuple[int, dict, bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, headers, body = routes.get(
                self.path.split("?")[0], (404, {}, b"<html><title>404</title></html>")
            )
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return Handler, routes


LAZY_HTML = (
    "<html><head><title>lazy fixture</title></head>"
    "<body style='margin:0'>"
    "<div id='spacer' style='height:4000px'></div>"
    "<script>window.addEventListener('scroll',function(){"
    "if(window.scrollY>200 && !document.getElementById('lazy-marker')){"
    "var d=document.createElement('div');d.id='lazy-marker';"
    "d.textContent='wardress-lazy-'+'fixture';document.body.appendChild(d);}"
    "});</script>"
    "</body></html>"
)
SHORT_HTML = "<html><head><title>short</title></head><body><p>tiny</p></body></html>"
TALL_STATIC_HTML = (
    "<html><head><title>tall</title></head>"
    "<body><div style='height:6000px'></div></body></html>"
)


@pytest.fixture()
def scroll_target():
    handler_cls, routes = _routes_handler()
    routes.update(
        {
            "/lazy": (200, {}, LAZY_HTML.encode()),
            "/short": (200, {}, SHORT_HTML.encode()),
            "/tall-static": (200, {}, TALL_STATIC_HTML.encode()),
        }
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def fast_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep integration tests fast: production settles 5s before scrolling."""
    monkeypatch.setattr(fetcher_mod, "SETTLE_MS", 200)


@pytest.fixture()
async def browser():
    async with async_playwright() as pw:
        try:
            br = await pw.chromium.launch(headless=True, args=BROWSER_LAUNCH_ARGS)
        except Exception as exc:  # browser not installed on this host
            pytest.skip(f"Chromium not available on this host: {exc}")
        try:
            yield br
        finally:
            await br.close()


# --- real-browser tests (hermetic: local server only) -------------------------


async def test_fetch_page_captures_lazy_below_fold_content(scroll_target, fast_settle) -> None:
    """FAILED-before: the pre-Phase-3 capture never scrolled, so this
    scroll-event lazy page's below-fold marker never appeared in any
    capture. The auto-scroll pass must trigger it and store it. (The
    fixture builds the marker text by concatenation so the literal only
    ever exists in the DOM after a real scroll — asserting on it proves
    the scroll happened, not that the page shipped a script.)"""
    result = await fetch_page(f"{scroll_target}/lazy", allow_private_networks=True)
    assert result.http_status == 200
    assert '<div id="lazy-marker">wardress-lazy-fixture</div>' in result.html
    assert result.screenshot.startswith(b"\x89PNG")


async def test_auto_scroll_page_real_browser_short_and_tall_pages(browser, scroll_target) -> None:
    """Direct real-browser behavior: a short page needs zero steps; a tall
    static page is walked to the bottom (heights recorded) and left at the
    top for the screenshot."""
    context = await browser.new_context()
    try:
        page = await context.new_page()

        await page.goto(f"{scroll_target}/short")
        evidence = await auto_scroll_page(page)
        assert evidence["scroll_steps"] == 0
        assert evidence["capped"] is False
        assert evidence["initial_height"] == evidence["final_height"]
        assert evidence["initial_height"] > 0

        await page.goto(f"{scroll_target}/tall-static")
        evidence = await auto_scroll_page(page)
        assert evidence["scroll_steps"] > 0
        assert evidence["capped"] is False
        # 6000px spacer + default body margins
        assert evidence["initial_height"] == evidence["final_height"]
        assert evidence["initial_height"] >= 6000
        assert await page.evaluate("window.scrollY") == 0  # returned to top
    finally:
        await context.close()


async def test_fetch_page_static_page_still_captures(browser, scroll_target, fast_settle) -> None:
    """The added scroll/stability passes must not disturb a plain static
    capture: same FetchResult shape, real content, PNG screenshot."""
    result = await fetch_page(f"{scroll_target}/short", allow_private_networks=True)
    assert result.http_status == 200
    assert "tiny" in result.html
    assert result.screenshot.startswith(b"\x89PNG")
    assert result.final_url == f"{scroll_target}/short"

