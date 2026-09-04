"""Transient-failure retry tests (PROMPT-002 Phase 6).

Unit tests cover the goto-failure classifier and the retry loop's
contracts without a browser: transient goto failures retry once at the
reduced nav timeout, an unsolved challenge retries once with the longer
wait, SSRF refusals and permanent FetchErrors never retry, and the total
attempt count is capped at 2. Integration tests drive the real
fetch_page against a local ThreadingHTTPServer (the hermetic
real-Chromium-skip pattern from test_cloudflare_detection.py) and prove
the retry paths end to end, including the retry_count recorded in
capture_evidence.

FAILED-before proofs are embedded: the pre-Phase-6 fetch_page made
exactly one attempt — a transient goto timeout failed the capture
immediately instead of retrying, and an unsolved challenge never got a
second, longer wait.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import worker.fetcher as fetcher_mod
from app.ssrf import SSRFBlockedError
from worker.fetcher import (
    BOT_PROTECTION_ERROR,
    CHALLENGE_RETRY_WAIT_MS,
    CHALLENGE_WAIT_MS,
    NAV_TIMEOUT_MS,
    RETRY_NAV_TIMEOUT_MS,
    RETRY_PAUSE_MS,
    FetchError,
    FetchResult,
    _ChallengeUnsolvedError,
    _classify_goto_failure,
    _TransientNavError,
    fetch_page,
)

CHALLENGE_HTML = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><div class='cf-challenge-running'></div></body></html>"
)
NORMAL_HTML = (
    "<html><head><title>normal site</title></head>"
    "<body><h1>wardress-retry-fixture</h1></body></html>"
)


# --- unit tests (no browser) --------------------------------------------------


def test_retry_constants_shape() -> None:
    """The retry must be FASTER than the first attempt (spec: reduced nav
    timeout) and the challenge retry's wait must be the LONGER one."""
    assert RETRY_NAV_TIMEOUT_MS < NAV_TIMEOUT_MS
    assert RETRY_PAUSE_MS > 0
    assert CHALLENGE_RETRY_WAIT_MS > CHALLENGE_WAIT_MS


def test_classify_goto_failure_transient_paths() -> None:
    assert _classify_goto_failure(
        PlaywrightTimeoutError("Page.goto: Timeout 30000ms exceeded.")
    )
    assert _classify_goto_failure(
        PlaywrightError("Page.goto: net::ERR_CONNECTION_REFUSED at https://x/")
    )
    assert _classify_goto_failure(
        PlaywrightError("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/")
    )
    assert _classify_goto_failure(
        PlaywrightError("Page.goto: net::ERR_CONNECTION_RESET at https://x/")
    )


def test_classify_goto_failure_permanent_paths() -> None:
    """The route guard's denials are SSRF policy decisions — never retried
    — and unclassifiable goto failures stay permanent (retrying an unknown
    failure shape doubles the cost of permanent breakage)."""
    assert (
        _classify_goto_failure(
            PlaywrightError("Page.goto: net::ERR_BLOCKED_BY_CLIENT at https://x/")
        )
        is None
    )
    assert (
        _classify_goto_failure(PlaywrightError("Page.goto: something unexpected"))
        is None
    )


@pytest.fixture()
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep loop-level tests fast: the production pause is 3s."""
    monkeypatch.setattr(fetcher_mod, "RETRY_PAUSE_MS", 10)


async def test_ssrf_block_is_never_retried(fast_retry, monkeypatch) -> None:
    """An SSRF refusal (e.g. the final-URL recheck after a redirect) is a
    policy decision, not a transient error: exactly ONE attempt, the
    SSRFBlockedError propagates unchanged."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append(nav_timeout_ms)
        raise SSRFBlockedError("Host 'evil.example' resolves to a blocked address.")

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    with pytest.raises(SSRFBlockedError):
        await fetch_page("https://redirects-to-internal.example/")
    assert len(calls) == 1


async def test_permanent_fetch_error_is_never_retried(fast_retry, monkeypatch) -> None:
    """Permanent operational failures (HTML over budget, etc.) fail the
    capture immediately — no second attempt is spent on them."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append(nav_timeout_ms)
        raise FetchError("Page HTML exceeds the 10 MB limit")

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    with pytest.raises(FetchError, match="10 MB"):
        await fetch_page("https://huge.example/")
    assert len(calls) == 1


async def test_transient_nav_error_retries_once_then_fails(
    fast_retry, monkeypatch
) -> None:
    """The retry cap: a persistently transient goto failure gets exactly
    one retry, at the REDUCED nav timeout, carrying retry_count=1, and the
    final error is a user-safe FetchError."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append((nav_timeout_ms, retry_count))
        raise _TransientNavError("navigation timeout (Page.goto: Timeout exceeded.)")

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    with pytest.raises(FetchError, match="navigation timeout"):
        await fetch_page("https://slow.example/")
    assert [nav for nav, _ in calls] == [NAV_TIMEOUT_MS, RETRY_NAV_TIMEOUT_MS]
    assert [rc for _, rc in calls] == [0, 1]


