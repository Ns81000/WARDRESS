"""PROMPT-002 Phase 12 — compact detector regression-corpus builder.

Detection changes (PROMPT-002 Phases 8-11) were verified with hand-built
fixtures, and the 646-sample fusion dataset was measured once; nothing
mechanically re-measures the detectors' aggregate behavior. This tool makes
that standing and cheap: it builds a deterministic, COMPACT regression
corpus (a strict subset of the fusion dataset's axes, exact per-axis counts
pinned as constants below) by REUSING build_fusion_dataset.py's scenario
builders — ``measure_sample`` runs the real production pipeline
(``run_detection``) over the same procedurally crafted page pairs, so every
row is a fresh measurement of the current layer code, never an authored
vector.

Per row the corpus stores id / axis / label / language / 4-dp-rounded
features / skipped layers / fused risk, where the fused risk is computed
from the ROUNDED feature vector through the deployed ``layer9_fusion``
(rule floors included) so the artifact is self-consistent and exactly
reproducible from its own contents (difference vs production fusion is
rounding-only, <= 5e-5).

The artifact (``worker/detection/training/regression_corpus.json``) is
written ATOMICALLY (tmp file + ``os.replace``, the fusion dataset builder's
mechanism) and validated before writing: the build fails loudly if any
attack row's content layers fall to/below the verdict noise floor
(``worker.scan_tasks.NOISE_FLOOR``) or any benign-dynamic row fuses to/above
the material-change bar (``app.scanning.MATERIAL_CHANGE_RISK``) — i.e. a
detector regression cannot be regenerated into the artifact silently.
``tests/test_detection_regression.py`` pins the per-axis invariants against
the committed artifact (CI-fast path) and rebuilds the corpus in-process as
the drift check.

Axis-selection decisions (documented per the phase spec):

- Sanity axes are EXCLUDED. They are fit-time guardrails whose invariants
  are already pinned by tests/test_fusion_dataset.py against the committed
  dataset, and ``sanity_benign_quiet`` fuses 0.6583 under the deployed
  model's dominant layer-4 coefficient (Phase 11's recorded refit-time
  lead) — it would false-trip the benign material-change invariant.
- ``ab_test_variant``, ``site_redesign``, ``vendor_script_added`` and
  ``cert_header_rotation`` are EXCLUDED: they are genuine content deltas /
  heavy legitimate restructuring that legitimately fuse to/above the 0.40
  material bar (see app/scanning.py's comment), so the corpus's uniform
  benign invariant would not hold for them.
- ``combined_subthreshold`` is KEPT as the deliberately-sub-threshold
  weakest case (Phase 11 measured its axis-minimum content peak at
  0.0518): it is covered by the changed-verdict invariant and is the
  documented exception to the 0.10 per-axis strength floor in the tests.
- ``seo_spam_early`` is EXCLUDED on measured grounds: its weakest rows
  score content peaks at/below the verdict noise floor (min observed
  0.0200 in this phase's axis survey), so the corpus's uniform attack
  invariants cannot hold for it — the fusion dataset keeps the axis, and
  the harness's per-axis floor logic documents the fact here.
- The remaining kept axes cover every detection channel (2-8) and every
  rule-floor tier; channel-adjacent duplicates are dropped to keep the
  corpus compact.

Usage (from backend/):
    uv run --frozen python -m tools.build_regression_corpus
Regeneration requires the pinned dev dependencies and the local MiniLM
cache; HF_HUB_OFFLINE=1 is enforced by build_fusion_dataset's import so
generation never touches the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Reuse surface — no scenario logic is duplicated here (phase spec).
from faker import Faker  # noqa: E402

from app.scanning import MATERIAL_CHANGE_RISK  # noqa: E402
from tools.build_fusion_dataset import (  # noqa: E402
    _FAKERS,
    FEATURE_KEYS,
    LANGS,
    SEED,
    measure_sample,
)
from tools.build_fusion_dataset import (  # noqa: E402
    ATTACK_AXES as FUSION_ATTACK_AXES,
)
from tools.build_fusion_dataset import (  # noqa: E402
    BENIGN_AXES as FUSION_BENIGN_AXES,
)
from worker.detection.fusion import layer9_fusion  # noqa: E402
from worker.scan_tasks import NOISE_FLOOR  # noqa: E402

SCHEMA_VERSION = 1
ROWS_PER_AXIS = 8
ARTIFACT_PATH = BACKEND_DIR / "worker" / "detection" / "training" / "regression_corpus.json"

# Exact per-axis counts, pinned constants (the test asserts the artifact
# matches these dict-for-dict). Strict subsets of the fusion tables.
ATTACK_AXES: dict[str, int] = {
    "sig_strong_banner": ROWS_PER_AXIS,
    "sig_leet": ROWS_PER_AXIS,
    "sig_medium_weak": ROWS_PER_AXIS,
    "script_new_domain": ROWS_PER_AXIS,
    "form_action_swap": ROWS_PER_AXIS,
    "hidden_spam_inline": ROWS_PER_AXIS,
    "hidden_spam_stealth": ROWS_PER_AXIS,
    "cloaking_heavy": ROWS_PER_AXIS,
    "visual_banner_deface": ROWS_PER_AXIS,
    "laundering_padded": ROWS_PER_AXIS,
    "multi_vector_screamer": ROWS_PER_AXIS,
    "combined_subthreshold": ROWS_PER_AXIS,
}
BENIGN_DYNAMIC_AXES: dict[str, int] = {
    "rotating_ad": ROWS_PER_AXIS,
    "timestamp_counter": ROWS_PER_AXIS,
    "cache_busting_refs": ROWS_PER_AXIS,
    "minor_css_churn": ROWS_PER_AXIS,
    "mixed_noise_combo": ROWS_PER_AXIS,
    "editorial_update": ROWS_PER_AXIS,
    "nonnative_editorial": ROWS_PER_AXIS,
}
SUBTHRESHOLD_EXCEPTION_AXES = frozenset({"combined_subthreshold"})

assert set(ATTACK_AXES) <= set(FUSION_ATTACK_AXES), "attack subset must reuse fusion axes"
assert set(BENIGN_DYNAMIC_AXES) <= set(FUSION_BENIGN_AXES), "benign subset must reuse fusion axes"
assert set(ATTACK_AXES) & set(BENIGN_DYNAMIC_AXES) == set()


META_NOTES = [
    "Rows are MEASURED by running the real pipeline (run_detection) over the fusion "
    "dataset builder's procedurally crafted page pairs for a strict subset of axes; "
    "nothing is hand-authored. Regenerate deliberately (and re-verify the per-axis "
    "invariants) whenever detector behavior changes intentionally.",
    "Fused risk is computed from each row's ROUNDED feature vector through the deployed "
    "layer9_fusion (rule floors included), so the artifact is exactly self-consistent; "
    "vs production fusion on raw scores the difference is rounding-only (<= 5e-5).",
    "Content-layer invariants exclude layer1_hash (a byte-flip flag: 1.0 for ANY "
    "content change), matching Phase 11's re-measurement convention and the fusion "
    "dataset's sanity invariants.",
    "Deliberately excluded axes: sanity_* (fit-time guardrails, already pinned by "
    "test_fusion_dataset; sanity_benign_quiet also fuses 0.6583 under the deployed "
    "model's dominant layer-4 coefficient — a recorded refit-time lead); "
    "ab_test_variant, site_redesign, vendor_script_added, cert_header_rotation "
    "(legitimate heavy content deltas that legitimately reach the 0.40 material bar); "
    "seo_spam_early (measured here: weakest rows' content peak 0.0200, at the verdict "
    "noise floor — kept in the fusion dataset only); channel-adjacent duplicates of "
    "the kept attack axes.",
    "combined_subthreshold is deliberately sub-threshold by construction (Phase 11 "
    "measured its axis-minimum content peak at 0.0518): covered by the "
    "changed-verdict invariant, exempt from the 0.10 per-axis strength floor.",
    "Regeneration requires the pinned dev dependencies and the local MiniLM cache; "
    "HF_HUB_OFFLINE=1 is enforced by build_fusion_dataset so generation never touches "
    "the network. The committed artifact is the CI-fast path; the in-process rebuild "
    "in tests/test_detection_regression.py is the drift check.",
]


def _reset_faker_state() -> None:
    """build_fusion_dataset's determinism mechanics: faker instances cache
    and advance; reseed the shared state before every generation so
    repeated builds in one process stay identical."""
    Faker.seed(SEED)
    for cached in _FAKERS.values():
        cached.seed_instance(SEED)


def _plan_language(axis: str, table: dict[str, int], idx: int) -> str:
    """Same language-cycling scheme as the fusion dataset's generate():
    per-axis staggered cycling over the allowed locales (nonnative_editorial
    never gets English — its mutation rewrites in a foreign script)."""
    allowed = ("ar", "ru", "zh") if axis == "nonnative_editorial" else LANGS
    offset = sorted(table).index(axis) % len(allowed)
    return allowed[(idx + offset) % len(allowed)]


def _reconstructed_results(features: list[float], skipped: set[str]) -> dict:
    """The layer-results mapping the stored features encode: skipped layers
    as skip results (structural proofs of zero), everything else as
    measured scores — the shape layer9_fusion consumes in production."""
    return {
        key: (
            {"score": None, "skipped": True, "evidence": {"reason": "gated"}}
            if key in skipped
            else {"score": value, "evidence": {}}
        )
        for key, value in zip(FEATURE_KEYS, features, strict=True)
    }


def _fused_risk(features: list[float], skipped: set[str]) -> float:
    return float(layer9_fusion(_reconstructed_results(features, skipped))["score"])


def _content_peak(features: list[float], skipped: set[str]) -> float:
    """Max score over NON-SKIPPED content layers (2-8). layer1_hash is a
    byte-flip flag (1.0 for ANY change) and pins nothing about the content
    detectors — excluded, matching Phase 11's re-measurement convention."""
    return max(
        (
            value
            for key, value in zip(FEATURE_KEYS, features, strict=True)
            if key != "layer1_hash" and key not in skipped
        ),
        default=0.0,
    )



