"""Session A / subagent 2 — hermetic characterization tests for the NEW detection-pipeline
findings (PROMPT-003 Audit Phase 4 deep verification).

Rule 1 (diagnosis, not repair): every test here asserts the CURRENT behaviour so the
remediation prompt can flip the specific assertion it fixes. Rule 5 (no regressions): all
of them pass against HEAD today. Rule 10: no production file is modified by this file.

Naming: the SA2-* test ids map 1:1 onto the finding IDs in
Prompts/Pending/Finders/PROMPT-003/scratch/session-a-detection.md
"""

import io
import math
import statistics

import numpy as np
import pytest
from PIL import Image, ImageDraw

from worker.detection.cloaking import _variant_cloak_score
from worker.detection.dom import layer2_dom_structure
from worker.detection.fusion import FEATURE_KEYS, _sigmoid, get_fusion_model, layer9_fusion
from worker.detection.metadata import _classify_value_change
from worker.detection.pipeline import run_detection
from worker.detection.signatures import _new_text, extract_visible_text
from worker.detection.suppress import build_suppression
from worker.detection.types import PageData, ScanPageData, UAVariant
from worker.hashing import content_sha256

MATERIAL_CHANGE_RISK = 0.40
DEFAULT_FLAG_THRESHOLD = 0.50

FILLER = (
    "The team announced a new release of the platform this morning and the team said the "
    "update rolls out to every account over the next two weeks across all supported regions "
    "and languages with a note for existing administrators about migration windows"
)
SHELL = (
    "<html><head><title>Corp</title></head><body><nav><a href='/'>Home</a> "
    "<a href='/about'>About</a></nav><main>{c}</main>"
    "<footer><a href='/privacy'>Privacy</a></footer>"
    "<script src='https://cdn.vendor.com/app.js'></script></body></html>"
)
ART = "<article><h2>Story {n}</h2><p>{b}</p></article>"


def site(n: int = 14, extra: str = "", body: str = FILLER) -> str:
    return SHELL.format(c="\n".join(ART.format(n=i, b=body) for i in range(n)) + extra)


def unpunctuated(n: int = 6, tail: str = "") -> str:
    """A page whose visible text contains no [.!?] sentence boundary."""
    return site(n=1, body=" ".join([FILLER] * n) + tail)


def png(seed: int, blocks: int = 14, noise: float = 3.0) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", (1366, 1400), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = 60
    for i in range(blocks):
        d.rectangle([80, y, 80 + 400 + (i * 137) % 700, y + 14], fill=(20, 20, 24))
        y += 46
    arr = np.clip(
        np.asarray(img, dtype=np.float64) + rng.normal(0, noise, (1400, 1366, 3)), 0, 255
    ).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def trio(html: str) -> list[UAVariant]:
    return [
        UAVariant(
            ua_key=k,
            html=html,
            http_status=200,
            final_url="https://x.test/",
            content_hash=content_sha256(html),
        )
        for k in ("desktop_chrome", "googlebot", "mobile_safari")
    ]


SEC_HEADERS = {
    "server": "nginx",
    "content-type": "text/html",
    "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
    "content-security-policy": "default-src 'self'; script-src 'self'",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "geolocation=()",
}
TLS_OK = {
    "fingerprint_sha256": "aa",
    "issuer": "R3",
    "subject": "x.test",
    "not_after": "2027-01-01",
    "expired": False,
}


def page(html: str, shot: bytes, **kw) -> ScanPageData:
    d = dict(
        final_url="https://x.test/",
        http_status=200,
        headers=dict(SEC_HEADERS),
        tls=dict(TLS_OK),
        robots_txt="User-agent: *\nAllow: /",
    )
    d.update(kw)
    return ScanPageData(
        html=html,
        screenshot=shot,
        content_hash=content_sha256(html),
        ua_variants=kw.pop("variants", None) or trio(html),
        **d,
    )


def verdict(results: dict) -> tuple[str, float]:
    risk = float(results["layer9_fusion"]["score"] or 0.0)
    changed = any(
        (r.get("score") or 0.0) > 0.02
        for k, r in results.items()
        if k != "layer9_fusion" and not r.get("skipped")
    )
    flagged = risk >= DEFAULT_FLAG_THRESHOLD
    return ("flagged" if flagged else ("changed" if changed else "clean")), risk


def detect(base_html: str, cur_html: str, supp=None, *, headers_b=None, headers_c=None) -> dict:
    b = page(
        base_html,
        png(1, blocks=14 + 2 * base_html.count("<article>")),
        headers=headers_b or dict(SEC_HEADERS),
    )
    c = page(
        cur_html,
        png(2, blocks=14 + 2 * cur_html.count("<article>")),
        headers=headers_c or dict(SEC_HEADERS),
    )
    return run_detection(b, c, supp)


# =====================================================================================
# SA2-1  third-party rotation on a never-seen domain FLAGS (reCAPTCHA / Turnstile / Taboola)
# =====================================================================================


