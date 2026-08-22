"""Rule-based minimum-risk floors in fusion (layer 9).

Finding: realistic single-vector defacements fuse far below the default
flag threshold AND below the LLM escalation floor — and the fitted
model's sign-inverted layer-2 coefficient lets attacker-padded benign
churn cancel even conclusive hostile evidence (a saturated "HACKED BY"
match + ~15 hidden divs fused to ~0.10 through the real pipeline).

The floors bound the final score from below whenever unambiguous
single-vector evidence exists, independent of model coefficients — so
these tests deliberately avoid pinning model probabilities (the fusion
arc's Phases 8-10 will refit the model) and assert only floor-guaranteed
bounds plus "no floor fired" guards.
"""

import pytest

from worker.detection.fusion import FEATURE_KEYS, layer9_fusion
from worker.detection.pipeline import run_detection
from worker.detection.suppress import build_suppression
from worker.detection.types import PageData, ScanPageData, UAVariant
from worker.hashing import content_sha256

BASE_HTML = (
    "<html><head><title>Acme</title></head><body>"
    "<h1>Acme Corp</h1><p>Reliable widgets since 1970.</p>"
    "<a href='https://acme.com/about'>About</a>"
    "</body></html>"
)


def page(html: str) -> PageData:
    return PageData(html=html, final_url="https://acme.com/", content_hash=content_sha256(html))


def scan_page(html: str, ua_variants: list[UAVariant] | None = None) -> ScanPageData:
    return ScanPageData(
        html=html,
        final_url="https://acme.com/",
        content_hash=content_sha256(html),
        ua_variants=ua_variants or [],
    )


def _results_from_scores(scores: dict[str, float]) -> dict[str, dict]:
    out = {}
    for key in FEATURE_KEYS:
        s = scores.get(key)
        if s is None:
            out[key] = {"score": None, "skipped": True, "evidence": {"reason": "gated"}}
        else:
            out[key] = {"score": s, "evidence": {}}
    return out


def _vector(**overrides: float) -> dict[str, float]:
    scores = {key: 0.0 for key in FEATURE_KEYS}
    scores["layer1_hash"] = 1.0
    scores.update(overrides)
    return scores


def _applied(result: dict) -> list[dict]:
    return result["evidence"].get("rule_floor", {}).get("applied", [])


# --- pre-fix failing proofs: laundering is bounded below by floors ---


def test_padded_strong_signature_cannot_launder_below_floor() -> None:
    """A saturated strong-tier signature match padded with attacker-
    controlled hidden divs (l2 -> ~1.0) must stay at/above the signature
    floor; pre-fix this fused to ~0.10."""
    hidden_pad = "".join(f"<div style='display:none'>partner note {i}</div>" for i in range(15))
    current = BASE_HTML.replace(
        "<p>Reliable widgets since 1970.</p>", "<p>HACKED BY CYBER WARRIORS CREW</p>"
    ).replace("</body>", hidden_pad + "</body>")
    results = run_detection(page(BASE_HTML), scan_page(current))

    assert results["layer5_signatures"]["score"] >= 0.85
    assert results["layer9_fusion"]["score"] >= 0.90
    rules = _applied(results["layer9_fusion"])
    assert any(r["layer"] == "layer5_signatures" and r["floor"] == 0.90 for r in rules)


def test_severe_cloaking_with_churn_padding_stays_above_floor() -> None:
    """Cloaking evidence laundered via churn padding: pre-fix the vector
    [l7=0.95, l2=1.0] fused to ~0.03 despite crawlers being served a
    different site."""
    result = layer9_fusion(
        _results_from_scores(_vector(layer7_cloaking=0.95, layer2_dom_structure=1.0))
    )
    assert result["score"] >= 0.90
    assert any(r["layer"] == "layer7_cloaking" for r in _applied(result))


