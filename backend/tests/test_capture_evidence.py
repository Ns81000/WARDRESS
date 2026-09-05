"""Capture-evidence tests (PROMPT-002 Phase 4).

Unit tests cover the FetchResult backward-compatibility contract (the
new field defaults to None — pre-Phase-4 constructions keep working) and
the capture_quality classification matrix. The integration tests drive
the real fetch_page (hermetic local server, real-Chromium-skip pattern
from test_page_prepare.py) and prove the assembled evidence dict carries
the exact scroll/stability/screenshot keys plus the informational
capture_quality label.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import worker.fetcher as fetcher_mod
from app.capture import CAPTURE_METHOD_VERSION
from worker.fetcher import BROWSER_LAUNCH_ARGS, FetchResult, _classify_capture_quality, fetch_page
from worker.page_prepare import auto_scroll_page

HTML = (
    "<html><head><title>static</title></head>"
    "<body><h1>wardress-evidence-fixture</h1></body></html>"
)


# --- unit tests (no browser) --------------------------------------------------


def test_fetch_result_capture_evidence_defaults_to_none() -> None:
    """Backward compatibility: every pre-Phase-4 construction site (and
    every test double built from the old shape) keeps working, and the
    field reads as 'unknown' rather than a missing attribute."""
    result = FetchResult(
        html=HTML,
        screenshot=b"\x89PNG-fake",
        final_url="https://example.com/",
        http_status=200,
        headers={"content-type": "text/html"},
    )
    assert result.capture_evidence is None


def test_fetch_result_accepts_and_stores_capture_evidence() -> None:
    evidence = {"scroll_steps": 0, "stable": True, "capture_quality": "full"}
    result = FetchResult(
        html=HTML,
        screenshot=b"\x89PNG-fake",
        final_url="https://example.com/",
        http_status=200,
        headers={},
        capture_evidence=evidence,
    )
    assert result.capture_evidence is evidence


def test_classify_capture_quality_full() -> None:
    evidence = {
        "scroll_steps": 2,
        "initial_height": 2000,
        "final_height": 2000,
        "capped": False,
        "scroll_time_ms": 700,
        "stable": True,
        "polls": 3,
        "final_length": 42,
        "screenshot_capped": False,
        "actual_height": 2000,
    }
    assert _classify_capture_quality(evidence) == "full"


def test_classify_capture_quality_scroll_time_capped_is_partial() -> None:
    evidence = {
        "capped": True,
        "stable": True,
        "screenshot_capped": False,
        "actual_height": 50_000,
    }
    assert _classify_capture_quality(evidence) == "partial"


def test_classify_capture_quality_unstable_content_is_partial() -> None:
    evidence = {
        "capped": False,
        "stable": False,
        "screenshot_capped": False,
        "actual_height": 900,
    }
    assert _classify_capture_quality(evidence) == "partial"


def test_classify_capture_quality_screenshot_capped_is_partial() -> None:
    """The spec pins 'full' to 'screenshot not capped'; a height-capped
    screenshot is a successful but incomplete capture -> partial."""
    evidence = {
        "capped": False,
        "stable": True,
        "screenshot_capped": True,
        "actual_height": 30_000,
    }
    assert _classify_capture_quality(evidence) == "partial"


def test_classify_capture_quality_unmeasurable_height_is_degraded() -> None:
    """A critical step failed but the capture completed: the height probe
    died, so the cap decision and completeness are unknown."""
    assert _classify_capture_quality({"actual_height": 0}) == "degraded"
    assert _classify_capture_quality({}) == "degraded"
    assert (
        _classify_capture_quality(
            {"actual_height": 0, "capped": False, "stable": True, "screenshot_capped": False}
        )
        == "degraded"
    )


# --- hermetic local server ----------------------------------------------------


@pytest.fixture()
def evidence_target():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            body = HTML.encode()
            self.send_response(200)
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
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            br = await pw.chromium.launch(headless=True, args=BROWSER_LAUNCH_ARGS)
        except Exception as exc:  # browser not installed on this host
            pytest.skip(f"Chromium not available on this host: {exc}")
        try:
            yield br
        finally:
            await br.close()


# --- real-browser tests (hermetic: local server only) --------------------------


async def test_fetch_page_assembles_capture_evidence(evidence_target, fast_settle) -> None:
    """The full capture path returns evidence merging the Phase-3 helper
    dicts, the Phase-4 screenshot facts, and the health label — and the
    label is 'full' for a short static page (nothing capped, stable)."""
    result = await fetch_page(f"{evidence_target}/", allow_private_networks=True)
    evidence = result.capture_evidence
    assert evidence is not None
    # Scroll evidence (worker/page_prepare.py contract).
    assert evidence["scroll_steps"] == 0  # nothing below the fold
    assert evidence["initial_height"] == evidence["final_height"]
    assert evidence["initial_height"] > 0
    assert evidence["capped"] is False
    assert isinstance(evidence["scroll_time_ms"], int)
    # Stability evidence.
    assert evidence["stable"] is True
    assert evidence["polls"] >= 2
    assert evidence["final_length"] > 0
    # Screenshot evidence (this phase).
    assert evidence["screenshot_capped"] is False
    assert evidence["actual_height"] == evidence["final_height"]
    # Health label — informational only.
    assert evidence["capture_quality"] == "full"
    assert result.screenshot.startswith(b"\x89PNG")
    # PROMPT-002 Phase 7 final assembly: migration-gate version, honest
    # stealth status, challenge-gate outcome, attempt wall clock.
    assert evidence["capture_method_version"] == CAPTURE_METHOD_VERSION
    assert evidence["stealth_applied"] is True
    assert evidence["cloudflare_challenge_detected"] is False
    assert evidence["cloudflare_challenge_resolved"] is False
    assert isinstance(evidence["capture_wall_clock_ms"], int)
    assert evidence["capture_wall_clock_ms"] >= 0


async def test_page_prepare_evidence_keys_unchanged(browser, evidence_target) -> None:
    """Guard: the scroll evidence dict Phase 4 merges still carries its
    exact documented key set (page_prepare contract untouched)."""
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await page.goto(f"{evidence_target}/")
        scroll = await auto_scroll_page(page)
        assert set(scroll) == {
            "scroll_steps",
            "initial_height",
            "final_height",
            "capped",
            "scroll_time_ms",
        }
    finally:
        await context.close()