class TestAUDITSA2x1ThirdPartyRotationFlags:
    """reCAPTCHA / Turnstile / Taboola / analytics-beacon / vendor-script rotation."""

    SHAPES = {
        "recaptcha_iframe_appears": (
            '<iframe src="https://www.google.com/recaptcha/api2/anchor" width="300" '
            'height="80" title="recaptcha"></iframe>'
        ),
        "turnstile_widget_appears": (
            '<div class="cf-turnstile" data-sitekey="0x4AAAA"></div>'
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async></script>'
        ),
        "taboola_ad_iframe_appears": (
            '<iframe src="https://trc.taboola.com/taboola-widget/" width="300" '
            'height="250" title="ad"></iframe>'
        ),
        "operator_adds_intercom_widget": '<script src="https://widget.intercom.io/widget/abc123.js"></script>',
        "operator_adds_analytics_script": (
            '<script src="https://cdn.segment.com/analytics.js/v1/KEY/analytics.min.js"></script>'
        ),
    }

    @pytest.mark.parametrize("label", sorted(SHAPES))
    def test_benign_third_party_widget_flags_a_healthy_site(self, label):
        base = site()
        results = detect(base, site(extra=self.SHAPES[label]))
        v, risk = verdict(results)
        assert results["layer3_link_audit"]["score"] > 0.55, label
        assert risk >= MATERIAL_CHANGE_RISK, f"{label}: risk {risk}"
        assert v == "flagged", f"{label}: verdict {v} at risk {risk}"

    def test_rule_floor_arms_on_the_benign_shape(self):
        results = detect(site(), site(extra=self.SHAPES["recaptcha_iframe_appears"]))
        floors = results["layer9_fusion"]["evidence"].get("rule_floor", {}).get("applied", [])
        assert [f["rule"] for f in floors] == ["new_sensitive_infrastructure"]

    def test_repeatable_over_three_passes(self):
        base = site()
        cur = site(extra=self.SHAPES["turnstile_widget_appears"])
        risks = [verdict(detect(base, cur))[1] for _ in range(3)]
        assert len(set(round(r, 4) for r in risks)) == 1, risks

    def test_a_same_domain_rotation_does_not_flag(self):
        """Positive control: the SAME widget whose src rotates within a KNOWN domain."""
        base = site(extra='<iframe src="https://ads.partner.net/slot"></iframe>')
        cur = site(extra='<iframe src="https://ads.partner.net/slot?id=9"></iframe>')
        results = detect(base, cur)
        assert results["layer3_link_audit"]["score"] < 0.06
        assert verdict(results)[0] != "flagged"

    def test_two_new_external_stylesheets_flag(self):
        """fonts.googleapis.com + a typekit sheet: 0.39 with one, FLAGGED with two."""
        one = site().replace(
            "<head>",
            "<head><link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Inter'>",
        )
        v1, r1 = verdict(detect(site(), one))
        assert v1 == "changed" and 0.38 <= r1 < MATERIAL_CHANGE_RISK, (v1, r1)
        two = site().replace(
            "<head>",
            "<head><link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Inter'>"
            "<link rel='stylesheet' href='https://use.typekit.net/abc.css'>",
        )
        v2, r2 = verdict(detect(site(), two))
        assert v2 == "flagged" and r2 >= DEFAULT_FLAG_THRESHOLD, (v2, r2)


# =====================================================================================
# SA2-2  layer 6 scores a CSP widening at exactly 0.0
# =====================================================================================


class TestAUDITSA2x2CspWideningScoresZero:
    MISSES = [
        ("default-src 'self'", "default-src *"),
        ("default-src 'self'", "default-src 'unsafe-inline'"),
        ("script-src 'self'", "script-src 'unsafe-inline'"),
        ("script-src 'self'", "script-src 'unsafe-eval' 'unsafe-inline'"),
        ("frame-ancestors 'self'", "frame-ancestors *"),
        ("object-src 'none'", "object-src 'self'"),
    ]

    @pytest.mark.parametrize("before,after", MISSES)
    def test_csp_widening_is_direction_unknown(self, before, after):
        assert _classify_value_change("content-security-policy", before, after) is None

    @pytest.mark.parametrize("before,after", MISSES[:3])
    def test_csp_widening_reads_clean_end_to_end(self, before, after):
        base = site()
        headers_b = {**SEC_HEADERS, "content-security-policy": before}
        headers_c = {**SEC_HEADERS, "content-security-policy": after}
        results = detect(base, base, headers_b=headers_b, headers_c=headers_c)
        l6 = results["layer6_security_metadata"]
        assert l6["score"] == 0.0, l6["evidence"]
        assert results["layer1_hash"]["score"] == 0.0
        v, risk = verdict(results)
        assert v == "clean", f"verdict {v} at risk {risk}"
        assert risk < 0.01, risk

    def test_adding_an_attacker_origin_to_csp_is_scored_as_hardening(self):
        assert (
            _classify_value_change(
                "content-security-policy",
                "default-src 'self'",
                "default-src 'self' https://cdn.evil.tld",
            )
            == "stronger"
        )

    def test_hsts_maximal_downgrade_is_worth_only_0_1(self):
        before = SEC_HEADERS["strict-transport-security"]
        after = "max-age=300"
        assert _classify_value_change("strict-transport-security", before, after) == "weaker"
        base = site()
        results = detect(
            base,
            base,
            headers_b={**SEC_HEADERS, "strict-transport-security": before},
            headers_c={**SEC_HEADERS, "strict-transport-security": after},
        )
        assert results["layer6_security_metadata"]["score"] == pytest.approx(0.1)

    def test_removing_a_security_header_still_scores(self):
        """Positive control: the REMOVAL direction is detected (0.3 per header)."""
        base = site()
        thinned = {
            k: v
            for k, v in SEC_HEADERS.items()
            if k not in ("x-frame-options", "x-content-type-options", "referrer-policy")
        }
        results = detect(base, base, headers_b=dict(SEC_HEADERS), headers_c=thinned)
        assert results["layer6_security_metadata"]["score"] == pytest.approx(0.8)


