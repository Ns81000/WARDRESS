"""Phase 41 — Final Docs Sweep: drift-resistance pins.

Seven doc-only findings closed here (edit-UI claim, vacuous type-check
command, RBAC API-key rows, "full visible text" semantics claim, Layer-6
directional header diff, usage brute-force claim, link-audit diagram).
Same discipline as Phases 33/34: pin the ABSENCE of each defective claim,
ONE truthful anchor per corrected surface, and code-fact anchors so the
docs and the code cannot drift apart silently in either direction.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
CONFIGURATION_DOCS = REPO / "docs" / "configuration.mdx"
SECURITY_DOCS = REPO / "docs" / "security-and-dev.mdx"
USAGE_DOCS = REPO / "docs" / "usage.mdx"
REMEDIATION_DOCS = REPO / "docs" / "remediation-hooks.mdx"
SEMANTICS_DOC = REPO / "docs" / "layers" / "8-semantics.mdx"
METADATA_DOC = REPO / "docs" / "layers" / "6-security-metadata.mdx"
LINK_AUDIT_DOC = REPO / "docs" / "layers" / "3-link-audit.mdx"
PACKAGE_JSON = REPO / "frontend" / "package.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_remediation_docs_do_not_claim_an_edit_ui():
    text = _read(REMEDIATION_DOCS)
    assert "an Admin can edit the hook" not in text
    assert "no edit form in the dashboard" in text
    assert "/remediation-hooks/<hook_id>" in text
    assert "requires_manual_confirm" in text
    assert "Add hook" in text


def test_readme_type_check_command_compiles_files():
    readme = _read(README)
    dev_docs = _read(SECURITY_DOCS)
    for text in (readme, dev_docs):
        assert "pnpm exec tsc --noEmit" not in text
        assert "pnpm type-check" in text
    package = _read(PACKAGE_JSON)
    assert '"type-check": "tsc -b --noEmit"' in package


def test_security_and_dev_backend_section_matches_the_postgres_harness():
    text = _read(SECURITY_DOCS)
    assert "in-memory SQLite" not in text
    assert "aiosqlite" not in text
    assert "Alembic migrations" in text
    assert "PostgreSQL instance" in text


def test_rbac_tables_split_key_creation_from_key_management():
    for path in (README, CONFIGURATION_DOCS):
        lines = [
            line
            for line in _read(path).splitlines()
            if line.startswith("|") and "Create new API keys" in line
        ]
        assert len(lines) == 1, f"{path.name}: expected exactly one create-keys row"
        row = lines[0]
        granted = row.count("✓") + row.count('icon="check"')
        assert granted == 2, f"{path.name}: key creation must be analyst+, not viewer-granted"
        assert "Manage personal API keys" not in "\n".join(_read(path).splitlines())


def test_semantics_doc_describes_multi_window_drift_not_full_text_embedding():
    text = _read(SEMANTICS_DOC)
    assert "full** baseline visible text" not in text
    assert "(0.85 - semantic_similarity) / 0.85" not in text
    assert "multi-window" in text.lower() or "Multi-window" in text or "windows" in text
    assert "best-matching" in text
    assert "lower of the two directions" in text
    assert "48 embed calls" in text


def test_layer6_doc_describes_the_directional_header_diff():
    text = _read(METADATA_DOC)
    assert "disappearing or weakening** is a downgrade" not in text
    assert "security_headers_weakened" in text
    assert "security_headers_strengthened" in text
    assert "security_headers_changed" in text
    assert "score = min(0.8, 0.3 * len(removed) + 0.1 * len(weakened))" in text


def test_usage_doc_brute_force_claim_names_the_enforced_controls():
    text = _read(USAGE_DOCS)
    assert "strict server-side rate limits to prevent brute-force attacks" not in text
    assert "per-account lockout" in text
    assert "audit trail" in text


def test_link_audit_diagram_matches_its_own_table_and_the_code():
    text = _read(LINK_AUDIT_DOC)
    diagram_lines = [line for line in text.splitlines() if "Collect 5 ref kinds" in line]
    assert len(diagram_lines) == 1
    node = diagram_lines[0]
    assert "img" not in node
    assert "iframe" in node
