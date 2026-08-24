"""Phase 33 — Docs Sweep A (ops/remediation): drift-resistance pins.

The audit filed three docs-mismatch findings against these surfaces (Telegram
remediation approval, "separate Celery queue", unconditional uninstall backup
contract). The corrections are prose, but their regression class is mechanical:
someone re-adding an aspirational claim the code does not implement. These pins
make that drift fail loudly instead of shipping silently. They deliberately pin
the ABSENCE of each defective claim plus ONE truthful anchor per surface —
never full sentence shapes, so legitimate copy edits don't false-alarm.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
REMEDIATION_DOCS = REPO / "docs" / "remediation-hooks.mdx"
INSTALLATION_DOCS = REPO / "docs" / "installation.mdx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_does_not_claim_a_separate_celery_queue_for_firings():
    text = _read(README)
    assert "separate Celery queue" not in text
    assert "slow/broken endpoints never block the scan engine" not in text
    assert "same single queue and worker pool" in text


def test_remediation_docs_do_not_claim_telegram_approval():
    text = _read(REMEDIATION_DOCS)
    assert "or use the Telegram Bot" not in text
    assert "log into the dashboard" in text
    assert "AI-assistant actions only" in text


def test_uninstall_readme_documents_the_enforced_backup_contract():
    text = _read(README)
    assert "-AllowIncompleteBackup" in text
    assert "stops before deleting anything" in text
    assert "RESTORE.txt" in text


def test_uninstall_installation_docs_document_the_enforced_backup_contract():
    text = _read(INSTALLATION_DOCS)
    assert "-AllowIncompleteBackup" in text
    assert "stops before\ndeleting anything" in text or "stops before deleting anything" in text
    assert "docker compose cp" in text
    assert "RESTORE.txt" in text
