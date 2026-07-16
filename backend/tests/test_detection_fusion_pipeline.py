"""Detection layers 6-9 + pipeline unit tests: security metadata,
cloaking, semantics (lexicon parts — MiniLM embedding is exercised in the
live-stack verification, mocked here), fusion, and gating."""

import pytest

from worker.detection import pipeline as pipeline_mod
from worker.detection.cloaking import layer7_cloaking
from worker.detection.fusion import (
    FEATURE_KEYS,
    build_feature_vector,
    get_fusion_model,
    layer9_fusion,
)
from worker.detection.metadata import layer6_security_metadata
from worker.detection.pipeline import run_detection
from worker.detection.semantics import layer8_semantics
from worker.detection.types import PageData, ScanPageData, UAVariant
from worker.hashing import content_sha256

HTML = "<html><body><h1>Acme</h1><p>Reliable widgets.</p></body></html>"


def page(html: str = HTML, **kwargs) -> PageData:
    defaults = {"final_url": "https://acme.com/", "content_hash": content_sha256(html)}
    defaults.update(kwargs)
    return PageData(html=html, **defaults)


def scan_page(html: str = HTML, **kwargs) -> ScanPageData:
    defaults = {"final_url": "https://acme.com/", "content_hash": content_sha256(html)}
    defaults.update(kwargs)
    return ScanPageData(html=html, **defaults)


def _score(result: dict) -> float:
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["evidence"], dict)
    return result["score"]


TLS_A = {
    "fingerprint_sha256": "a" * 64,
    "not_after": "2027-01-01T00:00:00+00:00",
    "expired": False,
    "subject": "CN=acme.com",
    "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
}
HEADERS_SECURE = {
    "content-security-policy": "default-src 'self'",
    "strict-transport-security": "max-age=63072000",
    "x-frame-options": "DENY",
    "content-type": "text/html",
}


# --- layer 6: security metadata ---


def test_layer6_no_changes() -> None:
    b = page(tls=dict(TLS_A), headers=dict(HEADERS_SECURE), robots_txt="User-agent: *")
    c = page(tls=dict(TLS_A), headers=dict(HEADERS_SECURE), robots_txt="User-agent: *")
    assert _score(layer6_security_metadata(b, c)) == 0.0


def test_layer6_no_metadata_at_all() -> None:
    result = layer6_security_metadata(page(), page())
    assert _score(result) == 0.0
    assert "note" in result["evidence"]["tls"]


def test_layer6_cert_reissue_same_issuer_scores_low() -> None:
    new_tls = dict(TLS_A, fingerprint_sha256="b" * 64)
    result = layer6_security_metadata(page(tls=dict(TLS_A)), page(tls=new_tls))
    assert 0.0 < _score(result) <= 0.2
    assert result["evidence"]["tls"]["fingerprint_changed"] is True


def test_layer6_cert_issuer_change_scores_higher() -> None:
    new_tls = dict(TLS_A, fingerprint_sha256="b" * 64, issuer="CN=Sketchy CA,C=XX")
    result = layer6_security_metadata(page(tls=dict(TLS_A)), page(tls=new_tls))
    assert _score(result) >= 0.5
    assert result["evidence"]["tls"]["issuer_changed"] is True


def test_layer6_expired_cert_flagged() -> None:
    new_tls = dict(TLS_A, expired=True)
    result = layer6_security_metadata(page(tls=dict(TLS_A)), page(tls=new_tls))
    assert _score(result) >= 0.5
    assert result["evidence"]["tls"]["expired"] is True


def test_layer6_security_header_removed() -> None:
    weakened = {k: v for k, v in HEADERS_SECURE.items() if k != "content-security-policy"}
    result = layer6_security_metadata(page(headers=HEADERS_SECURE), page(headers=weakened))
    assert _score(result) >= 0.3
    assert result["evidence"]["headers"]["security_headers_removed"] == ["content-security-policy"]


def test_layer6_header_added_is_not_a_threat() -> None:
    more = dict(HEADERS_SECURE, **{"referrer-policy": "no-referrer"})
    result = layer6_security_metadata(page(headers=HEADERS_SECURE), page(headers=more))
    assert _score(result) == 0.0
    assert "referrer-policy" in result["evidence"]["headers"]["security_headers_added"]


def test_layer6_robots_txt_changed() -> None:
    result = layer6_security_metadata(
        page(robots_txt="User-agent: *\nDisallow:"),
        page(robots_txt="User-agent: *\nDisallow: /\n# pwned"),
    )
    assert _score(result) > 0.0
    assert result["evidence"]["robots_txt"]["changed"] is True


def test_layer6_degraded_header_probe_not_a_downgrade() -> None:
    """A scan whose header probe failed (empty map) must not report every
    baseline security header as removed."""
    result = layer6_security_metadata(page(headers=HEADERS_SECURE), page(headers={}))
    assert result["evidence"]["headers"].get("security_headers_removed") is None
    assert "note" in result["evidence"]["headers"]
    assert _score(result) == 0.0


def test_layer6_tls_data_lost_scores_moderate() -> None:
    result = layer6_security_metadata(page(tls=dict(TLS_A)), page(tls=None))
    assert 0.4 <= _score(result) <= 0.8


