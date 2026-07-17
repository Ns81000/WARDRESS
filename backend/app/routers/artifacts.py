"""Serve stored scan/baseline screenshots to the dashboard.

Auth-protected; paths come from DB rows only (never client-supplied), and
are additionally confined to the artifacts root to make traversal
structurally impossible.
"""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.models import Baseline, Scan

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _resolve_artifact(rel_path: str) -> Path:
    root = Path(get_settings().artifacts_dir).resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    if not candidate.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return candidate


@router.get("/baselines/{baseline_id}/screenshot")
async def baseline_screenshot(
    baseline_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    baseline = await db.scalar(select(Baseline).where(Baseline.id == baseline_id))
    if baseline is None or not baseline.screenshot_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return FileResponse(_resolve_artifact(baseline.screenshot_path), media_type="image/png")


@router.get("/scans/{scan_id}/screenshot")
async def scan_screenshot(
    scan_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is None or not scan.screenshot_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return FileResponse(_resolve_artifact(scan.screenshot_path), media_type="image/png")


# HTML snapshots power the DOM diff tree viewer (Phase 3). Served as
# text/plain, never text/html: a stored page is untrusted captured
# content and must not be renderable/executable in the dashboard origin.
# The frontend parses it with DOMParser (inert document) client-side.
_HTML_AS_TEXT = "text/plain; charset=utf-8"


@router.get("/baselines/{baseline_id}/html")
async def baseline_html(
    baseline_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    baseline = await db.scalar(select(Baseline).where(Baseline.id == baseline_id))
    if baseline is None or not baseline.html_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return FileResponse(_resolve_artifact(baseline.html_path), media_type=_HTML_AS_TEXT)


@router.get("/scans/{scan_id}/html")
async def scan_html(
    scan_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is None or not scan.html_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return FileResponse(_resolve_artifact(scan.html_path), media_type=_HTML_AS_TEXT)