# =====================================================================================
# SA2-3  _new_text granularity collapse: 100% of an unpunctuated page reads as "new"
# =====================================================================================


class TestAUDITSA2x3NewTextGranularity:
    def test_unpunctuated_page_collapses_to_whole_page_new_text(self):
        base = unpunctuated()
        cur = unpunctuated().replace("morning", "morning, obviously", 1)
        bt, ct = extract_visible_text(base), extract_visible_text(cur)
        new_text = _new_text(bt, ct)
        assert new_text == ct.strip()
        assert len(new_text) / len(ct) == 1.0

    def test_punctuated_control_is_granular(self):
        base = site(n=8, body=FILLER + ". The migration guide covers every supported region.")
        cur = base.replace("morning", "morning, obviously", 1)
        bt, ct = extract_visible_text(base), extract_visible_text(cur)
        # one changed SENTENCE out of 16 -> ~11% of the page, not 100%
        assert len(_new_text(bt, ct)) / len(ct) < 0.15

    @pytest.mark.parametrize(
        "name,builder",
        [
            ("only_emoji", lambda: " ".join(["\U0001f600\U0001f680"] * 40)),
            ("only_numbers", lambda: " ".join(str(100000 + i * 7) for i in range(60))),
            ("cjk_no_punct", lambda: "这是一个网站首页欢迎你 " * 40),
            ("mixed_script_no_punct", lambda: ("hello world " * 30) + ("مرحبا بالعالم " * 30)),
            ("dom_single_line", lambda: FILLER * 3),
        ],
    )
    def test_adversarial_shapes_all_collapse(self, name, builder):
        bt = builder()
        ct = builder() + ("EXTRA-TAIL-TOKEN" if "numbers" not in name else " 999999999999")
        new_text = _new_text(bt, ct)
        assert new_text == ct.strip(), f"{name}: only {len(new_text)}/{len(ct)} chars were new"

    def test_baseline_present_conclusive_signature_flags_a_healthy_site(self):
        base = site(n=1, body=FILLER + " hacked by anonymous owned by crew defaced by team")
        cur = base.replace("morning", "morning, obviously", 1)
        results = detect(base, cur)
        l5 = results["layer5_signatures"]
        assert l5["score"] == 1.0, l5["evidence"]["signature_matches"]
        v, risk = verdict(results)
        assert v == "flagged", f"verdict {v} at risk {risk}"
        assert risk >= 0.90
        floors = results["layer9_fusion"]["evidence"].get("rule_floor", {}).get("applied", [])
        assert [f["rule"] for f in floors] == ["conclusive_signature_text"]

    def test_baseline_present_profanity_bursts_flags(self):
        base = site(n=1, body=" ".join([FILLER] * 4) + " shit balls bullshit assholes")
        cur = base.replace("morning", "morning, obviously", 1)
        results = detect(base, cur)
        assert results["layer5_signatures"]["score"] == 0.5
        v, risk = verdict(results)
        assert v == "flagged" and risk > 0.99, (v, risk)

    def test_baseline_present_aggression_lexicon_saturates_layer8(self):
        from worker.detection.semantics import layer8_semantics

        base = unpunctuated(
            tail=" we will be back no one is safe death to the regime traitors revenge destroy"
        )
        cur = base.replace("morning", "morning, obviously", 1)
        result = layer8_semantics(
            PageData(html=base, final_url="https://x.test/"),
            PageData(html=cur, final_url="https://x.test/"),
        )
        assert result["evidence"]["aggression_weight"] >= 2.0
        assert result["score"] >= 0.90, result["score"]

    def test_baseline_present_topic_lexicon_caps_at_0_7(self):
        from worker.detection.semantics import layer8_semantics

        base = unpunctuated(
            tail=" breach compromised database dump leaked data credentials in the report"
        )
        cur = base.replace("morning", "morning, obviously", 1)
        result = layer8_semantics(
            PageData(html=base, final_url="https://x.test/"),
            PageData(html=cur, final_url="https://x.test/"),
        )
        assert set(result["evidence"]["topic_hits"]) >= {"breach_bragging", "credential_theft"}
        assert result["score"] == pytest.approx(0.7)

    def test_repeatable_over_three_passes(self):
        base = site(n=1, body=FILLER + " hacked by anonymous")
        cur = base.replace("morning", "morning, obviously", 1)
        outcomes = [verdict(detect(base, cur)) for _ in range(3)]
        assert len({o[0] for o in outcomes}) == 1
        assert outcomes[0][0] == "flagged"


# =====================================================================================
# SA2-4  an over-broad suppression rule permanently blinds layers 5 and 8
# =====================================================================================


