"""Layer 9 — fusion classifier (§5): one calibrated risk score from the
eight sub-scores via scikit-learn logistic regression.

No labeled scan history exists at install time, so the model is fitted
at first use on a *seed dataset*: layer-score vectors for documented
scenarios (clean rescans, dynamic-content noise, benign deploys, partial
and full defacements). The scenarios encode the same domain knowledge a
hand-tuned weighted sum would — but going through LogisticRegression
gives calibrated probabilities now and a drop-in upgrade path later:
once enough per-site scan history with user verdicts accumulates,
retraining on real rows (and stepping up to gradient boosting, per §5)
replaces the seed set without touching the pipeline.

The fitted model is cached per worker process; fitting is deterministic
(fixed seed data, lbfgs). Skipped layers contribute their gate value
(layer 1 identical -> downstream layers "identical too") or 0.0, with a
`ran` mask in evidence so the UI can show which layers actually voted.
"""

import logging
import math
import threading

import numpy as np
from sklearn.linear_model import LogisticRegression

from worker.detection.types import layer_result

logger = logging.getLogger(__name__)

# Feature order — one score per layer 1-8, fixed forever (retraining on
# real history must produce compatible vectors).
FEATURE_KEYS = [
    "layer1_hash",
    "layer2_dom_structure",
    "layer3_link_audit",
    "layer4_visual_diff",
    "layer5_signatures",
    "layer6_security_metadata",
    "layer7_cloaking",
    "layer8_semantics",
]

# Seed scenarios: (layer scores 1-8, label). Label 1 = defacement.
# Grounded in how the layers actually score (see each layer's docstring):
_SEED_ROWS: list[tuple[list[float], int]] = [
    # -- clean: identical page (layer 1 gates everything downstream)
    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0),
    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.0, 0.0], 0),
    # -- dynamic content noise: hash flips, tiny DOM/visual wiggle
    ([1.0, 0.05, 0.0, 0.02, 0.0, 0.0, 0.0, 0.0], 0),
    ([1.0, 0.1, 0.05, 0.05, 0.0, 0.0, 0.0, 0.05], 0),
    ([1.0, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.0], 0),
    ([1.0, 0.15, 0.1, 0.08, 0.0, 0.1, 0.0, 0.1], 0),
    # -- benign deploy: real changes, no hostile signals
    ([1.0, 0.35, 0.25, 0.3, 0.0, 0.0, 0.0, 0.2], 0),
    ([1.0, 0.45, 0.3, 0.4, 0.0, 0.15, 0.0, 0.3], 0),
    ([1.0, 0.3, 0.4, 0.25, 0.0, 0.0, 0.0, 0.15], 0),
    # -- site redesign: heavy but benign churn (no signature/cloaking)
    ([1.0, 0.6, 0.35, 0.55, 0.0, 0.1, 0.0, 0.4], 0),
    # -- cert rotation / header tweaks only
    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.0, 0.0], 0),
    ([1.0, 0.05, 0.0, 0.03, 0.0, 0.55, 0.0, 0.0], 0),
    # -- classic full defacement: everything screams
    ([1.0, 0.9, 0.8, 0.85, 1.0, 0.5, 0.0, 0.9], 1),
    ([1.0, 0.8, 0.6, 0.9, 1.0, 0.0, 0.0, 0.8], 1),
    ([1.0, 0.95, 0.9, 0.95, 0.9, 0.6, 0.2, 0.95], 1),
    # -- stealthy injection: small DOM change, new script domain
    ([1.0, 0.4, 0.85, 0.1, 0.0, 0.0, 0.0, 0.1], 1),
    ([1.0, 0.3, 0.9, 0.05, 0.0, 0.2, 0.0, 0.0], 1),
    # -- signature-only (text replaced, layout kept)
    ([1.0, 0.2, 0.1, 0.3, 1.0, 0.0, 0.0, 0.6], 1),
    ([1.0, 0.15, 0.0, 0.2, 0.85, 0.0, 0.0, 0.5], 1),
    # -- cloaking: browser view clean-ish, crawler sees different page
    ([1.0, 0.1, 0.1, 0.05, 0.0, 0.0, 0.9, 0.2], 1),
    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.95, 0.0], 1),
    # -- semantic rewrite (content meaning flipped, structure kept)
    ([1.0, 0.2, 0.05, 0.25, 0.3, 0.0, 0.0, 0.9], 1),
    ([1.0, 0.25, 0.15, 0.35, 0.55, 0.1, 0.0, 0.85], 1),
    # -- visual takeover (image-based defacement, DOM barely moves)
    ([1.0, 0.15, 0.05, 0.9, 0.0, 0.0, 0.0, 0.3], 1),
    ([1.0, 0.1, 0.0, 0.95, 0.2, 0.0, 0.0, 0.2], 1),
]

