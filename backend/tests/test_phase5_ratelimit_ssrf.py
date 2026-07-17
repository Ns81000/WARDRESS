"""Rate limiting (§9) and SSRF DNS-pinning transport (§9) unit tests."""

import httpx
import pytest

from app.ratelimit import FixedWindowLimiter
from app.ssrf import SSRFBlockedError
from app.ssrf_transport import SSRFPinningTransport


class TestFixedWindowLimiter:
    def test_allows_up_to_limit_then_blocks(self):
        limiter = FixedWindowLimiter(limit=3, window_seconds=60)
        assert [limiter.check("k")[0] for _ in range(3)] == [True, True, True]
        allowed, retry = limiter.check("k")
        assert allowed is False and retry >= 1

    def test_keys_are_independent(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60)
        assert limiter.check("a")[0] is True
        assert limiter.check("b")[0] is True  # different key, own budget
        assert limiter.check("a")[0] is False

    def test_zero_limit_disables(self):
        limiter = FixedWindowLimiter(limit=0, window_seconds=60)
        assert all(limiter.check("k")[0] for _ in range(100))


class TestRateLimitMiddleware:
    async def test_per_ip_limit_returns_429(self, client, monkeypatch):
        # Force a tiny per-IP limit and rebuild the limiters.
        from app import ratelimit
        from app.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("RATE_LIMIT_PER_IP", "3")
        ratelimit.reset_limiters()
        try:
            statuses = [
                (await client.get("/api/health/live")).status_code for _ in range(6)
            ]
            assert 429 in statuses
        finally:
            get_settings.cache_clear()
            monkeypatch.setenv("RATE_LIMIT_PER_IP", "0")
            ratelimit.reset_limiters()


class TestSSRFPinningTransport:
    async def test_blocks_loopback_literal(self):
        async with httpx.AsyncClient(
            transport=SSRFPinningTransport(allow_private_networks=False), timeout=5
        ) as c:
            with pytest.raises(SSRFBlockedError):
                await c.get("http://127.0.0.1/")

    async def test_blocks_loopback_hostname(self):
        async with httpx.AsyncClient(
            transport=SSRFPinningTransport(allow_private_networks=False), timeout=5
        ) as c:
            with pytest.raises(SSRFBlockedError):
                await c.get("http://localhost/")

    async def test_allows_private_when_opted_in(self, monkeypatch):
        # With the opt-in, a loopback literal is permitted past validation
        # (the connection itself will fail in CI, which is fine — we only
        # assert it is NOT SSRF-blocked).
        transport = SSRFPinningTransport(allow_private_networks=True)
        async with httpx.AsyncClient(transport=transport, timeout=2) as c:
            try:
                await c.get("http://127.0.0.1:9/")  # discard port; connect fails
            except SSRFBlockedError:
                pytest.fail("loopback should be allowed with the opt-in")
            except httpx.HTTPError:
                pass  # connection refused is the expected non-SSRF outcome