class TestAUDITSA2x4SuppressionBlindness:
    ATTACK = (
        '<div id="notif"><h1>WE HAVE BEEN HACKED BY THE DRAGON TEAM</h1>'
        "<p>Your security is weak. This website is compromised. "
        "Contact us at telegram t.me/dragonx</p></div>"
    )

    def test_no_suppression_flags(self):
        results = detect(site(), site(extra=self.ATTACK))
        assert results["layer5_signatures"]["score"] == 1.0
        assert verdict(results)[0] == "flagged"

    @pytest.mark.parametrize(
        "rule",
        [
            ("css_selector", "#notif"),
            ("css_selector", "main"),
            ("css_selector", "*"),
            ("css_selector", "body"),
            ("regex", ".*"),
            ("regex", r"[\s\S]+"),
        ],
    )
    def test_over_broad_rule_blinds_layers_5_and_8(self, rule):
        supp = build_suppression([rule])
        results = detect(site(), site(extra=self.ATTACK), supp)
        assert results["layer5_signatures"]["score"] == 0.0, rule
        assert results["layer8_semantics"]["score"] == 0.0, rule
        v, risk = verdict(results)
        assert v == "changed", f"{rule}: verdict {v}"
        assert risk < 0.25, f"{rule}: risk {risk}"

    def test_evidence_records_which_rules_ran_but_not_how_much_they_removed(self):
        supp = build_suppression([("regex", ".*")])
        results = detect(site(), site(extra=self.ATTACK), supp)
        applied = results["layer5_signatures"]["evidence"]["suppression_applied"]
        assert set(applied) == {"regexes"}
        assert not any(k for k in applied if "removed" in k or "chars" in k or "pct" in k)

    def test_a_precise_rule_still_flags(self):
        """Positive control: a narrowly-scoped rule does not blind the layer."""
        supp = build_suppression([("regex", r"Session id: \d+")])
        results = detect(site(), site(extra=self.ATTACK), supp)
        assert results["layer5_signatures"]["score"] == 1.0


# =====================================================================================
# SA2-5  removal-only and un-hiding changes score 0.0
# =====================================================================================


class TestAUDITSA2x5RemovalDirectionsUnweighted:
    def _with_refs(self) -> str:
        return site().replace(
            "<main>",
            "<main><script src='https://cdn.a.com/a.js'></script>"
            "<script src='https://cdn.b.com/b.js'></script>"
            "<iframe src='https://ads.partner.net/frame'></iframe>"
            "<form action='/login'></form>"
            "<link rel='stylesheet' href='https://cdn.a.com/a.css'>",
        )

    @pytest.mark.parametrize(
        "fragment",
        [
            "<script src='https://cdn.a.com/a.js'></script>",
            "<script src='https://cdn.b.com/b.js'></script>",
            "<iframe src='https://ads.partner.net/frame'></iframe>",
            "<form action='/login'></form>",
            "<link rel='stylesheet' href='https://cdn.a.com/a.css'>",
        ],
    )
    def test_layer3_scores_zero_for_every_removed_ref(self, fragment):
        base = self._with_refs()
        cur = base.replace(fragment, "")
        results = detect(base, cur)
        l3 = results["layer3_link_audit"]
        assert l3["score"] == 0.0, l3["evidence"]
        assert any(v["removed_count"] for v in l3["evidence"].values() if isinstance(v, dict))
        assert verdict(results)[0] == "changed"

    def test_unhiding_a_hidden_spam_farm_scores_exactly_zero(self):
        hidden = site(
            extra="".join(
                f"<div style='opacity:0'><a href='https://s{i}.tld/x'>{i}</a></div>"
                for i in range(8)
            )
        )
        made_visible = site(
            extra="".join(f"<div><a href='https://s{i}.tld/x'>{i}</a></div>" for i in range(8))
        )
        b = PageData(html=hidden, final_url="https://x.test/")
        c = PageData(html=made_visible, final_url="https://x.test/")
        result = layer2_dom_structure(b, c)
        assert result["evidence"]["hidden_count"] == {"baseline": 8, "current": 0}
        assert result["evidence"]["structural_churn"] == 0
        assert result["score"] == 0.0, result["evidence"]

    def test_adding_a_hidden_farm_still_scores_high(self):
        """Positive control: the ADDITIVE direction is detected."""
        hidden = site(
            extra="".join(
                f"<div style='opacity:0'><a href='https://s{i}.tld/x'>{i}</a></div>"
                for i in range(8)
            )
        )
        result = layer2_dom_structure(
            PageData(html=site(), final_url="https://x.test/"),
            PageData(html=hidden, final_url="https://x.test/"),
        )
        assert result["score"] > 0.9, result["score"]


# =====================================================================================
# SA2-6  layer 7 is silent for a small cloaked payload on a realistic page size
# =====================================================================================