async def test_transient_nav_error_recovers_on_second_attempt(
    fast_retry, monkeypatch
) -> None:
    """The point of the phase: a transient failure followed by a healthy
    attempt yields a successful capture whose evidence records the retry."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append((nav_timeout_ms, retry_count))
        if len(calls) == 1:
            raise _TransientNavError("network error (net::ERR_CONNECTION_RESET)")
        return FetchResult(
            html=NORMAL_HTML,
            screenshot=b"\x89PNG-fake",
            final_url=url,
            http_status=200,
            headers={},
            capture_evidence={"retry_count": retry_count},
        )

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    result = await fetch_page("https://flaky.example/")
    assert len(calls) == 2
    assert calls[0] == (NAV_TIMEOUT_MS, 0)
    assert calls[1] == (RETRY_NAV_TIMEOUT_MS, 1)
    assert result.capture_evidence is not None
    assert result.capture_evidence["retry_count"] == 1


async def test_unsolved_challenge_retries_with_longer_wait(
    fast_retry, monkeypatch
) -> None:
    """A challenge that didn't auto-solve retries ONCE with the longer
    wait window (and the reduced nav timeout); the second attempt's
    success is a normal capture with retry_count=1."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append((nav_timeout_ms, challenge_wait_ms, retry_count))
        if len(calls) == 1:
            raise _ChallengeUnsolvedError(BOT_PROTECTION_ERROR)
        return FetchResult(
            html=NORMAL_HTML,
            screenshot=b"\x89PNG-fake",
            final_url=url,
            http_status=200,
            headers={},
            capture_evidence={"retry_count": retry_count},
        )

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    result = await fetch_page("https://challenged.example/")
    assert calls[0] == (NAV_TIMEOUT_MS, CHALLENGE_WAIT_MS, 0)
    assert calls[1] == (RETRY_NAV_TIMEOUT_MS, CHALLENGE_RETRY_WAIT_MS, 1)
    assert result.capture_evidence is not None
    assert result.capture_evidence["retry_count"] == 1


async def test_unsolved_challenge_on_both_attempts_fails_after_two(
    fast_retry, monkeypatch
) -> None:
    """The challenge retry is also capped at one: a challenge that
    outlasts the LONGER wait too fails the capture with the same
    user-safe bot-protection message, after exactly 2 attempts."""
    calls: list = []

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        calls.append(challenge_wait_ms)
        raise _ChallengeUnsolvedError(BOT_PROTECTION_ERROR)

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    with pytest.raises(FetchError) as excinfo:
        await fetch_page("https://hard-blocked.example/")
    assert str(excinfo.value) == BOT_PROTECTION_ERROR
    assert calls == [CHALLENGE_WAIT_MS, CHALLENGE_RETRY_WAIT_MS]


async def test_retry_logs_warning_with_reason(
    fast_retry, monkeypatch, caplog
) -> None:
    """Operator visibility: every retry decision is logged at WARNING with
    the reason (scan_tasks stores only the final error)."""
    import logging

    def fake_gate(url, *, allow_private_networks=False):
        return None

    async def fake_attempt(
        url, *, allow_private_networks, nav_timeout_ms, challenge_wait_ms, retry_count
    ):
        if retry_count == 0:
            raise _TransientNavError("navigation timeout (boom)")
        return FetchResult(
            html=NORMAL_HTML,
            screenshot=b"",
            final_url=url,
            http_status=200,
            headers={},
            capture_evidence={"retry_count": retry_count},
        )

    monkeypatch.setattr(fetcher_mod, "assert_url_allowed", fake_gate)
    monkeypatch.setattr(fetcher_mod, "_capture_attempt", fake_attempt)
    with caplog.at_level(logging.WARNING, logger="worker.fetcher"):
        await fetch_page("https://flaky.example/")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("retry" in r.getMessage().lower() for r in warnings)
    assert any("navigation timeout" in r.getMessage() for r in warnings)


