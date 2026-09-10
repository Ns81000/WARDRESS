"""AUDIT-3 scratch probe 4 — SSRF route-guard verdict cache semantics (Rule 13).

Questions:
1. Once a host is validated once, are ALL later requests to that host in
   the same page load allowed WITHOUT re-validation (cache hit)?
2. Is the cache ever invalidated (it is per-fetch, so "never" within one
   fetch_page call is the expected answer)?
3. Does a DNS-level change between validation and connection have any
   re-checkpoint? (Code-reading answer: no — route.continue_() lets
   Chromium resolve independently; the cache only widens that window.)

Uses the production _make_ssrf_route_guard with a counting stub in place
of assert_url_allowed (no browser needed).
"""
import asyncio
import sys

sys.path.insert(0, "backend")

import worker.fetcher as fetcher_mod  # noqa: E402


class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = type("R", (), {"url": url})()
        self.continued = False
        self.aborted = False

    async def continue_(self) -> None:
        self.continued = True

    async def abort(self, reason: str) -> None:
        self.aborted = True


async def main() -> None:
    calls: list[str] = []

    async def fake_to_thread(fn, url, **kw):  # noqa: ANN001
        calls.append(url)
        return None

    orig = fetcher_mod.asyncio.to_thread
    fetcher_mod.asyncio.to_thread = fake_to_thread
    try:
        guard = fetcher_mod._make_ssrf_route_guard(allow_private_networks=False)
        url = "https://example.com/a.png"
        for i in range(1, 6):
            route = FakeRoute(url)
            await guard(route)
            print(f"request {i}: validated_calls={len(calls)} continued={route.continued}")
        print(f"total assert_url_allowed invocations for 5 requests: {len(calls)}")
    finally:
        fetcher_mod.asyncio.to_thread = orig


asyncio.run(main())