# --- layer 7: cloaking ---


def _variant(ua_key: str, html: str, status: int = 200, **kwargs) -> UAVariant:
    return UAVariant(
        ua_key=ua_key,
        html=html,
        http_status=status,
        content_hash=content_sha256(html) if html else "",
        **kwargs,
    )


def test_layer7_consistent_across_uas() -> None:
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", HTML),
            _variant("googlebot", HTML),
            _variant("mobile_safari", HTML),
        ]
    )
    result = layer7_cloaking(page(), current)
    assert _score(result) == 0.0
    comparable = [v for v in result["evidence"]["variants"] if v["comparable"]]
    assert all(v.get("similarity") == 1.0 for v in comparable)


def test_layer7_cloaked_googlebot_detected() -> None:
    spam = "<html><body><h1>Cheap pills casino</h1><p>spam spam spam links</p></body></html>"
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", HTML),
            _variant("googlebot", spam),
            _variant("mobile_safari", HTML),
        ]
    )
    result = layer7_cloaking(page(), current)
    assert _score(result) >= 0.7


def test_layer7_bot_blocking_is_not_cloaking() -> None:
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", HTML),
            _variant("googlebot", "<html><body>403 Forbidden</body></html>", status=403),
            _variant("mobile_safari", HTML),
        ]
    )
    assert _score(layer7_cloaking(page(), current)) == 0.0


def test_layer7_variant_fetch_error_degrades() -> None:
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", HTML),
            UAVariant(ua_key="googlebot", error="ConnectTimeout: ..."),
        ]
    )
    result = layer7_cloaking(page(), current)
    assert _score(result) == 0.0


def test_layer7_no_variants_at_all() -> None:
    result = layer7_cloaking(page(), scan_page())
    assert _score(result) == 0.0
    assert "note" in result["evidence"]


def test_layer7_unusable_reference_degrades() -> None:
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", "", status=500),
            _variant("googlebot", HTML),
        ]
    )
    result = layer7_cloaking(page(), current)
    assert _score(result) == 0.0
    assert "reference" in result["evidence"]["note"]


def test_layer7_mild_dynamic_variation_below_knee() -> None:
    slightly_different = HTML.replace("Reliable widgets.", "Reliable widgets. Visitor #42")
    current = scan_page(
        ua_variants=[
            _variant("desktop_chrome", HTML),
            _variant("googlebot", slightly_different),
        ]
    )
    assert _score(layer7_cloaking(page(), current)) == 0.0


# --- layer 8: semantics (lexicon paths; embeddings mocked) ---


@pytest.fixture(autouse=True)
def no_network_embeddings(monkeypatch: pytest.MonkeyPatch):
    """Unit tests never download MiniLM: embed_text -> None (the layer's
    documented degraded mode). The live-stack check covers real inference."""
    from worker.detection import semantics

    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


def test_layer8_clean_rescan_scores_zero() -> None:
    assert _score(layer8_semantics(page(), page())) == 0.0


def test_layer8_aggression_lexicon() -> None:
    angry = HTML.replace(
        "<p>Reliable widgets.</p>",
        "<p>You will pay the price. We will be back. No one is safe.</p>",
    )
    result = layer8_semantics(page(), page(angry))
    assert _score(result) >= 0.6
    assert result["evidence"]["aggression_hits"]


def test_layer8_topic_keywords() -> None:
    braggy = HTML.replace(
        "<p>Reliable widgets.</p>",
        "<p>Your database dumped and leaked data on t.me/xyz — total breach.</p>",
    )
    result = layer8_semantics(page(), page(braggy))
    assert _score(result) >= 0.35
    assert "breach_bragging" in result["evidence"]["topic_hits"]


def test_layer8_embeddings_unavailable_degrades() -> None:
    result = layer8_semantics(page(), page(HTML.replace("Acme", "Bcme")))
    assert result["evidence"]["semantic_similarity"] is None  # degraded, not crashed
    assert 0.0 <= result["score"] <= 1.0


def test_layer8_baseline_text_never_flags() -> None:
    threat_blog = HTML.replace(
        "<p>Reliable widgets.</p>", "<p>Analysis: attackers said 'no one is safe'.</p>"
    )
    assert _score(layer8_semantics(page(threat_blog), page(threat_blog))) == 0.0


# --- layer 9: fusion ---


def _results_from_scores(scores: dict[str, float | None]) -> dict[str, dict]:
    out = {}
    for key in FEATURE_KEYS:
        s = scores.get(key)
        if s is None:
            out[key] = {"score": None, "skipped": True, "evidence": {"reason": "gated"}}
        else:
            out[key] = {"score": s, "evidence": {}}
    return out


def test_fusion_model_is_deterministic() -> None:
    m1, m2 = get_fusion_model(), get_fusion_model()
    assert m1 is m2  # process cache


def test_fusion_all_clean_scores_low() -> None:
    result = layer9_fusion(_results_from_scores(dict.fromkeys(FEATURE_KEYS, 0.0)))
    assert result["score"] < 0.2


