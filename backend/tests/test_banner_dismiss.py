"""Consent/cookie-banner suppression tests (PROMPT-002 Phase 5).

Unit tests drive `worker/banner_dismiss.py` through doubles (no
browser): scheme-aware cookie materialization (https/http/ports/IPv6,
Secure-flag gating, never a bare `"domain": ""`), the never-raise
injection contract, and the dismissal loop (first visible match,
invisible/off-screen skipping, consent iframes, click failures, the
bounded late-banner wait). Integration tests use the hermetic local
ThreadingHTTPServer + real-Chromium-skip pattern from
test_page_prepare.py / test_capture_evidence.py and prove capture-level
behavior: a visible banner is clicked through the real fetch_page path
(and the consent cookies travel onto the page), an invisible banner is
left alone, and banner evidence rides in capture_evidence without
touching capture_quality.

FAILED-before proofs are embedded: the pre-Phase-5 fetch_page never
injected consent cookies and never dismissed banners, so consent-gated
pages were captured with the banner obscuring their content.
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

import worker.fetcher as fetcher_mod
from worker.banner_dismiss import (
    DISMISS_SELECTORS,
    dismiss_banners,
    inject_consent_cookies,
    materialize_consent_cookies,
)
from worker.fetcher import BROWSER_LAUNCH_ARGS, fetch_page

# --- cookie materialization (no browser) --------------------------------------


def test_materialize_https_cookies_are_scheme_aware_without_bare_domain() -> None:
    cookies = materialize_consent_cookies("https://example.com/some/path")
    names = [c["name"] for c in cookies]
    assert len(cookies) == 13
    assert names[0] == "OptanonAlertBoxClosed"
    for cookie in cookies:
        # Scheme-aware url target — never a bare `"domain": ""` literal.
        assert cookie["url"] == "https://example.com"
        assert "domain" not in cookie
        assert cookie["name"] and cookie["value"]
    assert "OptanonAlertBoxClosed" in names


def test_materialize_preserves_explicit_port() -> None:
    cookies = materialize_consent_cookies("https://example.com:8443/")
    assert cookies, "explicit-port https target must still materialize"
    for cookie in cookies:
        assert cookie["url"] == "https://example.com:8443"


def test_materialize_brackets_ipv6_literals() -> None:
    cookies = materialize_consent_cookies("http://[::1]:8080/")
    assert cookies
    for cookie in cookies:
        assert cookie["url"] == "http://[::1]:8080"


def test_materialize_sets_secure_cookies_only_on_https() -> None:
    https = materialize_consent_cookies("https://example.com/")
    http = materialize_consent_cookies("http://example.com/")
    secured_https = {c["name"] for c in https if c.get("secure")}
    secured_http = {c["name"] for c in http if c.get("secure")}
    assert secured_https, "Secure-flagged consent cookies must exist on https targets"
    assert "OptanonAlertBoxClosed" in secured_https
    assert secured_http == set(), "Chromium refuses Secure cookies on http:"


def test_materialize_rejects_unusable_urls() -> None:
    for bad in ("ftp://example.com/", "not a url", "", "https://", "https:///path"):
        assert materialize_consent_cookies(bad) == []


class RecordingContext:
    def __init__(self, *, fail=False):
        self.calls: list[list[dict]] = []
        self.fail = fail

    async def add_cookies(self, cookies: list[dict]) -> None:
        if self.fail:
            raise RuntimeError("simulated context failure")
        self.calls.append(list(cookies))


def test_inject_consent_cookies_returns_injected_names() -> None:
    context = RecordingContext()
    names = asyncio.run(inject_consent_cookies(context, "https://example.com/"))
    assert names[0] == "OptanonAlertBoxClosed"
    assert len(context.calls) == 1  # one batched add_cookies call
    assert [c["name"] for c in context.calls[0]] == names


def test_inject_consent_cookies_skips_unusable_targets() -> None:
    context = RecordingContext()
    assert asyncio.run(inject_consent_cookies(context, "ftp://example.com/")) == []
    assert context.calls == []


def test_inject_consent_cookies_never_raises_on_context_failure() -> None:
    failing = RecordingContext(fail=True)
    result = asyncio.run(inject_consent_cookies(failing, "https://example.com/"))
    assert result == []


# --- dismissal doubles (no browser) -------------------------------------------


class FakeElement:
    def __init__(self, *, visible=True, box=None, click_fails=False):
        self.visible = visible
        self.box = box if box is not None else {"x": 10, "y": 10, "width": 120, "height": 40}
        self.click_fails = click_fails
        self.clicks = 0

    async def is_visible(self):
        return self.visible

    async def bounding_box(self):
        return self.box

    async def click(self, timeout=None):  # noqa: ASYNC109 — mirrors Playwright's API
        if self.click_fails:
            raise RuntimeError("element detached mid-click")
        self.clicks += 1


class FakeFrame:
    def __init__(self, elements=None, *, fail=False, url="https://example.test/"):
        self.elements = elements or {}
        self.fail = fail
        self.url = url

    async def query_selector(self, selector):
        if self.fail:
            raise RuntimeError("simulated frame failure")
        return self.elements.get(selector)


class FakePage:
    def __init__(self, frames, *, wait_times_out=False, on_wait=None):
        self._frames = frames
        self.viewport_size = {"width": 1366, "height": 768}
        self.wait_times_out = wait_times_out
        self.on_wait = on_wait
        self.wait_selector_calls: list[tuple] = []

    @property
    def main_frame(self):
        return self._frames[0]

    @property
    def frames(self):
        return self._frames

    async def wait_for_selector(self, selector, *, state=None, timeout=None):  # noqa: ASYNC109
        self.wait_selector_calls.append((selector, state, timeout))
        if self.on_wait is not None:
            self.on_wait()
        if self.wait_times_out or self.on_wait is None:
            # Real Playwright raises TimeoutError when nothing matched in
            # the budget — the default double mirrors that.
            raise RuntimeError("simulated wait timeout")
        return None

    async def wait_for_timeout(self, ms):
        pass


async def test_dismiss_clicks_first_visible_match() -> None:
    first = FakeElement()
    second = FakeElement()
    page = FakePage(
        [FakeFrame({"#onetrust-accept-btn-handler": first, ".cc-accept-all": second})]
    )
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is True
    assert evidence["selector"] == "#onetrust-accept-btn-handler"
    assert evidence["attempts"] == 1  # first selector on the main frame
    assert first.clicks == 1 and second.clicks == 0


async def test_dismiss_no_banners_returns_gracefully() -> None:
    page = FakePage([FakeFrame({})])
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence == {
        "dismissed": False,
        "selector": None,
        "attempts": len(DISMISS_SELECTORS),
    }
    # The one bounded late-banner wait ran over the combined selector list.
    assert len(page.wait_selector_calls) == 1
    selector, state, timeout = page.wait_selector_calls[0]
    assert selector == ",".join(DISMISS_SELECTORS)
    assert state == "visible" and timeout is not None and timeout > 0


async def test_dismiss_skips_invisible_banner() -> None:
    page = FakePage([FakeFrame({"#onetrust-accept-btn-handler": FakeElement(visible=False)})])
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is False
    assert evidence["selector"] is None
    assert evidence["attempts"] == len(DISMISS_SELECTORS)


async def test_dismiss_skips_offscreen_button() -> None:
    page = FakePage(
        [
            FakeFrame(
                {
                    "#onetrust-accept-btn-handler": FakeElement(
                        box={"x": -300, "y": -300, "width": 120, "height": 40}
                    )
                }
            )
        ]
    )
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is False


async def test_dismiss_click_failure_tries_next_selector() -> None:
    broken = FakeElement(click_fails=True)
    good = FakeElement()
    page = FakePage(
        [FakeFrame({"#onetrust-accept-btn-handler": broken, "#accept-cookies": good})]
    )
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is True
    assert evidence["selector"] == "#accept-cookies"
    assert broken.clicks == 0 and good.clicks == 1


async def test_dismiss_finds_banner_in_consent_iframe() -> None:
    iframe_button = FakeElement()
    child = FakeFrame({".fc-cta-consent": iframe_button}, url="https://consent.quantcast.test/")
    page = FakePage([FakeFrame({}), child])
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is True
    assert evidence["selector"] == ".fc-cta-consent"
    assert evidence["attempts"] > len(DISMISS_SELECTORS)  # walked past the main frame
    assert iframe_button.clicks == 1


async def test_dismiss_waits_for_late_banner_then_clicks() -> None:
    frame = FakeFrame({})
    late = FakeElement()

    def reveal() -> None:
        frame.elements["#onetrust-accept-btn-handler"] = late

    page = FakePage([frame], on_wait=reveal)
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is True
    assert evidence["selector"] == "#onetrust-accept-btn-handler"
    assert late.clicks == 1


async def test_dismiss_bounded_by_timeout_when_nothing_appears() -> None:
    page = FakePage([FakeFrame({})], wait_times_out=True)
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence == {
        "dismissed": False,
        "selector": None,
        "attempts": len(DISMISS_SELECTORS),
    }
    assert len(page.wait_selector_calls) == 1  # never re-waits


async def test_dismiss_never_raises_on_broken_page() -> None:
    class BrokenPage:
        @property
        def main_frame(self):
            raise RuntimeError("page closed")

        viewport_size = None

    evidence = await dismiss_banners(BrokenPage(), timeout_ms=100)
    assert evidence["dismissed"] is False
    assert evidence["attempts"] == 0


async def test_dismiss_never_raises_on_broken_frame() -> None:
    page = FakePage([FakeFrame(fail=True), FakeFrame({})])
    evidence = await dismiss_banners(page, timeout_ms=100)
    assert evidence["dismissed"] is False
    assert evidence["attempts"] == 2 * len(DISMISS_SELECTORS)


# --- real-browser tests (hermetic: local server only) --------------------------

BANNER_HTML = (
    "<html><head><title>banner</title></head><body>"
    "<h1>wardress-banner-fixture</h1>"
    "<div id='overlay' style='position:fixed;inset:0;background:#fff;"
    "z-index:99999;text-align:center;padding-top:40vh'>Cookie banner"
    "<button id='accept-cookies' onclick='accept()'>Accept</button></div>"
    "<script>function accept(){document.getElementById('overlay').style.display='none';}</script>"
    "</body></html>"
)

HIDDEN_BANNER_HTML = BANNER_HTML.replace(
    "<button id='accept-cookies' onclick='accept()'>",
    "<button id='accept-cookies' style='display:none;' onclick='accept()'>",
)

COOKIE_ECHO_HTML = (
    "<html><head><title>cookies</title></head><body>"
    "<script>document.body.textContent = document.cookie;</script>"
    "</body></html>"
)


@pytest.fixture()
def banner_target():
    pages = {
        "/banner": (200, BANNER_HTML.encode()),
        "/hidden-banner": (200, HIDDEN_BANNER_HTML.encode()),
        "/cookie-echo": (200, COOKIE_ECHO_HTML.encode()),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            status, body = pages.get(self.path, (404, b"not found"))
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the test runner output
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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


async def test_dismiss_banners_real_browser_clicks_visible_banner(browser, banner_target) -> None:
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await page.goto(f"{banner_target}/banner")
        evidence = await dismiss_banners(page, timeout_ms=2_000)
        assert evidence["dismissed"] is True
        assert evidence["selector"] == "#accept-cookies"
        assert evidence["attempts"] >= 1
        # The click actually removed the banner overlay.
        overlay_display = await page.evaluate(
            "getComputedStyle(document.getElementById('overlay')).display"
        )
        assert overlay_display == "none"
    finally:
        await context.close()


async def test_dismiss_banners_real_browser_ignores_hidden_banner(browser, banner_target) -> None:
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await page.goto(f"{banner_target}/hidden-banner")
        evidence = await dismiss_banners(page, timeout_ms=300)
        assert evidence["dismissed"] is False
        assert evidence["selector"] is None
        assert evidence["attempts"] >= len(DISMISS_SELECTORS)
    finally:
        await context.close()


async def test_injected_cookies_carry_no_secure_flag_on_http(browser, banner_target) -> None:
    """The spec's Secure-on-http tripwire, end to end: Chromium refuses
    Secure cookies on http:, so the materializer must never set them."""
    context = await browser.new_context()
    try:
        names = await inject_consent_cookies(context, f"{banner_target}/banner")
        assert "OptanonAlertBoxClosed" in names
        cookies = await context.cookies()
        assert {c["name"] for c in cookies} >= set(names)
        assert not any(c.get("secure") for c in cookies), "no Secure cookies on http targets"
    finally:
        await context.close()


async def test_fetch_page_dismisses_banner_and_injects_cookies(banner_target, fast_settle) -> None:
    """FAILED-before: the pre-Phase-5 capture stored the banner overlay
    with its content obscured. Through the real fetch_page, the banner is
    dismissed (evidence recorded, overlay hidden in the capture) and the
    consent cookies are readable by the page itself."""
    result = await fetch_page(f"{banner_target}/banner", allow_private_networks=True)
    assert result.http_status == 200
    evidence = result.capture_evidence
    assert evidence is not None
    assert evidence["dismissed"] is True
    assert evidence["selector"] == "#accept-cookies"
    # Banner evidence must not touch the capture-quality semantics.
    assert evidence["capture_quality"] == "full"
    assert result.screenshot.startswith(b"\x89PNG")

    cookie_result = await fetch_page(f"{banner_target}/cookie-echo", allow_private_networks=True)
    assert cookie_result.http_status == 200
    assert "CookieScriptConsent=" in cookie_result.html


async def test_fetch_page_banner_free_page_still_captures(banner_target, fast_settle) -> None:
    """A page without any visible banner keeps the pre-Phase-5 behavior
    and evidence shape, with dismissed=False."""
    result = await fetch_page(f"{banner_target}/hidden-banner", allow_private_networks=True)
    assert result.http_status == 200
    evidence = result.capture_evidence
    assert evidence is not None
    assert evidence["dismissed"] is False
    assert evidence["selector"] is None
    assert evidence["capture_quality"] == "full"
    assert result.screenshot.startswith(b"\x89PNG")
