"""Cloudflare challenge detection tests (PROMPT-002 Phase 2).

Unit tests cover the pure indicator logic (no browser). Integration tests
drive the real fetch_page against a local ThreadingHTTPServer (same
hermetic pattern as test_stealth.py) and skip when Chromium is not
installed on the host.

FAILED-before proofs are embedded: the pre-Phase-2 fetch_page stored
challenge HTML as a successful capture instead of raising.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

import worker.fetcher as fetcher_mod
from worker import stealth as stealth_mod
from worker.fetcher import (
    BOT_PROTECTION_ERROR,
    BROWSER_LAUNCH_ARGS,
    CAPTURE_USER_AGENT,
    FetchError,
    fetch_page,
    is_challenge_title,
    looks_like_challenge_page,
)
from worker.stealth import apply_stealth

CHALLENGE_HTML = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><div class='cf-challenge-running'></div></body></html>"
)
BLOCK_HTML = (
    "<html><head><title>Attention Required! | Cloudflare</title></head>"
    "<body><div class='cf-error-details'><span>blocked</span></div></body></html>"
)
NORMAL_HTML = (
    "<html><head><title>normal site</title></head>"
    "<body><h1>wardress-normal-fixture</h1></body></html>"
)
# A legitimate page that merely *writes about* challenge pages: the
# markers appear as visible TEXT, never as element classes.
SIMILAR_TEXT_HTML = (
    "<html><head><title>How Cloudflare challenges work</title></head>"
    "<body><article>"
    "<p>The interstitial says &quot;Just a moment...&quot; while the widget"
    " element gets a cf-challenge-running class.</p>"
    "<p>wardress-similar-text-fixture</p>"
    "</article></body></html>"
)
# Mimics a Cloudflare JS challenge that auto-solves in place: title and
# marker flip to the real page after a delay (delay > fetcher's settle
# window so the wait-and-recheck loop is what observes the solve).
AUTO_SOLVE_DELAY_MS = 3_200
AUTO_SOLVE_HTML = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<div class='cf-challenge-running'></div>"
    "<script>setTimeout(function(){document.title='wardress-solved';"
    "var d=document.querySelector('.cf-challenge-running');"
    "if(d){d.remove();}}, " + str(AUTO_SOLVE_DELAY_MS) + ");</script>"
    "</body></html>"
)


# --- unit tests (no browser) -------------------------------------------------


def test_is_challenge_title_matches_only_canonical_markers() -> None:
    assert is_challenge_title("Just a moment...")
    assert is_challenge_title("just a moment")
    assert is_challenge_title("Attention Required! | Cloudflare")
    assert is_challenge_title("  Attention Required  ")
    assert not is_challenge_title("normal site")
    assert not is_challenge_title("")
    assert not is_challenge_title(None)


def test_looks_like_challenge_page_indicator_paths() -> None:
    # title-only path
    assert looks_like_challenge_page(title="Just a moment...")
    # DOM-class path
    assert looks_like_challenge_page(has_challenge_marker=True)
    # status + header path
    assert looks_like_challenge_page(http_status=403, headers={"cf-ray": "abc"})
    assert looks_like_challenge_page(http_status=403, headers={"CF-Ray": "abc"})


def test_looks_like_challenge_page_negative_paths() -> None:
    assert not looks_like_challenge_page()
    assert not looks_like_challenge_page(title="normal site")
    assert not looks_like_challenge_page(http_status=403, headers={})
    assert not looks_like_challenge_page(http_status=403, headers={"server": "nginx"})
    assert not looks_like_challenge_page(http_status=200, headers={"cf-ray": "abc"})
    assert not looks_like_challenge_page(http_status=503, headers={"cf-ray": "abc"})
    # Body-text mentions are not indicators — only the title and classes are.
    assert not looks_like_challenge_page(
        title="How Cloudflare challenges work",
        has_challenge_marker=False,
        http_status=200,
        headers={"content-type": "text/html"},
    )


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


@pytest.fixture()
def challenge_target():
    handler_cls, routes = _routes_handler()
    routes.update(
        {
            "/challenge": (200, {}, CHALLENGE_HTML.encode()),
            "/block": (200, {}, BLOCK_HTML.encode()),
            "/normal": (200, {}, NORMAL_HTML.encode()),
            "/similar-text": (200, {}, SIMILAR_TEXT_HTML.encode()),
            "/auto-solve": (200, {}, AUTO_SOLVE_HTML.encode()),
            "/403-cfray": (403, {"cf-ray": "8f0a-test"}, NORMAL_HTML.encode()),
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
def fast_challenge_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep persistence tests fast: the production wait is 10s."""
    monkeypatch.setattr(fetcher_mod, "CHALLENGE_WAIT_MS", 1_200)
    monkeypatch.setattr(fetcher_mod, "CHALLENGE_POLL_MS", 300)


