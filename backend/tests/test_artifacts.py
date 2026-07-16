"""Artifact-serving endpoint tests: auth, missing rows/files, and
confinement of stored paths to the artifacts root."""

import uuid

import httpx
import pytest

from app.config import get_settings
from app.models import Baseline, BaselineStatus, Site


@pytest.fixture
def artifacts_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    # Settings is lru_cached; patch the cached instance's attribute.
    monkeypatch.setattr(get_settings(), "artifacts_dir", str(tmp_path))
    return tmp_path


async def _site_with_baseline(db_factory, screenshot_path: str | None) -> Baseline:
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com/")
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="a" * 64,
            screenshot_path=screenshot_path,
        )
        db.add(baseline)
        await db.commit()
        await db.refresh(baseline)
        return baseline


async def test_screenshot_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/artifacts/baselines/{uuid.uuid4()}/screenshot")
    assert resp.status_code == 401


async def test_screenshot_unknown_id_404(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(
        f"/api/artifacts/baselines/{uuid.uuid4()}/screenshot", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_screenshot_served(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, artifacts_dir
) -> None:
    rel = "baselines/x/screenshot.png"
    target = artifacts_dir / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x89PNG fake")
    baseline = await _site_with_baseline(db_factory, rel)

    resp = await client.get(
        f"/api/artifacts/baselines/{baseline.id}/screenshot", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG fake"


async def test_screenshot_row_without_file_404(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, artifacts_dir
) -> None:
    # DB row points at a file that no longer exists (volume wiped).
    baseline = await _site_with_baseline(db_factory, "baselines/x/screenshot.png")
    resp = await client.get(
        f"/api/artifacts/baselines/{baseline.id}/screenshot", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_screenshot_path_outside_root_404(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, artifacts_dir
) -> None:
    """Stored paths come from our own worker, but confinement must hold
    even if a row ever carried a path escaping the artifacts root."""
    outside = artifacts_dir.parent / "secret.png"
    outside.write_bytes(b"outside")
    baseline = await _site_with_baseline(db_factory, "../secret.png")
    resp = await client.get(
        f"/api/artifacts/baselines/{baseline.id}/screenshot", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_screenshot_null_path_404(
    client: httpx.AsyncClient, auth_headers: dict, db_factory, artifacts_dir
) -> None:
    baseline = await _site_with_baseline(db_factory, None)
    resp = await client.get(
        f"/api/artifacts/baselines/{baseline.id}/screenshot", headers=auth_headers
    )
    assert resp.status_code == 404