def test_severe_cloaking_with_hidden_padding_stays_above_floor_pipeline() -> None:
    """Same laundering through the real pipeline: googlebot sees an
    entirely different page while the browser-facing DOM is padded with
    hidden divs (no signature text present)."""
    spam = (
        "<html><body>"
        + " ".join(f"spam-token-{i} casino pills" for i in range(200))
        + "</body></html>"
    )
    hidden_pad = "".join(f"<div style='display:none'>partner note {i}</div>" for i in range(15))
    current = BASE_HTML.replace("</body>", hidden_pad + "</body>")
    variants = [
        UAVariant(
            ua_key=key,
            html=current if key != "googlebot" else spam,
            http_status=200,
            content_hash=content_sha256(current if key != "googlebot" else spam),
        )
        for key in ("desktop_chrome", "googlebot", "mobile_safari")
    ]
    results = run_detection(page(BASE_HTML), scan_page(current, ua_variants=variants))

    assert results["layer7_cloaking"]["score"] >= 0.85
    assert results["layer9_fusion"]["score"] >= 0.90


def test_new_external_script_domain_reaches_escalation_band_floor() -> None:
    """One injected <script src> on a brand-new domain must fuse to at
    least the infrastructure floor (inside the LLM escalation band);
    pre-fix this scenario fused to ~0.096 — invisible to everything."""
    current = BASE_HTML.replace(
        "</body>", "<script src='https://malware-cdn.example/inject.js'></script></body>"
    )
    results = run_detection(page(BASE_HTML), scan_page(current))

    assert results["layer3_link_audit"]["score"] >= 0.55
    assert results["layer9_fusion"]["score"] >= 0.40
    assert any(r["layer"] == "layer3_link_audit" for r in _applied(results["layer9_fusion"]))


def test_fallback_path_honors_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    """The floors are model-independent: even when the fitted model is
    unavailable, conclusive evidence keeps its floor (pre-fix the fallback
    returned max(sub-scores) = 0.87 here)."""
    from worker.detection import fusion

    def broken_model():
        raise RuntimeError("model exploded")

    monkeypatch.setattr(fusion, "get_fusion_model", broken_model)
    result = fusion.layer9_fusion(_results_from_scores(_vector(layer5_signatures=0.87)))
    assert result["score"] >= 0.90
    assert "fallback" in result["evidence"]["model"]
    assert any(r["layer"] == "layer5_signatures" for r in _applied(result))


# --- guards: floors must never fire on benign/ambiguous profiles ---


@pytest.mark.parametrize(
    "scores",
    [
        # clean rescan / all-zero
        dict.fromkeys(FEATURE_KEYS, 0.0),
        # dynamic-content noise (hash flips, tiny wiggle)
        _vector(layer2_dom_structure=0.05, layer4_visual_diff=0.03, layer8_semantics=0.05),
        # benign deploy: real changes, no hostile signals
        _vector(
            layer2_dom_structure=0.45,
            layer3_link_audit=0.3,
            layer4_visual_diff=0.4,
            layer6_security_metadata=0.15,
            layer8_semantics=0.3,
        ),
        # site redesign: heavy benign churn
        _vector(
            layer2_dom_structure=0.6,
            layer3_link_audit=0.35,
            layer4_visual_diff=0.55,
            layer6_security_metadata=0.1,
            layer8_semantics=0.4,
        ),
    ],
)
def test_benign_profiles_never_trip_floors(scores: dict[str, float]) -> None:
    result = layer9_fusion(_results_from_scores(scores))
    assert "rule_floor" not in result["evidence"]


@pytest.mark.parametrize("value", [0.55, 0.6, 0.7, 0.84])
def test_subtrigger_signature_evidence_does_not_floor(value: float) -> None:
    """Medium signatures (0.55), profanity bursts (cap 0.6), script flips
    (0.7) and just-below-trigger values need corroboration by design —
    no floor for them."""
    result = layer9_fusion(_results_from_scores(_vector(layer5_signatures=value)))
    assert "rule_floor" not in result["evidence"]


def test_single_light_ref_addition_does_not_floor() -> None:
    """One new <a href> external domain (weight 0.35 -> layer3 ≈ 0.27) is
    ordinary editorial churn — below the infrastructure trigger."""
    current = BASE_HTML.replace(
        "</body>", "<a href='https://linkspam.example/collect'>read more</a></body>"
    )
    results = run_detection(page(BASE_HTML), scan_page(current))
    assert results["layer3_link_audit"]["score"] < 0.55
    assert "rule_floor" not in results["layer9_fusion"]["evidence"]