def validate(samples: list[dict]) -> dict:
    """Fail the build loudly rather than regenerate a regressed corpus into
    the artifact. Returns evidence recorded in the artifact's meta."""
    ids = [s["id"] for s in samples]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate sample ids")
    expected: dict[str, int] = {**ATTACK_AXES, **BENIGN_DYNAMIC_AXES}
    by_axis: dict[str, int] = {}
    for s in samples:
        by_axis[s["axis"]] = by_axis.get(s["axis"], 0) + 1
    if by_axis != dict(sorted(expected.items())):
        raise ValueError(f"per-axis counts diverge from the pinned constants: {by_axis}")
    for s in samples:
        feats = s["features"]
        if len(feats) != len(FEATURE_KEYS):
            raise ValueError(f"{s['id']}: wrong feature width")
        for v in feats:
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{s['id']}: feature out of range: {feats}")
        skipped = set(s["layers_skipped"])
        if any(feats[FEATURE_KEYS.index(k)] != 0.0 for k in skipped):
            raise ValueError(f"{s['id']}: skipped layer with nonzero feature")
        if s["label"] == 1:
            peak = _content_peak(feats, skipped)
            if not peak > NOISE_FLOOR:
                raise ValueError(
                    f"{s['id']}: attack content peak {peak:.4f} <= NOISE_FLOOR "
                    "— detectors regressed; do NOT ship this corpus"
                )
        else:
            if s["fused_risk"] >= MATERIAL_CHANGE_RISK:
                raise ValueError(
                    f"{s['id']}: benign-dynamic fused {s['fused_risk']:.4f} >= "
                    "MATERIAL_CHANGE_RISK — churn tightened cadence; do NOT ship"
                )
    return {"unique_ids": True, "axis_counts_match_constants": True}