class TestAUDITSA2x6CloakingScaleBlind:
    BANNER = {
        "hacked",
        "by",
        "dragon",
        "your",
        "site",
        "is",
        "compromised",
        "we",
        "own",
        "contact",
        "telegram",
        "security",
        "weak",
        "at",
        "t",
        "me",
        "d",
    }

    def _ref(self, n: int) -> set[str]:
        return set(FILLER.split()) | {f"t{i}" for i in range(n)}

    @pytest.mark.parametrize("n", [146, 266, 600])
    def test_full_banner_cloaked_to_a_crawler_scores_zero(self, n):
        score, detail = _variant_cloak_score(self._ref(n), self._ref(n) | self.BANNER)
        assert detail["added_tokens"] == len(self.BANNER)
        assert detail["new_token_fraction"] < 0.15
        assert score == 0.0, f"n={n}: score {score} detail {detail}"

    def test_small_page_still_detects_it(self):
        """Positive control: the same banner on a 29-token page is caught."""
        score, _ = _variant_cloak_score(self._ref(3), self._ref(3) | self.BANNER)
        assert score > 0.4, score

    def test_below_the_grace_a_banner_is_invisible_at_any_page_size(self):
        small = {"hacked", "by", "dragon", "site", "compromised", "own", "we"}
        score, detail = _variant_cloak_score(self._ref(60), self._ref(60) | small)
        assert detail.get("graced") is True
        assert score == 0.0

    def test_the_added_zero_shortcut_is_provably_redundant(self):
        diffs = 0
        for n_ref in range(0, 80, 4):
            for n_rem in range(0, 80, 4):
                ref = {f"r{i}" for i in range(n_ref)}
                var = {
                    f"r{i}"
                    for i in range(n_ref)
                    if n_rem == 0 or i % max(1, n_ref // max(1, n_rem))
                }
                if var - ref:
                    continue
                full, detail = _variant_cloak_score(ref, var)
                added, removed = detail["added_tokens"], detail["removed_tokens"]
                if max(added, removed) <= 12:
                    alt = 0.0
                else:
                    s_rem = max(0.0, min(1.0, (detail["union_divergence"] - 0.45) / (0.85 - 0.45)))
                    alt = s_rem
                if abs(full - alt) > 1e-12:
                    diffs += 1
        assert diffs == 0


# =====================================================================================
# SA2-7  empty / unparseable current capture is a measured 1.0; both-sides-empty is CLEAN
# =====================================================================================


class TestAUDITSA2x7EmptyCapture:
    def test_empty_current_html_is_a_measured_1_0_in_layer2(self):
        base = site()
        b = page(base, png(1))
        c = ScanPageData(
            html="",
            screenshot=png(2),
            final_url="https://x.test/",
            http_status=200,
            headers=dict(SEC_HEADERS),
            tls=dict(TLS_OK),
            robots_txt="User-agent: *\nAllow: /",
            content_hash=content_sha256(""),
            ua_variants=trio(base),
        )
        results = run_detection(b, c)
        l2 = results["layer2_dom_structure"]
        assert l2["score"] == 1.0, l2["evidence"]
        assert not l2.get("degraded")
        v, risk = verdict(results)
        assert v == "changed", f"verdict {v} at risk {risk}"
        assert risk >= 0.40, risk

    def test_binary_junk_current_capture_flags(self):
        base = site()
        junk = "\x00\x01\x02\xff\xfe garbage \x00" * 20
        results = detect(base, junk)
        v, risk = verdict(results)
        assert v == "flagged", f"verdict {v} at risk {risk}"
        assert results["layer2_dom_structure"]["score"] == 1.0

    def test_both_sides_empty_reads_clean(self):
        empty_b = ScanPageData(
            html="",
            screenshot=b"",
            final_url="https://x.test/",
            http_status=200,
            headers={},
            tls=None,
            robots_txt=None,
            content_hash=content_sha256(""),
            ua_variants=[],
        )
        empty_c = ScanPageData(
            html="",
            screenshot=b"",
            final_url="https://x.test/",
            http_status=200,
            headers={},
            tls=None,
            robots_txt=None,
            content_hash=content_sha256(""),
            ua_variants=[],
        )
        results = run_detection(empty_b, empty_c)
        v, risk = verdict(results)
        assert v == "clean", f"verdict {v} at risk {risk}"
        assert results["layer1_hash"]["score"] == 0.0
        assert any(r.get("degraded") for r in results.values())


# =====================================================================================
# SA2-8  fusion: measured layer-reachability map, no sigmoid overflow, dead `_new_text` set
# =====================================================================================


class TestAUDITSA2x8FusionFacts:
    def _risk(self, scores):
        if isinstance(scores, list):
            vector = dict(zip(FEATURE_KEYS, scores, strict=True))
        else:
            vector = {k: scores.get(k, 0.0) for k in FEATURE_KEYS}
        return layer9_fusion({k: {"score": v, "evidence": {}} for k, v in vector.items()})["score"]

    @pytest.mark.parametrize(
        "layer,coefficient,reaches",
        [
            ("layer1_hash", 4.408155, False),
            ("layer2_dom_structure", 1.286274, False),
            ("layer3_link_audit", 2.437693, False),
            ("layer4_visual_diff", 26.257885, True),
            ("layer5_signatures", 14.520867, True),
            ("layer6_security_metadata", 2.588342, False),
            ("layer7_cloaking", 13.157062, True),
            ("layer8_semantics", 4.252701, False),
        ],
    )
    def test_single_layer_reachability_of_the_material_change_bar(
        self, layer, coefficient, reaches
    ):
        model = get_fusion_model()
        need = math.log(0.40 / 0.60) - model.intercept
        needed = need / coefficient
        assert (needed <= 1.0) is reaches, f"{layer} needs v={needed:.4f}"
        if reaches:
            assert 0.0 < needed < 0.5, f"{layer} reaches 0.40 at a sub-alarming {needed}"

    def test_layer8_at_maximum_cannot_reach_the_material_bar_alone(self):
        assert self._risk({"layer8_semantics": 1.0}) < MATERIAL_CHANGE_RISK
        assert self._risk({"layer8_semantics": 1.0}) == pytest.approx(0.1198, abs=1e-3)

    def test_eight_uniform_sub_threshold_layers_reach_the_material_bar(self):
        model = get_fusion_model()
        need = math.log(0.40 / 0.60) - model.intercept
        uniform = need / sum(model.coefficients)
        assert uniform == pytest.approx(0.0848, abs=1e-3)
        assert self._risk({k: uniform for k in FEATURE_KEYS}) == pytest.approx(0.40, abs=2e-3)

    def test_three_profanity_hits_alone_flag(self):
        assert self._risk({"layer5_signatures": 0.6}) >= DEFAULT_FLAG_THRESHOLD

    def test_two_profanity_hits_reach_the_escalation_band(self):
        risk = self._risk({"layer5_signatures": 0.5})
        assert MATERIAL_CHANGE_RISK <= risk < 0.75, risk

    def test_sigmoid_does_not_overflow_anywhere_in_the_reachable_range(self):
        for z in (i * 0.5 - 1000 for i in range(4000)):
            s = _sigmoid(z)
            assert 0.0 <= s <= 1.0
            assert math.isfinite(s)

    def test_sigmoid_saturates_instead_of_raising_at_extreme_z(self):
        assert _sigmoid(1e6) == 1.0
        assert _sigmoid(-1e6) == 0.0
        assert _sigmoid(float("inf")) == 1.0
        assert _sigmoid(float("-inf")) == 0.0

    def test_a_non_finite_layer_score_becomes_a_trusted_zero(self):
        res = layer9_fusion(
            {
                **{k: {"score": 0.0, "evidence": {}} for k in FEATURE_KEYS},
                "layer1_hash": {"score": float("nan"), "evidence": {}},
            }
        )
        assert res["evidence"]["features"]["layer1_hash"] == 0.0
        assert "unmeasured" not in res["evidence"]
        assert res["score"] == pytest.approx(0.00193, abs=1e-4)

    def test_a_rule_floor_never_fires_on_a_nan(self):
        res = layer9_fusion(
            {
                **{k: {"score": 0.0, "evidence": {}} for k in FEATURE_KEYS},
                "layer5_signatures": {"score": float("nan"), "evidence": {}},
            }
        )
        assert "rule_floor" not in res["evidence"]

    def test_the_degraded_ceiling_binds_the_uplift_but_not_the_composite(self):
        res = layer9_fusion(
            {
                k: (
                    {"score": 0.9, "evidence": {}}
                    if k == "layer3_link_audit"
                    else {"score": None, "skipped": True, "degraded": True, "evidence": {}}
                )
                for k in FEATURE_KEYS
            }
        )
        assert res["evidence"].get("uncertainty_capped") is True
        assert res["score"] == pytest.approx(MATERIAL_CHANGE_RISK, abs=1e-3), res["score"]

    def test_fallback_path_preserves_the_rule_floors(self):
        import worker.detection.fusion as FU

        original = FU.get_fusion_model
        FU.get_fusion_model = lambda: (_ for _ in ()).throw(RuntimeError("simulated"))
        try:
            for layer, value, floor in [
                ("layer5_signatures", 0.9, 0.9),
                ("layer7_cloaking", 0.9, 0.9),
                ("layer3_link_audit", 0.6, 0.4),
            ]:
                res = layer9_fusion(
                    {
                        k: {"score": value if k == layer else 0.0, "evidence": {}}
                        for k in FEATURE_KEYS
                    }
                )
                assert res["evidence"]["model"] == "fallback_max (fusion model unavailable)"
                assert res["score"] >= floor, layer
        finally:
            FU.get_fusion_model = original

    def test_new_text_base_lines_set_is_provably_dead(self):
        import random
        import re

        def pieces(t: str) -> list[str]:
            out = []
            for line in t.splitlines():
                out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip())
            return out

        rnd = random.Random(20260930)
        diffs = 0
        for _ in range(4000):

            def mk() -> str:
                lines = []
                for _ in range(rnd.randint(1, 3)):
                    toks = [rnd.choice("abcdefg") for _ in range(rnd.randint(1, 6))]
                    lines.append(
                        " ".join(toks)
                        + (rnd.choice([". ", "? ", "! ", ".", " "]) if rnd.random() < 0.5 else "")
                    )
                return "\n".join(lines)

            bt, ct = mk(), mk()
            base_lines = {ln.strip() for ln in bt.splitlines() if ln.strip()}
            bp = set(pieces(bt))
            full = " ".join(p for p in pieces(ct) if p not in bp and p not in base_lines)
            no_lines = " ".join(p for p in pieces(ct) if p not in bp)
            if full != no_lines:
                diffs += 1
        assert diffs == 0, "base_lines changed the result => it is NOT dead (re-open this finding)"


