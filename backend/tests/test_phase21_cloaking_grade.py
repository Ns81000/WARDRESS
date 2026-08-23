"""Layer 7 cloaking: graded dual-channel scoring (Phase 21).

Finding: the soft knee (`score = (d - 0.5)/0.5 if d > 0.5 else 0.0`) hard-
zeroed everything below union-relative divergence 0.5, so crawlers could be
served up to ~50% foreign content at exactly score 0.0 — SEO-spam cloaking,
the layer's stated primary target, was viable at scale while silent (audit
measured: 100..499 spam tokens against a 500-token reference all scored
0.000; union dilution on larger pages stayed silent even further).

The fix grades divergence continuously with two complementary channels and
an absolute churn grace:
- additive channel: max(union divergence, |B∖A| / |A|) ramping from 0.15 —
  the reference-relative fraction punishes injected spam independent of how
  much shared base vocabulary dilutes the union;
- removal-dominant pairs keep a conservative ramp from 0.45 because servers
  legitimately strip content for mobile UAs;
- pairs differing by <= _MIN_FOREIGN_TOKENS unique tokens are request-to-
  request churn (timestamps, counters, rotating widgets) AND the regime
  where token-set Jaccard exaggerates trivial edits on short pages — always
  exactly 0.0.

The failing-before proof for this module ran formally via `git stash push --
worker/detection/cloaking.py` (see the fix log): the additive-sweep tests
failed on the stashed pre-fix tree with scores 0.000.
"""

import pytest

from worker.detection.cloaking import (
    _MIN_FOREIGN_TOKENS,
    _text_similarity,
    layer7_cloaking,
)
from worker.detection.pipeline import run_detection
from worker.detection.types import PageData, ScanPageData, UAVariant
from worker.hashing import content_sha256

REF_PAGE = " ".join(f"word{i}" for i in range(500))


def _html(text: str) -> str:
    return f"<html><body><p>{text}</p></body></html>"


def _variant(ua_key: str, text: str) -> UAVariant:
    html = _html(text)
    return UAVariant(ua_key=ua_key, html=html, http_status=200, content_hash=content_sha256(html))


def _scan(ref_text: str, rotated: list[tuple[str, str]]) -> ScanPageData:
    return ScanPageData(
        html=_html(ref_text),
        final_url="https://acme.com/",
        content_hash="primary-hash",
        ua_variants=[_variant("desktop_chrome", ref_text)] + [_variant(ua, t) for ua, t in rotated],
    )


def _score(ref_text: str, rotated: list[tuple[str, str]]) -> dict:
    result = layer7_cloaking(
        PageData(html=_html(ref_text), final_url="u", content_hash="h"),
        _scan(ref_text, rotated),
    )
    assert 0.0 <= result["score"] <= 1.0
    return result


def _additive(n: int) -> tuple[str, str]:
    spam = " ".join(f"spam{k}" for k in range(n))
    return "googlebot", f"{REF_PAGE} {spam}"


# --- the finding: additive cloaking must register -------------------------------


@pytest.mark.parametrize("n", [300, 400, 450, 499])
def test_audit_sweep_additive_spam_no_longer_scores_zero(n: int) -> None:
    """The audit's exact sweep rows (499 spam tokens scored 0.000 pre-fix):
    substantial additive foreign content now grades proportionally."""
    result = _score(REF_PAGE, [_additive(n)])
    assert result["score"] >= 0.6


def test_small_additive_registering_weakly() -> None:
    """20% foreign vocabulary (100 tokens) leaves the dead zone instead of
    scoring exactly 0.0 (pre-fix: 0.000)."""
    result = _score(REF_PAGE, [_additive(100)])
    assert result["score"] > 0.0


def test_union_dilution_on_large_reference_registers() -> None:
    """600 foreign tokens on a 2000-token reference: union-relative
    divergence is only ~0.23 but the reference-relative fraction carries it
    above zero (pre-fix: 0.000)."""
    ref2000 = " ".join(f"w{i}" for i in range(2000))
    result = _score(
        ref2000,
        [("googlebot", f"{ref2000} " + " ".join(f"s{i}" for i in range(600)))],
    )
    assert result["score"] >= 0.2


