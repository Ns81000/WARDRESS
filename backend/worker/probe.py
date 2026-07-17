"""Scan-time metadata prober (layers 6 & 7 inputs).

Alongside the Playwright render, each capture gathers:
- the TLS certificate (expiry, SHA-256 fingerprint, subject/issuer) via
  a raw ssl handshake — Playwright doesn't expose the peer cert;
- robots.txt content (layer 6 diffs it);
- raw httpx fetches of the page under rotated User-Agents including a
  desktop-Chrome *reference* (layer 7 compares rotated UAs against that
  reference, raw-vs-raw);
- the full (curated-list-free) response header map for the primary URL,
  so layer 6 can diff security headers.

Every probe is individually fail-safe (rule 6): a TLS handshake error,
missing robots.txt, or a blocked UA fetch degrades that one input to
None/error-note — never fails the scan. All network work honors the
site's SSRF policy: URLs are validated up front and redirects are
re-validated hop by hop.
"""

import asyncio
import hashlib
import logging
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx

from app.ssrf import SSRFBlockedError, assert_url_allowed
from app.ssrf_transport import SSRFPinningTransport
from worker.detection.types import UAVariant
from worker.hashing import content_sha256

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 20.0
MAX_RAW_BYTES = 5 * 1024 * 1024  # raw UA fetches: cap read size
MAX_ROBOTS_BYTES = 128 * 1024

# Layer 7 UA rotation (§5): reference + crawler + mobile.
USER_AGENTS: dict[str, str] = {
    "desktop_chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "googlebot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
        "Googlebot/2.1; +http://www.google.com/bot.html) Chrome/126.0.0.0 Safari/537.36"
    ),
    "mobile_safari": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
}


@dataclass
class ProbeResult:
    tls: dict | None = None
    robots_txt: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    ua_variants: list[UAVariant] = field(default_factory=list)


def _name_attrs(name_seq) -> dict:
    """Flatten ssl.getpeercert() subject/issuer tuples into a dict."""
    out: dict[str, str] = {}
    for rdn in name_seq or ():
        for key, value in rdn:
            out[key] = value
    return out


async def probe_tls(url: str) -> dict | None:
    """TLS certificate metadata for an https URL; None for http or on any
    handshake problem (recorded at debug level — sites legitimately break)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname
    port = parsed.port or 443
    try:
        context = ssl.create_default_context()
        # Certificate *observation*, not trust decision: capture even
        # expired/self-signed certs (their weirdness is layer-6 evidence,
        # and scans of such sites must not lose the whole TLS picture).
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            timeout=PROBE_TIMEOUT_S,
        )
        try:
            ssl_obj = writer.get_extra_info("ssl_object")
            der = ssl_obj.getpeercert(binary_form=True)
            peer = ssl_obj.getpeercert()  # parsed dict (empty w/ CERT_NONE)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: S110 — best-effort socket teardown
                pass
        if der is None:
            return None
        info: dict = {"fingerprint_sha256": hashlib.sha256(der).hexdigest()}
        # With CERT_NONE the parsed dict is empty; parse the DER instead.
        try:
            from cryptography import x509

            cert = x509.load_der_x509_certificate(der)
            not_after = cert.not_valid_after_utc
            not_before = cert.not_valid_before_utc
            info["not_after"] = not_after.isoformat()
            info["not_before"] = not_before.isoformat()
            info["expired"] = not_after < datetime.now(UTC)
            info["subject"] = cert.subject.rfc4514_string()
            info["issuer"] = cert.issuer.rfc4514_string()
        except Exception:
            # cryptography parse failed — keep what getpeercert gave us.
            if peer:
                info["subject"] = str(_name_attrs(peer.get("subject")))
                info["issuer"] = str(_name_attrs(peer.get("issuer")))
                info["not_after"] = peer.get("notAfter")
        return info
    except (TimeoutError, OSError, ssl.SSLError, ValueError) as exc:
        logger.debug("TLS probe failed for %s: %s", host, exc)
        return None


def _redirect_guard(allow_private_networks: bool):
    """httpx event hook: re-validate every redirect hop against SSRF policy."""

    async def check(response: httpx.Response) -> None:
        if response.next_request is not None:
            assert_url_allowed(
                str(response.next_request.url), allow_private_networks=allow_private_networks
            )

    return check


async def _fetch_raw(
    client: httpx.AsyncClient, url: str, ua_key: str
) -> tuple[UAVariant, dict[str, str]]:
    """One raw GET under the given UA. Returns the variant plus the
    response header map (used for layer 6 when this is the reference)."""
    variant = UAVariant(ua_key=ua_key)
    headers: dict[str, str] = {}
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENTS[ua_key]})
        variant.http_status = resp.status_code
        variant.final_url = str(resp.url)
        body = resp.content[:MAX_RAW_BYTES]
        variant.html = body.decode(resp.encoding or "utf-8", errors="replace")
        variant.content_hash = content_sha256(variant.html)
        headers = {k.lower(): v for k, v in resp.headers.items()}
    except SSRFBlockedError as exc:
        variant.error = str(exc)
    except httpx.HTTPError as exc:
        variant.error = f"{type(exc).__name__}: {str(exc)[:200]}"
    return variant, headers


async def probe_site(url: str, *, allow_private_networks: bool = False) -> ProbeResult:
    """Gather all side-channel metadata for one capture. Never raises."""
    result = ProbeResult()

    try:
        assert_url_allowed(url, allow_private_networks=allow_private_networks)
    except SSRFBlockedError as exc:
        # The main fetch already refused this URL; record and bail.
        logger.warning("Probe skipped, URL blocked: %s", exc)
        return result

    result.tls = await probe_tls(url)

    limits = httpx.Limits(max_connections=4)
    timeout = httpx.Timeout(PROBE_TIMEOUT_S)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=8,
            limits=limits,
            timeout=timeout,
            verify=False,  # noqa: S501 — observation, not trust: layer 6 must still see sites with broken TLS; cert issues are captured as evidence by probe_tls
            # DNS-pinning transport (§9): every hop resolves + validates +
            # connects to the same address, closing the rebinding window.
            # It supersedes the response-hook redirect guard (kept as a
            # belt-and-braces check for the final URL).
            transport=SSRFPinningTransport(
                allow_private_networks=allow_private_networks, verify=False
            ),
            event_hooks={"response": [_redirect_guard(allow_private_networks)]},
        ) as client:
            # robots.txt
            robots_url = urljoin(url, "/robots.txt")
            try:
                resp = await client.get(
                    robots_url, headers={"User-Agent": USER_AGENTS["desktop_chrome"]}
                )
                if resp.status_code == 200:
                    result.robots_txt = resp.content[:MAX_ROBOTS_BYTES].decode(
                        resp.encoding or "utf-8", errors="replace"
                    )
            except (httpx.HTTPError, SSRFBlockedError) as exc:
                logger.debug("robots.txt probe failed: %s", exc)

            # Rotated-UA fetches (layer 7). The desktop-Chrome reference
            # fetch doubles as layer 6's full header capture.
            for ua_key in USER_AGENTS:
                variant, headers = await _fetch_raw(client, url, ua_key)
                result.ua_variants.append(variant)
                if ua_key == "desktop_chrome" and variant.error is None:
                    result.headers = headers
    except Exception as exc:
        # A constructor/transport failure degrades the whole probe, never
        # the scan.
        logger.warning("Metadata probe degraded: %s", str(exc)[:200])

    return result
