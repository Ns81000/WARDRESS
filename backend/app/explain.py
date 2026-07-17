""" "Explain this incident" (§8): plain-English scan summary via the
configured LLM provider, cached on the scan row.

Shared by the API endpoint and the Telegram bot so both surfaces behave
identically (same prompt, same cache, same degradation)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import LLMUnavailable, build_explain_prompt, resolve_provider
from app.models import Scan, ScanFinding, Site

logger = logging.getLogger(__name__)


class ExplainError(Exception):
    """User-facing explanation failure ('not configured', 'scan not
    finished'). The message is safe to show verbatim."""


def _findings_notes(findings: list[ScanFinding]) -> list[str]:
    """Compact human-readable evidence bullets for the prompt (never raw
    dumps — the prompt stays small and the model stays focused)."""
    notes: list[str] = []
    for f in findings:
        ev = f.evidence or {}
        if f.skipped or not ev:
            continue
        if f.layer_key == "layer3_link_audit":
            for domain_list_key in ("added_new_domains", "added_script_domains"):
                domains = ev.get(domain_list_key)
                if isinstance(domains, dict):
                    for kind, items in domains.items():
                        if items:
                            notes.append(f"new external {kind} domains: {', '.join(items[:5])}")
                elif isinstance(domains, list) and domains:
                    notes.append(f"new external domains: {', '.join(domains[:5])}")
        elif f.layer_key == "layer5_signatures":
            matches = ev.get("matches") or []
            phrases = [m.get("matched", "") for m in matches[:5] if isinstance(m, dict)]
            if phrases:
                notes.append(f"matched known defacement phrasing: {', '.join(phrases)}")
        elif f.layer_key == "layer4_visual_diff":
            ssim = ev.get("ssim")
            if ssim is not None:
                notes.append(f"visual similarity (SSIM) dropped to {ssim}")
        elif f.layer_key == "layer6_security_metadata":
            removed = ev.get("removed_security_headers") or []
            if removed:
                notes.append(f"security headers removed: {', '.join(removed[:5])}")
            if ev.get("tls_changed"):
                notes.append("TLS certificate changed")
        elif f.layer_key == "layer2_dom_structure":
            for k in ("script_delta", "iframe_delta", "hidden_delta"):
                if ev.get(k):
                    notes.append(f"{k.replace('_delta', '')} count changed by {ev[k]}")
    return notes[:10]


async def explain_scan(db: AsyncSession, scan_id: uuid.UUID, *, force: bool = False) -> dict:
    """Generate (or return the cached) explanation for one scan.
    Returns {"explanation", "provider", "generated_at", "cached"}.
    Raises ExplainError with a user-safe message on any failure."""
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is None:
        raise ExplainError("Scan not found")
    if scan.verdict is None:
        raise ExplainError("This scan has not finished yet")

    if scan.explanation and not force:
        return {
            "explanation": scan.explanation,
            "provider": scan.explanation_provider or "unknown",
            "generated_at": scan.explanation_at,
            "cached": True,
        }

    provider = await resolve_provider(db)
    if provider is None:
        raise ExplainError(
            "No AI provider is configured — add a Gemini API key or enable Ollama in Settings"
        )

    site = await db.scalar(select(Site).where(Site.id == scan.site_id))
    findings = (
        await db.scalars(
            select(ScanFinding).where(ScanFinding.scan_id == scan.id).order_by(ScanFinding.layer)
        )
    ).all()

    prompt = build_explain_prompt(
        site_name=site.name if site else "unknown",
        site_url=site.url if site else "unknown",
        verdict=scan.verdict.value,
        risk_score=float(scan.risk_score or 0.0),
        flag_threshold=float(site.flag_threshold if site else 0.5),
        layer_scores=scan.layer_scores,
        findings_notes=_findings_notes(list(findings)),
    )
    try:
        text = await provider.generate(prompt)
    except LLMUnavailable as exc:
        raise ExplainError(f"The AI provider could not answer right now: {exc}") from None

    scan.explanation = text
    scan.explanation_provider = provider.kind
    scan.explanation_at = datetime.now(UTC)
    await db.commit()
    return {
        "explanation": text,
        "provider": provider.kind,
        "generated_at": scan.explanation_at,
        "cached": False,
    }
