"""Phase 43 — Final Docs/README Sync: drift-resistance pins.

One last full pass reconciling README.md and every docs/ file against the
fully-fixed, fully-re-audited codebase (fresh verification, not prior
phases' notes). Same discipline as Phases 33/34/41: pin the ABSENCE of
each stale claim, ONE truthful anchor per corrected surface, and code-fact
anchors so docs and code cannot drift apart silently in either direction.
Docs-only phase: no production code changed; these pins are the deliverable
that keeps it that way.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
USAGE_DOCS = REPO / "docs" / "usage.mdx"
INTRODUCTION_DOCS = REPO / "docs" / "introduction.mdx"
API_REFERENCE_DOCS = REPO / "docs" / "api-reference.mdx"
DETECTION_LAYERS_DOCS = REPO / "docs" / "detection-layers.mdx"
COMPONENTS_DOC = REPO / "docs" / "frontend" / "components.mdx"
DOM_DOC = REPO / "docs" / "layers" / "2-dom-structure.mdx"
VISUAL_DOC = REPO / "docs" / "layers" / "4-visual-diff.mdx"
SIGNATURES_DOC = REPO / "docs" / "layers" / "5-signatures.mdx"
CLOAKING_DOC = REPO / "docs" / "layers" / "7-cloaking.mdx"
LINK_AUDIT_DOC = REPO / "docs" / "layers" / "3-link-audit.mdx"
CONTENT_HASH_DOC = REPO / "docs" / "layers" / "1-content-hash.mdx"
SEMANTICS_DOC = REPO / "docs" / "layers" / "8-semantics.mdx"
REMEDIATION_DOCS = REPO / "docs" / "remediation-hooks.mdx"
RISK_GAUGE_TSX = REPO / "frontend" / "src" / "components" / "risk-gauge.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_detection_layers_mermaid_gate_excludes_visual_layer():
    text = _read(DETECTION_LAYERS_DOCS)
    assert "Skip 2 · 3 · 4 · 5 · 8" not in text
    assert "Run 2 · 3 · 4 · 5 · 8" not in text
    assert "Skip 2 · 3 · 5 · 8" in text
    assert "Run 2 · 3 · 5 · 8" in text
    # Layer 4 belongs to the always-run group alongside 6 and 7.
    always_lines = []
    inside = False
    for line in text.splitlines():
        if line.strip().startswith("subgraph ALWAYS"):
            inside = True
            continue
        if inside and line.strip() == "end":
            break
        if inside:
            always_lines.append(line)
    always = "\n".join(always_lines)
    assert "L4[4 · Visual Diff]" in always
    assert "L6[6 · Security Metadata]" in always
    assert "L7[7 · Cloaking]" in always


def test_readme_layer_rows_describe_post_fix_mechanics():
    text = _read(README)
    # Layer 2: technique-independent hiding (Phase 23), not inline-only.
    assert "style attributes that force element hiding" not in text
    assert "hidden by any technique" in text
    assert "stylesheet classes" in text
    # Layer 3: iframes collected + browser-faithful normalization (Phases 36).
    assert "iframe sources" in text
    assert "browser-faithfully" in text
    # Layer 4: chroma term (Phase 36).
    assert "chroma-shift term" in text
    # Layer 5: leet decoding + inflow rule (Phase 22).
    assert "leetspeak spellings" in text
    assert "inflow of a previously-absent script" in text


def test_health_captions_match_measured_telemetry():
    for path in (README, USAGE_DOCS):
        text = _read(path)
        assert "average scan execution throughput" not in text
        assert "average scan duration, and degraded-capture counts" in text


def test_introduction_self_hosted_card_matches_local_imagery():
    text = _read(INTRODUCTION_DOCS)
    # Phase 27 removed every third-party image fetch; the old disclosure is
    # false. PROMPT-001 restored bundled same-origin logos + an opt-in
    # server-side favicon resolver; the copy must state the new truth.
    assert "loads site favicons and provider logos from public CDNs" not in text
    assert "no browser request ever reaches a third-party image CDN" in text
    assert "OFF by default" in text
    # The configured-channels egress truth stays.
    assert "channels you configure" in text


def test_api_reference_notes_analyst_gate_on_key_creation():
    text = _read(API_REFERENCE_DOCS)
    assert "session (own keys) · POST analyst+" in text


def test_dom_doc_describes_technique_independent_hidden_detection():
    text = _read(DOM_DOC)
    assert "or its inline `style` contains" not in text
    assert "`<style>` blocks" in text
    assert "`opacity: 0` or `font-size: 0`" in text
    assert "@media" in text
    assert "input[type=hidden]" in text
    assert "hidden_detection" in text


def test_visual_doc_describes_chroma_term_and_degraded_contract():
    text = _read(VISUAL_DOC)
    assert "three ways" not in text
    assert "Three measurements" not in text
    assert "Four measurements" in text
    assert 'converted to grayscale (`convert("L")`)' not in text
    assert "the layer returns `0.0` with a note and the other eight layers still run" not in text
    assert "**degraded** result (`score: null`, `degraded: true`)" in text
    assert "*unknown*" in text
    assert "0.30 * chroma_score" in text
    assert "chroma_mean_delta_255" in text
    assert "0.15–0.20" in text


def test_signatures_doc_describes_dual_view_matching_and_inflow_rule():
    text = _read(SIGNATURES_DOC)
    # Dual-view leet decoding with verbatim evidence.
    assert "leet-decoded" in text.lower() or "leetspeak decoding" in text
    assert "`H@CK3D BY`" in text
    assert "original page spelling" in text
    # The inflow rule exists beside the dominance flip.
    assert "New-script inflow" in text
    assert "page_share >= 0.05" in text
    assert "script_inflow" in text
    assert "scripts_added" in text
    # Full-text profiling default (cap demoted to opt-in).
    assert "**full** visible text" in text
    # Old sole-rule framing retired.
    old_sole_rule = "flip_score  = 0.7 if script_flip else 0.0"
    assert old_sole_rule not in text


def test_cloaking_doc_describes_graded_scoring_not_soft_knee():
    text = _read(CLOAKING_DOC)
    assert "(worst_divergence - 0.5) / 0.5" not in text
    assert "soft knee sits at 0.5" not in text
    assert "Divergence up to 50% scores `0.0`" not in text
    assert "returns `0.0` with a note" not in text
    # Graded dual-channel reality: churn grace, two ramps, new-token fraction,
    # degraded-not-zero probe handling.
    assert "12 or fewer" in text
    assert "new-token fraction" in text
    assert "**0.15**" in text
    assert "**0.45**" in text
    assert "**degraded** result (`score: null`)" in text
    assert "worst (highest) variant score" in text


def test_link_audit_doc_documents_whatwg_normalization():
    text = _read(LINK_AUDIT_DOC)
    assert "browser-faithfully" in text
    assert "/\\evil.com/x.js" in text


def test_content_hash_doc_marks_missing_baseline_degraded_not_skipped():
    text = _read(CONTENT_HASH_DOC)
    assert "are skipped with the reason" not in text
    assert "marked **degraded**" in text
    assert "*unknown* to fusion" in text


def test_semantics_doc_warns_about_tiny_page_drift_amplification():
    text = _read(SEMANTICS_DOC)
    assert "Tiny pages amplify drift" in text
    assert "raise the site's flag threshold" in text


def test_remediation_hooks_doc_documents_ssrf_discipline():
    text = _read(REMEDIATION_DOCS)
    assert "allow_private_networks" in text
    assert "SSRF address gate" in text
    assert "pins the connection" in text


def test_components_doc_risk_tone_band_is_described_as_display_only():
    text = _read(COMPONENTS_DOC)
    assert "— the scheduler's material-change band." not in text
    assert "distinct from the scheduler's material-change bar" in text
    # Code-fact anchor: the component really does use the fixed 0.15 display
    # band this section documents (either side drifting fails loudly).
    gauge = _read(RISK_GAUGE_TSX)
    assert "risk >= 0.15" in gauge
