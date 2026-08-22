"""Fusion Arc Part A — dataset guarantees for the committed training artifact.

The artifact (worker/detection/training/fusion_dataset.json) is what Phase 9's
refit will consume, so its anti-bias controls are pinned here: exact class
balance, axis x language stratification across all three splits, hard
input-level uniqueness, sanity-row guardrails, and the laundering-axis
coverage that lets a refit avoid sign-inverted coefficients. Artifact checks
are pure JSON — hermetic and fast. Builder mechanics are exercised through a
smoke build with embed_text stubbed off (the layer's documented degraded
mode), mirroring the suite-wide no-network convention; the committed artifact
itself was generated with real MiniLM embeddings (meta.embedder records this).
"""

import json
import math

import pytest

from tools.build_fusion_dataset import (
    ARTIFACT_PATH,
    FEATURE_KEYS,
    LANGS,
    SANITY_AXES,
    build,
    cross_split_feature_duplicates,
)

ARTIFACT = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
META = ARTIFACT["meta"]
SAMPLES = ARTIFACT["samples"]

REQUIRED_KEYS = {
    "id",
    "label",
    "axis",
    "language",
    "sanity",
    "split",
    "features",
    "layers_skipped",
    "params",
    "input_sha256",
}


def _content_peak(sample: dict) -> float:
    return max(sample["features"][1:])


# --- committed artifact: schema & meta coherence ------------------------------