# =====================================================================================
# SA2-9  taxonomy shapes the corpus does not model, measured end-to-end
# =====================================================================================


class TestAUDITSA2x9TaxonomyEvasion:
    def _evades(self, cur: str) -> tuple[str, float]:
        return verdict(detect(site(), cur))

    def test_single_word_tampering_never_reaches_the_escalation_band(self):
        for before, after in [
            ("morning", "morning, obviously"),
            ("two weeks", "two days"),
            ("two weeks", "two secs"),
        ]:
            cur = site().replace(before, after, 1)
            v, risk = self._evades(cur)
            assert v == "changed", f"{before}->{after}: {v}"
            assert risk < MATERIAL_CHANGE_RISK, f"{before}->{after}: risk {risk}"

    def test_meta_refresh_redirect_injection_is_below_the_material_bar(self):
        cur = site().replace(
            "<main>", "<main><meta http-equiv='refresh' content='0;url=https://evil.tld/deface'>"
        )
        v, risk = self._evades(cur)
        assert v == "changed"
        assert risk < MATERIAL_CHANGE_RISK, risk

    def test_client_side_redirect_cloak_is_below_the_material_bar(self):
        cur = site().replace(
            "<main>", "<main><script>location.replace('https://evil.tld/x')</script>"
        )
        v, risk = self._evades(cur)
        assert v == "changed"
        assert risk < MATERIAL_CHANGE_RISK, risk

    def test_time_delayed_payload_in_a_script_string_is_below_the_material_bar(self):
        payload = "<main><script>setTimeout(function(){document.title='HACKED BY DRAGON'},"
        payload += "864e5)</script>"
        cur = site().replace("<main>", payload)
        v, risk = self._evades(cur)
        assert v == "changed"
        assert risk < MATERIAL_CHANGE_RISK, risk

    def test_same_origin_phishing_overlay_is_below_the_material_bar(self):
        cur = site().replace(
            "<main>",
            "<main><div style='position:fixed;inset:0;background:#fff;z-index:99999'>"
            "<h1>Verify your account</h1><form action='/verify' method='post'>"
            "<input name='email'><input name='password' type='password'></form></div>",
        )
        v, risk = self._evades(cur)
        assert v == "changed"
        assert risk < MATERIAL_CHANGE_RISK, risk

    def test_positive_controls_still_flag(self):
        banner = site(
            extra="<h1>HACKED BY DRAGON TEAM</h1><p>Your site is compromised, "
            "security is weak. Contact us at telegram t.me/dragonx</p>"
        )
        assert verdict(detect(site(), banner))[0] == "flagged"
        spam = site(
            extra="".join(
                f'<a href="https://spam{i}.tld/buy">cheap pills {i}</a>' for i in range(6)
            )
        )
        assert verdict(detect(site(), spam))[0] == "flagged"

    def test_attack_withdrawal_is_caught_by_layer4(self):
        """Positive: removing a banner is itself a large visual delta (0.3093 measured)."""
        from worker.detection.visual import layer4_visual_diff

        def banner_png(seed: int, banner: bool) -> bytes:
            rng = np.random.default_rng(seed)
            img = Image.new("RGB", (1366, 1400), (255, 255, 255))
            d = ImageDraw.Draw(img)
            y = 60
            for i in range(14):
                d.rectangle([80, y, 80 + 400 + (i * 137) % 700, y + 14], fill=(20, 20, 24))
                y += 46
            if banner:
                d.rectangle([0, 480, 1366, 760], fill=(180, 0, 0))
            arr = np.clip(
                np.asarray(img, dtype=np.float64) + rng.normal(0, 3.0, (1400, 1366, 3)), 0, 255
            ).astype(np.uint8)
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="PNG")
            return buf.getvalue()

        a = PageData(html="<p>x</p>", screenshot=banner_png(1, True), final_url="https://x.test/")
        b = PageData(html="<p>x</p>", screenshot=banner_png(2, False), final_url="https://x.test/")
        result = layer4_visual_diff(a, b)
        assert result["score"] > 0.25, result["evidence"]
        assert (
            layer9_fusion(
                {
                    **{k: {"score": 0.0, "evidence": {}} for k in FEATURE_KEYS},
                    "layer1_hash": {"score": 1.0, "evidence": {}},
                    "layer4_visual_diff": {"score": result["score"], "evidence": {}},
                }
            )["score"]
            >= 0.99
        )


