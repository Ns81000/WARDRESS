"""PROMPT-002 Phase 9 — CSP & header normalization for detection (layer 6).

Fix Phase 36's comparator already normalizes per-response CSP noise
UPSTREAM of the directional scoring: `_csp_directives` collapses nonce
blobs to the `'nonce-'` placeholder and lowercases/whitespace-splits
tokens before `_classify_value_change` ever compares the policies. This
module pins that behavior explicitly (the Phase 9 spec's "verify, then
build" branch) and closes the one gap the verification pass found: the
nonce-prefix match was case-SENSITIVE, while the CSP3 grammar (RFC 5234
ABNF literals) and every browser match `'nonce-` case-insensitively — so
a server emitting `'NONCE-<random>'` per response accrued undirected
evidence noise on every scan.

Also pinned here, per the spec's edge-case list:
- multi-directive policies where only nonces changed score 0.0;
- a nonce change WITH a real directive change still scores (directional
  scoring from Phase 36 works after normalization);
- CSP-Report-Only and CSP are different headers: switching between them
  is a real change (the enforcing policy disappearing scores 0.3);
- hashes and wildcards are NOT normalized — only nonces are;
- formatting noise (case, whitespace, semicolons) is silent;
- quoting differences are NOT normalized (conservative: an unquoted
  `self` is a host token, not the keyword — recorded honestly, unscored).
"""

from worker.detection.metadata import (
    _classify_value_change,
    _csp_directives,
    layer6_security_metadata,
)
from worker.detection.types import PageData, ScanPageData
from worker.hashing import content_sha256

HTML = "<html><body><h1>Acme Corp</h1><p>Reliable widgets.</p></body></html>"

BASE_HEADERS = {
    "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
    "strict-transport-security": "max-age=31536000",
    "x-frame-options": "DENY",
}


def _pair(b_headers, c_headers):
    kw = dict(tls=None, robots_txt="")
    b = PageData(html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML), **kw)
    c = ScanPageData(
        html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML), **kw
    )
    b.headers = b_headers
    c.headers = c_headers
    return b, c


def _hdr_evidence(result):
    return result["evidence"]["headers"]


def _assert_no_header_noise(result):
    ev = _hdr_evidence(result)
    for bucket in (
        "security_headers_removed",
        "security_headers_weakened",
        "security_headers_strengthened",
        "security_headers_changed",
        "security_headers_added",
    ):
        assert not ev.get(bucket), bucket


