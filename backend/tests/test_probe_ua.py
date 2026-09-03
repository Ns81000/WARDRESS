"""Probe User-Agent rotation tests (PROMPT-002 Phase 2).

The probe's rotated UAs must be syntactically valid, era-consistent with
the capture's UA (worker/stealth.py — layer 7 compares raw-UA responses
against the Playwright render), and actually exercised per variant by
probe_site. Hermetic: httpx.MockTransport only, no sockets.
"""

import re

import httpx
import pytest

from worker import probe as probe_mod
from worker.probe import USER_AGENTS, probe_site
from worker.stealth import CAPTURE_USER_AGENT


def _chrome_major(ua: str) -> int:
    match = re.search(r"Chrome/(\d+)\.", ua)
    assert match is not None, f"no Chrome token in {ua!r}"
    return int(match.group(1))


def test_ua_strings_are_syntactically_valid() -> None:
    """Every rotated UA must have the canonical token shape a real browser
    sends — a malformed string is a bot-detection gift even for raw httpx."""
    for key, ua in USER_AGENTS.items():
        assert ua == ua.strip() and ua, key
        assert ua.startswith("Mozilla/5.0"), key
        assert "AppleWebKit/537.36" in ua or "AppleWebKit/605.1.15" in ua, key
        assert "KHTML, like Gecko" in ua, key
        assert re.search(r"Safari/\d+(\.\d+)*$", ua), key
        # Any Chrome token present must be a full four-part version.
        for token in re.findall(r"Chrome/[\d.]+", ua):
            assert re.fullmatch(r"Chrome/\d+\.\d+\.\d+\.\d+", token), (key, token)
        assert len(ua) < 300, key


def test_ua_chrome_variants_match_the_capture_era() -> None:
    """FAILED-before: the probe shipped Chrome/126.0.0.0 while the Phase 1
    capture moved to the current stable (152). Layer 7 compares raw-UA
    fetches against the rendered page, so the raw desktop reference must
    stay in the same Chrome era as CAPTURE_USER_AGENT — and recent."""
    capture_major = _chrome_major(CAPTURE_USER_AGENT)
    assert capture_major >= 130, "CAPTURE_USER_AGENT itself went stale"
    for key in ("desktop_chrome", "googlebot"):
        assert _chrome_major(USER_AGENTS[key]) == capture_major, key


def test_ua_keys_are_exactly_the_layer7_rotation() -> None:
    """The rotation contract (§5): reference + crawler + mobile. Renaming a
    key would silently change what layer 7 compares."""
    assert set(USER_AGENTS) == {"desktop_chrome", "googlebot", "mobile_safari"}
    assert "Googlebot/" in USER_AGENTS["googlebot"]
    assert "iPhone" in USER_AGENTS["mobile_safari"]
    assert "Mobile/" in USER_AGENTS["mobile_safari"]


async def test_probe_site_sends_each_rotated_ua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rotation still works end to end: probe_site fetches the page once
    per UA key, each fetch carries that key's UA header, and every variant
    succeeds. (robots.txt additionally reuses the desktop reference UA.)"""

    async def fake_tls(url: str):
        return None

    monkeypatch.setattr(probe_mod, "probe_tls", fake_tls)
    monkeypatch.setattr(probe_mod, "assert_url_allowed", lambda url, **kw: None)

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers["User-Agent"])
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /")
        return httpx.Response(200, content=b"<html><body>page</body></html>")

    real_client = httpx.AsyncClient

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", PatchedClient)

    result = await probe_site("https://example.com/")
    assert {v.ua_key for v in result.ua_variants} == set(USER_AGENTS)
    for variant in result.ua_variants:
        assert variant.error is None, variant.ua_key
        assert "page" in variant.html
        assert variant.http_status == 200
    assert set(USER_AGENTS.values()) <= set(sent)
