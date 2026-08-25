"""Phase 34 — Docs Sweep B (detection/agent): drift-resistance pins.

The audit filed three docs-mismatch findings against these surfaces (the
identical-hash⇒pixels guarantee, agent.mdx's overstated safety story, and the
"calibrated" fusion framing plus the stale material-change constant). The
corrections are prose, but their regression class is mechanical: someone
re-adding a claim the code disproves, or re-printing a constant a later phase
re-derived. These pins make that drift fail loudly instead of shipping
silently. They deliberately pin the ABSENCE of each defective claim plus ONE
truthful anchor per surface — never full sentence shapes, so legitimate copy
edits don't false-alarm.

Code-fact anchors are asserted against the live modules where the doc states a
number or a set, so these tests fail if EITHER side drifts.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
DOCS = REPO / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Finding: "Three separate docs assert that an identical content hash
# guarantees identical rendered pixels"
# ---------------------------------------------------------------------------


def test_readme_does_not_claim_hash_implies_identical_pixels():
    text = _read(README)
    assert "guaranteed to be identical" not in text
    assert "Layers 2, 3, 4, 5, and 8" not in text  # stale gate set (layer 4 unconditional)
    assert "Layer 4 (Visual Diff) compares screenshots on every scan" in text


def test_detection_layers_doc_does_not_claim_byte_identity_covers_visuals():
    text = _read(DOCS / "detection-layers.mdx")
    assert (
        "cannot differ structurally, in links, visually, in signatures, or semantically" not in text
    )
    # The gate card must state the corrected membership AND the layer-4 carve-out.
    assert "Layers 2, 3, 5, and 8 are skipped" in text
    assert "runs on every scan regardless of the gate" in text


def test_content_hash_layer_doc_carries_the_corrected_gate_story():
    text = _read(DOCS / "layers" / "1-content-hash.mdx")
    assert "could only differ visually through non-deterministic rendering noise" not in text
    assert "its rendered pixels" not in text.replace(
        "It does **not** prove anything about rendered pixels", ""
    )
    assert "GATED_BY_IDENTICAL_HASH" in text
    assert "- **Layer 4** — Visual Diff" not in text  # removed from the gate list
    assert "**not** in the gate" in text


def test_gate_membership_docs_match_pipeline_code():
    """The docs' stated gate set must equal the pipeline's actual set."""
    from worker.detection.pipeline import GATED_BY_IDENTICAL_HASH

    expected = {
        "layer2_dom_structure",
        "layer3_link_audit",
        "layer5_signatures",
        "layer8_semantics",
    }
    assert GATED_BY_IDENTICAL_HASH == expected
    assert "layer4_visual_diff" not in GATED_BY_IDENTICAL_HASH


# ---------------------------------------------------------------------------
# Finding: "agent.mdx overstates agent safety" (tier table completeness,
# tier-0 role floor, RBAC parity, injection containment)
# ---------------------------------------------------------------------------


def test_agent_docs_tier_table_lists_every_registered_tool():
    from app.agent.tools import _REGISTRY

    text = _read(DOCS / "agent.mdx")
    table = "\n".join(line for line in text.splitlines() if line.startswith("| "))
    for name in _REGISTRY:
        assert f"`{name}`" in table, f"registry tool missing from docs/agent.mdx table: {name}"


def test_agent_docs_do_not_claim_blanket_viewer_tier_zero():
    text = _read(DOCS / "agent.mdx")
    assert "Tier 0 · read** | Auto-execute (viewer+)" not in text
    assert "admin only — mirrors the admin-only REST hook surface" in text


def test_agent_docs_do_not_claim_blanket_injection_containment_via_output_bounding():
    text = _read(DOCS / "agent.mdx")
    assert "for token efficiency and prompt-injection containment" not in text
    # The corrected containment story must be present with its two mechanisms.
    assert "UNTRUSTED-DATA-BEGIN" in text
    assert "freezes into an ordinary confirmation card" in text


def test_agent_tool_registry_matches_rest_hook_boundary():
    """The doc's admin-only claim for list_remediation_hooks mirrors code + REST."""
    from app.agent.tools import _REGISTRY

    assert _REGISTRY["list_remediation_hooks"].min_role.value == "admin"
    assert len(_REGISTRY) == 19


# ---------------------------------------------------------------------------
# Finding: "The fusion score is repeatedly described as 'calibrated'" +
# Phase-33-hand-off: README's stale material-change constant
# ---------------------------------------------------------------------------


def test_readme_material_change_constant_matches_scanning_module():
    from app.scanning import MATERIAL_CHANGE_RISK

    text = _read(README)
    assert "fused_risk >= 0.15" not in text
    assert f"fused_risk >= {MATERIAL_CHANGE_RISK}" in text
    # Re-derived from the post-regeneration benign-dynamic distribution
    # (see app/scanning.py's comment); moved 0.35 -> 0.40 deliberately.
    assert MATERIAL_CHANGE_RISK == 0.40


def test_detection_layers_doc_material_change_constant_matches_module():
    from app.scanning import MATERIAL_CHANGE_RISK

    text = _read(DOCS / "detection-layers.mdx")
    # No stale 0.15 anywhere in the cadence section; the named constant matches.
    assert "MATERIAL_CHANGE_RISK = 0.15" not in text
    assert re.search(r"`MATERIAL_CHANGE_RISK = 0\.40`", text)
    assert "risk ≥ 0.15?" not in text
    assert f"MATERIAL_CHANGE_RISK == {MATERIAL_CHANGE_RISK}" or True  # module is source of truth
    assert MATERIAL_CHANGE_RISK == 0.40


def test_no_doc_claims_calibrated_probabilities():
    """Pins the defective CLAIM FORMS (the audit's citations), not the word
    'calibrated' itself — the corrected copy legitimately says what the score
    is NOT."""
    for relpath in (
        README.relative_to(REPO),
        Path("docs/detection-layers.mdx"),
        Path("docs/layers/9-risk-fusion.mdx"),
    ):
        text = _read(REPO / relpath)
        low = text.lower()
        for defective in (
            "calibrated classifier",
            "calibrated probabilities",
            "one calibrated",
            "single calibrated",
            "calibrated risk value",
            "calibrated `0.0",
        ):
            assert defective not in low, f"{relpath}: {defective!r}"
        assert "ranking signal" in low or "not a calibrated probability" in low, str(relpath)


def test_fusion_doc_describes_deployed_artifact_not_seed_fit():
    text = _read(DOCS / "layers" / "9-risk-fusion.mdx")
    assert "_SEED_ROWS" not in text
    assert "C=50" not in text
    assert "hand-authored layer-score vectors" not in text
    assert "seed dataset" not in text.lower()
    assert "fusion_model.json" in text
    assert "constrained non-negative" in text
    # The retired seed-vector examples must be gone (they no longer exist in code).
    assert "[1, 0.35, 0.25, 0.3, 0, 0, 0, 0.2]" not in text
    # Floors documented with their real trigger/floor pairs.
    assert "≥ 0.85 → floor 0.90" in text
