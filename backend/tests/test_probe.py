"""Metadata prober tests using httpx.MockTransport — request/response
handling only, no sockets. TLS handshake probing is exercised against the
live compose stack (it needs a real socket)."""

import httpx
import pytest

from app.ssrf import SSRFBlockedError
from worker import probe as probe_mod
from worker.probe import USER_AGENTS, ProbeResult, _fetch_raw, _redirect_guard, probe_site


def _client(handler, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


async def test_fetch_raw_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENTS["googlebot"]
        return httpx.Response(
            200, content=b"<html><body>bot view</body></html>", headers={"X-Test": "1"}
        )

    async with _client(handler) as client:
        variant, headers = await _fetch_raw(client, "https://example.com/", "googlebot")
    assert variant.http_status == 200
    assert "bot view" in variant.html
    assert variant.content_hash
    assert variant.error is None
    assert headers["x-test"] == "1"


async def test_fetch_raw_network_error_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    async with _client(handler) as client:
        variant, headers = await _fetch_raw(client, "https://example.com/", "googlebot")
    assert variant.error is not None and "ConnectTimeout" in variant.error
    assert variant.http_status is None
    assert headers == {}


async def test_fetch_raw_undecodable_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xfe\x00garbage\x00")

    async with _client(handler) as client:
        variant, _ = await _fetch_raw(client, "https://example.com/", "googlebot")
    assert variant.error is None  # decoded with errors="replace", no crash
    assert variant.content_hash


async def test_fetch_raw_caps_body_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "MAX_RAW_BYTES", 100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10_000)

    async with _client(handler) as client:
        variant, _ = await _fetch_raw(client, "https://example.com/", "googlebot")
    assert len(variant.html) == 100


async def test_redirect_guard_blocks_private_hop() -> None:
    guard = _redirect_guard(False)
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}, request=request)
    # httpx populates next_request during redirect-following; simulate it.
    response.next_request = httpx.Request("GET", "http://127.0.0.1/admin")
    with pytest.raises(SSRFBlockedError):
        await guard(response)


async def test_redirect_guard_allows_public_hop() -> None:
    guard = _redirect_guard(False)
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(302, headers={"location": "https://example.org/"}, request=request)
    response.next_request = httpx.Request("GET", "https://example.org/")
    await guard(response)  # no raise


async def test_probe_site_blocked_url_returns_empty() -> None:
    result = await probe_site("http://127.0.0.1/", allow_private_networks=False)
    assert isinstance(result, ProbeResult)
    assert result.tls is None
    assert result.ua_variants == []


async def test_probe_site_full_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """probe_site with mocked transport + TLS: robots captured, three UA
    variants fetched, reference headers stored lowercase."""

    async def fake_tls(url: str):
        return {"fingerprint_sha256": "f" * 64}

    monkeypatch.setattr(probe_mod, "probe_tls", fake_tls)
    monkeypatch.setattr(probe_mod, "assert_url_allowed", lambda url, **kw: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /admin")
        ua = request.headers["User-Agent"]
        is_bot = "Googlebot" in ua
        body = b"<html><body>bot</body></html>" if is_bot else b"<html><body>page</body></html>"
        return httpx.Response(200, content=body, headers={"Server": "test"})

    real_client = httpx.AsyncClient

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", PatchedClient)

    result = await probe_site("https://example.com/")
    assert result.tls == {"fingerprint_sha256": "f" * 64}
    assert "Disallow: /admin" in result.robots_txt
    assert {v.ua_key for v in result.ua_variants} == {
        "desktop_chrome",
        "googlebot",
        "mobile_safari",
    }
    googlebot = next(v for v in result.ua_variants if v.ua_key == "googlebot")
    desktop = next(v for v in result.ua_variants if v.ua_key == "desktop_chrome")
    assert "bot" in googlebot.html and "page" in desktop.html
    assert result.headers["server"] == "test"


async def test_probe_site_transport_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_tls(url: str):
        return None

    monkeypatch.setattr(probe_mod, "probe_tls", fake_tls)
    monkeypatch.setattr(probe_mod, "assert_url_allowed", lambda url, **kw: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    real_client = httpx.AsyncClient

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("verify", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", PatchedClient)

    result = await probe_site("https://example.com/")  # must not raise
    assert result.robots_txt is None
    assert all(v.error for v in result.ua_variants)


async def test_probe_tls_none_ssl_object_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """probe_tls contract: None on any handshake problem. A transport
    teardown race can make get_extra_info('ssl_object') return None — the
    probe must return None, never raise AttributeError into the scan task."""
    import asyncio

    from worker.probe import probe_tls

    class FakeWriter:
        def get_extra_info(self, name):
            return None  # the teardown race

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def fake_open_connection(*args, **kwargs):
        return object(), FakeWriter()

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)
    assert await probe_tls("https://example.com/") is None


async def test_probe_tls_unexpected_error_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error type outside the expected timeout/OS/SSL set (e.g. an
    AttributeError from a half-torn-down transport) degrades to None."""
    import asyncio

    from worker.probe import probe_tls

    async def exploding_open_connection(*args, **kwargs):
        raise AttributeError("simulated teardown race")

    monkeypatch.setattr(asyncio, "open_connection", exploding_open_connection)
    assert await probe_tls("https://example.com/") is None
