"""SSRF protection for target-site fetches (§9).

Every URL the platform is asked to fetch goes through `assert_url_allowed`
before any network activity. Default-deny covers loopback, RFC1918,
link-local, CGNAT, and other special-purpose ranges for both IPv4 and
IPv6, plus non-http(s) schemes and credential-bearing URLs. A site owner
can opt in per site (`sites.allow_private_networks`) to monitor an
internal host — that flag relaxes only the address-range checks, never
the scheme/credential rules.

Known limitation (logged in PROGRESS.md): validation resolves DNS at
check time while Playwright resolves again at fetch time, so a
fast-flipping DNS record (rebinding) could pass the check and then
resolve privately. The fetch pipeline re-validates the final URL after
redirects, which closes the redirect vector. Phase 5 adds the
`_address_blocked` helper and `SSRFPinningTransport`
(app/ssrf_transport.py) so the raw-httpx probe path resolves, validates,
and connects to the SAME address on every hop (no second resolution to
race); Playwright navigation still resolves independently, so the
redirect re-validation remains its primary guard.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlockedError(ValueError):
    """Raised when a fetch target is refused. Message is user-safe."""


_ALLOWED_SCHEMES = {"http", "https"}


def _is_forbidden_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address that is not plain global unicast.

    `not is_global` is the backbone of the deny-list: it covers RFC1918,
    loopback, link-local, ULA, CGNAT (100.64/10), documentation and
    reserved ranges in one property. Multicast is checked separately
    because 224/4 reports is_global=True.
    """
    return addr.is_multicast or not addr.is_global


def resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to every A/AAAA address. Raises SSRFBlockedError
    on resolution failure (an unresolvable target is also unfetchable)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise SSRFBlockedError(f"Could not resolve host {host!r}") from exc
    addrs = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addrs:
        raise SSRFBlockedError(f"Host {host!r} resolved to no usable addresses")
    return addrs


def assert_url_allowed(url: str, *, allow_private_networks: bool = False) -> None:
    """Validate a fetch target. Raises SSRFBlockedError with a user-safe
    message on any violation; returns None when the URL is acceptable."""
    if not isinstance(url, str) or len(url) > 2048:
        raise SSRFBlockedError("URL missing or too long (max 2048 characters)")

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise SSRFBlockedError("URL could not be parsed") from exc

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SSRFBlockedError("Only http and https URLs can be monitored")

    if parsed.username or parsed.password:
        raise SSRFBlockedError("URLs with embedded credentials are not allowed")

    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("URL has no host")

    # Literal IP? Check it directly (getaddrinfo would accept exotic
    # notations like 0x7f.1 — urlparse+ip_address normalizes first).
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if allow_private_networks:
        # Opt-in relaxes the range checks for addresses someone can
        # actually host a site on (private, loopback, link-local, CGNAT)
        # but still refuses multicast/unspecified/other reserved space.
        # Note ::1 reports is_reserved=True, hence the loopback carve-out.
        def blocked(a):
            return a.is_multicast or a.is_unspecified or (a.is_reserved and not a.is_loopback)
    else:
        blocked = _is_forbidden_address

    if literal is not None:
        if blocked(literal):
            raise SSRFBlockedError(
                f"Address {host} is in a blocked range. Enable 'allow private "
                "networks' on this site if you intend to monitor an internal host."
            )
        return

    for addr in resolve_host(host):
        if blocked(addr):
            raise SSRFBlockedError(
                f"Host {host!r} resolves to a blocked address ({addr}). Enable "
                "'allow private networks' on this site if you intend to monitor "
                "an internal host."
            )


def _address_blocked(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private_networks: bool
) -> bool:
    """Shared address-range policy, used by assert_url_allowed's inline
    check and by the pinning transport (app/ssrf_transport.py)."""
    if allow_private_networks:
        return (
            addr.is_multicast
            or addr.is_unspecified
            or (addr.is_reserved and not addr.is_loopback)
        )
    return _is_forbidden_address(addr)
