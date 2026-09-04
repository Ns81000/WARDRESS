"""Screenshot height-cap tests (PROMPT-002 Phase 4).

Unit tests drive `worker.fetcher._take_screenshot` through a scripted
Page double (no browser): the cap decision, the exact screenshot call
shape, and the never-fail height probe. Integration tests use the
hermetic local ThreadingHTTPServer + real-Chromium-skip pattern from
test_page_prepare.py / test_stealth.py and prove the capture-level
behavior: a page taller than stealth.MAX_SCREENSHOT_HEIGHT yields a
valid PNG of exactly the cap height plus screenshot_capped evidence,
and a short page is captured at its full height.

FAILED-before proof: the pre-Phase-4 capture took an uncapped full-page
screenshot — an infinite-scroll page that hit the scroll time cap could
rasterize 50,000+ px (OOM / corrupt-PNG territory on many GPUs) — and
FetchResult had no capture_evidence at all.

Spec deviation proven here (Rule 12): the prompt's literal
`full_page=False, clip=...` shape clamps the result to the current
viewport under Playwright 1.61 (probed live in the worker container:
1366x768, not 1366x16384), so the cap runs under full_page=True, whose
clip coordinates are page coordinates.
"""

import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

import worker.fetcher as fetcher_mod
from worker.fetcher import BROWSER_LAUNCH_ARGS, _take_screenshot, fetch_page
from worker.stealth import MAX_SCREENSHOT_HEIGHT

# --- scripted Page double (no browser) ---------------------------------------


class ScreenshotPage:
    """Implements the _take_screenshot surface: evaluate() answering the
    height probe and screenshot() recording its exact kwargs."""

    def __init__(
        self,
        *,
        height: int = 2000,
        probe_fails: bool = False,
        viewport_width: int | None = 1366,
    ):
        self.height = height
        self.probe_fails = probe_fails
        self.viewport_width = viewport_width
        self.calls: list[dict] = []

    @property
    def viewport_size(self):
        if self.viewport_width is None:
            return None
        return {"width": self.viewport_width, "height": 768}

    async def evaluate(self, js):
        if self.probe_fails:
            raise RuntimeError("simulated page JS failure")
        return self.height

    async def screenshot(self, **kwargs):
        self.calls.append(kwargs)
        return b"\x89PNG-fake"


async def test_short_page_screenshots_full_height_uncapped() -> None:
    page = ScreenshotPage(height=2000)
    shot, evidence = await _take_screenshot(page)
    assert shot == b"\x89PNG-fake"
    # Uncapped path: plain full-page raster, no clip.
    assert page.calls == [{"full_page": True, "type": "png", "timeout": 45_000}]
    assert evidence == {"screenshot_capped": False, "actual_height": 2000}


async def test_tall_page_is_clipped_to_the_cap() -> None:
    page = ScreenshotPage(height=200_000)
    shot, evidence = await _take_screenshot(page)
    assert shot == b"\x89PNG-fake"
    assert len(page.calls) == 1
    call = page.calls[0]
    assert call["full_page"] is True  # clip coordinates are page coordinates
    assert call["clip"] == {
        "x": 0,
        "y": 0,
        "width": 1366,
        "height": MAX_SCREENSHOT_HEIGHT,
    }
    assert call["type"] == "png" and call["timeout"] == 45_000
    assert evidence == {"screenshot_capped": True, "actual_height": 200_000}


async def test_height_probe_failure_never_fails_the_capture() -> None:
    """A dead probe records actual_height=0 and falls back to the normal
    full-page screenshot — evidence gathering must not fail a capture."""
    page = ScreenshotPage(height=200_000, probe_fails=True)
    shot, evidence = await _take_screenshot(page)
    assert shot == b"\x89PNG-fake"
    assert page.calls == [{"full_page": True, "type": "png", "timeout": 45_000}]
    assert evidence == {"screenshot_capped": False, "actual_height": 0}


async def test_clip_width_falls_back_to_context_viewport() -> None:
    """A page without a reported viewport size still gets a well-formed
    clip: the width falls back to the capture context's viewport."""
    page = ScreenshotPage(height=200_000, viewport_width=None)
    _, evidence = await _take_screenshot(page)
    assert evidence["screenshot_capped"] is True
    assert page.calls[0]["clip"]["width"] == fetcher_mod.CONTEXT_VIEWPORT["width"]


# --- hermetic local server ----------------------------------------------------

SHORT_HTML = (
    "<html><head><title>short</title></head>"
    "<body style='margin:0'><div style='height:2000px'></div></body></html>"
)
TALL_HTML = (
    "<html><head><title>tall</title></head>"
    "<body style='margin:0'><div style='height:20000px'></div></body></html>"
)


@pytest.fixture()
def cap_target():
    routes = {
        "/short": (200, {}, SHORT_HTML.encode()),
        "/tall": (200, {}, TALL_HTML.encode()),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            status, headers, body = routes.get(
                self.path, (404, {}, b"<html><body>not found</body></html>")
            )
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
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


def png_dimensions(png: bytes) -> tuple[int, int]:
    return struct.unpack(">II", png[16:24])


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


async def test_take_screenshot_real_browser_short_and_tall_pages(
    browser, cap_target
) -> None:
    """Short page: full-height PNG, not capped. Tall page: the raster is
    capped to exactly MAX_SCREENSHOT_HEIGHT and is still a valid PNG
    (what the visual-diff layer needs)."""
    context = await browser.new_context(
        viewport=fetcher_mod.CONTEXT_VIEWPORT, user_agent=fetcher_mod.CAPTURE_USER_AGENT
    )
    try:
        page = await context.new_page()

        await page.goto(f"{cap_target}/short")
        shot, evidence = await _take_screenshot(page)
        assert evidence["screenshot_capped"] is False
        assert evidence["actual_height"] == 2000
        assert shot.startswith(b"\x89PNG")
        assert png_dimensions(shot) == (1366, 2000)

        await page.goto(f"{cap_target}/tall")
        shot, evidence = await _take_screenshot(page)
        assert evidence["screenshot_capped"] is True
        assert evidence["actual_height"] == 20000
        assert shot.startswith(b"\x89PNG")
        assert png_dimensions(shot) == (1366, MAX_SCREENSHOT_HEIGHT)
    finally:
        await context.close()


async def test_fetch_page_capped_path_end_to_end(
    cap_target, fast_settle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the real fetch_page: a page taller than the (shrunk) cap is
    height-capped, the PNG is exactly the cap height, and the evidence
    travels on FetchResult with capture_quality 'partial'."""
    monkeypatch.setattr(fetcher_mod, "MAX_SCREENSHOT_HEIGHT", 600)
    result = await fetch_page(f"{cap_target}/tall", allow_private_networks=True)
    assert result.http_status == 200
    assert result.screenshot.startswith(b"\x89PNG")
    assert png_dimensions(result.screenshot) == (1366, 600)
    assert result.capture_evidence is not None
    assert result.capture_evidence["screenshot_capped"] is True
    assert result.capture_evidence["actual_height"] == 20000
    assert result.capture_evidence["capture_quality"] == "partial"


async def test_fetch_page_uncapped_short_page_evidence(cap_target, fast_settle) -> None:
    """A page under the cap is captured at full height with the uncapped
    evidence shape — the capped path never fires spuriously."""
    result = await fetch_page(f"{cap_target}/short", allow_private_networks=True)
    assert result.http_status == 200
    assert result.screenshot.startswith(b"\x89PNG")
    assert result.capture_evidence is not None
    assert result.capture_evidence["screenshot_capped"] is False
    assert result.capture_evidence["actual_height"] == 2000