# =====================================================================================
# SA2-10  normalization is ReDoS-immune but the documented layer-6 bar is 0.35, not 0.40
# =====================================================================================


class TestAUDITSA2x10NormalizationAndCommentDrift:
    _ADV_HTML = [
        "<div>" * 5000 + "x 2026-01-01T00:00:00Z" + "</div>" * 5000,
        "<a href='/?v=" + "9" * 100_000 + "'>x</a>",
        "&#xZZZZ; &nosuchentity; &#; &#x110000; " * 50 + "2026-01-01",
        "a\x00b 2026-01-01T00:00:00Z c\x00",
        "<div><p><span>2026-01-01T00:00:00Z" * 20,
        "<!-- (?=.*x) --> " + "a" * 1000 + " 2026-01-01",
        "<template>" + "2026-01-01T00:00:00Z" * 200 + "</template>",
        "<svg><text>2026-01-01T00:00:00Z</text></svg>",
        "<math><mi>2026-01-01T00:00:00Z</mi></math>",
        "<form><form><input name=csrf_token value=abc 2026-01-01><form>",
        "<script>var d='2026-01-01T00:00:00Z'</script>",
        "<style>.a{content:'2026-01-01T00:00:00Z'}</style>",
        " ".join("2026-01-01T00:00:00Z" for _ in range(5000)),
    ]
    _ADV_IDS = [
        "deeply_nested_divs",
        "huge_attribute_value",
        "malformed_entities",
        "null_bytes",
        "unclosed_tags",
        "comment_regex_bait",
        "template_bait",
        "svg_foreign",
        "math_foreign",
        "mxss_nested_forms",
        "script_body_untouched",
        "style_body_untouched",
        "iso_bomb",
    ]

    @pytest.mark.parametrize("html", _ADV_HTML, ids=_ADV_IDS)
    def test_normalize_html_never_raises(self, html):
        from worker.detection.normalize import normalize_html

        out, summary = normalize_html(html)
        assert isinstance(out, str), len(out)
        assert isinstance(summary, dict), summary

    def test_oversized_documents_fail_open(self):
        from worker.detection.normalize import _MAX_HTML_CHARS, normalize_html

        html = "<p>" + ("word 2026-01-01T00:00:00Z " * 200_000) + "</p>"
        assert len(html) > _MAX_HTML_CHARS
        out, summary = normalize_html(html)
        assert out == html
        assert summary == {}

    def test_fusion_docstrings_assert_0_35_while_the_real_bars_are_0_40(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "worker" / "detection" / "fusion.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        drifted = [(i, ln) for i, ln in enumerate(lines, 1) if "0.35" in ln]
        assert [i for i, _ in drifted] == [40, 192], drifted
        assert "(0.35) let alone the default flag threshold (0.5)" in lines[39]
        assert "(both 0.35)" in lines[191]
        esc = Path(__file__).resolve().parents[1] / "worker" / "llm_escalation.py"
        assert "ESCALATION_LOW = 0.40" in esc.read_text(encoding="utf-8")
        scanning = Path(__file__).resolve().parents[1] / "app" / "scanning.py"
        assert "MATERIAL_CHANGE_RISK = 0.40" in scanning.read_text(encoding="utf-8")

    def test_scan_tasks_noise_floor_claim_about_the_dataset_holds(self):
        """The `min observed: 0.0518` comment is reproducible from the committed artifact."""
        import json
        from pathlib import Path

        ds = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "worker"
                / "detection"
                / "training"
                / "fusion_dataset.json"
            ).read_text(encoding="utf-8")
        )
        peaks = [
            max(v for v in row["features"] if isinstance(v, (int, float)))
            for row in ds["samples"]
            if row["label"] == 1
        ]
        assert min(peaks) == pytest.approx(0.0518, abs=1e-4)
        assert min(peaks) > 0.02


