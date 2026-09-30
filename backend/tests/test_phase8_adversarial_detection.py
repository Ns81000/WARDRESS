"""PROMPT-003 Audit Phase 8 — adversarial detection accuracy: fixture repros.

Audit Phase 8 (NB-DET-1) built 85 hermetic attack/benign fixture pairs and
pushed each through the DEPLOYED pipeline (`worker.detection.pipeline
.run_detection`) with real-Chromium screenshots, 3 passes each. These tests
carry the subset reproducible without a browser: screenshots are synthesised
with PIL exactly the way the phase's real renders differed (a coloured
rectangle composited over a stable page render).

Two kinds of test live here:

  * PASSING characterization tests — behaviours that work today and that no
    standing test guards. The important one is the ATTACK-WITHDRAWAL row
    (Session A backlog item 18: caught at ~0.99 via layer 4, with no corpus row
    guarding it, so a regression would be silent). These are the regression
    guards this phase recommends committing.

  * XFAIL tests — deterministic repros of the Phase-8 findings. Each asserts
    the CURRENT (wrong) behaviour and carries the finding ID, so a remediation
    prompt flips exactly one assertion. `strict=False` keeps the suite green
    (Rule 5) while a fixed behaviour surfaces as XPASS.

Diagnosis only — no production code was changed (Rule 1).
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from worker.detection.dom import layer3_link_audit
from worker.detection.fusion import FEATURE_KEYS, layer9_fusion
from worker.detection.metadata import layer6_security_metadata
from worker.detection.pipeline import run_detection
from worker.detection.signatures import extract_visible_text
from worker.detection.suppress import _apply_to_html, build_suppression
from worker.detection.types import PageData, ScanPageData, UAVariant
from worker.hashing import content_sha256

URL = "https://shop.example.com/"
HEADERS = {
    "content-security-policy": "default-src 'self'; script-src 'self'; object-src 'none'",
    "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "geolocation=(), camera=()",
}
ROBOTS = "User-agent: *\nAllow: /\n"
TLS = {
    "not_after": "2027-01-01T00:00:00+00:00",
    "fingerprint_sha256": "a" * 64,
    "subject": "CN=shop.example.com",
    "issuer": "CN=Example CA",
}

BANNER = (
    "<div id='notif'><h1>HACKED BY THE DRAGON TEAM</h1>"
    "<p>Your security is weak. Contact us at telegram t.me/dragonx</p></div>"
)
BODY = (
    "<html><head><title>Northwind</title></head><body>"
    "<header><nav><a href='/'>Home</a><a href='/news'>News</a></nav></header>"
    "<main><h1>Northwind Trading Co.</h1>"
    + "".join(
        f"<article class='card'><h2><a href='/news/i{i}'>Field notes {i}</a></h2>"
        f"<p>The quarterly supply chain review covered {i} regional hubs and the "
        f"lead times fell by roughly a third across the catalogue this season.</p>"
        f"<p>Posted by the editorial desk.</p></article>"
        for i in range(1, 13)
    )
    + "</main><footer><p>Northwind Trading Co. registered in Delaware.</p>"
    "<form action='/login' method='post'><input name='q'></form></footer>"
    "<script src='https://cdn.northwind-static.example/analytics.js'></script>"
    "</body></html>"
)
DEFACED = BODY.replace("</main>", BANNER + "</main>")


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _page_shot(h: int = 1400, w: int = 800) -> Image.Image:
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 90], fill=(27, 108, 168))
    y = 130
    for _ in range(34):
        d.rectangle([60, y, w - 60, y + 22], fill=(220, 220, 220))
        y += 34
    return img


_BARE = _page_shot()
_BANNERED = _bare_with_banner = _BARE.copy()
ImageDraw.Draw(_BANNERED).rectangle([0, 100, _BARE.width, 220], fill=(139, 0, 0))

CLEAN_SHOT = _to_bytes(_BARE)
DEFACED_SHOT = _to_bytes(_BANNERED)
HUE_SHOT = _to_bytes(Image.eval(_BARE, lambda v: 255 - v))  # a full chroma flip


def _pair(
    base_html, cur_html, *, shot_b=b"", shot_c=b"", headers=None, cur_headers=None, variants=None
):
    return (
        PageData(
            html=base_html,
            screenshot=shot_b,
            final_url=URL,
            http_status=200,
            headers=dict(HEADERS) if headers is None else headers,
            tls=dict(TLS),
            robots_txt=ROBOTS,
            content_hash=content_sha256(base_html),
        ),
        ScanPageData(
            html=cur_html,
            screenshot=shot_c,
            final_url=URL,
            http_status=200,
            headers=dict(HEADERS) if cur_headers is None else cur_headers,
            tls=dict(TLS),
            robots_txt=ROBOTS,
            content_hash=content_sha256(cur_html),
            ua_variants=list(variants or []),
        ),
    )


def _run(base_html, cur_html, *, suppression=None, **kw):
    b, c = _pair(base_html, cur_html, **kw)
    return run_detection(b, c, suppression)


def _verdict(results, flag_threshold: float = 0.50):
    """Reproduce worker/scan_tasks.py:300-347."""
    risk = float(results["layer9_fusion"]["score"] or 0.0)
    changed = any(
        (r.get("score") or 0.0) > 0.02
        for k, r in results.items()
        if k != "layer9_fusion" and not r.get("skipped")
    )
    return risk, ("flagged" if risk >= flag_threshold else ("changed" if changed else "clean"))


GAP = "AUDIT-8-x: the current behaviour IS the finding — flip this assertion after the fix"


# ===========================================================================
# PASSING characterization tests — working today, unguarded by any test.
# ===========================================================================
class TestPhase8PositiveControls:
    """Behaviour that works today and that no committed test guards."""

    def test_attack_withdrawal_is_flagged_via_layer4(self) -> None:
        """REGRESSION GUARD — Session A backlog item 18. A defacement present in
        the BASELINE and removed in the scan is caught, by layer 4's visual
        delta. Measured 0.7078 / flagged, 3/3 passes, real-Chromium pair."""
        res = _run(DEFACED, BODY, shot_b=DEFACED_SHOT, shot_c=CLEAN_SHOT)
        risk, verdict = _verdict(res)
        assert res["layer4_visual_diff"]["score"] > 0.2225
        assert verdict == "flagged", (risk, verdict)

    def test_attack_withdrawal_is_not_merely_the_byte_flip(self) -> None:
        """The conclusive text is gone in the scan, so layers 5 and 8 must be
        0.0 — layer 4 is carrying this detection on its own."""
        res = _run(DEFACED, BODY, shot_b=DEFACED_SHOT, shot_c=CLEAN_SHOT)
        assert res["layer5_signatures"]["score"] == 0.0
        assert res["layer8_semantics"]["score"] == 0.0

    def test_html_defacement_banner_flags(self) -> None:
        res = _run(BODY, DEFACED, shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT)
        risk, verdict = _verdict(res)
        assert res["layer5_signatures"]["score"] == 1.0
        assert verdict == "flagged", (risk, verdict)

    def test_static_render_noise_is_below_the_escalation_bar(self) -> None:
        """Session A's positive result, re-pinned: layer 4 alone at 0.2225
        reaches the 0.40 material bar, so pure render noise must stay under it."""
        assert CLEAN_SHOT == _to_bytes(_page_shot())  # the synthetic render is stable
        res = _run(BODY, BODY, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT)
        assert res["layer4_visual_diff"]["score"] == 0.0

    def test_layer3_removal_direction_is_evidence_only(self) -> None:
        """AUDIT-4-6 characterization: a removal-only reference change scores
        0.0 and is recorded in evidence, so a remediation author knows the
        signal is absent rather than merely unlogged."""
        stripped = BODY.replace(
            "<script src='https://cdn.northwind-static.example/analytics.js'></script>", ""
        )
        res = layer3_link_audit(*_pair(BODY, stripped))
        assert res["score"] == 0.0
        assert res["evidence"]["script_src"]["removed_count"] == 1

    def test_layer8_alone_cannot_reach_the_material_bar(self) -> None:
        """AUDIT-SA2-4 reachability: layer 8 at its maximum contributes 0.1198,
        so a complete content takeover cannot be carried by semantics alone."""
        zero = {"score": 0.0, "evidence": {}}
        res = layer9_fusion(
            {
                "layer1_hash": zero,
                "layer2_dom_structure": zero,
                "layer3_link_audit": zero,
                "layer4_visual_diff": zero,
                "layer5_signatures": zero,
                "layer6_security_metadata": zero,
                "layer7_cloaking": zero,
                "layer8_semantics": {"score": 1.0, "evidence": {}},
            }
        )
        assert float(res["score"]) < 0.40

    def test_layer4_alone_can_reach_the_flag_threshold(self) -> None:
        """The 26.26 coefficient: 0.24 on layer 4 alone crosses 0.50. This is
        the standing map of which channels can and cannot reach the bars."""
        zero = {"score": 0.0, "evidence": {}}
        res = layer9_fusion(
            {
                "layer1_hash": zero,
                "layer2_dom_structure": zero,
                "layer3_link_audit": zero,
                "layer4_visual_diff": {"score": 0.24, "evidence": {}},
                "layer5_signatures": zero,
                "layer6_security_metadata": zero,
                "layer7_cloaking": zero,
                "layer8_semantics": zero,
            }
        )
        assert float(res["score"]) >= 0.40


# ===========================================================================
# NB-DET-1 — the three mandated visual-only attack fixtures.
# ===========================================================================
class TestPhase8VisualOnlyAttacks:
    """All three mandated visual-only attacks ARE caught in production
    (real Chromium, 3/3 passes, layer 4 measured — the capture→screenshot
    path does deliver a usable image). These pin that contract so a future
    capture regression cannot silently blind the only channel that carries
    them."""

    def test_style_injection_defacement_is_loud(self) -> None:
        res = _run(
            BODY,
            BODY.replace("<title>", "<style>body{filter:invert(1)}</style><title>"),
            shot_b=CLEAN_SHOT,
            shot_c=DEFACED_SHOT,
        )
        risk, verdict = _verdict(res)
        assert res["layer4_visual_diff"]["score"] > 0.2225
        assert verdict == "flagged", (risk, verdict)

    def test_canvas_takeover_without_any_html_text_is_caught(self) -> None:
        canvas = (
            "<canvas id='t' style='position:fixed;inset:0;width:100%;height:100%'></canvas>"
            "<script>(function(){var c=document.getElementById('t');c.width=c.clientWidth;"
            "c.height=c.clientHeight;var x=c.getContext('2d');x.fillStyle='#7a0b0b';"
            "x.fillRect(0,0,c.width,c.height);})();</script>"
        )
        res = _run(
            BODY,
            BODY.replace("</body>", canvas + "</body>"),
            shot_b=CLEAN_SHOT,
            shot_c=DEFACED_SHOT,
        )
        assert _verdict(res)[1] == "flagged"

    def test_svg_geometry_takeover_is_caught(self) -> None:
        svg = (
            "<svg viewBox='0 0 800 700' preserveAspectRatio='xMidYMid meet' "
            "style='position:fixed;inset:0;width:100%;height:100%;z-index:2147483647'>"
            "<rect width='800' height='700' fill='#101010'/>"
            "<rect x='300' y='300' width='70' height='70' fill='#ffffff'/>"
            "<rect x='390' y='300' width='70' height='70' fill='#ffffff'/></svg>"
        )
        res = _run(
            BODY, BODY.replace("</body>", svg + "</body>"), shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT
        )
        assert _verdict(res)[1] == "flagged"


# ===========================================================================
# XFAIL — deterministic repros of the Phase-8 findings.
# ===========================================================================
class TestPhase8VisualTwinAndScale:
    """The benign twins of the visual-only attacks, and layer 4's area
    sensitivity. These are the operationally important half: a false positive
    on a brand refresh alerts an operator on completely legitimate behaviour."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_legit_webfont_swap_does_not_flag(self) -> None:
        """VB2. Measured: hijack L4=0.3043 / 0.9979 flagged; benign swap
        L4=0.3627 / 0.9995 flagged. The benign twin is LOUDER than the attack —
        layer 4 cannot tell them apart, and only the DOM delta separates them."""
        swapped = BODY.replace(
            "</head>",
            "<style>@font-face{font-family:B;src:url('/b.ttf')}body{font-family:B}</style></head>",
        )
        res = _run(BODY, swapped, shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT)
        assert _verdict(res)[1] != "flagged"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_hue_only_brand_refresh_does_not_flag(self) -> None:
        """VB1b. A full-rebrand `hsl()` swap on a real render measures
        L4=0.0235 / risk 0.2276 (below the bar) but is only 24x from it."""
        res = _run(BODY, BODY.replace("Northwind", "Northwind"), shot_b=CLEAN_SHOT, shot_c=HUE_SHOT)
        assert _verdict(res)[1] != "flagged"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_layer4_has_an_area_floor(self) -> None:
        """AUDIT-8-x. Layer 4's sensitivity is set by the changed AREA: a 3px
        full-width strip (0.1% of a 3103px page) measures 0.1514 and fuses to
        0.0936 — silent — while a 15px strip (0.5%) measures 0.2817 and flags
        at 0.7593. A small (320x120) defaced logo on the same page measures
        0.0975 / risk 0.0244. There is no area floor anywhere in visual.py."""
        tiny = _BARE.copy()
        ImageDraw.Draw(tiny).rectangle([0, 100, _BARE.width, 103], fill=(139, 0, 0))
        res = _run(BODY, BODY, shot_b=_to_bytes(tiny), shot_c=CLEAN_SHOT)
        assert res["layer4_visual_diff"]["score"] > 0.2225