def build_corpus(out_path: Path | None = ARTIFACT_PATH) -> dict:
    """Generate the regression corpus. Returns the artifact dict; writes it
    atomically to ``out_path`` when a path is given (``None`` = in-memory
    rebuild only — the drift-check path never touches the artifact)."""
    from worker.detection.semantics import embed_text

    if embed_text("wardress regression corpus embedder probe") is None:
        raise RuntimeError(
            "MiniLM embeddings unavailable — refusing to generate a silently-degraded "
            "regression corpus. Load the sentence-transformers cache first "
            "(HF_HUB_OFFLINE=1 is enforced; the committed artifact at "
            "worker/detection/training/regression_corpus.json is the CI-fast path)."
        )
    embedder_meta = {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "mode": "real-local-cache",
    }

    _reset_faker_state()
    samples: list[dict] = []
    done = 0
    total = sum(ATTACK_AXES.values()) + sum(BENIGN_DYNAMIC_AXES.values())
    print(f"Generating regression corpus (~{total} rows, rows/axis={ROWS_PER_AXIS})...", flush=True)
    for table, label in ((ATTACK_AXES, 1), (BENIGN_DYNAMIC_AXES, 0)):
        for axis in sorted(table):
            for idx in range(table[axis]):
                lang = _plan_language(axis, table, idx)
                measured = measure_sample(axis, label, idx, lang)
                skipped = set(measured["layers_skipped"])
                samples.append(
                    {
                        "id": measured["id"],
                        "axis": axis,
                        "label": label,
                        "language": lang,
                        "features": measured["features"],
                        "layers_skipped": measured["layers_skipped"],
                        "fused_risk": round(_fused_risk(measured["features"], skipped), 4),
                    }
                )
                done += 1
                if done % 40 == 0:
                    print(f"  measured {done}/{total} rows...", flush=True)

    validation = validate(samples)
    by_axis: dict[str, int] = {}
    for s in samples:
        by_axis[s["axis"]] = by_axis.get(s["axis"], 0) + 1
    artifact = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "seed": SEED,
            "generator": "backend/tools/build_regression_corpus.py",
            "feature_keys": list(FEATURE_KEYS),
            "embedder": embedder_meta,
            "rows_per_axis": ROWS_PER_AXIS,
            "axes": {
                "attack": dict(sorted(ATTACK_AXES.items())),
                "benign_dynamic": dict(sorted(BENIGN_DYNAMIC_AXES.items())),
            },
            "counts": {
                "total": len(samples),
                "attack": sum(s["label"] for s in samples),
                "benign": sum(1 for s in samples if s["label"] == 0),
                "by_axis": dict(sorted(by_axis.items())),
            },
            "validation": validation,
            "notes": META_NOTES,
        },
        "samples": samples,
    }

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp_path, out_path)
        print(f"Wrote {len(samples)} regression rows -> {out_path}", flush=True)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    build_corpus(out_path=args.out)


if __name__ == "__main__":
    main()