_model: LogisticRegression | None = None
_model_lock = threading.Lock()


def get_fusion_model() -> LogisticRegression:
    """Deterministic seed-fitted logistic regression, cached per process."""
    global _model
    with _model_lock:
        if _model is None:
            X = np.array([row for row, _ in _SEED_ROWS], dtype=np.float64)
            y = np.array([label for _, label in _SEED_ROWS], dtype=np.int64)
            model = LogisticRegression(C=50.0, solver="lbfgs", max_iter=5000)
            model.fit(X, y)
            _model = model
        return _model


def _coerce_score(value) -> float:
    """A layer score coerced to a finite float in [feature space]. A
    malformed value (non-numeric, NaN, inf) contributes 0.0 rather than
    raising — a single bad sub-score must not take out the whole layer."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(num):
        return 0.0
    return num


def build_feature_vector(layer_results: dict[str, dict]) -> tuple[list[float], dict[str, bool]]:
    """Flatten per-layer results into the fixed feature order. A skipped
    layer contributes 0.0 (its gate already established 'no change') and
    is marked ran=False. A present-but-malformed score also contributes 0.0
    (see _coerce_score) so fusion stays robust to a misbehaving layer."""
    features: list[float] = []
    ran: dict[str, bool] = {}
    for key in FEATURE_KEYS:
        result = layer_results.get(key)
        if result is None or result.get("skipped"):
            features.append(0.0)
            ran[key] = False
        else:
            features.append(_coerce_score(result.get("score")))
            ran[key] = True
    return features, ran


def layer9_fusion(layer_results: dict[str, dict]) -> dict:
    """Fuse layers 1-8 into one calibrated risk score. Never raises: any
    failure (malformed input, broken model fit) degrades to the max
    sub-score with a note."""
    features: list[float] = []
    ran: dict[str, bool] = {}
    try:
        features, ran = build_feature_vector(layer_results)
        model = get_fusion_model()
        proba = float(model.predict_proba(np.array([features]))[0][1])
        contributions = {
            key: round(float(coef) * val, 4)
            for key, coef, val in zip(FEATURE_KEYS, model.coef_[0], features, strict=True)
        }
        evidence = {
            "model": "logistic_regression (seed-fitted, scikit-learn)",
            "features": {k: round(v, 4) for k, v in zip(FEATURE_KEYS, features, strict=True)},
            "layers_ran": ran,
            "contributions": contributions,
            "intercept": round(float(model.intercept_[0]), 4),
            "upgrade_path": (
                "retrain on labeled scan history; gradient boosting once volume allows (§5)"
            ),
        }
        return layer_result(proba, evidence)
    except Exception as exc:
        logger.exception("Fusion model failed; degrading to max sub-score")
        fallback = max(features) if features else 0.0
        return layer_result(
            fallback,
            {
                "model": "fallback_max (fusion model unavailable)",
                "error": str(exc)[:200],
                # zip without strict: features may be empty if the vector
                # build itself failed — the fallback must still return.
                "features": {k: round(v, 4) for k, v in zip(FEATURE_KEYS, features, strict=False)},
                "layers_ran": ran,
            },
        )