def test_skipped_layers_do_not_trip_floors() -> None:
    """Identical-hash scan: every content layer is gated to score None;
    nothing may fire a floor off a skipped layer."""
    results = run_detection(page(BASE_HTML), scan_page(BASE_HTML))
    assert results["layer1_hash"]["score"] == 0.0
    assert results["layer2_dom_structure"]["skipped"] is True
    assert "rule_floor" not in results["layer9_fusion"]["evidence"]


def test_suppressed_injection_does_not_trip_infrastructure_floor() -> None:
    """Suppression runs before fusion: a rule covering the injected
    subtree removes it from BOTH sides, so layer 3 never sees the new
    domain and the infrastructure floor never fires."""
    current = BASE_HTML.replace(
        "</body>",
        "<div class='ad-injection'><script src='https://malware-cdn.example/inject.js'>"
        "</script></div></body>",
    )
    supp = build_suppression([("css_selector", ".ad-injection")])
    results = run_detection(page(BASE_HTML), scan_page(current), supp)

    assert results["layer3_link_audit"]["score"] < 0.55
    assert "rule_floor" not in results["layer9_fusion"]["evidence"]


def test_malformed_scores_cannot_trip_floors() -> None:
    results = _results_from_scores(_vector())
    results["layer5_signatures"] = {"score": "not-a-number", "evidence": {}}
    results["layer7_cloaking"] = {"score": float("nan"), "evidence": {}}
    result = layer9_fusion(results)
    assert "rule_floor" not in result["evidence"]
    assert 0.0 <= result["score"] <= 1.0


# --- monotonicity + boundaries ---


def test_score_is_monotone_in_attack_evidence() -> None:
    """More attack signal never lowers the final risk (system-level
    monotonicity, guaranteed structurally by max-composition)."""
    seen = -1.0
    for value in (0.0, 0.5, 0.84, 0.85, 0.86, 0.9, 1.0):
        result = layer9_fusion(
            _results_from_scores(_vector(layer2_dom_structure=0.6, layer5_signatures=value))
        )
        assert result["score"] >= seen
        seen = result["score"]


@pytest.mark.parametrize(
    ("overrides", "expected_layer"),
    [
        ({"layer3_link_audit": 0.549}, None),
        ({"layer3_link_audit": 0.55}, "layer3_link_audit"),
        ({"layer5_signatures": 0.849}, None),
        ({"layer5_signatures": 0.85}, "layer5_signatures"),
        ({"layer7_cloaking": 0.849}, None),
        ({"layer7_cloaking": 0.85}, "layer7_cloaking"),
    ],
)
def test_trigger_boundaries(overrides: dict[str, float], expected_layer: str | None) -> None:
    result = layer9_fusion(_results_from_scores(_vector(**overrides)))
    rules = _applied(result)
    if expected_layer is None:
        assert rules == []
    else:
        assert [r["layer"] for r in rules] == [expected_layer]


def test_floor_evidence_shape() -> None:
    result = layer9_fusion(_results_from_scores(_vector(layer5_signatures=1.0)))
    block = result["evidence"]["rule_floor"]
    assert block["model_probability"] >= 0.0
    entry = block["applied"][0]
    assert set(entry) == {"rule", "layer", "value", "floor"}
    assert entry["rule"] == "conclusive_signature_text"
    assert entry["floor"] == 0.90


def test_floor_never_lowers_a_high_model_score() -> None:
    """max-composition: when the model already scores above the floor,
    the final score equals the model probability exactly."""
    result = layer9_fusion(
        _results_from_scores(
            _vector(
                layer2_dom_structure=0.9,
                layer3_link_audit=0.8,
                layer4_visual_diff=0.85,
                layer5_signatures=1.0,
                layer6_security_metadata=0.5,
                layer8_semantics=0.9,
            )
        )
    )
    proba = result["evidence"]["rule_floor"]["model_probability"]
    # Evidence rounds to 4dp; the score itself is unrounded.
    assert result["score"] == pytest.approx(proba, abs=1e-4)
