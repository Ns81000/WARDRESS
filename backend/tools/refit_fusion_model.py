"""Fusion Arc Part B — constrained refit of the layer 9 risk-fusion model.

Consumes the committed Phase 8 dataset (measured layer outputs over balanced
attack/benign scenarios) and produces the deployed-model artifact
(worker/detection/training/fusion_model.json): an L2-regularized logistic
regression whose coefficients are CONSTRAINED >= 0, so fused risk is
monotone in every evidence channel by construction. The hand-authored seed
rows fitted without constraints assigned sign-inverted weights to DOM-churn
(-6.54) and security-metadata (-1.39) evidence, letting attacker-controlled
benign padding launder unsaturated attacks below the flag threshold (audit
finding 5.1); the box constraint makes that failure mode structurally
impossible instead of accidentally absent, and lets uninformative channels
settle at exactly 0 rather than inheriting a collinear noise sign.

Methodology:
- Split discipline: hyperparameter (lambda) selection via deterministic
  stratified 5-fold CV on the TRAIN split only; final fit on TRAIN; VAL is
  the honest held-out set this phase reports calibration/discrimination on;
  TEST remains untouched for Fusion Arc Part C's integration validation.
- Fit: penalized binary NLL minimized by scipy L-BFGS-B with analytic
  gradient, bounds coef >= 0, intercept free. Fully deterministic (no RNG,
  no wall-clock anywhere in the artifact).
- Fail-loud quality gates refuse to write an artifact that violates
  non-negativity, monotonicity, or minimum calibration standards.

Usage (from backend/):
    .venv\\Scripts\\python.exe -m tools.refit_fusion_model
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import numpy as np  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.special import expit  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from worker.detection.fusion import FEATURE_KEYS  # noqa: E402

DATASET_PATH = BACKEND_DIR / "worker" / "detection" / "training" / "fusion_dataset.json"
MODEL_PATH = BACKEND_DIR / "worker" / "detection" / "training" / "fusion_model.json"

SCHEMA_VERSION = 1
N_FOLDS = 5
N_BINS = 10
LAMBDA_GRID = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)

MONOTONICITY_STEPS = np.linspace(0.0, 1.0, 11)
MONOTONICITY_CONTEXTS = (
    ("all_quiet", [0.0] * 8),
    ("hash_flip_only", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    ("benign_redesign", [1.0, 0.6, 0.35, 0.55, 0.0, 0.15, 0.0, 0.4]),
    ("multi_signal_attack", [1.0, 0.8, 0.6, 0.9, 1.0, 0.0, 0.2, 0.8]),
)

COEFFICIENT_NOTES = {
    "layer1_hash": (
        "Pure byte-flip flag: it fires for every benign deploy as well as "
        "every attack, so it earns a modest prior-update weight — evidence "
        "that something changed, never evidence of hostility on its own."
    ),
    "layer2_dom_structure": (
        "DOM churn saturates under benign redesigns and deploys exactly as "
        "under attacks (the class/churn confounding behind finding 5.1's "
        "-6.54 seed-fit weight). Measured weight is positive but modest: "
        "churn corroborates other channels, it never convicts alone."
    ),
    "layer3_link_audit": (
        "New external script/iframe/form-action infrastructure is genuine "
        "hostile signal, but legitimate sites add vendor scripts routinely; "
        "mid-weight corroboration, with Phase 7's rule floor binding the "
        "heavy single-vector case."
    ),
    "layer4_visual_diff": (
        "Pixel divergence is computed after layer 4 handles rendering noise "
        "and suppression internally, so residual visual change is rarely "
        "benign: near-maximum weight."
    ),
    "layer5_signatures": (
        "Matched defacement signature text is essentially conclusive on its "
        "own (layer 5's own contract): near-maximum weight."
    ),
    "layer6_security_metadata": (
        "Certificate/header rotation occurs in BOTH classes (routine "
        "reissues and CSP tightening on the benign side, attacker-owned-box "
        "changes on the hostile side), and layer 6 scores any value change "
        "as weakening regardless of direction. Its measured information "
        "content is ~0, so the constraint settles it at exactly 0 instead "
        "of letting collinear noise pick a sign (the seed fit scored it "
        "-1.39, actively reducing risk as metadata changed)."
    ),
    "layer7_cloaking": (
        "Crawler-vs-browser divergence beyond layer 7's soft knee is "
        "attack-only evidence in the measured data: maximum weight."
    ),
    "layer8_semantics": (
        "Meaning-level drift fires on manifesto-style rewrites and SEO spam "
        "within the embed window; strong weight, bounded by the channel's "
        "documented blind spots past the cap."
    ),
}

META_NOTES = [
    "Coefficients are constrained >= 0 during fitting, so d(risk)/d(feature) "
    "= sigmoid'(z) * w >= 0 everywhere: more evidence can never lower risk "
    "(the property finding 5.1 showed the seed fit violated).",
    "lambda selected by deterministic stratified 5-fold CV on the train "
    "split under the one-standard-error rule: the STRONGEST grid value whose "
    "mean fold log-loss is within one standard error of the optimum. Plain "
    "argmin slides to the weakest regularization on near-separable data and "
    "yields near-step-function scores around thin margins.",
    "VAL metrics are the honest held-out numbers for this phase; the TEST "
    "split is deliberately untouched here and reserved for Fusion Arc Part "
    "C's end-to-end integration validation.",
    "The dataset's coarse 8-dim feature space collapses distinct inputs onto "
    "shared vectors (see the dataset's leakage_evidence); unique train "
    "vectors carrying BOTH labels set a Bayes-error ceiling, so training "
    "accuracy below 1.0 is expected and is evidence against saturation, not "
    "against quality.",
    "sanity_checks rows with expect=low are RECORDED, not enforced: benign "
    "rows landing above the default flag threshold are an operating-point "
    "(threshold/band) decision owned by Fusion Arc Part C together with the "
    "Phase 7 floor constants, not something to hand-tune away here. Rows "
    "with expect=high ARE enforced (>= 0.85): a fit that cannot recognize a "
    "total takeover is broken at any operating point.",
    "Regeneration workflow: rebuild the dataset (tools.build_fusion_dataset), "
    "then rerun this module; the artifact binds its dataset via sha256.",
]


def normalized_digest(path: Path) -> str:
    """sha256 over LF-normalized bytes: identical regardless of whether a
    checkout materialized the text file with LF or CRLF endings."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_dataset(path: Path) -> tuple[np.ndarray, ...]:
    """Validated (X_train, y_train, X_val, y_val, X_test, y_test, samples, meta)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("meta")
    samples = raw.get("samples")
    if not isinstance(meta, dict) or not isinstance(samples, list):
        raise ValueError("dataset artifact missing meta/samples")
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"dataset schema_version {meta.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    if meta.get("feature_keys") != list(FEATURE_KEYS):
        raise ValueError("dataset feature_keys diverge from runtime FEATURE_KEYS order")

    splits: dict[str, tuple[list[list[float]], list[int], list[bool]]] = {
        sp: ([], [], []) for sp in ("train", "val", "test")
    }
    for s in samples:
        feats = s["features"]
        if len(feats) != len(FEATURE_KEYS):
            raise ValueError(f"{s['id']}: wrong feature width")
        for v in feats:
            if not np.isfinite(v) or not 0.0 <= v <= 1.0:
                raise ValueError(f"{s['id']}: feature out of range: {feats}")
        if s["label"] not in (0, 1):
            raise ValueError(f"{s['id']}: label {s['label']!r}")
        split = s["split"]
        if split not in splits:
            raise ValueError(f"{s['id']}: unknown split {split!r}")
        xs, ys, sanity = splits[split]
        xs.append([float(v) for v in feats])
        ys.append(int(s["label"]))
        sanity.append(bool(s["sanity"]))

    arrays = []
    for sp in ("train", "val", "test"):
        xs, ys, sanity = splits[sp]
        if not xs or len(set(ys)) < 2:
            raise ValueError(f"split {sp} empty or single-class — refusing to fit")
        arrays += [np.array(xs, dtype=np.float64), np.array(ys, dtype=np.int64)]
        if sp == "train":
            arrays.append(np.array(sanity, dtype=bool))

    uniq: dict[tuple[float, ...], set[int]] = {}
    for row, lbl in zip(splits["train"][0], splits["train"][1], strict=True):
        uniq.setdefault(tuple(row), set()).add(lbl)
    conflicts = sum(1 for labels in uniq.values() if len(labels) > 1)
    return (*arrays, conflicts, meta)


def stratified_fold_of(labels: np.ndarray, folds: int) -> np.ndarray:
    """Deterministic balanced assignment: walk each class's indices in
    dataset order, always consuming the smallest fold (ties -> lowest)."""
    fold_of = np.empty(len(labels), dtype=np.int64)
    counts = [0] * folds
    for cls in (0, 1):
        for i in np.flatnonzero(labels == cls):
            f = min(range(folds), key=lambda k: (counts[k], k))
            fold_of[i] = f
            counts[f] += 1
    return fold_of


def fit_constrained(X: np.ndarray, y: np.ndarray, lam: float) -> tuple[np.ndarray, float]:
    """MAP estimate: sum_i log(1+exp(z_i)) - y_i z_i + lam/2 ||w||^2 with
    z = Xw + b, under w >= 0 (intercept free). Analytic gradient."""
    Xd = np.asarray(X, dtype=np.float64)
    yd = np.asarray(y, dtype=np.float64)
    n_features = Xd.shape[1]

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w, b = theta[:-1], theta[-1]
        z = Xd @ w + b
        loss = np.logaddexp(0.0, z) - yd * z
        grad_z = expit(z) - yd
        return (
            float(loss.sum() + 0.5 * lam * float(w @ w)),
            np.concatenate([Xd.T @ grad_z + lam * w, [grad_z.sum()]]),
        )

    result = minimize(
        objective,
        np.zeros(n_features + 1),
        jac=True,
        method="L-BFGS-B",
        bounds=[(0.0, None)] * n_features + [(None, None)],
        options={"maxiter": 20000, "ftol": 1e-14, "gtol": 1e-11},
    )
    if not result.success:
        raise RuntimeError(f"L-BFGS-B failed to converge (lambda={lam}): {result.message}")
    return np.asarray(result.x[:-1], dtype=np.float64), float(result.x[-1])


def cross_validate_lambda(X: np.ndarray, y: np.ndarray) -> tuple[float, list[dict]]:
    fold_of = stratified_fold_of(y, N_FOLDS)
    table = []
    for lam in sorted(LAMBDA_GRID, reverse=True):
        fold_logloss = []
        for f in range(N_FOLDS):
            tr, te = fold_of != f, fold_of == f
            w, b = fit_constrained(X[tr], y[tr], lam)
            p = expit(X[te] @ w + b)
            eps = 1e-15
            fold_logloss.append(
                float(
                    -np.mean(
                        y[te] * np.log(np.clip(p, eps, 1 - eps))
                        + (1 - y[te]) * np.log(np.clip(1 - p, eps, 1))
                    )
                )
            )
        table.append(
            {
                "lambda": lam,
                "fold_logloss": fold_logloss,
                "mean_logloss": float(np.mean(fold_logloss)),
            }
        )
    best = min(table, key=lambda r: r["mean_logloss"])
    # One-standard-error rule: take the STRONGEST regularization whose mean
    # CV log-loss is within one standard error of the optimum. Plain argmin
    # slides to the grid edge on near-separable data (log-loss keeps paying
    # for sharper weights), producing near-step-function scores around thin
    # data margins; the 1-SE rule is the standard guard against that.
    se = float(np.std(best["fold_logloss"], ddof=1) / np.sqrt(N_FOLDS))
    threshold = best["mean_logloss"] + se
    chosen = next(r["lambda"] for r in table if r["mean_logloss"] <= threshold)
    return chosen, table


def binary_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    pred = (p >= 0.5).astype(np.int64)
    eps = 1e-15
    pc = np.clip(p, eps, 1 - eps)
    return {
        "n": int(len(y)),
        "accuracy": float((pred == y).mean()),
        "logloss": float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))),
        "brier": float(np.mean((p - y) ** 2)),
        "auc": float(roc_auc_score(y, p)),
        "ece": ece_score(y, p),
        "confusion_at_0_5": {
            "true_positive": int(((pred == 1) & (y == 1)).sum()),
            "false_positive": int(((pred == 1) & (y == 0)).sum()),
            "false_negative": int(((pred == 0) & (y == 1)).sum()),
            "true_negative": int(((pred == 0) & (y == 0)).sum()),
        },
        "frac_extreme_predictions": float(((p < 0.02) | (p > 0.98)).mean()),
    }


def ece_score(y: np.ndarray, p: np.ndarray, bins: int = N_BINS) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for k in range(bins):
        lo, hi = edges[k], edges[k + 1]
        mask = (p >= lo) & (p <= hi) if k == bins - 1 else (p >= lo) & (p < hi)
        if mask.sum():
            total += mask.mean() * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(total)


def reliability_bins(y: np.ndarray, p: np.ndarray) -> list[dict]:
    edges = np.linspace(0.0, 1.0, N_BINS + 1)
    out = []
    for k in range(N_BINS):
        lo, hi = edges[k], edges[k + 1]
        mask = (p >= lo) & (p <= hi) if k == N_BINS - 1 else (p >= lo) & (p < hi)
        out.append(
            {
                "lower": float(lo),
                "upper": float(hi),
                "n": int(mask.sum()),
                "mean_p": round(float(p[mask].mean()), 4) if mask.sum() else None,
                "frac_pos": round(float(y[mask].mean()), 4) if mask.sum() else None,
            }
        )
    return out


def max_monotonicity_violation(w: np.ndarray, b: float) -> float:
    worst = 0.0
    for _, base in MONOTONICITY_CONTEXTS:
        for j in range(len(FEATURE_KEYS)):
            prev = -np.inf
            for step in MONOTONICITY_STEPS:
                vec = list(base)
                vec[j] = float(step)
                p = float(expit(float(np.dot(w, vec)) + b))
                worst = max(worst, prev - p)
                prev = p
    return worst


def sanity_check_predictions(w: np.ndarray, b: float, X: np.ndarray, y: np.ndarray) -> list[dict]:
    checks = []
    for vec, label in zip(X, y, strict=True):
        content_peak = max(vec[1:])
        if label == 1 and content_peak >= 0.85:
            checks.append(
                {
                    "expect": "high",
                    "vector": [round(float(v), 4) for v in vec],
                    "probability": round(float(expit(float(np.dot(w, vec)) + b)), 6),
                }
            )
        elif label == 0 and content_peak <= 0.35:
            checks.append(
                {
                    "expect": "low",
                    "vector": [round(float(v), 4) for v in vec],
                    "probability": round(float(expit(float(np.dot(w, vec)) + b)), 6),
                }
            )
    return checks


def build(dataset_path: Path = DATASET_PATH, out_path: Path = MODEL_PATH) -> Path:
    import scipy
    import sklearn

    X_tr, y_tr, sanity_tr, X_va, y_va, X_te, y_te, conflicts, ds_meta = load_dataset(dataset_path)
    try:
        dataset_ref = str(dataset_path.relative_to(BACKEND_DIR))
    except ValueError:
        dataset_ref = str(dataset_path.resolve())
    split_counts = {
        "total": int(len(X_tr) + len(X_va) + len(X_te)),
        "train": int(len(X_tr)),
        "val": int(len(X_va)),
        "test_untouched": int(len(X_te)),
    }
    del X_te, y_te  # TEST split intentionally untouched (Part C reserves it)

    lambda_sel, cv_table = cross_validate_lambda(X_tr, y_tr)
    w, b = fit_constrained(X_tr, y_tr, lambda_sel)

    if (w < -1e-12).any():
        raise RuntimeError(f"negative coefficient escaped the box constraint: {w}")
    violation = max_monotonicity_violation(w, b)
    if violation > 1e-12:
        raise RuntimeError(f"monotonicity violated by {violation}")

    p_tr = expit(X_tr @ w + b)
    p_va = expit(X_va @ w + b)
    m_tr, m_va = binary_metrics(y_tr, p_tr), binary_metrics(y_va, p_va)

    checks = sanity_check_predictions(w, b, X_tr[sanity_tr], y_tr[sanity_tr])
    degenerate = [c for c in checks if c["expect"] == "high" and c["probability"] < 0.85]
    if degenerate:
        raise RuntimeError(
            f"sanity takeover rows no longer recognized — degenerate fit: {degenerate[:3]}"
        )

    gates = (
        ("val_auc", m_va["auc"], "min", 0.80),
        ("val_brier", m_va["brier"], "max", 0.25),
        ("val_ece", m_va["ece"], "max", 0.20),
        ("train_accuracy", m_tr["accuracy"], "min", 0.70),
        ("train_accuracy", m_tr["accuracy"], "ceiling", 0.98),
    )
    failures = []
    for name, value, direction, limit in gates:
        if (direction == "min" and value < limit) or (
            direction in ("max", "ceiling") and value > limit
        ):
            failures.append(f"{name} ({direction} {limit}): measured {value:.4f}")
    if failures:
        raise RuntimeError("refit quality gates failed:\n  " + "\n  ".join(failures))

    artifact = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "tool": "backend/tools/refit_fusion_model.py",
            "dataset": {
                "path": dataset_ref,
                # Line-ending-insensitive so the binding survives git's
                # checkout normalization (text files may arrive LF or CRLF).
                "sha256": normalized_digest(dataset_path),
                "schema_version": ds_meta.get("schema_version"),
                "samples": split_counts,
            },
            "feature_keys": list(FEATURE_KEYS),
            "fit": {
                "method": "MAP logistic regression, L2-penalized, coefficients constrained >= 0",
                "solver": "scipy.optimize.minimize L-BFGS-B (analytic gradient)",
                "lambda_grid": sorted(LAMBDA_GRID),
                "cv_folds": N_FOLDS,
                "selection_rule": (
                    "one-standard-error: strongest lambda whose mean fold "
                    "log-loss <= best mean fold log-loss + 1 SE (train-only)"
                ),
                "cv_table": cv_table,
                "lambda_selected": lambda_sel,
                "library_versions": {
                    "numpy": np.__version__,
                    "scipy": scipy.__version__,
                    "scikit_learn": sklearn.__version__,
                },
            },
            "metrics": {
                "train": {
                    **m_tr,
                    "min_abs_prediction_error": round(float(np.min(np.abs(p_tr - y_tr))), 6),
                },
                "val": m_va,
                "reliability_bins_val": reliability_bins(y_va, p_va),
                "label_conflicts_within_train_unique_vectors": int(conflicts),
                "max_monotonicity_violation": round(violation, 12),
                "test_split_policy": (
                    "untouched; consumed by Fusion Arc Part C integration validation"
                ),
            },
            "sanity_checks": checks,
            "coefficient_notes": COEFFICIENT_NOTES,
            "notes": META_NOTES,
        },
        "model": {"intercept": b, "coefficients": [float(v) for v in w]},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".json.tmp")
    # newline="\n" keeps the bytes identical across OSes and immune to git's
    # checkout normalization (LF in, LF out).
    tmp_path.write_text(json.dumps(artifact, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp_path, out_path)

    print(f"lambda={lambda_sel}  train={m_tr}")
    print(f"             val ={m_va}")
    print(f"wrote {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--out", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    build(dataset_path=args.dataset, out_path=args.out)


if __name__ == "__main__":
    main()