# --- real-browser tests (hermetic: local server only) ------------------------


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


async def test_fetch_page_raises_when_challenge_persists(
    challenge_target, fast_challenge_wait
) -> None:
    """FAILED-before: pre-Phase-2 fetch_page returned the challenge HTML as
    a successful FetchResult. Now a persistent challenge is a hard failure
    with the user-safe message that scan_tasks stores on the failed row."""
    with pytest.raises(FetchError) as excinfo:
        await fetch_page(f"{challenge_target}/challenge", allow_private_networks=True)
    assert str(excinfo.value) == BOT_PROTECTION_ERROR
    assert "Cloudflare challenge detected" in str(excinfo.value)


async def test_fetch_page_raises_on_403_cf_ray_block_page(
    challenge_target, fast_challenge_wait
) -> None:
    """The status+header indicator path works through the real stack: a 403
    carrying cf-ray is treated as a challenge even when the DOM is calm."""
    with pytest.raises(FetchError, match="Cloudflare challenge detected"):
        await fetch_page(f"{challenge_target}/403-cfray", allow_private_networks=True)


async def test_fetch_page_waits_out_auto_solving_challenge(challenge_target) -> None:
    """Wait-and-retry: a challenge that auto-solves during the wait window
    produces a normal capture of the REAL page (with the real title in the
    DOM and a 200 PNG), never the challenge content."""
    result = await fetch_page(f"{challenge_target}/auto-solve", allow_private_networks=True)
    assert result.http_status == 200
    assert "wardress-solved" in result.html
    # The marker ELEMENT is gone after the solve (the solving script's own
    # text still mentions the class name, so assert on the element).
    assert "<div class='cf-challenge-running'></div>" not in result.html
    assert result.screenshot.startswith(b"\x89PNG")


async def test_fetch_page_does_not_false_positive_on_similar_text(
    challenge_target,
) -> None:
    """Non-challenge pages that merely mention the markers in body text (a
    blog post about Cloudflare) must capture normally: only the title and
    element classes are indicators."""
    result = await fetch_page(f"{challenge_target}/similar-text", allow_private_networks=True)
    assert result.http_status == 200
    assert "wardress-similar-text-fixture" in result.html


async def test_challenge_detection_works_without_stealth(
    challenge_target, fast_challenge_wait, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detection is independent of stealth status: with playwright-stealth
    absent (dev-environment degradation path), a persistent challenge still
    fails the capture instead of storing challenge HTML."""
    monkeypatch.setattr(stealth_mod, "Stealth", None)
    with pytest.raises(FetchError, match="Cloudflare challenge detected"):
        await fetch_page(f"{challenge_target}/challenge", allow_private_networks=True)


async def test_challenge_probe_js_reads_title_and_classes(browser, challenge_target) -> None:
    """The same DOM probe fetch_page uses, driven on a stealthed context:
    a normal page reports its title and no marker, so the OR-combined
    indicator stays False and the capture path is untouched."""
    context = await browser.new_context(user_agent=CAPTURE_USER_AGENT)
    await apply_stealth(context)
    page = await context.new_page()
    await page.goto(f"{challenge_target}/normal")
    markers = await page.evaluate(fetcher_mod._CHALLENGE_PROBE_JS)
    assert markers["title"] == "normal site"
    assert markers["marker"] is False
    assert not fetcher_mod.looks_like_challenge_page(
        title=markers["title"],
        has_challenge_marker=markers["marker"],
        http_status=200,
        headers={},
    )
    await context.close()