class TestCspNonceNormalization:
    def test_multi_directive_policy_only_nonces_changed_is_silent(self):
        """Nonce-only churn across a realistic multi-directive policy must
        vanish from every evidence bucket, not just score 0.0."""
        csp_base = (
            "default-src 'self'; script-src 'nonce-AAAA2222' 'strict-dynamic'; "
            "style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        csp_cur = (
            "default-src 'self'; script-src 'nonce-ZZZZ9999' 'strict-dynamic'; "
            "style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | {"content-security-policy": csp_base},
                BASE_HEADERS | {"content-security-policy": csp_cur},
            )
        )
        assert result["score"] == 0.0
        _assert_no_header_noise(result)

    def test_nonce_value_case_variance_is_equal(self):
        assert (
            _classify_value_change(
                "content-security-policy",
                "script-src 'nonce-AbCdEf0123'",
                "script-src 'nonce-ZyXwVu9876'",
            )
            == "equal"
        )

    def test_csp_directive_parser_collapses_nonce_with_uppercase_prefix(self):
        # CSP3 ABNF literals are case-insensitive and browsers match the
        # 'nonce-' prefix that way; the collapse must keep up or servers
        # emitting 'NONCE-...' accrue undirected evidence on every scan.
        dirs = _csp_directives("script-src 'NONCE-AAAbbb999'")
        assert dirs["script-src"] == frozenset({"'nonce-'"})

    def test_uppercase_nonce_prefix_variance_is_silent(self):
        csp_base = "default-src 'self'; script-src 'NONCE-AAAA2222'"
        csp_cur = "default-src 'self'; script-src 'NONCE-ZZZZ9999'"
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | {"content-security-policy": csp_base},
                BASE_HEADERS | {"content-security-policy": csp_cur},
            )
        )
        assert result["score"] == 0.0
        ev = _hdr_evidence(result)
        # Failing-before proof: pre-fix this bucket held the CSP entry.
        assert not ev.get("security_headers_changed")
        assert not ev.get("security_headers_weakened")

    def test_nonce_variance_does_not_mask_a_directive_removal(self):
        """Weaker precedence survives the unknown-token noise: dropping
        frame-ancestors must still score even when the nonce also churned
        with an uppercase prefix (pre-fix that churn read as undirected —
        'weaker' still wins the precedence, post-fix it reads as equal)."""
        csp_base = "default-src 'self'; frame-ancestors 'none'; script-src 'NONCE-AAAA2222'"
        csp_cur = "default-src 'self'; script-src 'NONCE-ZZZZ9999'"
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | {"content-security-policy": csp_base},
                BASE_HEADERS | {"content-security-policy": csp_cur},
            )
        )
        assert result["score"] == 0.1
        weakened = _hdr_evidence(result)["security_headers_weakened"]
        assert [e["header"] for e in weakened] == ["content-security-policy"]

    def test_nonce_change_with_directive_removal_scores_positive(self):
        base = {"content-security-policy": "default-src 'self'; frame-ancestors 'none'"}
        cur = {"content-security-policy": "default-src 'self'"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.1
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_weakened"]] == [
            "content-security-policy"
        ]

    def test_nonce_change_with_directive_removal_scores_with_churn_present(self):
        base = {
            "content-security-policy": (
                "default-src 'self'; frame-ancestors 'none'; script-src 'nonce-AAAA'"
            )
        }
        cur = {"content-security-policy": "default-src 'self'; script-src 'nonce-ZZZZ'"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.1
        assert _hdr_evidence(result)["security_headers_weakened"][0]["header"] == (
            "content-security-policy"
        )

    def test_nonce_change_with_directive_addition_recorded_strengthened(self):
        base = {"content-security-policy": "default-src 'self'"}
        cur = {
            "content-security-policy": (
                "default-src 'self'; script-src 'nonce-ZZZZ' 'strict-dynamic'"
            )
        }
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.0
        strengthened = _hdr_evidence(result)["security_headers_strengthened"]
        assert [e["header"] for e in strengthened] == ["content-security-policy"]
        # Evidence records the RAW values (nonce intact) for auditability.
        assert "'nonce-ZZZZ'" in strengthened[0]["current"]

    def test_wildcard_removal_is_real_signal_beside_nonce_churn(self):
        base = {"content-security-policy": "script-src 'nonce-AAAA' *"}
        cur = {"content-security-policy": "script-src 'nonce-ZZZZ'"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.1
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_weakened"]] == [
            "content-security-policy"
        ]

    def test_hash_values_are_never_collapsed(self):
        """Only nonces normalize: a swapped hash means the inline script
        changed — recorded honestly (undirected), never read as equal."""
        base = {"content-security-policy": "script-src 'sha256-AAAAQ=='"}
        cur = {"content-security-policy": "script-src 'sha256-ZZZZQQ=='"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.0
        undirected = _hdr_evidence(result)["security_headers_changed"]
        assert [e["header"] for e in undirected] == ["content-security-policy"]
        assert undirected[0]["baseline"] == "script-src 'sha256-AAAAQ=='"

    def test_identical_hash_beside_nonce_churn_stays_equal(self):
        base = {"content-security-policy": "script-src 'nonce-AAAA' 'sha256-QFRD=='"}
        cur = {"content-security-policy": "script-src 'nonce-ZZZZ' 'sha256-QFRD=='"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.0
        assert not _hdr_evidence(result).get("security_headers_changed")


class TestCspFormattingNoise:
    def test_case_whitespace_and_semicolons_are_silent(self):
        base = {"content-security-policy": "default-src 'self'; img-src 'self' data:"}
        cur = {"content-security-policy": "DEFAULT-SRC   'SELF' ;;\timg-src  'self'  data:  ;;"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.0
        _assert_no_header_noise(result)

    def test_trailing_semicolon_only_difference_is_equal(self):
        assert (
            _classify_value_change(
                "content-security-policy", "default-src 'self'", "default-src 'self'; "
            )
            == "equal"
        )

    def test_quoting_differences_are_recorded_not_normalized(self):
        """An unquoted `self` is a host token, not the keyword — quotes are
        NOT formatting noise. The difference is recorded honestly and
        never scored (conservative normalization, never masking)."""
        base = {"content-security-policy": "default-src 'self'"}
        cur = {"content-security-policy": "default-src self"}
        result = layer6_security_metadata(
            *_pair(
                BASE_HEADERS | base,
                BASE_HEADERS | cur,
            )
        )
        assert result["score"] == 0.0
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_changed"]] == [
            "content-security-policy"
        ]


class TestCspReportOnlyIsADifferentHeader:
    def test_enforcing_to_report_only_switch_is_a_real_removal(self):
        """Switching the enforcement header for a report-only one removes
        content-security-policy — that IS a real change, scored."""
        base = dict(BASE_HEADERS)
        cur = dict(BASE_HEADERS)
        cur["content-security-policy-report-only"] = cur.pop("content-security-policy")
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.3
        assert _hdr_evidence(result)["security_headers_removed"] == ["content-security-policy"]

    def test_report_only_to_enforcing_switch_records_addition(self):
        base = dict(BASE_HEADERS)
        base["content-security-policy-report-only"] = base.pop("content-security-policy")
        cur = dict(BASE_HEADERS)
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.0
        assert _hdr_evidence(result)["security_headers_added"] == ["content-security-policy"]

    def test_report_only_variance_beside_a_stable_policy_is_not_compared(self):
        """The report-only header is not in the tracked set: its per-response
        nonce churn never reaches the comparison; the enforcing policy is
        still diffed for real."""
        csp = "default-src 'self'"
        base = dict(
            BASE_HEADERS,
            **{"content-security-policy-report-only": "script-src 'nonce-AAAA'"},
        )
        cur = dict(
            BASE_HEADERS,
            **{"content-security-policy-report-only": "script-src 'nonce-ZZZZ'"},
        )
        base["content-security-policy"] = csp
        cur["content-security-policy"] = csp
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.0
        _assert_no_header_noise(result)



class TestOtherHeaderFormattingNoise:
    def test_referrer_policy_case_and_whitespace_is_silent(self):
        base = dict(BASE_HEADERS, **{"referrer-policy": "strict-origin-when-cross-origin"})
        cur = dict(BASE_HEADERS, **{"referrer-policy": "STRICT-ORIGIN-WHEN-CROSS-ORIGIN  "})
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.0
        assert not _hdr_evidence(result).get("security_headers_changed")

    def test_permissions_policy_spacing_and_case_is_silent(self):
        base = dict(BASE_HEADERS, **{"permissions-policy": "camera=(), geolocation=(self)"})
        cur = dict(BASE_HEADERS, **{"permissions-policy": "CAMERA=(),  GEOLOCATION=( self )"})
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.0
        assert not _hdr_evidence(result).get("security_headers_changed")

    def test_xcto_case_and_whitespace_is_silent(self):
        base = dict(BASE_HEADERS, **{"x-content-type-options": "nosniff"})
        cur = dict(BASE_HEADERS, **{"x-content-type-options": "  NOSNIFF "})
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.0
        assert not _hdr_evidence(result).get("security_headers_changed")


class TestDirectionalScoringIntactAfterNormalization:
    def test_hardening_recorded_despite_nonce_churn(self):
        base = {
            "content-security-policy": "default-src 'self'; script-src 'nonce-AAAA'",
            "strict-transport-security": "max-age=31536000",
            "x-frame-options": "DENY",
        }
        hardened = {
            "content-security-policy": (
                "default-src 'self'; script-src 'nonce-ZZZZ' 'strict-dynamic'; "
                "object-src 'none'"
            ),
            "strict-transport-security": "max-age=63072000; includeSubDomains",
            "x-frame-options": "DENY",
        }
        result = layer6_security_metadata(*_pair(base, hardened))
        assert result["score"] == 0.0
        ev = _hdr_evidence(result)
        assert {e["header"] for e in ev.get("security_headers_strengthened", [])} == {
            "content-security-policy",
            "strict-transport-security",
        }
        assert not ev.get("security_headers_weakened")

    def test_hsts_downgrade_scores_beside_csp_nonce_churn(self):
        base = {
            "content-security-policy": "default-src 'self'; script-src 'nonce-AAAA'",
            "strict-transport-security": "max-age=63072000",
        }
        cur = {
            "content-security-policy": "default-src 'self'; script-src 'nonce-ZZZZ'",
            "strict-transport-security": "max-age=600",
        }
        result = layer6_security_metadata(*_pair(base, cur))
        assert result["score"] == 0.1
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_weakened"]] == [
            "strict-transport-security"
        ]
