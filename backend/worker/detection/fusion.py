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

Rule-based minimum-risk floors: the fitted model arbitrates between
attack profiles and benign-churn profiles that share coarse feature
values, which historically let attacker-controlled benign churn cancel
strong hostile evidence through sign-inverted coefficients (padding a
conclusive "HACKED BY" match with a handful of hidden divs fused to
~0.10). Floors bound the FINAL score from below wherever individual
layer evidence is unambiguous — independent of any future refit of the
model, because they read only the fixed FEATURE_KEYS vector and compose
monotonically (final = max(model probability, floors)). Trigger tiers
follow signal specificity: near-zero-benign-base-rate evidence floors at
flag-threshold territory; evidence legitimate sites also produce
occasionally (new external vendor scripts) floors into the LLM
escalation band, so ambiguity routes to the semantic second opinion
instead of auto-alerting.
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

# --- Rule-based minimum-risk floors ---
# (feature key, fires at score >=, floor applied, rule name).
#
# Triggers sit where benign base rates are negligible or the response is
# deliberately non-alarming:
# - Strong-tier defacement signatures are "essentially conclusive on
#   their own" (layer 5's own contract); medium patterns weigh 0.55 and
#   profanity bursts cap at 0.6, so only a strong hit (or multiple
#   mediums) reaches the trigger. Floor: flag-threshold territory — this
#   evidence must never be cancellable by churn padding.
# - Crawler-vs-browser divergence >= 0.85 means crawlers are served a
#   different site; benign dynamic variation stays at 0.0 via layer 7's
#   soft knee, so the same conclusive tier applies.
# - A brand-new external script/iframe/form-action domain (or ~3 lighter
#   new-domain refs) appeared and the content hash flipped (layer 3 can
#   not run otherwise). Trigger 0.55 == weighted new-domain count >=
#   ~0.89 on layer 3's saturation curve (1 - e^(-0.9 * w)). Legitimate
#   sites do add vendor scripts, so the floor lands INSIDE the LLM
#   escalation band ([ESCALATION_LOW, ESCALATION_HIGH)) rather than at
#   the flag threshold: cadence tightens and the semantic second opinion
#   engages, but a lone ambiguous vector never auto-alerts.
_RULE_FLOORS: tuple[tuple[str, float, float, str], ...] = (
    ("layer5_signatures", 0.85, 0.90, "conclusive_signature_text"),
    ("layer7_cloaking", 0.85, 0.90, "severe_cloaking"),
    ("layer3_link_audit", 0.55, 0.40, "new_sensitive_infrastructure"),
)


def _rule_floor(features_by_key: dict[str, float]) -> tuple[float, list[dict]]:
    """Strongest floor whose trigger fired, plus per-rule evidence.

    Reads coerced feature values only, so skipped/malformed layers (0.0)
    can never fire a floor. Never raises."""
    applied = 0.0
    fired: list[dict] = []
    for key, trigger, floor, name in _RULE_FLOORS:
        value = features_by_key.get(key)
        if value is not None and value >= trigger:
            applied = max(applied, floor)
            fired.append({"rule": name, "layer": key, "value": round(value, 4), "floor": floor})
    return applied, fired


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
    """Fuse layers 1-8 into one risk score: the fitted model's
    probability, lifted to at least any fired rule floor (see
    _RULE_FLOORS). Never raises: any failure (malformed input, broken
    model fit) degrades to max(fallback sub-score, floors) with a note —
    the floors are model-independent and survive even a broken fit."""
    features: list[float] = []
    ran: dict[str, bool] = {}
    try:
        features, ran = build_feature_vector(layer_results)
        floor_value, floor_rules = _rule_floor(dict(zip(FEATURE_KEYS, features, strict=True)))
        model = get_fusion_model()
        proba = float(model.predict_proba(np.array([features]))[0][1])
        score = max(proba, floor_value)
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
        if floor_rules:
            evidence["rule_floor"] = {
                "applied": floor_rules,
                "model_probability": round(proba, 4),
            }
        return layer_result(score, evidence)
    except Exception as exc:
        logger.exception("Fusion model failed; degrading to max sub-score")
        fallback = max(features) if features else 0.0
        # Floors are independent of the fitted model, so they still bind
        # when the fit itself is unavailable. zip non-strict: features may
        # be empty/partial if the vector build itself failed.
        floor_value, floor_rules = _rule_floor(dict(zip(FEATURE_KEYS, features, strict=False)))
        evidence = {
            "model": "fallback_max (fusion model unavailable)",
            "error": str(exc)[:200],
            "features": {k: round(v, 4) for k, v in zip(FEATURE_KEYS, features, strict=False)},
            "layers_ran": ran,
        }
        if floor_rules:
            evidence["rule_floor"] = {"applied": floor_rules}
        return layer_result(
            max(fallback, floor_value),
            evidence,
        )