def test_additive_cloaking_reaches_severe_floor_through_pipeline() -> None:
    """Additive cloaking on a hash-gated scan (identical primary DOM):
    layer 7 alone must reach the Phase-7 severe-cloaking floor end to end."""
    baseline_html = "<html><body><h1>Acme</h1><p>" + REF_PAGE[:200] + "</p></body></html>"
    spam = (
        "<html><body><p>"
        + " ".join(f"spam{k} casino pills" for k in range(200))
        + "</p></body></html>"
    )
    variants = [
        _variant("desktop_chrome", baseline_html),
        _variant("googlebot", spam),
    ]
    results = run_detection(
        PageData(html=baseline_html, final_url="u", content_hash=content_sha256(baseline_html)),
        ScanPageData(
            html=baseline_html,
            final_url="u",
            content_hash=content_sha256(baseline_html),
            ua_variants=variants,
        ),
    )
    assert results["layer2_dom_structure"]["skipped"] is True
    l7_score = results["layer7_cloaking"]["score"]
    assert l7_score >= 0.85
    applied = results["layer9_fusion"]["evidence"]["rule_floor"]["applied"]
    assert any(r["layer"] == "layer7_cloaking" for r in applied)


# --- monotonicity ----------------------------------------------------------------


def test_score_monotone_in_added_foreign_mass() -> None:
    seen = -1.0
    for n in (13, 50, 100, 200, 300, 400, 500, 700):
        value = _score(REF_PAGE, [_additive(n)])["score"]
        assert value >= seen
        seen = value


# --- the churn grace: benign dynamics stay at exactly zero -----------------------


@pytest.mark.parametrize(
    "label, ref, var",
    [
        (
            "timestamp tick",
            "Welcome to Acme services here now more body text",
            "Welcome to Acme services here now more body text 14 22 05",
        ),
        (
            "visitor counter on a tiny page",
            "Acme Reliable widgets",
            "Acme Reliable widgets Visitor #42",
        ),
        (
            "rotating ad widget at the grace edge",
            " ".join(f"t{i}" for i in range(300)),
            " ".join(f"t{i}" for i in range(300))
            + " "
            + " ".join(f"ad{i}" for i in range(_MIN_FOREIGN_TOKENS)),
        ),
        (
            "mobile adaptation strips 40%, adds nothing",
            " ".join(f"m{i}" for i in range(100)),
            " ".join(f"m{i}" for i in range(60)),
        ),
        (
            "aside removal on a small page",
            "Brand hero nav home about contact footer legal note extra words",
            "Brand hero nav home about contact footer legal",
        ),
        ("both sides blank visible text", "", ""),
        ("one side blank (reference blank)", "", "some crawler-only content here indeed"),
    ],
)
def test_churn_grace_shapes_score_exactly_zero(label: str, ref: str, var: str) -> None:
    result = _score(ref, [("googlebot", var)])
    assert result["score"] == 0.0, label


def test_grace_boundary_is_absolute_not_relative() -> None:
    """Exactly _MIN_FOREIGN_TOKENS foreign tokens on ANY page size graces to
    zero; one more token starts grading (tiny page => large relative jump)."""
    tiny_ref = "a b c"
    at_edge = _score(
        tiny_ref,
        [("googlebot", tiny_ref + " " + " ".join(f"x{i}" for i in range(_MIN_FOREIGN_TOKENS)))],
    )
    over_edge = _score(
        tiny_ref,
        [("googlebot", tiny_ref + " " + " ".join(f"x{i}" for i in range(_MIN_FOREIGN_TOKENS + 1)))],
    )
    assert at_edge["score"] == 0.0
    assert over_edge["score"] > 0.0


# --- removal direction keeps its conservative ramp --------------------------------


def test_moderate_content_reduction_stays_quiet() -> None:
    """Crawler served ~42% less vocabulary (aggressive-but-plausible mobile
    adaptation), nothing added: still inside the conservative dead zone."""
    ref = " ".join(f"r{i}" for i in range(200))
    result = _score(ref, [("mobile_safari", " ".join(f"r{i}" for i in range(115)))])
    assert result["score"] == 0.0


