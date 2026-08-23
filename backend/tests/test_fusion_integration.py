"""Fusion Arc Part C — integration guarantees for the deployed model.

Phase 10 wires the committed refit artifact
(worker/detection/training/fusion_model.json) into layer9_fusion,
replacing the seed-fitted scikit-learn model whose sign-inverted
coefficients (finding 5.1) let attacker-controlled churn launder
unsaturated attacks below every threshold. These tests pin, against the
RUNTIME path:

- the deployed model IS the committed artifact (coefficient identity),
  and it satisfies finding 5.1's structural property (no negative
  coefficients) — both failed before integration;
- laundering padding cannot reduce risk through the real fusion call —
  failed pre-integration (0.73 -> 0.05 under the seed fit);
- a server-side visual asset swap (Phase 6's structurally-undetectable
  class) now reaches flag-threshold territory end to end — failed
  pre-integration (fused ~0.13 at default threshold);
- missing/corrupt/invalid artifacts degrade loudly-but-gracefully to the
  documented fallback (floors still bind), never crash a scan;
- held-out benign-dynamic scenarios from the training dataset's TEST
  split stay below the flag threshold AND below the material-change
  cadence band (the constant was re-derived this phase from exactly
  these measurements);
- the operating-point constants stay coherent with each other.
"""

import json
import math
from pathlib import Path

import pytest

from app.scanning import MATERIAL_CHANGE_RISK
from worker.detection import fusion
from worker.detection.fusion import (
    FEATURE_KEYS,
    MODEL_ARTIFACT_PATH,
    get_fusion_model,
    layer9_fusion,
)
from worker.llm_escalation import ESCALATION_HIGH, ESCALATION_LOW

DATASET_PATH = Path(__file__).resolve().parents[1] / "worker/detection/training/fusion_dataset.json"

