"""PROMPT-002 Phase 12 — detector regression harness.

Root cause: detection changes (PROMPT-002 Phases 8-11) were verified with
hand-built fixtures, and the 646-sample fusion dataset was measured once —
nothing mechanically re-measures the detectors' AGGREGATE behavior, so a
regression in any layer's emission can only surface by luck. This module
pins a compact, deterministic regression corpus
(``worker/detection/training/regression_corpus.json``, built by
``tools/build_regression_corpus.py`` from the SAME scenario builders as the
fusion training dataset) against three kinds of guarantees:

1. Per-axis invariants against the committed artifact (pure JSON, fast):
   every attack row still reads "changed" with a content layer (2-8,
   non-skipped) above the verdict noise floor — layer 1's byte-flip flag is
   excluded from the peak, exactly as Phase 11's re-measurement and the
   dataset's own sanity invariants do; every attack axis keeps a minimum
   content peak of 0.10, with rule-floor coverage as the structural
   alternative and one documented deliberately-sub-threshold exception
   (``combined_subthreshold``); every benign-dynamic row fuses strictly
   below MATERIAL_CHANGE_RISK so dynamic churn can never tighten cadence.
2. Self-consistency: each stored fused risk reproduces exactly from the
   stored (rounded) features through the deployed ``layer9_fusion``.
3. Determinism / drift: a fresh in-process rebuild reproduces the
   committed artifact row-for-row, and two rebuilds are identical — a
   detector change that alters any measured row fails here, loudly.

The committed artifact is the CI-fast path; the rebuild (measured ~40 s
per build after the MiniLM load — minutes, not tens) runs once per session
through a module-scoped fixture shared by the drift tests.

Failing-before proof (run against the unmodified tree, Phase 12 session):
collection ImportError — neither the tool, the artifact, nor any of these
pins existed. The invariant tests are behavior pins of measured reality
(same epistemic status as test_fusion_dataset's artifact guards); the
genuinely new executable behaviors (rebuild determinism, docs pin) are
called out in their docstrings.
"""

import json
from pathlib import Path

import pytest

from app.scanning import MATERIAL_CHANGE_RISK
from tools.build_regression_corpus import (
    ARTIFACT_PATH,
    BENIGN_DYNAMIC_AXES,
    ROWS_PER_AXIS,
    SUBTHRESHOLD_EXCEPTION_AXES,
)
from tools.build_regression_corpus import (
    ATTACK_AXES as REGRESSION_ATTACK_AXES,
)
from tools.build_regression_corpus import (
    SCHEMA_VERSION as REGRESSION_SCHEMA_VERSION,
)
from worker.detection.fusion import _RULE_FLOORS, FEATURE_KEYS, layer9_fusion
from worker.scan_tasks import NOISE_FLOOR

CONTENT_KEYS = FEATURE_KEYS[1:]  # layers 2-8; layer 1 is a byte-flip flag

ARTIFACT = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
META = ARTIFACT["meta"]
SAMPLES = ARTIFACT["samples"]

# Content-layer channels whose unambiguous evidence is covered by a rule
# floor (fusion._RULE_FLOORS): a row is floor-covered when some floor's
# trigger fires on its stored features, i.e. the floor pins the risk from
# below regardless of what the fitted model does.
_FLOOR_TRIGGERS = [
    (FEATURE_KEYS.index(key), trigger)
    for key, trigger, _floor, _name in _RULE_FLOORS
    if key in CONTENT_KEYS
]


def _content_peak(row: dict) -> float:
    """Max score over NON-SKIPPED content layers (2-8). Skipped layers are
    structural proofs of zero (hash gate), not sub-noise measurements."""
    skipped = set(row["layers_skipped"])
    return max(
        (
            v
            for k, v in zip(FEATURE_KEYS, row["features"], strict=True)
            if k in CONTENT_KEYS and k not in skipped
        ),
        default=0.0,
    )


def _results_from_row(row: dict) -> dict:
    """Reconstruct the layer-results mapping the stored features encode:
    skipped layers as skip results (proofs of zero), everything else as
    measured scores — the same shape the fusion layer consumes in
    production and the same reconstruction test_fusion_integration uses."""
    skipped = set(row["layers_skipped"])
    return {
        key: (
            {"score": None, "skipped": True, "evidence": {"reason": "gated"}}
            if key in skipped
            else {"score": value, "evidence": {}}
        )
        for key, value in zip(FEATURE_KEYS, row["features"], strict=True)
    }


