"""Report content assembly + Markdown rendering (§8).

Both exports must describe a scan identically, so the shared loader and
formatting live here. Everything is plain data in / strings out — no
WeasyPrint imports; PDF rendering stays in app/routers/reports.py (a
worker thread in the API process, per the header rationale there).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Baseline, Scan, ScanFinding, Site


@dataclass
class ReportAsset:
    """A file bundled alongside a Markdown export (screenshot or chart).

    ``filename`` is the name inside the ZIP's ``assets/`` directory,
    ``caption`` labels it in the Markdown, ``data`` is the raw bytes, and
    ``kind`` is ``"image"`` for screenshots or ``"chart"`` for the timeline.
    """

    filename: str
    caption: str
    data: bytes
    kind: str = "image"


LAYER_TITLES = {
    1: "Layer 1 — Cryptographic hash",
    2: "Layer 2 — DOM structural diff",
    3: "Layer 3 — Link/script audit",
    4: "Layer 4 — Visual diff",
    5: "Layer 5 — Signature/keyword match",
    6: "Layer 6 — Security metadata",
    7: "Layer 7 — Cloaking/geo detection",
    8: "Layer 8 — NLP/semantic analysis",
    9: "Layer 9 — Fusion classifier",
}

# Evidence keys rendered as the per-layer summary table; anything not
# whitelisted is summarized as a count so reports stay readable and
# nothing sensitive/oversized leaks into an exported document.
_EVIDENCE_LIST_CAP = 10
_EVIDENCE_VALUE_CAP = 300


def _fmt_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        shown = [str(v)[:80] for v in value[:_EVIDENCE_LIST_CAP]]
        suffix = f" (+{len(value) - _EVIDENCE_LIST_CAP} more)" if len(value) > 10 else ""
        return ", ".join(shown) + suffix if shown else "-"
    if isinstance(value, dict):
        parts = [f"{k}: {_fmt_value(v)}" for k, v in list(value.items())[:_EVIDENCE_LIST_CAP]]
        return "; ".join(parts)[:_EVIDENCE_VALUE_CAP] or "-"
    return str(value)[:_EVIDENCE_VALUE_CAP]


def evidence_rows(evidence: dict | None) -> list[tuple[str, str]]:
    """(key, display value) pairs, deterministic order, capped."""
    if not evidence:
        return []
    return [(key, _fmt_value(value)) for key, value in evidence.items()]


class ReportData:
    """Everything a report needs, loaded once."""

    def __init__(
        self,
        site: Site,
        scan: Scan,
        baseline: Baseline | None,
        findings: list[ScanFinding],
        history: list[Scan],
    ) -> None:
        self.site = site
        self.scan = scan
        self.baseline = baseline
        self.findings = findings
        self.history = history
        self.generated_at = datetime.now(UTC)

    @property
    def verdict_label(self) -> str:
        return (self.scan.verdict.value if self.scan.verdict else "unknown").capitalize()

    @property
    def risk_pct(self) -> str:
        return f"{round((self.scan.risk_score or 0.0) * 100)}%"

    @property
    def threshold_pct(self) -> str:
        return f"{round(self.site.flag_threshold * 100)}%"


async def load_report_data(db: AsyncSession, scan_id: uuid.UUID) -> ReportData | None:
    """None when the scan doesn't exist or isn't completed — reports are
    for finished observations only."""
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is None or scan.verdict is None:
        return None
    site = await db.scalar(select(Site).where(Site.id == scan.site_id))
    if site is None:
        return None
    baseline = (
        await db.scalar(select(Baseline).where(Baseline.id == scan.baseline_id))
        if scan.baseline_id
        else None
    )
    findings = (
        await db.scalars(
            select(ScanFinding).where(ScanFinding.scan_id == scan.id).order_by(ScanFinding.layer)
        )
    ).all()
    # Timeline window: the surrounding history, oldest first.
    history = (
        await db.scalars(
            select(Scan)
            .where(Scan.site_id == site.id, Scan.risk_score.is_not(None))
            .order_by(Scan.created_at.desc())
            .limit(50)
        )
    ).all()
    return ReportData(site, scan, baseline, list(findings), list(reversed(history)))


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "-"


def render_markdown(data: ReportData, assets: list[ReportAsset] | None = None) -> str:
    """The §7 /api/reports/{scan_id}/markdown export.

    When ``assets`` is provided (the ZIP bundle path), captured screenshots
    and the timeline chart are referenced as relative image links into the
    ``assets/`` directory; without them the export stays a single portable
    Markdown file.
    """
    scan, site = data.scan, data.site
    assets = assets or []
    lines = [
        f"# Wardress incident report — {site.name}",
        "",
        f"Generated {_fmt_dt(data.generated_at)} by Wardress.",
        "",
        "## Executive summary",
        "",
        f"- **Site:** {site.name} ({site.url})",
        f"- **Scan:** `{scan.id}`",
        f"- **Scanned:** {_fmt_dt(scan.finished_at)}",
        f"- **Verdict:** {data.verdict_label}",
        f"- **Fused risk:** {data.risk_pct} (alert threshold {data.threshold_pct})",
        f"- **Baseline captured:** {_fmt_dt(data.baseline.captured_at) if data.baseline else '-'}",
    ]
    if scan.explanation:
        lines += ["", "## Analyst summary", "", scan.explanation.strip()]

    image_assets = [a for a in assets if a.kind == "image"]
    if image_assets:
        lines += ["", "## Captured evidence", ""]
        for asset in image_assets:
            img = f"![{asset.caption}](assets/{asset.filename})"
            lines += [f"**{asset.caption}**", "", img, ""]

    lines += ["", "## Per-layer findings", ""]
    for finding in data.findings:
        title = LAYER_TITLES.get(finding.layer, f"Layer {finding.layer}")
        lines.append(f"### {title}")
        lines.append("")
        if finding.skipped:
            reason = (finding.evidence or {}).get("reason", "skipped")
            lines.append(f"*Skipped:* {reason}")
        else:
            lines.append(f"**Score:** {round((finding.score or 0.0) * 100)}%")
            rows = evidence_rows(finding.evidence)
            if rows:
                lines += ["", "| Evidence | Value |", "| --- | --- |"]
                lines += [
                    f"| {key} | {value.replace('|', '/').replace(chr(10), ' ')} |"
                    for key, value in rows
                ]
        lines.append("")

    if data.history:
        lines += ["## Incident timeline (recent scans)", ""]
        chart = next((a for a in assets if a.kind == "chart"), None)
        if chart:
            lines += [f"![{chart.caption}](assets/{chart.filename})", ""]
        lines += ["| Scan time | Verdict | Risk |", "| --- | --- | --- |"]
        for h in data.history:
            verdict = h.verdict.value if h.verdict else "-"
            marker = " (this report)" if h.id == scan.id else ""
            lines.append(
                f"| {_fmt_dt(h.finished_at or h.created_at)} | {verdict}{marker} | "
                f"{round((h.risk_score or 0.0) * 100)}% |"
            )
        lines.append("")

    lines.append("---")
    lines.append("Wardress — the watch that never stands down.")
    return "\n".join(lines) + "\n"


def timeline_svg(data: ReportData, width: int = 640, height: int = 160) -> str:
    """The report's incident timeline as an inline static SVG (§8: a
    pre-rendered image, never live JS). Risk 0-1 across recent scans,
    threshold as a dashed line, the reported scan marked."""
    pad_left, pad_right, pad_top, pad_bottom = 36, 12, 12, 24
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    points = [(h.risk_score or 0.0, h.id == data.scan.id) for h in data.history]
    if not points:
        points = [(data.scan.risk_score or 0.0, True)]

    def x(i: int) -> float:
        return pad_left + (plot_w * i / max(1, len(points) - 1))

    def y(risk: float) -> float:
        return pad_top + plot_h * (1.0 - max(0.0, min(1.0, risk)))

    poly = " ".join(f"{x(i):.1f},{y(r):.1f}" for i, (r, _) in enumerate(points))
    threshold_y = y(data.site.flag_threshold)
    marks = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(r):.1f}" r="{5 if mine else 2.5}" '
        f'fill="{"#ff2047" if mine else "#3b9eff"}"/>'
        for i, (r, mine) in enumerate(points)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h}" '
        f'stroke="#c8ccce" stroke-width="1"/>'
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" '
        f'y2="{pad_top + plot_h}" stroke="#c8ccce" stroke-width="1"/>'
        f'<text x="{pad_left - 6}" y="{pad_top + 4}" text-anchor="end" font-size="9" '
        f'fill="#888e90" font-family="Helvetica">100%</text>'
        f'<text x="{pad_left - 6}" y="{pad_top + plot_h + 3}" text-anchor="end" font-size="9" '
        f'fill="#888e90" font-family="Helvetica">0%</text>'
        f'<line x1="{pad_left}" y1="{threshold_y:.1f}" x2="{pad_left + plot_w}" '
        f'y2="{threshold_y:.1f}" stroke="#ff801f" stroke-width="1" stroke-dasharray="4 3"/>'
        f'<polyline points="{poly}" fill="none" stroke="#3b9eff" stroke-width="1.5"/>'
        f"{marks}"
        "</svg>"
    )