def test_meta_schema_and_feature_order() -> None:
    assert META["schema_version"] == 1
    assert META["seed"] == 20260822
    assert META["feature_keys"] == list(FEATURE_KEYS)
    assert META["generator"].endswith("build_fusion_dataset.py")
    assert META["embedder"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    # The shipped artifact must be full-fidelity: real local embeddings, not
    # the stubbed degraded mode used by smoke builds in CI.
    assert META["embedder"]["mode"] == "real-local-cache"
    assert META["notes"] and all(isinstance(n, str) for n in META["notes"])


def test_every_sample_is_structurally_valid() -> None:
    ids = set()
    fingerprints = set()
    for s in SAMPLES:
        assert REQUIRED_KEYS <= set(s), s["id"]
        assert s["label"] in (0, 1)
        assert s["language"] in LANGS
        assert s["split"] in ("train", "val", "test")
        assert s["sanity"] == s["axis"].startswith("sanity_")
        feats = s["features"]
        assert len(feats) == len(FEATURE_KEYS)
        for v in feats:
            assert math.isfinite(v) and 0.0 <= v <= 1.0
        # Gating contract: skipped layers contribute feature 0.0.
        for key in s["layers_skipped"]:
            assert key in FEATURE_KEYS
            assert feats[FEATURE_KEYS.index(key)] == 0.0
        fp = s["input_sha256"]
        assert len(fp) == 64 and int(fp, 16) >= 0
        assert s["id"] not in ids, "duplicate id"
        assert fp not in fingerprints, f"input fingerprint collision: {s['id']}"
        ids.add(s["id"])
        fingerprints.add(fp)
    assert len(SAMPLES) == len(ids) == len(fingerprints)


def test_meta_counts_match_samples() -> None:
    counts = META["counts"]
    n_attack = sum(s["label"] for s in SAMPLES)
    assert counts["total"] == len(SAMPLES)
    assert counts["attack"] == n_attack
    assert counts["benign"] == len(SAMPLES) - n_attack
    # Exact balance is the point of Phase 8 (the old seed set was skewed).
    assert counts["attack"] == counts["benign"]
    by_axis = {}
    by_lang = {}
    for s in SAMPLES:
        by_axis[s["axis"]] = by_axis.get(s["axis"], 0) + 1
        by_lang[s["language"]] = by_lang.get(s["language"], 0) + 1
    assert counts["by_axis"] == dict(sorted(by_axis.items()))
    assert counts["by_language"] == dict(sorted(by_lang.items()))
    split_label = {s: {"attack": 0, "benign": 0} for s in ("train", "val", "test")}
    for s in SAMPLES:
        bucket = split_label[s["split"]]
        bucket["attack" if s["label"] else "benign"] += 1
    assert counts["by_split_label"] == {k: dict(v) for k, v in sorted(split_label.items())}


# --- anti-bias controls --------------------------------------------------------


@pytest.mark.parametrize("split", ["train", "val", "test"])
def test_every_split_is_class_balanced(split: str) -> None:
    rows = [s for s in SAMPLES if s["split"] == split]
    frac = sum(s["label"] for s in rows) / len(rows)
    assert 0.44 <= frac <= 0.56


def test_splits_cover_expected_proportions() -> None:
    total = len(SAMPLES)
    n_train = sum(1 for s in SAMPLES if s["split"] == "train")
    n_val = sum(1 for s in SAMPLES if s["split"] == "val")
    n_test = sum(1 for s in SAMPLES if s["split"] == "test")
    assert n_train + n_val + n_test == total
    assert abs(n_val / total - 0.15) < 0.03
    assert abs(n_test / total - 0.15) < 0.03


def test_stratification_axes_reach_all_splits() -> None:
    by_axis_split: dict[str, set[str]] = {}
    for s in SAMPLES:
        if s["sanity"]:
            continue
        by_axis_split.setdefault(s["axis"], set()).add(s["split"])
    for axis, splits in by_axis_split.items():
        assert "train" in splits, axis
        if sum(1 for s in SAMPLES if s["axis"] == axis and not s["sanity"]) >= 7:
            assert {"val", "test"} <= splits, axis


def test_both_classes_cover_all_languages() -> None:
    evidence = META["leakage_evidence"]["languages_by_label"]
    for label in ("0", "1"):
        assert sorted(evidence[label]) == sorted(LANGS)


def test_laundering_coverage_exists_for_refit() -> None:
    """The axis that breaks class/churn confounding: attack rows carrying high
    DOM-churn features must exist alongside benign churn, or a refit could
    re-learn 'high layer2 -> benign' (the original sign inversion)."""
    launder_l2 = [s["features"][1] for s in SAMPLES if s["axis"] == "laundering_padded"]
    assert len(launder_l2) >= 10
    assert max(launder_l2) >= 0.9
    benign_churn = [s["features"][1] for s in SAMPLES if not s["label"]]
    assert max(benign_churn) >= 0.4
    attack_l6 = [s["features"][5] for s in SAMPLES if s["label"]]
    benign_l6 = [s["features"][5] for s in SAMPLES if not s["label"]]
    assert max(attack_l6) > 0.0 and max(benign_l6) > 0.0


def test_leakage_evidence_matches_recomputation() -> None:
    dups = cross_split_feature_duplicates(SAMPLES)
    evidence = META["leakage_evidence"]
    assert evidence["unique_input_fingerprints"] is True
    assert evidence["cross_split_exact_feature_duplicates"] == len(dups)
    dist = evidence["nearest_cross_split_linf_distance"]
    pair = tuple(evidence["nearest_cross_split_pair"])
    best = (1.1, "", "")
    nonzero = [s for s in SAMPLES if any(s["features"])]
    for i, a in enumerate(nonzero):
        for b in nonzero[i + 1 :]:
            if a["split"] != b["split"]:
                d = max(abs(x - y) for x, y in zip(a["features"], b["features"], strict=True))
                if d < best[0]:
                    best = (d, a["id"], b["id"])
    assert round(best[0], 4) == dist
    assert (best[1], best[2]) == pair


# --- sanity rows ----------------------------------------------------------------


def test_sanity_rows_present_guarded_and_train_only() -> None:
    sanity = [s for s in SAMPLES if s["sanity"]]
    assert len(sanity) == sum(SANITY_AXES.values())
    assert all(s["split"] == "train" for s in sanity)
    takeovers = [s for s in sanity if s["axis"] == "sanity_attack_takeover"]
    quiets = [s for s in sanity if s["axis"].startswith("sanity_benign")]
    assert len(takeovers) == SANITY_AXES["sanity_attack_takeover"]
    assert (
        len(quiets) == SANITY_AXES["sanity_benign_identical"] + SANITY_AXES["sanity_benign_quiet"]
    )
    for s in takeovers:
        assert s["label"] == 1
        assert _content_peak(s) >= 0.85
    for s in quiets:
        assert s["label"] == 0
        assert _content_peak(s) <= 0.35


# --- builder mechanics (smoke scale, embedder stubbed off) ----------------------


@pytest.fixture()
def no_embeddings(monkeypatch: pytest.MonkeyPatch):
    from worker.detection import semantics

    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


def test_sampled_payloads_match_production_patterns() -> None:
    """The payload grammar derives from the production regex tables; every
    sampled string must genuinely match its source pattern (otherwise attack
    rows would silently lose their intended signal)."""
    import random

    from tools.build_fusion_dataset import (
        _MEDIUM,
        _PROF,
        _STRONG,
        _WEAK,
        aggression_sentence,
        sample_pattern,
    )
    from worker.detection.semantics import _AGGRESSION, _TOPICS

    rng = random.Random("phase8-sampler-check")
    compiled_tables = [(compiled, 12) for compiled, _w in (*_STRONG, *_MEDIUM, *_WEAK)]
    compiled_tables += [(p, 12) for p in _PROF]
    for compiled, draws in compiled_tables:
        for _ in range(draws):
            sampled = sample_pattern(compiled.pattern, rng)
            assert compiled.search(sampled), (compiled.pattern, sampled)
    for topic in sorted(_TOPICS):
        for compiled in _TOPICS[topic]:
            for _ in range(6):
                sampled = sample_pattern(compiled.pattern, rng)
                assert compiled.search(sampled), (topic, compiled.pattern, sampled)
    # The aggression helper draws a random pattern per call; its output must
    # match whichever pattern produced it.
    for _ in range(24):
        line = aggression_sentence(rng)
        assert any(p.search(line) for p, _w in _AGGRESSION), line


def test_smoke_build_deterministic_across_runs(tmp_path, no_embeddings) -> None:
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    build(scale="smoke", out_path=out_a, embedder_required=False)
    build(scale="smoke", out_path=out_b, embedder_required=False)
    assert json.loads(out_a.read_text(encoding="utf-8")) == json.loads(
        out_b.read_text(encoding="utf-8")
    )


def test_smoke_build_records_stub_embedder_and_validates(tmp_path, no_embeddings) -> None:
    out = tmp_path / "smoke.json"
    build(scale="smoke", out_path=out, embedder_required=False)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["meta"]["scale"] == "smoke"
    assert data["meta"]["embedder"]["mode"] == "unavailable-stub"
    samples = data["samples"]
    assert sum(s["label"] for s in samples) == sum(1 for s in samples if not s["label"])
    # build() runs validate() internally; a successful write implies every
    # guard passed — assert the headline ones explicitly anyway.
    assert data["meta"]["leakage_evidence"]["unique_input_fingerprints"] is True