def test_fusion_full_defacement_scores_high() -> None:
    result = layer9_fusion(
        _results_from_scores(
            {
                "layer1_hash": 1.0,
                "layer2_dom_structure": 0.9,
                "layer3_link_audit": 0.8,
                "layer4_visual_diff": 0.85,
                "layer5_signatures": 1.0,
                "layer6_security_metadata": 0.5,
                "layer7_cloaking": 0.0,
                "layer8_semantics": 0.9,
            }
        )
    )
    assert result["score"] > 0.8


def test_fusion_dynamic_noise_scores_low() -> None:
    result = layer9_fusion(
        _results_from_scores(
            {
                "layer1_hash": 1.0,
                "layer2_dom_structure": 0.05,
                "layer3_link_audit": 0.0,
                "layer4_visual_diff": 0.03,
                "layer5_signatures": 0.0,
                "layer6_security_metadata": 0.0,
                "layer7_cloaking": 0.0,
                "layer8_semantics": 0.0,
            }
        )
    )
    assert result["score"] < 0.35


def test_fusion_signature_hit_dominates() -> None:
    result = layer9_fusion(
        _results_from_scores(
            {
                "layer1_hash": 1.0,
                "layer2_dom_structure": 0.2,
                "layer3_link_audit": 0.1,
                "layer4_visual_diff": 0.25,
                "layer5_signatures": 1.0,
                "layer6_security_metadata": 0.0,
                "layer7_cloaking": 0.0,
                "layer8_semantics": 0.55,
            }
        )
    )
    assert result["score"] > 0.6


def test_fusion_cloaking_alone_flags() -> None:
    scores = dict.fromkeys(FEATURE_KEYS, 0.0)
    scores["layer7_cloaking"] = 0.95
    result = layer9_fusion(_results_from_scores(scores))
    assert result["score"] > 0.5


def test_fusion_skipped_layers_masked() -> None:
    results = _results_from_scores(
        {
            "layer1_hash": 0.0,
            "layer2_dom_structure": None,
            "layer3_link_audit": None,
            "layer4_visual_diff": None,
            "layer5_signatures": None,
            "layer6_security_metadata": 0.0,
            "layer7_cloaking": 0.0,
            "layer8_semantics": None,
        }
    )
    vector, ran = build_feature_vector(results)
    assert vector == [0.0] * 8
    assert ran["layer2_dom_structure"] is False
    assert layer9_fusion(results)["score"] < 0.2


def test_fusion_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker.detection import fusion

    def broken_model():
        raise RuntimeError("model exploded")

    monkeypatch.setattr(fusion, "get_fusion_model", broken_model)
    scores = dict.fromkeys(FEATURE_KEYS, 0.0)
    scores["layer5_signatures"] = 0.9
    result = fusion.layer9_fusion(_results_from_scores(scores))
    assert result["score"] == 0.9  # fallback: max sub-score
    assert "fallback" in result["evidence"]["model"]


# --- pipeline gating ---


def test_pipeline_identical_hash_gates_content_layers() -> None:
    results = run_detection(page(), scan_page())
    assert results["layer1_hash"]["score"] == 0.0
    for gated in (
        "layer2_dom_structure",
        "layer3_link_audit",
        "layer4_visual_diff",
        "layer5_signatures",
        "layer8_semantics",
    ):
        assert results[gated]["skipped"] is True
        assert "gated by layer 1" in results[gated]["evidence"]["reason"]
    # Metadata + cloaking still ran.
    assert "skipped" not in results["layer6_security_metadata"]
    assert "skipped" not in results["layer7_cloaking"]
    assert results["layer9_fusion"]["score"] is not None


def test_pipeline_changed_hash_runs_all_layers() -> None:
    changed = HTML.replace("Acme", "HACKED BY XYZ")
    results = run_detection(page(), scan_page(changed))
    for _, key in pipeline_mod.LAYERS:
        assert key in results
        if key != "layer9_fusion":
            assert not results[key].get("skipped"), key


def test_pipeline_layer_crash_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding(baseline, current):
        raise RuntimeError("parser exploded")

    monkeypatch.setitem(pipeline_mod._LAYER_FUNCS, "layer5_signatures", exploding)
    results = run_detection(page(), scan_page(HTML.replace("Acme", "Other")))
    assert results["layer5_signatures"]["skipped"] is True
    assert "RuntimeError" in results["layer5_signatures"]["evidence"]["error"]
    # Everything else still produced results, and fusion still fused.
    assert results["layer2_dom_structure"]["score"] is not None
    assert results["layer9_fusion"]["score"] is not None


def test_pipeline_missing_baseline_html_skips_content_layers() -> None:
    baseline = page("")  # artifact lost; hash retained
    baseline.content_hash = "0" * 64
    results = run_detection(baseline, scan_page(HTML))
    assert results["layer1_hash"]["score"] == 1.0
    assert results["layer2_dom_structure"]["skipped"] is True
    assert "artifact unavailable" in results["layer2_dom_structure"]["evidence"]["reason"]
    # Visual diff can still run (screenshot artifact is independent).
    assert "layer4_visual_diff" in results