class TestPhase8HeaderAttacks:
    """AUDIT-SA2-2 confirmed with real screenshots on both sides: a CSP
    widening is `clean` at 0.0019."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_csp_widening_to_wildcard_is_not_clean(self) -> None:
        widened = dict(
            HEADERS, **{"content-security-policy": "default-src *; script-src *; object-src *"}
        )
        res = _run(BODY, BODY, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT, cur_headers=widened)
        assert _verdict(res)[1] != "clean"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_attacker_origin_added_to_csp_is_classified_weaker(self) -> None:
        """The textbook CSP-weakening-for-exfil pattern is classified
        `stronger` (more tokens) and scores 0.0."""
        widened = dict(
            HEADERS,
            **{
                "content-security-policy": "default-src 'self' https://cdn.evil-exfil.tld; "
                "script-src 'self' https://cdn.evil-exfil.tld; object-src 'none'"
            },
        )
        res = layer6_security_metadata(*_pair(BODY, BODY, cur_headers=widened))
        assert res["evidence"].get("security_headers_weakened")

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_hsts_downgrade_magnitude_is_scored_by_severity(self) -> None:
        """2 y + includeSubDomains + preload -> max-age=300 is a total HSTS
        neutralisation; measured layer6 = 0.1 and a fused risk of 0.0025."""
        down = dict(HEADERS, **{"strict-transport-security": "max-age=300"})
        res = layer6_security_metadata(*_pair(BODY, BODY, cur_headers=down))
        assert res["score"] >= 0.5

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_meta_http_equiv_csp_is_read_by_layer6(self) -> None:
        """E12. A page shipping its own `<meta http-equiv=Content-Security-
        Policy>` weaker than the header is invisible to layer 6 (0.1392)."""
        meta = BODY.replace(
            "</head>",
            "<meta http-equiv='Content-Security-Policy' "
            "content=\"default-src *; script-src * 'unsafe-inline'\">",
        )
        res = layer6_security_metadata(*_pair(BODY, meta))
        assert "csp" in str(res["evidence"]).lower()


class TestPhase8BenignFalsePositives:
    """AUDIT-SA2-1 / AUDIT-2-4 confirmed. 11 of 21 benign fixtures FLAG; 12 of
    21 cross the 0.40 material bar."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_recaptcha_widget_appearing_does_not_flag(self) -> None:
        widget = (
            "<div class='g-recaptcha'><iframe "
            "src='https://www.google.com/recaptcha/api2/anchor?k=6LcX'></iframe></div>"
        )
        res = _run(
            BODY, BODY.replace("</body>", widget + "</body>"), shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT
        )
        assert _verdict(res)[1] != "flagged"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_vendor_script_added_does_not_flag(self) -> None:
        res = _run(
            BODY,
            BODY.replace(
                "</body>", "<script src='https://cdn.vendor-metrics.example/a.js'></script></body>"
            ),
            shot_b=CLEAN_SHOT,
            shot_c=CLEAN_SHOT,
        )
        assert _verdict(res)[1] != "flagged"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_two_new_external_stylesheets_stay_below_the_material_bar(self) -> None:
        """Measured 0.4511 end-to-end with a real render: adding two webfonts
        lands in the 0.40-0.75 escalation band, i.e. an LLM call per scan plus
        a permanently tightened cadence — on completely legitimate behaviour."""
        two = BODY.replace(
            "</head>",
            "<link rel='stylesheet' "
            "href='https://fonts.googleapis.com/css2?family=Inter'>"
            "<link rel='stylesheet' href='https://use.typekit.net/a.css'>",
        )
        res = _run(BODY, two, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT)
        assert float(res["layer9_fusion"]["score"]) < 0.40

    def test_eight_articles_of_benign_editorial_churn_stay_below_the_bar(self) -> None:
        """PASSING bound, measured 0.2484 end-to-end with a real render. It holds
        only because the churn term is content-weighted to 0.2
        (dom.py:_CONTENT_CHURN_WEIGHT) — pin it so that weight cannot be
        retuned without someone noticing the consequence."""
        extra = "".join(
            f"<article class='card'><h2><a href='/news/n{i}'>New dispatch {i}</a></h2>"
            f"<p>Additional reporting from the regional desk on the latest figures.</p>"
            "</article>"
            for i in range(8)
        )
        res = _run(
            BODY, BODY.replace("</main>", extra + "</main>"), shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT
        )
        assert float(res["layer9_fusion"]["score"]) < 0.40


