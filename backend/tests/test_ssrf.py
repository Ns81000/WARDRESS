"""SSRF guard unit tests (§9). Live network probing is out of scope
(manual-QA carve-out) — these exercise the validator in-process only."""

import pytest

from app.ssrf import SSRFBlockedError, assert_url_allowed

BLOCKED_URLS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/admin",
    "http://localhost/",
    "http://0.0.0.0/",
    "http://10.0.0.5/",
    "http://172.16.1.1/",
    "http://192.168.1.1/router",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fd00::1]/",
    "http://100.64.0.1/",  # CGNAT
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_blocked_by_default(url: str) -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_private_allowed_with_optin(url: str) -> None:
    assert_url_allowed(url, allow_private_networks=True)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "",
        "not a url at all",
    ],
)
def test_bad_schemes_rejected(url: str) -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed(url)


def test_bad_schemes_rejected_even_with_optin() -> None:
    # The opt-in relaxes address ranges only, never schemes.
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed("file:///etc/passwd", allow_private_networks=True)


def test_credentials_in_url_rejected() -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed("http://user:pass@example.com/")
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed("http://user:pass@example.com/", allow_private_networks=True)


def test_overlong_url_rejected() -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed("http://example.com/" + "a" * 3000)


def test_non_string_rejected() -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed(None)  # type: ignore[arg-type]


def test_multicast_reserved_blocked_even_with_optin() -> None:
    for url in ("http://224.0.0.1/", "http://240.0.0.1/"):
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed(url, allow_private_networks=True)


def test_unresolvable_host_rejected() -> None:
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed("http://this-host-does-not-exist.invalid/")


def test_public_ip_literal_allowed() -> None:
    # Documentation range 192.0.2.0/24 is is_global=False but also
    # reserved-adjacent; use a real public literal instead (no traffic is
    # sent — literal IPs skip DNS and only pass range checks).
    assert_url_allowed("http://93.184.216.34/")  # must not raise
