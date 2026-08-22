"""Layer 9 — fusion classifier (§5): one risk score from the eight
sub-scores via logistic regression.

No labeled scan history exists at install time, so the deployed model is
a committed ARTIFACT (training/fusion_model.json): a MAP-fit logistic
regression whose coefficients were constrained >= 0 during fitting, so
fused risk is monotone in every evidence channel by construction — more
evidence can never lower the score. The artifact was fitted exclusively
on measured layer outputs (see training/fusion_dataset.json and
tools/refit_fusion_model.py, which record the fit's provenance,
cross-validation, and held-out calibration); loading validates the
schema, the FEATURE_KEYS order, and the non-negativity constraint, and
refuses anything else rather than silently scoring with a foreign model.
The loaded model is cached per process.

The score is a ranking signal in [0, 1], not a calibrated probability:
the coarse eight-dimensional feature space cannot separate some profiles
(notably "operator added third-party scripts" from "attacker injected
scripts" — the measured vectors collide), and per-site suppression rules
plus the human confirm queue are the designed mitigations where the
features genuinely cannot decide.

Rule-based minimum-risk floors: floors bound the FINAL score from below
wherever individual layer evidence is unambiguous — independent of any
future refit of the model, because they read only the fixed FEATURE_KEYS
vector and compose monotonically (final = max(model probability,
floors)). They guarantee that low-churn single-vector shapes stay
visible inside the LLM escalation band even when the model's estimate
alone would fall below it. Skipped layers contribute 0.0 with a `ran`
mask in evidence so the UI can show which layers actually voted.

Any failure (missing/corrupt artifact, malformed input) degrades to
max(fallback sub-score, floors) with a note — detection never crashes
because its classifier is unavailable.
"""

import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

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

# Deployed model artifact: produced by tools/refit_fusion_model.py from
# the measured dataset in training/fusion_dataset.json (provenance, CV
# table, and held-out calibration are recorded inside the artifact).
MODEL_ARTIFACT_PATH = Path(__file__).resolve().parent / "training" / "fusion_model.json"

_ARTIFACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FusionModel:
    coefficients: tuple[float, ...]
    intercept: float
    lambda_selected: float | None
    dataset_sha256: str | None


_model: FusionModel | None = None
_model_lock = threading.Lock()


def _load_fusion_model(path: Path) -> FusionModel:
    """Read + validate the committed artifact; raise on anything that is
    not exactly the schema the runtime expects. A silently-wrong model is
    worse than no model (the caller degrades to a documented fallback)."""
    artifact = json.loads(path.read_text(encoding="utf-8"))
    meta = artifact.get("meta")
    model = artifact.get("model")
    if not isinstance(meta, dict) or not isinstance(model, dict):
        raise RuntimeError(f"{path.name}: missing meta/model sections")
    if meta.get("schema_version") != _ARTIFACT_SCHEMA_VERSION:
        raise RuntimeError(
            f"{path.name}: schema_version {meta.get('schema_version')!r} "
            f"!= {_ARTIFACT_SCHEMA_VERSION}"
        )
    if meta.get("feature_keys") != list(FEATURE_KEYS):
        raise RuntimeError(f"{path.name}: feature_keys diverge from runtime FEATURE_KEYS order")
    raw_coefs = model.get("coefficients")
    intercept = model.get("intercept")
    if not isinstance(raw_coefs, list) or len(raw_coefs) != len(FEATURE_KEYS):
        raise RuntimeError(f"{path.name}: expected {len(FEATURE_KEYS)} coefficients")
    coefficients = []
    for key, value in zip(FEATURE_KEYS, raw_coefs, strict=True):
        num = float(value)
        if not math.isfinite(num):
            raise RuntimeError(f"{path.name}: non-finite coefficient for {key}")
        if num < 0.0:
            # Structural finding-5.1 guarantee: evidence can only add risk.
            raise RuntimeError(f"{path.name}: negative coefficient for {key} ({num})")
        coefficients.append(num)
    b = float(intercept)
    if not math.isfinite(b):
        raise RuntimeError(f"{path.name}: non-finite intercept")
    fit = meta.get("fit") if isinstance(meta.get("fit"), dict) else {}
    dataset = meta.get("dataset") if isinstance(meta.get("dataset"), dict) else {}
    return FusionModel(
        coefficients=tuple(coefficients),
        intercept=b,
        lambda_selected=fit.get("lambda_selected"),
        dataset_sha256=dataset.get("sha256"),
    )


def get_fusion_model() -> FusionModel:
    """The deployed refit model, loaded once per process and cached.

    Raises when the artifact is missing or fails validation — layer9_fusion
    catches and degrades to its fallback path. A failed load is deliberately
    NOT cached so recovery needs only fixing the file, not a restart."""
    global _model
    with _model_lock:
        if _model is None:
            try:
                _model = _load_fusion_model(MODEL_ARTIFACT_PATH)
            except Exception as exc:
                raise RuntimeError(f"fusion model artifact unusable: {exc}") from exc
        return _model


def _sigmoid(z: float) -> float:
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


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
#   ~0.89 on layer 3's saturation curve (1 - e^(-0.9 * w)). The floor
#   lands INSIDE the LLM escalation band ([ESCALATION_LOW, ESCALATION_HIGH))
#   so sub-threshold shapes of this evidence stay visible to cadence
#   tightening and the semantic second opinion. (The refitted model ranks
#   heavy new-domain infrastructure above the flag threshold on its own —
#   the measured feature space cannot separate vendor additions from
#   injections, so per-site suppression rules and the confirm queue are
#   the designed mitigations there; see the module docstring.)
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
    """Fuse layers 1-8 into one risk score: the deployed model's
    probability, lifted to at least any fired rule floor (see
    _RULE_FLOORS). Never raises: any failure (malformed input, missing or
    invalid model artifact) degrades to max(fallback sub-score, floors)
    with a note — the floors are model-independent and survive even a
    broken fit."""
    features: list[float] = []
    ran: dict[str, bool] = {}
    try:
        features, ran = build_feature_vector(layer_results)
        floor_value, floor_rules = _rule_floor(dict(zip(FEATURE_KEYS, features, strict=True)))
        model = get_fusion_model()
        z = math.fsum(c * v for c, v in zip(model.coefficients, features, strict=True)) + (
            model.intercept
        )
        proba = _sigmoid(z)
        score = max(proba, floor_value)
        contributions = {
            key: round(coef * val, 4)
            for key, coef, val in zip(FEATURE_KEYS, model.coefficients, features, strict=True)
        }
        evidence = {
            "model": (
                "logistic_regression (refit artifact; MAP fit on measured "
                "data, coefficients constrained >= 0)"
            ),
            "model_artifact": {
                "file": MODEL_ARTIFACT_PATH.name,
                "lambda_selected": model.lambda_selected,
                "dataset_sha256": model.dataset_sha256,
            },
            "features": {k: round(v, 4) for k, v in zip(FEATURE_KEYS, features, strict=True)},
            "layers_ran": ran,
            "contributions": contributions,
            "intercept": round(model.intercept, 4),
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