class TestPhase8EvasionShapes:
    """Attacks that defeat a specific channel by construction. Every one of
    these reads `changed` at 0.1372-0.2330 with real screenshots present."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_base_href_hijack_is_seen_by_layer3(self) -> None:
        """E1. Layer 3 resolves references against `PageData.final_url`, so a
        `<base href>` that re-points every relative URL IN THE BROWSER is
        invisible to it. Measured 0.1392 / changed."""
        hijack = BODY.replace("<head>", "<head><base href='https://evil-cloak.tld/'>")
        res = _run(BODY, hijack, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT)
        assert res["layer3_link_audit"]["score"] > 0.0

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_hidden_text_revealed_is_seen_by_layer2(self) -> None:
        """E13/E14. Layer 2's sensitive channel is `max(0, current - baseline)`
        over the hidden count, so dropping `display:none` makes that count go
        DOWN and scores nothing; layers 5/8 see no new text either. Measured
        0.1372 / changed for both a spam reveal and a conclusive defacement
        reveal."""
        hid = BODY.replace(
            "</main>", "<div style='display:none'>HACKED BY THE DRAGON TEAM</div></main>"
        )
        vis = hid.replace(" style='display:none'", "")
        res = _run(hid, vis, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT)
        assert res["layer2_dom_structure"]["score"] > 0.0

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_removal_only_defacement_is_seen_by_layer3(self) -> None:
        """BA12. Stripping the site's own login form + analytics script scores
        0.1453 / changed."""
        stripped = BODY.replace(
            "<script src='https://cdn.northwind-static.example/analytics.js'></script>", ""
        )
        res = _run(BODY, stripped, shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT)
        assert res["layer3_link_audit"]["score"] > 0.0

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_noscript_payload_is_rendered_by_the_capture(self) -> None:
        """E5. A full-viewport defacement inside <noscript> is invisible to
        Wardress's own screenshot (Playwright enables JS) and to every content
        layer. Measured 0.1411 / changed."""
        payload = (
            "<noscript><div style='position:fixed;inset:0;background:#000;"
            "color:#fff;padding:80px'>YOUR SITE HAS BEEN HACKED</div></noscript>"
        )
        res = _run(
            BODY, BODY.replace("</body>", payload + "</body>"), shot_b=CLEAN_SHOT, shot_c=CLEAN_SHOT
        )
        assert res["layer5_signatures"]["score"] > 0.0

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_small_cloaked_payload_on_a_realistic_page_is_graded(self) -> None:
        """BA10 / AUDIT-SA2-3. The additive ramp is anchored to
        `min(1.0, added/|ref|)`, so a fixed 20-token conclusive payload decays
        as the reference grows: 0.1296 at ~60 reference tokens, 0.1032 at ~400
        and at ~1400. Layer 7's own escalation trigger is 0.4440."""
        ref = BODY + "<section>" + ("filler word alpha beta gamma delta " * 60) + "</section>"
        bot = ref.replace(
            "</main>",
            "<div><h1>WE HAVE BEEN HACKED BY THE DRAGON TEAM</h1>"
            "<p>your website security has been compromised contact us on "
            "telegram now</p></div></main>",
        )
        variants = [
            UAVariant("desktop_chrome", ref, 200, URL, None, content_sha256(ref)),
            UAVariant("googlebot", bot, 200, URL, None, content_sha256(bot)),
        ]
        res = _run(BODY, BODY, variants=variants)
        assert res["layer7_cloaking"]["score"] > 0.4


