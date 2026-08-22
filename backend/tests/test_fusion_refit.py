"""Fusion Arc Part B — guarantees for the committed refit model artifact.

The artifact (worker/detection/training/fusion_model.json) is what Phase 10
will integrate into layer9_fusion, so its safety-critical properties are
pinned here against the committed dataset: structural monotonicity via the
non-negativity constraint (the property finding 5.1 showed the seed fit
violated), held-out calibration/discrimination on the VAL split, the
one-standard-error lambda selection, non-saturation, and byte-stable
regeneration. Everything is pure JSON/numpy math — hermetic and fast; the
dataset's TEST split stays untouched for Part C's integration validation.
"""

import json

import numpy as np
import pytest

from tools.refit_fusion_model import (
    DATASET_PATH,
    LAMBDA_GRID,
    MODEL_PATH,
    MONOTONICITY_CONTEXTS,
    MONOTONICITY_STEPS,
    N_BINS,
    N_FOLDS,
    binary_metrics,
    build,
    ece_score,
    normalized_digest,
)
from worker.detection.fusion import FEATURE_KEYS

ARTIFACT = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
META = ARTIFACT["meta"]
MODEL = ARTIFACT["model"]
DATASET = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

W = np.array(MODEL["coefficients"], dtype=np.float64)
B = float(MODEL["intercept"])


def _sigmoid(z: float) -> float:
    return float(1.0 / (1.0 + np.exp(-z)))


def _proba(vec) -> float:
    return _sigmoid(float(np.dot(W, np.asarray(vec, dtype=np.float64)) + B))


# --- artifact schema & binding -------------------------------------------------


def test_artifact_schema_and_dataset_binding() -> None:
    assert META["schema_version"] == 1
    assert META["tool"].endswith("refit_fusion_model.py")
    assert META["feature_keys"] == list(FEATURE_KEYS)
    binding = META["dataset"]
    assert binding["sha256"] == normalized_digest(DATASET_PATH)
    assert binding["schema_version"] == DATASET["meta"]["schema_version"]
    counts = {
        split: sum(1 for s in DATASET["samples"] if s["split"] == split)
        for split in ("train", "val", "test")
    }
    assert binding["samples"]["total"] == len(DATASET["samples"])
    assert binding["samples"]["train"] == counts["train"]
    assert binding["samples"]["val"] == counts["val"]
    assert binding["samples"]["test_untouched"] == counts["test"]
    assert len(MODEL["coefficients"]) == len(FEATURE_KEYS)


def test_coefficients_non_negative_and_finite() -> None:
    """The finding-5.1 property: no evidence channel may carry a negative
    weight. The seed fit shipped with l2 = -6.54 / l6 = -1.39."""
    assert np.all(np.isfinite(W))
    assert B == B and np.isfinite(B)
    assert np.all(W >= 0.0)


# --- structural + empirical monotonicity ----------------------------------------


def test_probability_monotone_in_every_feature() -> None:
    """More evidence in any single channel never lowers fused risk — swept
    empirically across contexts through the exact deployed math."""
    for _, base in MONOTONICITY_CONTEXTS:
        for j in range(len(FEATURE_KEYS)):
            prev = -1.0
            for step in MONOTONICITY_STEPS:
                vec = list(base)
                vec[j] = float(step)
                p = _proba(vec)
                assert p >= prev - 1e-12, (base, j, step, p, prev)
                prev = p


def test_recorded_monotonicity_violation_is_zero() -> None:
    assert META["metrics"]["max_monotonicity_violation"] <= 1e-12


def test_laundering_padding_cannot_reduce_risk() -> None:
    """The audit's laundering lever: attacker-added benign churn had to be
    able to push unsaturated attacks BELOW threshold (measured 0.73 ->
    0.05 under the seed fit). Under the refit every padding level raises or
    holds risk."""
    profiles = {
        "stealthy": [1.0, 0.4, 0.85, 0.1, 0.0, 0.0, 0.0, 0.1],
        "semantic_rewrite": [1.0, 0.2, 0.05, 0.25, 0.3, 0.0, 0.0, 0.9],
        "signature_only": [1.0, 0.2, 0.1, 0.3, 1.0, 0.0, 0.0, 0.6],
    }
    for name, prof in profiles.items():
        base_p = _proba(prof)
        for pad in (0.6, 0.8, 1.0):
            padded = list(prof)
            padded[1] = pad
            assert _proba(padded) >= base_p - 1e-12, (name, pad)


# --- held-out calibration & discrimination (VAL split) ---------------------------


def _split_arrays(split: str):
    X = np.array([s["features"] for s in DATASET["samples"] if s["split"] == split])
    y = np.array([s["label"] for s in DATASET["samples"] if s["split"] == split])
    return X, y