# --- real-browser tests (hermetic: local server only) --------------------------


@pytest.fixture()
def retry_target():
    """A local server whose per-request behavior is scripted: each entry
    in `plan` is (delay_seconds, status, body) consumed by one request;
    when the plan runs dry, requests get an instant normal page. `state`
    counts every request received (the attempt-count oracle)."""
    state = {"requests": 0}
    plan: list = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            state["requests"] += 1
            if plan:
                delay, status, body = plan.pop(0)
            else:
                delay, status, body = 0.0, 200, NORMAL_HTML.encode()
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the test runner output
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", plan, state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def fast_retry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink every production wait so the integration tests stay fast:
    attempt 1's nav timeout must be SHORT enough for the scripted hang to
    exceed it (transient timeout) while the retry's is longer; challenge
    waits are sub-second; the pause and settle are near-zero."""
    monkeypatch.setattr(fetcher_mod, "SETTLE_MS", 100)
    monkeypatch.setattr(fetcher_mod, "NAV_TIMEOUT_MS", 800)
    monkeypatch.setattr(fetcher_mod, "RETRY_NAV_TIMEOUT_MS", 1_200)
    monkeypatch.setattr(fetcher_mod, "RETRY_PAUSE_MS", 100)
    monkeypatch.setattr(fetcher_mod, "BANNER_DISMISS_TIMEOUT_MS", 200)
    monkeypatch.setattr(fetcher_mod, "CHALLENGE_WAIT_MS", 900)
    monkeypatch.setattr(fetcher_mod, "CHALLENGE_POLL_MS", 200)
    monkeypatch.setattr(fetcher_mod, "CHALLENGE_RETRY_WAIT_MS", 1_200)


async def test_fetch_page_retries_transient_timeout_and_succeeds(
    retry_target, fast_retry_env
) -> None:
    """FAILED-before: the pre-Phase-6 fetch_page made exactly one attempt —
    the first request's hang timed out the capture immediately. Now the
    transient timeout gets one retry at the reduced budget, the second
    attempt captures the real page, and the evidence records retry_count=1."""
    base, plan, state = retry_target
    plan.append((2.0, 200, NORMAL_HTML.encode()))  # attempt 1: hangs past 800ms
    plan.append((0.0, 200, NORMAL_HTML.encode()))  # attempt 2: instant
    result = await fetch_page(f"{base}/", allow_private_networks=True)
    assert state["requests"] == 2
    assert result.capture_evidence is not None
    assert result.capture_evidence["retry_count"] == 1
    assert result.screenshot.startswith(b"\x89PNG")
    assert result.http_status == 200


async def test_fetch_page_first_attempt_success_records_zero_retries(
    retry_target, fast_retry_env
) -> None:
    """The happy path is unchanged: one request, and the evidence explicitly
    records that no retry happened."""
    base, plan, state = retry_target
    plan.append((0.0, 200, NORMAL_HTML.encode()))
    result = await fetch_page(f"{base}/", allow_private_networks=True)
    assert state["requests"] == 1
    assert result.capture_evidence is not None
    assert result.capture_evidence["retry_count"] == 0


async def test_fetch_page_retries_unsolved_challenge_with_longer_wait(
    retry_target, fast_retry_env
) -> None:
    """FAILED-before: a persistent challenge failed the capture after the
    first wait window. Now it retries once with the longer window; the
    scripted second response (the real page) is captured normally."""
    base, plan, state = retry_target
    plan.append((0.0, 200, CHALLENGE_HTML.encode()))  # attempt 1: persistent challenge
    plan.append((0.0, 200, NORMAL_HTML.encode()))  # attempt 2: the real page
    result = await fetch_page(f"{base}/", allow_private_networks=True)
    assert state["requests"] == 2
    assert result.capture_evidence is not None
    assert result.capture_evidence["retry_count"] == 1
    assert "wardress-retry-fixture" in result.html
    assert result.screenshot.startswith(b"\x89PNG")


async def test_fetch_page_never_exceeds_two_total_attempts(
    retry_target, fast_retry_env
) -> None:
    """The cap, end to end: a server that hangs on EVERY request gets
    exactly two navigation attempts before the capture fails."""
    base, plan, state = retry_target
    plan.extend([(2.0, 200, NORMAL_HTML.encode())] * 4)
    with pytest.raises(FetchError) as excinfo:
        await fetch_page(f"{base}/", allow_private_networks=True)
    assert state["requests"] == 2
    assert "navigation timeout" in str(excinfo.value)
