"""Phase 40 proofs: CI & test-quality low sweep.

- Every GitHub Actions ref pinned to a full commit SHA (one of them,
  astral-sh/setup-uv@v8, had stopped resolving upstream entirely).
- The dependency-audit gate's structural torch blind spot is disclosed and
  closed by a committed OSV cross-check tool.
- The alembic-check drift set (three migration-only indexes + a json/jsonb
  divergence on model_catalog_providers.env) that kept CI's migrations
  gate red is closed at its root: metadata declarations + one conversion
  migration, so `alembic check` exits green again.

The test_auth.py try/finally rewrite (MAX_SESSION_TTL env leak) is proven
by scratch falsifiability injection documented in WARDRESS_FIX_LOG.md — a
test guarding another test's cleanup shape would be regression theater.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from sqlalchemy.dialects import postgresql

from app.models import Base, ModelCatalogProvider
from tools.check_torch_osv import (
    build_query,
    locked_torch_versions,
    strip_local_label,
    summarize_advisory,
)
from tools.check_torch_osv import (
    main as torch_main,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
STATIC_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "static.yml"

EXPECTED_PINS = {
    "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",  # v5
    "astral-sh/setup-uv": "11f9893b081a58869d3b5fccaea48c9e9e46f990",  # v8.3.2
    "pnpm/action-setup": "0977fd99725f1db4007ccb2928dbb4e90d06cc86",  # v6
    "actions/setup-node": "a0853c24544627f65ddf259abe73b1d18a591444",  # v5
}


def workflow_uses(path: Path) -> list[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    refs = []
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if isinstance(step, dict) and step.get("uses"):
                refs.append(str(step["uses"]))
    return refs


class TestActionShaPins:
    def test_every_action_ref_in_ci_is_pinned_to_a_full_commit_sha(self):
        for ref in workflow_uses(CI_WORKFLOW):
            owner_action, _, resolved = ref.partition("@")
            assert len(resolved) == 40 and all(c in "0123456789abcdef" for c in resolved), (
                f"mutable/unpinned action ref in ci.yml: {ref}"
            )
            expected = EXPECTED_PINS.get(owner_action)
            if expected:
                assert resolved == expected, f"{owner_action} re-pinned silently: {ref}"

    def test_every_action_ref_in_static_is_pinned_to_a_full_commit_sha(self):
        for ref in workflow_uses(STATIC_WORKFLOW):
            owner_action, _, resolved = ref.partition("@")
            assert len(resolved) == 40 and all(c in "0123456789abcdef" for c in resolved), (
                f"mutable/unpinned action ref in static.yml: {ref}"
            )

    def test_no_mutable_major_tag_remains_in_either_workflow(self):
        for path in (CI_WORKFLOW, STATIC_WORKFLOW):
            text = path.read_text(encoding="utf-8")
            assert "uses:" not in text or "@v" not in "".join(
                line.split("uses:", 1)[1] for line in text.splitlines() if "uses:" in line
            ), f"major-tag pin still present in {path.name}"

    def test_setup_uv_pin_targets_an_actually_existing_ref(self):
        # astral-sh publishes no floating v8 tag/branch; the old @v8 ref
        # could not resolve at all. Pin must be the recorded v8.3.2 commit.
        refs = workflow_uses(CI_WORKFLOW)
        setup_refs = [r for r in refs if r.startswith("astral-sh/setup-uv@")]
        assert setup_refs, "setup-uv step missing from ci.yml"
        for ref in setup_refs:
            assert ref == "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990"


class TestTorchAdvisoryCrossCheck:
    def test_locked_torch_versions_parses_synthetic_lock(self, tmp_path):
        lock = tmp_path / "uv.lock"
        lock.write_text(
            '[[package]]\nname = "torch"\nversion = "2.13.0+cpu"\n'
            '[[package]]\nname = "torch"\nversion = "2.13.0"\n'
            '[[package]]\nname = "numpy"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )
        assert locked_torch_versions(lock) == ["2.13.0", "2.13.0+cpu"]

    def test_strip_local_label(self):
        assert strip_local_label("2.13.0+cpu") == "2.13.0"
        assert strip_local_label("2.13.0") == "2.13.0"

    def test_build_query_shape(self):
        payload = json.loads(build_query("2.13.0"))
        assert payload == {
            "package": {"name": "torch", "ecosystem": "PyPI"},
            "version": "2.13.0",
        }

    def test_summarize_advisory(self):
        line = summarize_advisory(
            {"id": "PYSEC-X", "aliases": ["CVE-1", "GHSA-y"], "summary": "bad thing"}
        )
        assert "PYSEC-X" in line and "CVE-1" in line and "bad thing" in line

    def test_main_exit_codes(self, monkeypatch, tmp_path):
        import tools.check_torch_osv as tool

        lock = tmp_path / "uv.lock"
        lock.write_text('[[package]]\nname = "torch"\nversion = "2.13.0+cpu"\n', encoding="utf-8")
        empty_lock = tmp_path / "empty.lock"
        empty_lock.write_text('[[package]]\nname = "numpy"\nversion = "1"\n', encoding="utf-8")

        monkeypatch.setattr(tool, "query_osv_with_retry", lambda payload: {"vulns": []})
        assert torch_main(["--lock", str(lock)]) == 0

        advisory = {"id": "PYSEC-X", "aliases": [], "summary": "s"}
        monkeypatch.setattr(tool, "query_osv_with_retry", lambda payload: {"vulns": [advisory]})
        assert torch_main(["--lock", str(lock)]) == 1

        def boom(payload):
            raise ConnectionError("unreachable")

        monkeypatch.setattr(tool, "query_osv_with_retry", boom)
        assert torch_main(["--lock", str(lock)]) == 2

        # No torch in the lockfile: nothing is unaudited -> honest pass.
        monkeypatch.setattr(tool, "query_osv_with_retry", lambda payload: {"vulns": []})
        assert torch_main(["--lock", str(empty_lock)]) == 0

        # Unreadable lockfile: fail closed with the could-not-verify code.
        assert torch_main(["--lock", str(tmp_path / "nope.lock")]) == 2

    def test_ci_discloses_exclusion_and_wires_the_cross_check(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "tools/check_torch_osv.py" in text
        assert "CPU-index" in text  # disclosure of WHY pip-audit cannot see torch
        assert "pip-audit --skip-editable" in text


class TestTriageCommentPointsAtTheRealLog:
    def test_ci_does_not_reference_the_nonexistent_progress_md(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "PROGRESS.md" not in text
        assert "WARDRESS_FIX_LOG.md" in text


class TestMigrationDriftClosure:
    @pytest.mark.parametrize(
        ("table", "index"),
        [
            ("alerts", "ix_alerts_created_at"),
            ("remediation_executions", "ix_remediation_executions_scan_id"),
            ("scans", "ix_scans_finished_at"),
        ],
    )
    def test_migration_only_indexes_declared_in_models(self, table, index):
        indexes = {ix.name for ix in Base.metadata.tables[table].indexes}
        assert index in indexes

    def test_env_column_declares_jsonb_on_postgres(self):
        env_type = ModelCatalogProvider.__table__.c.env.type
        impl = env_type.dialect_impl(postgresql.dialect())
        assert isinstance(impl, postgresql.JSONB)

    async def test_alembic_check_is_green_at_head(self, engine):
        env = dict(os.environ)
        env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)

        def alembic_check() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                [sys.executable, "-m", "alembic", "check"],
                cwd=str(BACKEND_DIR),
                env=env,
                capture_output=True,
                timeout=120,
            )

        proc = alembic_check()
        combined = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
        assert proc.returncode == 0, combined[-1500:]
