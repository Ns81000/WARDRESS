"""Stealth-module and stealth-hardened-capture tests (PROMPT-002 Phase 1).

Hermetic by design: every network interaction targets a local
ThreadingHTTPServer on 127.0.0.1 (same pattern as test_phase16). Real
browser tests launch the project's pinned Chromium with the capture's
launch args and skip with a clear reason when no browser is installed
on the host (CI/dev machines without `playwright install chromium`).

Failing-before proofs are embedded: the pre-Phase-1 code path (no
stealth, branded UA) is exercised side-by-side where meaningful.
"""

import inspect
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

from worker import stealth as stealth_mod
from worker.fetcher import (
    FetchResult,
    _capture_attempt,
    _make_ssrf_route_guard,
    fetch_page,
)
from worker.stealth import (
    BROWSER_LAUNCH_ARGS,
    CAPTURE_USER_AGENT,
    apply_stealth,
)

PAGE_HTML = (
    "<html><head><title>stealth fixture</title></head>"
    "<body><h1 id='marker'>wardress-stealth-fixture</h1></body></html>"
)


# --- hermetic local capture target -----------------------------------------


def _page_handler(state: list) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "user_agent": self.headers.get("User-Agent", ""),
                }
            )
            body = PAGE_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return Handler


@pytest.fixture()
def capture_target():
    """Local HTTP server that serves PAGE_HTML and records requests."""
    requests: list = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _page_handler(requests))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_address[1]}/", "requests": requests}
    finally:
        server.shutdown()
        server.server_close()


# --- browser fixture (skips when no Chromium on the host) ------------------


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


# --- unit tests (no browser needed) ----------------------------------------


async def test_apply_stealth_missing_package_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Dev environments without playwright-stealth must keep working:
    apply_stealth logs a warning and returns instead of raising."""
    monkeypatch.setattr(stealth_mod, "Stealth", None)

    class _DummyContext:  # must not be touched on the degradation path
        touched = False

    with caplog.at_level("WARNING", logger=stealth_mod.logger.name):
        await apply_stealth(_DummyContext())  # must not raise
    assert not _DummyContext.touched
    assert any("WITHOUT stealth" in r.message for r in caplog.records)


def test_capture_user_agent_no_longer_self_identifies() -> None:
    """FAILED-before: the old fetcher shipped
    'Mozilla/5.0 ... Wardress/0.1 SiteMonitor' — a self-identifying monitor
    UA that any WAF flags. The capture UA must now be an unbranded,
    syntactically valid desktop-Chrome string."""
    import worker.fetcher as fetcher_mod

    assert "Wardress" not in CAPTURE_USER_AGENT
    assert CAPTURE_USER_AGENT.startswith("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    assert "AppleWebKit/537.36" in CAPTURE_USER_AGENT
    assert "(KHTML, like Gecko) Chrome/" in CAPTURE_USER_AGENT
    assert CAPTURE_USER_AGENT.endswith("Safari/537.36")
    # The branded UA is gone from the module entirely (no stale alias).
    assert not hasattr(fetcher_mod, "USER_AGENT")
    assert "Wardress/0.1" not in inspect.getsource(fetcher_mod)


def test_fetch_page_applies_stealth_before_route_guard() -> None:
    """Ordering contract (rule 11 / §4.1): stealth patches are init scripts
    that must never override the SSRF guard — the guard must be installed
    after apply_stealth and must still be present on every fetch. Since
    Phase 6 the capture flow spans fetch_page (retry loop) and
    _capture_attempt (the per-attempt body), so the seam is pinned across
    both functions' sources."""
    src = inspect.getsource(fetch_page) + inspect.getsource(_capture_attempt)
    assert "apply_stealth(context)" in src
    assert "page.route(\"**/*\", _make_ssrf_route_guard(" in src
    assert src.index("apply_stealth(context)") < src.index("_make_ssrf_route_guard(")
    assert "BROWSER_LAUNCH_ARGS" in src


# --- real-browser tests (hermetic: local server only) ----------------------