def test_val_calibration_and_discrimination() -> None:
    X_va, y_va = _split_arrays("val")
    p_va = 1.0 / (1.0 + np.exp(-(X_va @ W + B)))
    m = binary_metrics(y_va, p_va)
    assert m["auc"] >= 0.85
    assert m["brier"] <= 0.18
    assert m["ece"] <= 0.20
    assert m["accuracy"] >= 0.75
    assert m["logloss"] <= 0.50
    stored = META["metrics"]["val"]
    for key in ("accuracy", "logloss", "brier", "auc", "ece"):
        assert stored[key] == pytest.approx(m[key], abs=1e-6), key


def test_val_reliability_bins_consistent() -> None:
    X_va, y_va = _split_arrays("val")
    p_va = 1.0 / (1.0 + np.exp(-(X_va @ W + B)))
    edges = np.linspace(0.0, 1.0, N_BINS + 1)
    stored_bins = META["metrics"]["reliability_bins_val"]
    assert len(stored_bins) == N_BINS
    total = 0
    for k, stored in enumerate(stored_bins):
        lo, hi = edges[k], edges[k + 1]
        mask = (p_va >= lo) & (p_va <= hi) if k == N_BINS - 1 else (p_va >= lo) & (p_va < hi)
        n = int(mask.sum())
        total += n
        assert stored["n"] == n
        if n:
            assert stored["mean_p"] == pytest.approx(round(float(p_va[mask].mean()), 4))
            assert stored["frac_pos"] == pytest.approx(round(float(y_va[mask].mean()), 4))
    assert total == len(y_va)
    recomputed_ece = ece_score(y_va, p_va)
    assert recomputed_ece == pytest.approx(META["metrics"]["val"]["ece"], abs=1e-9)


def test_model_is_not_saturated() -> None:
    """The old fit memorized its fiction seeds (accuracy 1.0, min |p-label|
    ~5e-5). The refit must stay away from both failure corners: not
    degenerate, and not overconfident across the board."""
    m_tr = META["metrics"]["train"]
    m_va = META["metrics"]["val"]
    assert 0.70 <= m_tr["accuracy"] <= 0.98
    assert m_tr["frac_extreme_predictions"] <= 0.5
    assert m_va["frac_extreme_predictions"] <= 0.5
    # Bayes-error disclosure: coarse feature space collapses distinct inputs;
    # the recorded conflict count must match the committed train split.
    uniq: dict[tuple[float, ...], set[int]] = {}
    for s in DATASET["samples"]:
        if s["split"] != "train":
            continue
        uniq.setdefault(tuple(s["features"]), set()).add(s["label"])
    conflicts = sum(1 for labels in uniq.values() if len(labels) > 1)
    assert META["metrics"]["label_conflicts_within_train_unique_vectors"] == conflicts


# --- hyperparameter selection ----------------------------------------------------


def test_cv_selection_follows_one_standard_error_rule() -> None:
    table = META["fit"]["cv_table"]
    assert {r["lambda"] for r in table} == set(LAMBDA_GRID)
    for row in table:
        assert len(row["fold_logloss"]) == N_FOLDS
        assert row["mean_logloss"] == pytest.approx(float(np.mean(row["fold_logloss"])), abs=1e-12)
    best = min(table, key=lambda r: r["mean_logloss"])
    se = float(np.std(best["fold_logloss"], ddof=1) / np.sqrt(N_FOLDS))
    strongest_within_se = max(
        r["lambda"] for r in table if r["mean_logloss"] <= best["mean_logloss"] + se
    )
    assert META["fit"]["lambda_selected"] == strongest_within_se
    assert META["fit"]["lambda_grid"] == sorted(LAMBDA_GRID)


# --- determinism ------------------------------------------------------------------


def test_refit_rebuilds_byte_identical(tmp_path) -> None:
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    build(dataset_path=DATASET_PATH, out_path=out_a)
    build(dataset_path=DATASET_PATH, out_path=out_b)
    raw_a = out_a.read_bytes()
    assert raw_a == out_b.read_bytes()
    assert json.loads(raw_a) == ARTIFACT


# --- sanity rows -------------------------------------------------------------------


def test_sanity_rows_recorded_takeovers_enforced() -> None:
    checks = META["sanity_checks"]
    highs = [c for c in checks if c["expect"] == "high"]
    lows = [c for c in checks if c["expect"] == "low"]
    assert highs and lows
    for c in highs:
        assert c["probability"] >= 0.85, c
        assert _proba(c["vector"]) == pytest.approx(c["probability"], abs=1e-4)
    for c in lows:
        assert _proba(c["vector"]) == pytest.approx(c["probability"], abs=1e-4)