# Benign-dynamic axes named by the phase plan + measured pure-noise axes:
# their maximum fused risk on the untouched TEST split defines the floor
# the material-change band must sit above.
BENIGN_DYNAMIC_AXES_FLAG_GUARD = (
    "rotating_ad",
    "timestamp_counter",
    "cache_busting_refs",
    "ab_test_variant",
)
BENIGN_DYNAMIC_AXES_MATERIAL_GUARD = (
    *BENIGN_DYNAMIC_AXES_FLAG_GUARD,
    "minor_css_churn",
    "mixed_noise_combo",
    "editorial_update",
    "nonnative_editorial",
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


@pytest.fixture
def fresh_model_cache():
    """Isolate tests that swap or invalidate the process-wide model cache."""
    saved = fusion._model
    fusion._model = None
    yield
    fusion._model = saved


# --- deployed model == committed artifact ---------------------------------------


def test_runtime_model_matches_committed_artifact() -> None:
    artifact = json.loads(MODEL_ARTIFACT_PATH.read_text(encoding="utf-8"))
    model = get_fusion_model()
    assert model.coefficients == tuple(float(v) for v in artifact["model"]["coefficients"]), (
        "runtime must score with the committed refit, not a locally fitted surrogate"
    )
    assert model.intercept == float(artifact["model"]["intercept"])


def test_runtime_model_coefficients_non_negative() -> None:
    """Finding 5.1's property must hold in the deployed model itself: no
    evidence channel may carry negative weight (the seed fit shipped
    l2 = -6.54 / l6 = -1.39)."""
    model = get_fusion_model()
    assert all(math.isfinite(c) and c >= 0.0 for c in model.coefficients)
    assert math.isfinite(model.intercept)


def test_evidence_describes_deployed_model() -> None:
    result = layer9_fusion(_results_from_scores(_vector()))
    evidence = result["evidence"]
    assert "seed" not in evidence["model"]
    assert "constrained >= 0" in evidence["model"]
    artifact_block = evidence["model_artifact"]
    assert artifact_block["file"] == "fusion_model.json"
    stored = json.loads(MODEL_ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert artifact_block["dataset_sha256"] == stored["meta"]["dataset"]["sha256"]
    assert artifact_block["lambda_selected"] == stored["meta"]["fit"]["lambda_selected"]
    assert evidence["intercept"] == pytest.approx(stored["model"]["intercept"], abs=1e-4)


# --- finding 5.1 closed at runtime -----------------------------------------------


def test_laundering_padding_cannot_reduce_risk_runtime() -> None:
    """The audit's exact laundering demo through the REAL deployed fusion:
    padding benign DOM churn must never lower risk (pre-integration the
    stealthy profile fell 0.7337 -> 0.0518 under padding)."""
    profiles = {
        "stealthy": [1.0, 0.4, 0.85, 0.1, 0.0, 0.0, 0.0, 0.1],
        "semantic_rewrite": [1.0, 0.2, 0.05, 0.25, 0.3, 0.0, 0.0, 0.9],
        "signature_only": [1.0, 0.2, 0.1, 0.3, 1.0, 0.0, 0.0, 0.6],
    }
    for name, prof in profiles.items():
        base = layer9_fusion(_results_from_scores(dict(zip(FEATURE_KEYS, prof, strict=True))))[
            "score"
        ]
        for pad in (0.6, 0.8, 1.0):
            padded = list(prof)
            padded[1] = pad
            padded_score = layer9_fusion(
                _results_from_scores(dict(zip(FEATURE_KEYS, padded, strict=True)))
            )["score"]
            assert padded_score >= base - 1e-12, (name, pad, base, padded_score)


def test_deployed_fusion_monotone_in_every_feature() -> None:
    contexts = {
        "all_quiet": [0.0] * 8,
        "hash_flip_only": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "benign_redesign": [1.0, 0.6, 0.35, 0.55, 0.0, 0.15, 0.0, 0.4],
        "multi_signal_attack": [1.0, 0.8, 0.6, 0.9, 1.0, 0.0, 0.2, 0.8],
    }
    for _, base in contexts.items():
        for key in FEATURE_KEYS:
            prev = -1.0
            for step in range(11):
                vec = dict(zip(FEATURE_KEYS, base, strict=True))
                vec[key] = step / 10.0
                score = layer9_fusion(_results_from_scores(vec))["score"]
                assert score >= prev - 1e-12, (key, step, prev, score)
                prev = score


# --- Phase 6's class now reaches flag territory end to end ------------------------


def _png_pair():
    import io

    from PIL import Image, ImageDraw

    from worker.detection.pipeline import run_detection
    from worker.detection.types import PageData, ScanPageData
    from worker.hashing import content_sha256

    w, h = 683, 400
    html = "<html><body><h1>Acme</h1><p>Reliable widgets.</p></body></html>"

    def render(swaps=()):
        img = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([0, h - 40, w, h], fill=(235, 235, 235))
        for box, rgb in swaps:
            d.rectangle(box, fill=rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    clean = PageData(
        html=html,
        screenshot=render(),
        final_url="https://acme.com/",
        content_hash=content_sha256(html),
    )
    # Trivial byte wiggle flips the hash (opening the content layers)
    # without altering visible text — a comment REPLACING the heading
    # would delete a word, which the calibrated drift mapping honestly
    # measures as real semantic change on a two-word page.
    cur_html = html.replace("</h1>", "</h1><!--x-->")

    def scan(png):
        return ScanPageData(
            html=cur_html,
            screenshot=png,
            final_url="https://acme.com/",
            content_hash=content_sha256(cur_html),
        )

    control = run_detection(clean, scan(render()))
    defaced_png = render([((0, 24, w, h // 2), (10, 10, 10))])
    attack = run_detection(clean, scan(defaced_png))
    return control, attack


def test_visual_takeover_flags_end_to_end() -> None:
    """A server-side asset replacement that leaves the serialized DOM
    essentially unchanged (Phase 6's blind class) must now fuse ABOVE the
    default flag threshold — pre-integration it fused to ~0.13."""
    control, attack = _png_pair()
    l4 = attack["layer4_visual_diff"]["score"]
    assert l4 > 0.3, f"fixture must produce decisive visual divergence, got {l4}"
    assert control["layer9_fusion"]["score"] < 0.5
    assert attack["layer9_fusion"]["score"] >= 0.5, (
        f"visual takeover fused to {attack['layer9_fusion']['score']}"
    )


# --- artifact failure modes --------------------------------------------------------


def _write_artifact(tmp_path: Path, **mutations) -> Path:
    artifact = json.loads(MODEL_ARTIFACT_PATH.read_text(encoding="utf-8"))
    if mutations.get("schema_version") is not None:
        artifact["meta"]["schema_version"] = mutations["schema_version"]
    if mutations.get("feature_keys") is not None:
        artifact["meta"]["feature_keys"] = mutations["feature_keys"]
    if mutations.get("coefficients") is not None:
        artifact["model"]["coefficients"] = mutations["coefficients"]
    if mutations.get("drop_intercept"):
        del artifact["model"]["intercept"]
    path = tmp_path / "fusion_model.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_missing_artifact_degrades_gracefully(tmp_path, monkeypatch, fresh_model_cache) -> None:
    monkeypatch.setattr(fusion, "MODEL_ARTIFACT_PATH", tmp_path / "absent.json")
    scores = _vector(layer5_signatures=0.87)
    result = layer9_fusion(_results_from_scores(scores))
    assert "fallback" in result["evidence"]["model"]
    assert result["score"] >= 0.90, "floors must survive an unusable artifact"
    assert 0.0 <= result["score"] <= 1.0


def test_corrupt_artifact_degrades_gracefully(tmp_path, monkeypatch, fresh_model_cache) -> None:
    bad = tmp_path / "fusion_model.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(fusion, "MODEL_ARTIFACT_PATH", bad)
    result = layer9_fusion(_results_from_scores(_vector(layer5_signatures=0.87)))
    assert "fallback" in result["evidence"]["model"]
    assert result["score"] >= 0.90


@pytest.mark.parametrize(
    ("mutation", "kwargs"),
    [
        ("schema_version", {"schema_version": 99}),
        ("feature_order", {"feature_keys": list(reversed(FEATURE_KEYS))}),
        ("negative_coef", {"coefficients": [1.0, -0.5, 0, 0, 0, 0, 0, 0]}),
        ("wrong_width", {"coefficients": [1.0, 2.0, 3.0]}),
        ("missing_intercept", {"drop_intercept": True}),
    ],
)
def test_invalid_artifacts_refused(
    tmp_path, monkeypatch, fresh_model_cache, mutation: str, kwargs: dict
) -> None:
    path = _write_artifact(tmp_path, **kwargs)
    monkeypatch.setattr(fusion, "MODEL_ARTIFACT_PATH", path)
    with pytest.raises(RuntimeError):
        get_fusion_model()


def test_failed_load_is_not_cached(monkeypatch, tmp_path, fresh_model_cache) -> None:
    """A broken artifact must not poison the process cache: fixing the file
    takes effect on the next call without a restart."""
    good = json.loads(MODEL_ARTIFACT_PATH.read_text(encoding="utf-8"))
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{broken", encoding="utf-8")
    p2.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(fusion, "MODEL_ARTIFACT_PATH", p1)
    with pytest.raises(RuntimeError):
        get_fusion_model()
    monkeypatch.setattr(fusion, "MODEL_ARTIFACT_PATH", p2)
    model = get_fusion_model()
    assert model.coefficients == tuple(float(v) for v in good["model"]["coefficients"])


# --- held-out operating-point guards (dataset TEST split) -------------------------


def _test_split_axis_max(axis: str) -> float:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    samples = [s for s in dataset["samples"] if s["split"] == "test" and s["axis"] == axis]
    assert samples, f"axis {axis} absent from TEST split"
    worst = 0.0
    for s in samples:
        scores = dict(zip(FEATURE_KEYS, s["features"], strict=True))
        worst = max(worst, layer9_fusion(_results_from_scores(scores))["score"])
    return worst


def test_heldout_benign_dynamic_axes_never_flag() -> None:
    """The phase plan's acceptance set — ads rotating, timestamps,
    cache-busting params, A/B variants — on the split reserved for this
    validation: none may reach the default flag threshold."""
    for axis in BENIGN_DYNAMIC_AXES_FLAG_GUARD:
        worst = _test_split_axis_max(axis)
        assert worst < 0.5, f"{axis} fused to {worst:.4f} on held-out benign dynamics"


def test_benign_dynamic_noise_stays_below_material_change_band() -> None:
    """MATERIAL_CHANGE_RISK was re-derived this phase from these rows: pure
    dynamic noise fuses to ~0.22-0.27 under the deployed model, so the band
    must sit above every such scenario or 'adaptive' scanning would mean
    'permanently tightened' (scanning.py's own stated invariant)."""
    for axis in BENIGN_DYNAMIC_AXES_MATERIAL_GUARD:
        worst = _test_split_axis_max(axis)
        assert worst < MATERIAL_CHANGE_RISK, f"{axis} fused to {worst:.4f}"


# --- constant coherence ------------------------------------------------------------


def test_operating_point_constants_coherent() -> None:
    """The floors were tuned against the escalation band; the material-
    change bar is deliberately the same number as the band's floor."""
    infra_floor = next(f for k, t, f, n in fusion._RULE_FLOORS if k == "layer3_link_audit")
    assert MATERIAL_CHANGE_RISK == ESCALATION_LOW
    assert ESCALATION_LOW <= infra_floor < ESCALATION_HIGH
    for key, _trigger, floor, _name in fusion._RULE_FLOORS:
        if key in ("layer5_signatures", "layer7_cloaking"):
            assert floor >= ESCALATION_HIGH
