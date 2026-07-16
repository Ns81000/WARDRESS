"""Artifact storage: HTML snapshots and screenshots on the scan-artifacts
volume. Paths are relative to the artifacts root and stored in the DB, so
the volume can move without a migration."""

from pathlib import Path

from app.config import get_settings


def artifacts_root() -> Path:
    return Path(get_settings().artifacts_dir)


def store_artifacts(kind: str, record_id: str, html: str, screenshot: bytes) -> tuple[str, str]:
    """Write html + screenshot under <root>/<kind>/<id>/ and return their
    volume-relative paths (html_rel, screenshot_rel)."""
    rel_dir = Path(kind) / record_id
    abs_dir = artifacts_root() / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    html_rel = rel_dir / "page.html"
    shot_rel = rel_dir / "screenshot.png"
    (artifacts_root() / html_rel).write_text(html, encoding="utf-8", errors="replace")
    (artifacts_root() / shot_rel).write_bytes(screenshot)
    return str(html_rel).replace("\\", "/"), str(shot_rel).replace("\\", "/")