async def test_apply_stealth_fresh_context_does_not_crash(browser, capture_target) -> None:
    """Stealth must not break legitimate Playwright functionality: a
    stealthed context still creates pages, loads pages, and evaluates JS."""
    context = await browser.new_context(user_agent=CAPTURE_USER_AGENT)
    await apply_stealth(context)
    page = await context.new_page()
    await page.goto(capture_target["url"])
    assert await page.title() == "stealth fixture"
    assert await page.locator("#marker").text_content() == "wardress-stealth-fixture"
    html = await page.content()
    assert "wardress-stealth-fixture" in html
    await context.close()


async def test_navigator_webdriver_undefined_after_stealth() -> None:
    """FAILED-before: stock Playwright headless reports
    navigator.webdriver === true — the loudest automation signal. After
    apply_stealth it must be undefined. The old-path proof launches
    WITHOUT the capture's launch args (the shared fixture browser already
    carries them, which alone suppresses the flag)."""
    async with async_playwright() as pw:
        try:
            plain_browser = await pw.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium not available on this host: {exc}")
        try:
            # old-path proof: an arg-less headless context reports webdriver True
            plain_page = await plain_browser.new_page()
            assert await plain_page.evaluate("navigator.webdriver") is True

            # new-path: same browser, capture launch args + stealth patches
            context = await plain_browser.new_context(user_agent=CAPTURE_USER_AGENT)
            await apply_stealth(context)
            page = await context.new_page()
            await page.goto("about:blank")
            assert await page.evaluate("navigator.webdriver") is None  # undefined
            await context.close()
        finally:
            await plain_browser.close()


async def test_ssrf_route_guard_still_blocks_internal_after_stealth(
    browser, capture_target
) -> None:
    """The guard must keep working AFTER stealth (rule 11's explicit test
    obligation). Default policy: navigating to the loopback target is
    aborted by the route guard (net::ERR_BLOCKED_BY_CLIENT). With the
    site's opt-in flag the SAME guard lets the request through — proving
    the block came from the guard, not from the browser."""
    # blocked under the default policy
    context = await browser.new_context(user_agent=CAPTURE_USER_AGENT)
    await apply_stealth(context)
    page = await context.new_page()
    await page.route("**/*", _make_ssrf_route_guard(allow_private_networks=False))
    from playwright.async_api import Error as PlaywrightError

    with pytest.raises(PlaywrightError, match="ERR_BLOCKED_BY_CLIENT"):
        await page.goto(capture_target["url"])
    assert capture_target["requests"] == []  # nothing reached the server
    await context.close()

    # allowed under the opt-in — same guard, same stealth
    context = await browser.new_context(user_agent=CAPTURE_USER_AGENT)
    await apply_stealth(context)
    page = await context.new_page()
    await page.route("**/*", _make_ssrf_route_guard(allow_private_networks=True))
    await page.goto(capture_target["url"])
    assert "wardress-stealth-fixture" in await page.content()
    assert len(capture_target["requests"]) == 1
    await context.close()


async def test_fetch_page_with_stealth_captures_local_site(capture_target) -> None:
    """End-to-end: fetch_page (stealth + new UA + context shape) captures
    valid HTML and a PNG screenshot from the local site, and the capture
    arrives with the unbranded Chrome UA."""
    result: FetchResult = await fetch_page(capture_target["url"], allow_private_networks=True)
    assert result.http_status == 200
    assert "wardress-stealth-fixture" in result.html
    assert result.screenshot.startswith(b"\x89PNG")
    assert result.final_url == capture_target["url"]
    assert len(result.screenshot) > 0

    sent = capture_target["requests"]
    assert len(sent) == 1
    ua = sent[0]["user_agent"]
    assert ua == CAPTURE_USER_AGENT
    assert "Wardress" not in ua


async def test_fetch_page_still_refuses_blocked_urls() -> None:
    """The top-level SSRF check is untouched: loopback is refused under the
    default policy before any browser launches."""
    from app.ssrf import SSRFBlockedError

    with pytest.raises(SSRFBlockedError):
        await fetch_page("http://127.0.0.1:9/nowhere")