def _axis_rows(axis: str) -> list[dict]:
    rows = [s for s in SAMPLES if s["axis"] == axis]
    assert rows, f"axis {axis} absent from the committed corpus"
    return rows


def _axis_floor_covered(rows: list[dict]) -> bool:
    """True when EVERY row of the axis fires at least one rule floor on its
    stored features (the 'rule-floor coverage' branch of the per-axis
    invariant)."""
    for row in rows:
        feats = row["features"]
        if not any(feats[i] >= trigger for i, trigger in _FLOOR_TRIGGERS):
            return False
    return True


# --- committed artifact: schema & meta coherence ------------------------------


def test_meta_schema_pins() -> None:
    assert META["schema_version"] == REGRESSION_SCHEMA_VERSION
    assert META["generator"].endswith("build_regression_corpus.py")
    assert META["feature_keys"] == list(FEATURE_KEYS)
    # The shipped corpus must be full-fidelity: real local embeddings, not a
    # silently-degraded stub build (same discipline as the fusion dataset).
    assert META["embedder"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert META["embedder"]["mode"] == "real-local-cache"
    assert META["rows_per_axis"] == ROWS_PER_AXIS
    assert META["axes"]["attack"] == REGRESSION_ATTACK_AXES
    assert META["axes"]["benign_dynamic"] == BENIGN_DYNAMIC_AXES
    assert META["notes"] and all(isinstance(n, str) for n in META["notes"])


def test_meta_counts_match_samples() -> None:
    counts = META["counts"]
    attack = [s for s in SAMPLES if s["label"] == 1]
    assert counts["total"] == len(SAMPLES)
    assert counts["attack"] == len(attack)
    assert counts["benign"] == len(SAMPLES) - len(attack)
    by_axis: dict[str, int] = {}
    for s in SAMPLES:
        by_axis[s["axis"]] = by_axis.get(s["axis"], 0) + 1
    assert counts["by_axis"] == dict(sorted(by_axis.items()))
    # Exact per-axis counts are pinned constants (compact corpus, strict
    # subset of the fusion dataset's axes) — drift fails here, not silently.
    expected: dict[str, int] = {**REGRESSION_ATTACK_AXES, **BENIGN_DYNAMIC_AXES}
    assert by_axis == expected
    assert len(REGRESSION_ATTACK_AXES) * ROWS_PER_AXIS == len(attack)
    assert len(BENIGN_DYNAMIC_AXES) * ROWS_PER_AXIS == len(SAMPLES) - len(attack)
    # Strict-subset property: the corpus reuses the fusion dataset's scenario
    # builders, never invents its own axes.
    from tools.build_fusion_dataset import ATTACK_AXES, BENIGN_AXES

    assert set(REGRESSION_ATTACK_AXES) <= set(ATTACK_AXES)
    assert set(BENIGN_DYNAMIC_AXES) <= set(BENIGN_AXES)
    assert not (set(REGRESSION_ATTACK_AXES) & set(BENIGN_DYNAMIC_AXES))


def test_every_row_is_structurally_valid() -> None:
    ids = set()
    axes = {**REGRESSION_ATTACK_AXES, **BENIGN_DYNAMIC_AXES}
    for s in SAMPLES:
        assert set(s) >= {
            "id",
            "axis",
            "label",
            "language",
            "features",
            "layers_skipped",
            "fused_risk",
        }
        assert s["label"] in (0, 1)
        assert s["axis"] in axes
        assert (s["axis"] in REGRESSION_ATTACK_AXES) == (s["label"] == 1)
        feats = s["features"]
        assert len(feats) == len(FEATURE_KEYS)
        for v in feats:
            assert v == v and 0.0 <= v <= 1.0  # finite + in range
            assert v == round(v, 4), "features must be stored rounded to 4 dp"
        for key in s["layers_skipped"]:
            assert key in FEATURE_KEYS
            assert feats[FEATURE_KEYS.index(key)] == 0.0
        assert s["id"].startswith(f"{s['axis']}-")
        assert s["id"] not in ids, "duplicate id"
        ids.add(s["id"])
        risk = s["fused_risk"]
        assert 0.0 <= risk <= 1.0 and risk == round(risk, 4)


# --- pinned detector invariants (against the committed artifact) ---------------


def test_every_attack_row_still_reads_changed() -> None:
    """The Phase-11 guarantee, made standing: no detector change may push an
    attack scenario's content layers under the verdict noise floor. (The
    layer-1 byte flag is excluded from the peak — a bare hash flip reads
    'changed' trivially and pins nothing about the content detectors.)"""
    for s in SAMPLES:
        if s["label"] != 1:
            continue
        peak = _content_peak(s)
        assert peak > NOISE_FLOOR, f"{s['id']}: content peak {peak:.4f} <= NOISE_FLOOR"


def test_every_attack_axis_meets_the_detection_floor() -> None:
    """Per-axis strength floor: each attack axis's WEAKEST row must still
    score >= 0.10 on some non-skipped content layer, OR the axis's evidence
    channel is rule-floor-covered on every row (the floor pins risk from
    below independent of the model). combined_subthreshold is the one
    documented exception: it is deliberately sub-threshold by construction
    (Phase 11 re-measured its axis minimum at 0.0518) and is covered by the
    changed-verdict invariant above, which it would otherwise never
    exercise."""
    for axis in REGRESSION_ATTACK_AXES:
        rows = _axis_rows(axis)
        weakest = min(_content_peak(s) for s in rows)
        if axis in SUBTHRESHOLD_EXCEPTION_AXES:
            continue
        assert weakest >= 0.10 or _axis_floor_covered(rows), (
            f"{axis}: weakest content peak {weakest:.4f} < 0.10 and no rule-floor coverage"
        )



def test_benign_dynamic_rows_stay_below_the_material_change_band() -> None:
    """Every benign-dynamic row must fuse strictly below the adaptive-cadence
    material bar — churn may never permanently tighten a site's scan
    interval (app/scanning.py's stated invariant)."""
    for s in SAMPLES:
        if s["label"] != 0:
            continue
        assert s["fused_risk"] < MATERIAL_CHANGE_RISK, (
            f"{s['id']}: fused {s['fused_risk']:.4f} >= MATERIAL_CHANGE_RISK"
        )


def test_stored_fused_risk_reproduces_from_stored_features() -> None:
    """Self-consistency: the deployed fusion layer, run over the stored
    (rounded) features with the stored skip state, reproduces the stored
    fused risk exactly. A refit or fusion-code change that moves any row's
    risk fails here and demands a deliberate corpus regeneration."""
    for s in SAMPLES:
        recomputed = float(layer9_fusion(_results_from_row(s))["score"])
        assert round(recomputed, 4) == s["fused_risk"], s["id"]


# --- determinism / drift (module-scoped: one rebuild pair per session) ----------


@pytest.fixture(scope="module")
def rebuilt_pair() -> tuple[dict, dict]:
    """Two fresh in-process rebuilds of the full corpus (real embedder,
    offline from the local MiniLM cache — build_fusion_dataset forces
    HF_HUB_OFFLINE=1 at import). Measured ~40 s per build after the model
    load; shared so the drift tests pay the cost once per session."""
    from tools.build_regression_corpus import build_corpus

    return build_corpus(out_path=None), build_corpus(out_path=None)


def test_two_rebuilds_are_identical(rebuilt_pair) -> None:
    a, b = rebuilt_pair
    assert a == b


def test_committed_artifact_matches_a_fresh_rebuild(rebuilt_pair) -> None:
    """The drift pin: a detector or scenario-builder change that alters any
    measured row (features, skips, fused risk, counts, embedder mode) makes
    the committed artifact diverge from the rebuild and fails here."""
    a, _b = rebuilt_pair
    assert a == ARTIFACT


# --- docs pin (Rule 13: the doc names the artifact/tool/test, the test
# makes either side's drift fail loudly; no constants pinned in prose) ---


def test_detection_layers_doc_documents_the_regression_corpus() -> None:
    text = (
        Path(__file__).resolve().parents[2] / "docs" / "detection-layers.mdx"
    ).read_text(encoding="utf-8")
    assert "regression_corpus.json" in text
    assert "build_regression_corpus.py" in text
    assert "test_detection_regression.py" in text

