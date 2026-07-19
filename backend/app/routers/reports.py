"""Report export (§7/§8): /api/reports/{scan_id}/pdf and /markdown.

PDF is WeasyPrint (Jinja2 HTML/CSS -> PDF, CSS Paged Media for the
cover page, running headers/footers and numbered pages) rendered in a
worker thread inside the API process — the Phase 0 rationale for
WeasyPrint-over-Playwright explicitly includes "report rendering must
work even if the browser pool is saturated or wedged", so it must not
queue behind scan jobs. Screenshots are embedded as data URIs read from
the artifacts volume (mounted read-only in the app container).
"""

import asyncio
import base64
import io
import logging
import re
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.reporting import (
    LAYER_TITLES,
    ReportAsset,
    ReportData,
    evidence_rows,
    load_report_data,
    render_markdown,
    timeline_svg,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

DB = Annotated[AsyncSession, Depends(get_db)]

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

_VERDICT_COLORS = {
    "flagged": "#ff2047",
    "changed": "#ff801f",
    "clean": "#11ff99",
    "error": "#a1a4a5",
}

_SUMMARY_SENTENCES = {
    "flagged": (
        "The fused risk met or exceeded the alert threshold: the change patterns "
        "resemble unauthorized modification and warrant review."
    ),
    "changed": (
        "Differences from the trusted baseline were observed, but the fused risk "
        "stayed below the alert threshold."
    ),
    "clean": "No meaningful differences from the trusted baseline were observed.",
    "error": "The scan could not complete normally; see the error detail on the scan.",
}


def _score_class(score: float | None, skipped: bool) -> str:
    if skipped:
        return "score-skip"
    s = score or 0.0
    if s >= 0.5:
        return "score-high"
    if s >= 0.15:
        return "score-mid"
    return "score-low"


def _screenshot_data_uri(rel_path: str | None) -> str | None:
    """Read a stored screenshot (confined to the artifacts root) and
    return it as a data URI, or None — a missing artifact degrades to a
    report without that image, never a failed export."""
    if not rel_path:
        return None
    root = Path(get_settings().artifacts_dir).resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    try:
        payload = base64.b64encode(candidate.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:image/png;base64,{payload}"


def _screenshot_bytes(rel_path: str | None) -> bytes | None:
    """Raw PNG bytes for a stored screenshot (confined to the artifacts
    root), or None — used to bundle images into the Markdown ZIP."""
    if not rel_path:
        return None
    root = Path(get_settings().artifacts_dir).resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    try:
        return candidate.read_bytes()
    except OSError:
        return None


def _markdown_assets(data: ReportData) -> list[ReportAsset]:
    """Screenshots + timeline chart to bundle beside a Markdown export.
    Only images that actually exist on disk are included; the timeline is
    always available (generated from numeric data)."""
    assets: list[ReportAsset] = []
    baseline_png = _screenshot_bytes(
        data.baseline.screenshot_path if data.baseline else None
    )
    if baseline_png:
        assets.append(
            ReportAsset("baseline.png", "Trusted baseline", baseline_png, kind="image")
        )
    scan_png = _screenshot_bytes(data.scan.screenshot_path)
    if scan_png:
        assets.append(
            ReportAsset("current-scan.png", "This scan", scan_png, kind="image")
        )
    if assets:
        # Only bundle the chart when there's already an assets/ dir to
        # justify the ZIP; a screenshot-free report stays a single file.
        assets.append(
            ReportAsset(
                "timeline.svg",
                "Incident timeline",
                timeline_svg(data).encode("utf-8"),
                kind="chart",
            )
        )
    return assets


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "-"


def _render_report_html(data: ReportData) -> str:
    scan, site = data.scan, data.site
    verdict = scan.verdict.value if scan.verdict else "error"
    findings_ctx = [
        {
            "title": LAYER_TITLES.get(f.layer, f"Layer {f.layer}"),
            "skipped": f.skipped,
            "skip_reason": (f.evidence or {}).get("reason", "skipped"),
            "score_display": ("skipped" if f.skipped else f"{round((f.score or 0.0) * 100)}%"),
            "score_class": _score_class(f.score, f.skipped),
            "rows": evidence_rows(f.evidence) if not f.skipped else [],
        }
        for f in data.findings
    ]
    history_ctx = [
        {
            "when": _fmt_dt(h.finished_at or h.created_at),
            "verdict": h.verdict.value if h.verdict else "-",
            "risk": f"{round((h.risk_score or 0.0) * 100)}%",
            "mine": h.id == scan.id,
        }
        for h in reversed(data.history)  # newest first in the table
    ]
    template = _jinja.get_template("report/report.html")
    return template.render(
        site_name=site.name,
        site_url=site.url,
        scan_id=str(scan.id),
        scanned_at=_fmt_dt(scan.finished_at),
        baseline_at=_fmt_dt(data.baseline.captured_at) if data.baseline else "-",
        generated_at=_fmt_dt(data.generated_at),
        verdict_label=data.verdict_label,
        verdict_color=_VERDICT_COLORS.get(verdict, "#a1a4a5"),
        risk_pct=data.risk_pct,
        threshold_pct=data.threshold_pct,
        summary_sentence=_SUMMARY_SENTENCES.get(verdict, ""),
        explanation=scan.explanation,
        explanation_provider=scan.explanation_provider or "AI",
        baseline_shot=_screenshot_data_uri(
            data.baseline.screenshot_path if data.baseline else None
        ),
        scan_shot=_screenshot_data_uri(scan.screenshot_path),
        timeline_svg=Markup(timeline_svg(data)),  # noqa: S704 — generated in-process from numeric data, no user input
        history_count=len(data.history),
        findings=findings_ctx,
        history=history_ctx,
    )


def _render_pdf_bytes(html: str) -> bytes:
    """CPU/IO-bound WeasyPrint render; called via asyncio.to_thread."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def _filename(site_name: str, scan_id: uuid.UUID, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", site_name).strip("-").lower() or "site"
    return f"wardress-report-{slug}-{str(scan_id)[:8]}.{ext}"


@router.get("/{scan_id}/markdown")
async def report_markdown(scan_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    data = await load_report_data(db, scan_id)
    if data is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Scan not found or not completed — reports need a finished scan",
        )
    assets = _markdown_assets(data)
    if not assets:
        # No screenshots on disk — a single portable Markdown file.
        markdown = render_markdown(data)
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_filename(data.site.name, scan_id, "md")}"'
                )
            },
        )

    # Screenshots present — bundle report.md + assets/ into a ZIP so the
    # image links resolve when the report is opened.
    markdown = render_markdown(data, assets)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.md", markdown)
        for asset in assets:
            zf.writestr(f"assets/{asset.filename}", asset.data)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(data.site.name, scan_id, "zip")}"'
            )
        },
    )


@router.get("/{scan_id}/pdf")
async def report_pdf(scan_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    data = await load_report_data(db, scan_id)
    if data is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Scan not found or not completed — reports need a finished scan",
        )
    html = _render_report_html(data)
    try:
        pdf = await asyncio.to_thread(_render_pdf_bytes, html)
    except Exception:
        logger.exception("PDF rendering failed for scan %s", scan_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PDF rendering failed — see server logs (Markdown export is still available)",
        ) from None
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(data.site.name, scan_id, "pdf")}"'
            )
        },
    )
