"""SSRF-safe httpx transport with DNS pinning (§9 rebinding closure).

The standing gap (PROGRESS.md, Phase 1): `assert_url_allowed` resolves
DNS at *check* time, then the HTTP client resolves again at *connect*
time — a fast-flipping record (DNS rebinding) can pass the check and then
connect to a private address. This transport closes that window for the
raw-httpx probe path by doing validation and connection against the SAME
resolved address:

For every request (including each redirect hop, since httpx routes those
back through the transport), it resolves the host, validates every
resolved address against the SSRF policy, then rewrites the outgoing
request to connect to one validated IP literal while preserving the
original Host header and TLS SNI. There is no second resolution to race.

Playwright navigation cannot use this transport; its guard remains the
post-redirect final-URL re-validation in worker/fetcher.py.
"""

import ipaddress
from urllib.parse import urlparse, urlunparse

import httpx

from app.ssrf import SSRFBlockedError, _address_blocked, resolve_host


class SSRFPinningTransport(httpx.AsyncBaseTransport):
    """Wraps a real async transport; validates + pins each request's
    target IP at connection time. Raises SSRFBlockedError (a ValueError)
    on any policy violation — callers already handle that type."""

    def __init__(self, *, allow_private_networks: bool, **transport_kwargs) -> None:
        self._allow_private = allow_private_networks
        # verify is handled by the caller's context; the inner transport
        # carries TLS settings passed through kwargs.
        self._inner = httpx.AsyncHTTPTransport(**transport_kwargs)

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._inner.__aexit__(*exc)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise SSRFBlockedError("Only http and https URLs can be fetched")
        host = parsed.hostname
        if not host:
            raise SSRFBlockedError("URL has no host")

        # Pin: if the host is already an IP literal, validate it directly;
        # otherwise resolve, validate every address, and pin to the first
        # allowed one.
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None

        if literal is not None:
            if _address_blocked(literal, self._allow_private):
                raise SSRFBlockedError(f"Address {host} is in a blocked range")
            return await self._inner.handle_async_request(request)

        pinned: str | None = None
        for addr in resolve_host(host):
            if _address_blocked(addr, self._allow_private):
                raise SSRFBlockedError(f"Host {host!r} resolves to a blocked address ({addr})")
            if pinned is None:
                pinned = str(addr)
        if pinned is None:  # pragma: no cover — resolve_host raises if empty
            raise SSRFBlockedError(f"Host {host!r} resolved to no usable address")

        # Rewrite the connection target to the pinned IP; keep Host + SNI.
        ip_netloc = f"[{pinned}]" if ":" in pinned else pinned
        if parsed.port:
            ip_netloc = f"{ip_netloc}:{parsed.port}"
        pinned_url = urlunparse(
            (parsed.scheme, ip_netloc, parsed.path or "/", parsed.params, parsed.query, "")
        )
        request.url = httpx.URL(pinned_url)
        if "host" not in {k.lower() for k in request.headers}:
            request.headers["Host"] = host
        # sni_hostname keeps TLS cert validation/SNI on the real hostname
        # even though we connect to the IP.
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._inner.handle_async_request(request)