def test_near_total_content_hiding_saturates() -> None:
    """Crawler served an almost empty page while the browser sees content:
    removal-dominant divergence saturates regardless of the grace."""
    ref = " ".join(f"r{i}" for i in range(200))
    result = _score(ref, [("googlebot", "stub")])
    assert result["score"] >= 0.85


def test_full_replacement_of_realistic_page_hits_floor_trigger() -> None:
    """Disjoint replacement pages saturate to 1.0 either way — the Phase-7
    severe-cloaking trigger (>= 0.85) stays reachable."""
    ref = " ".join(f"c{i}" for i in range(120))
    result = _score(ref, [("googlebot", " ".join(f"x{i}" for i in range(90)))])
    assert result["score"] == 1.0


# --- evidence contract ------------------------------------------------------------


def test_evidence_keeps_compat_keys_and_adds_diagnostics() -> None:
    result = _score(REF_PAGE, [_additive(300)])
    ev = result["evidence"]
    # consumed by app/explain.py and historical tooling:
    assert ev["reference_ua"] == "desktop_chrome"
    assert isinstance(ev["worst_divergence"], float)
    variant = next(v for v in ev["variants"] if v["ua"] == "googlebot")
    for key in ("comparable", "identical_hash", "similarity"):
        assert key in variant
    # additive diagnostics (frontend renders unknown keys not at all):
    assert variant["added_tokens"] == 300
    assert variant["removed_tokens"] == 0
    assert variant["new_token_fraction"] == pytest.approx(0.6, abs=0.001)
    assert ev["scoring"]["min_foreign_tokens"] == _MIN_FOREIGN_TOKENS
    assert ev["scoring"]["additive_ramp"][0] < ev["scoring"]["additive_ramp"][1]
    assert ev["scoring"]["removal_ramp"][0] > ev["scoring"]["additive_ramp"][0]


def test_similarity_values_themselves_are_unchanged_jaccard() -> None:
    """The graded model changes SCORES only; per-variant similarity remains
    raw token-set Jaccard (explain.py keys on it)."""
    ref = "alpha beta gamma delta epsilon"
    var = "alpha beta gamma zeta eta theta"
    expected = _text_similarity(ref, var)
    result = _score(ref, [("googlebot", var)])
    reported = result["evidence"]["variants"][0]["similarity"]
    assert reported == pytest.approx(round(expected, 3))


def test_bot_blocking_and_errors_still_never_score() -> None:
    blocked = UAVariant(ua_key="googlebot", html="", http_status=403, content_hash="")
    errored = UAVariant(ua_key="mobile_safari", error="ConnectTimeout: ...")
    cur = ScanPageData(
        html=_html(REF_PAGE),
        final_url="u",
        content_hash="h",
        ua_variants=[_variant("desktop_chrome", REF_PAGE), blocked, errored],
    )
    result = layer7_cloaking(PageData(html=_html(REF_PAGE), final_url="u", content_hash="h"), cur)
    assert result["score"] == 0.0
    comparable = [v for v in result["evidence"]["variants"] if v.get("comparable")]
    assert comparable == []


def test_identical_variant_hash_shortcuts_to_similarity_one() -> None:
    ref = " ".join(f"k{i}" for i in range(80))
    result = _score(ref, [("googlebot", ref)])
    variant = result["evidence"]["variants"][0]
    assert variant["identical_hash"] is True
    assert variant["similarity"] == 1.0
    assert result["score"] == 0.0


def test_layer_still_runs_under_identical_primary_hash() -> None:
    """Regression guard for the Phase-6 interplay: layers 6/7 run regardless
    of the layer-1 gate; this module's changes must not disturb that."""
    baseline_html = _html(REF_PAGE)
    results = run_detection(
        PageData(html=baseline_html, final_url="u", content_hash=content_sha256(baseline_html)),
        ScanPageData(
            html=baseline_html,
            final_url="u",
            content_hash=content_sha256(baseline_html),
            ua_variants=[_variant("desktop_chrome", REF_PAGE), _variant("googlebot", REF_PAGE)],
        ),
    )
    assert "skipped" not in results["layer7_cloaking"]
    assert results["layer7_cloaking"]["score"] == 0.0