class TestPhase8SuppressionAsAnAdversaryPrimitive:
    """Suppression runs before every content layer and REPLACES the content on
    both sides, so a suppressed span is invisible to layers 2/3/5/8. A `bbox`
    rule additionally paints the region out of BOTH screenshots, blinding the
    one channel that survived the css_selector/regex arms."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_defacement_inside_a_guessed_selector_is_still_visible_to_layer5(self) -> None:
        wrapped = BODY.replace("</main>", f"<div id='banner'>{BANNER}</div></main>")
        supp = build_suppression([("css_selector", "#banner")])
        res = _run(BODY, wrapped, shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT, suppression=supp)
        assert res["layer5_signatures"]["score"] > 0.0

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_defacement_with_a_matching_bbox_rule_still_flags(self) -> None:
        """S3h — the only escape from a conclusive defacement in the whole
        85-fixture suite. css_selector #banner + bbox over the top 30% blinds
        all nine layers; measured 0.1372 / changed."""
        wrapped = BODY.replace("</main>", f"<div id='banner'>{BANNER}</div></main>")
        supp = build_suppression([("css_selector", "#banner"), ("bbox", "0.0,0.0,1.0,0.30")])
        res = _run(BODY, wrapped, shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT, suppression=supp)
        assert _verdict(res)[1] == "flagged"

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_suppression_regex_timeout_is_symmetric_across_sides(self) -> None:
        """AUDIT-4-4's mechanism, isolated. A rule that BOTH times out AND has
        a matchable prefix makes the two sides receive DIFFERENT rewrites purely
        because of document order: baseline 1999.5 ms (timeout, `Session id:
        12345678` KEPT) vs scan 1.5 ms (rewritten) -> risk 0.8290 flagged,
        while the symmetric control reads 0.0019 clean."""
        bomb = "<p>" + ("a" * 5000) + "c</p>"
        sess = "<p>Session id: 12345678</p>"
        pat = r"(a|aa)+b|Session id: \d+"
        b_out = _apply_to_html(bomb + sess + BODY, build_suppression([("regex", pat)]))
        c_out = _apply_to_html(BODY + sess + bomb, build_suppression([("regex", pat)]))
        assert b_out == c_out
        assert "Session id: 12345678" in extract_visible_text(b_out)

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_overlapping_suppression_rules_report_their_coverage(self) -> None:
        """AUDIT-4-4's High half: `suppression_applied` records WHICH rules ran,
        never HOW MUCH content they removed, so neither an operator nor an
        auditor can tell that 100% of the page is invisible to two of nine
        layers."""
        supp = build_suppression([("css_selector", "main")])
        res = _run(BODY, DEFACED, shot_b=CLEAN_SHOT, shot_c=DEFACED_SHOT, suppression=supp)
        ev = res["layer5_signatures"]["evidence"].get("suppression_applied", {})
        assert ev.get("chars_removed") or ev.get("bytes_removed") or ev.get("coverage")


class TestPhase8CalibrationArtifact:
    """AUDIT-2-4 re-derived from the committed artifact: 36 of 323 benign rows
    reach 0.40 and 34 exceed the default 0.50 flag threshold, while the 56
    benign rows of the 152-row regression corpus reach none of them."""

    @pytest.mark.xfail(reason=GAP, strict=False)
    def test_sanity_benign_quiet_row_is_below_the_flag_threshold(self) -> None:
        ds = (
            Path(__file__).resolve().parents[1]
            / "worker"
            / "detection"
            / "training"
            / "fusion_dataset.json"
        )
        rows = json.loads(ds.read_text(encoding="utf-8"))["samples"]
        quiet = [r for r in rows if r["axis"] == "sanity_benign_quiet"]
        assert quiet, "the calibration sanity row must exist"
        skipped = set(quiet[0].get("layers_skipped") or [])
        res = layer9_fusion(
            {
                k: (
                    {"score": None, "skipped": True, "evidence": {}}
                    if k in skipped
                    else {"score": float(v), "evidence": {}}
                )
                for k, v in zip(FEATURE_KEYS, quiet[0]["features"], strict=True)
            }
        )
        assert float(res["score"]) < 0.50

    def test_regression_corpus_benign_rows_stay_below_the_bar(self) -> None:
        """Positive control for the row above: the guard the repository DOES
        own is genuinely clean — which is exactly why it is circular."""
        ds = (
            Path(__file__).resolve().parents[1]
            / "worker"
            / "detection"
            / "training"
            / "regression_corpus.json"
        )
        rows = json.loads(ds.read_text(encoding="utf-8"))["samples"]
        worst = 0.0
        for row in rows:
            if row["label"] != 0:
                continue
            skipped = set(row.get("layers_skipped") or [])
            res = layer9_fusion(
                {
                    k: (
                        {"score": None, "skipped": True, "evidence": {}}
                        if k in skipped
                        else {"score": float(v), "evidence": {}}
                    )
                    for k, v in zip(FEATURE_KEYS, row["features"], strict=True)
                }
            )
            worst = max(worst, float(res["score"] or 0.0))
        assert worst < 0.40, worst