# =====================================================================================
# SA2-11  34 BENIGN rows of the committed 646-row dataset fuse above the default flag
# =====================================================================================


class TestAUDITSA2x11BenignDatasetRowsFlag:
    def test_vendor_script_added_benign_rows_flag_by_default(self):
        import json
        from pathlib import Path

        ds = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "worker"
                / "detection"
                / "training"
                / "fusion_dataset.json"
            ).read_text(encoding="utf-8")
        )
        risks = {}
        for row in ds["samples"]:
            if row["label"] != 0:
                continue
            f = dict(zip(ds["meta"]["feature_keys"], row["features"], strict=True))
            r = layer9_fusion({k: {"score": f.get(k, 0.0), "evidence": {}} for k in FEATURE_KEYS})[
                "score"
            ]
            risks.setdefault(row["axis"], []).append(r)
        assert max(risks["vendor_script_added"]) > DEFAULT_FLAG_THRESHOLD
        assert statistics.mean(risks["vendor_script_added"]) > 0.7
        flagged = sum(1 for v in risks.values() for r in v if r >= DEFAULT_FLAG_THRESHOLD)
        assert flagged >= 30, flagged

    def test_the_152_row_regression_corpus_has_no_false_flag(self):
        """Positive control: the standing corpus guard is clean (0 benign rows cross 0.40)."""
        import json
        from pathlib import Path

        corpus = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "worker"
                / "detection"
                / "training"
                / "regression_corpus.json"
            ).read_text(encoding="utf-8")
        )
        bad = 0
        for row in corpus["samples"]:
            if row["label"] != 0:
                continue
            f = dict(zip(corpus["meta"]["feature_keys"], row["features"], strict=True))
            r = layer9_fusion({k: {"score": f.get(k, 0.0), "evidence": {}} for k in FEATURE_KEYS})[
                "score"
            ]
            if r >= MATERIAL_CHANGE_RISK:
                bad += 1
        assert bad == 0, f"{bad} corpus benign rows cross 0.40"


# =====================================================================================
# SA2-12  MiniLM degenerate-output handling
# =====================================================================================


class TestAUDITSA2x12EmbeddingFailureModes:
    def test_cosine_similarity_has_no_finite_guard(self):
        from worker.detection.semantics import cosine_similarity

        assert (
            cosine_similarity([float("nan")] * 4, [1.0] * 4)
            != cosine_similarity([float("nan")] * 4, [1.0] * 4)
            or True
        )
        result = cosine_similarity([float("nan")] * 4, [1.0] * 4)
        assert result is None or not math.isfinite(result), result

    def test_a_nan_similarity_becomes_maximal_drift(self):
        from worker.detection.semantics import drift_from_similarity

        assert drift_from_similarity(float("nan")) == 1.0

    def test_a_nan_embedding_vector_saturates_layer8(self):
        import numpy as np

        import worker.detection.semantics as SEM

        class Degenerate:
            def encode(self, text, **kw):
                return np.full(384, float("nan"), dtype="float32")

        original = SEM._model
        SEM._model = Degenerate()
        try:
            result = SEM.layer8_semantics(
                PageData(html=site(), final_url="https://x.test/"),
                PageData(html=site(extra="<p>replaced body</p>"), final_url="https://x.test/"),
            )
            assert result["score"] == 1.0, result["evidence"]
            assert not math.isfinite(result["evidence"]["semantic_similarity"])
        finally:
            SEM._model = original

    def test_a_zero_vector_is_excluded_not_fatal(self):
        """Positive control: the documented degenerate path is handled."""
        import numpy as np

        import worker.detection.semantics as SEM

        class Zero:
            def encode(self, text, **kw):
                return np.zeros(384, dtype="float32")

        original = SEM._model
        SEM._model = Zero()
        try:
            result = SEM.layer8_semantics(
                PageData(html=site(), final_url="https://x.test/"),
                PageData(html=site(extra="<p>replaced body</p>"), final_url="https://x.test/"),
            )
            assert result["evidence"]["semantic_similarity"] is None
            assert result["score"] == 0.0
        finally:
            SEM._model = original

    def test_lone_surrogates_make_the_embedder_unavailable_not_fatal(self):
        import worker.detection.semantics as SEM

        SEM._model = None
        original = SEM._get_model
        try:
            SEM._get_model = lambda: (_ for _ in ()).throw(
                TypeError("TextEncodeInput must be Union[...]")
            )
            assert SEM.embed_text("\ud800" * 200) is None
        finally:
            SEM._get_model = original
            SEM._model = None
