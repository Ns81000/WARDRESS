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

        if f.layer_key == "layer1_hash":
            if not ev.get("identical"):
                notes.append("HTML content SHA-256 hash changed against the baseline")

        elif f.layer_key == "layer2_dom_structure":
            # Check script_count, iframe_count, hidden_count, elements
            for k, label in [
                ("script_count", "script"),
                ("iframe_count", "iframe"),
                ("hidden_count", "hidden element"),
            ]:
                c = ev.get(k)
                if isinstance(c, dict):
                    base = c.get("baseline", 0)
                    curr = c.get("current", 0)
                    diff = curr - base
                    if diff != 0:
                        sign = "+" if diff > 0 else ""
                        notes.append(f"{label} count changed: {base} → {curr} ({sign}{diff})")
            base_el = ev.get("baseline_elements")
            curr_el = ev.get("current_elements")
            if base_el is not None and curr_el is not None and base_el != curr_el:
                diff = curr_el - base_el
                sign = "+" if diff > 0 else ""
                notes.append(f"total DOM elements changed: {base_el} → {curr_el} ({sign}{diff})")
            added_tags = ev.get("tags_added") or {}
            if isinstance(added_tags, dict) and added_tags:
                tags_str = ", ".join(f"<{tag}>" for tag in added_tags.keys())
                notes.append(f"added HTML tags: {tags_str}")

        elif f.layer_key == "layer3_link_audit":
            added_domains = []
            for kind in ("script_src", "iframe_src", "form_action", "link_href", "a_href"):
                kind_data = ev.get(kind)
                if isinstance(kind_data, dict):
                    new_doms = kind_data.get("added_new_domains") or []
                    for u in new_doms:
                        from urllib.parse import urlparse

                        dom = (urlparse(u).hostname or "").lower()
                        if dom and dom not in added_domains:
                            added_domains.append(dom)
            if added_domains:
                notes.append(f"new external domains referenced: {', '.join(added_domains[:5])}")

        elif f.layer_key == "layer4_visual_diff":
            ssim = ev.get("ssim")
            if ssim is not None:
                notes.append(f"visual similarity (SSIM) is {ssim} (1.0 is identical)")

        elif f.layer_key == "layer5_signatures":
            matches = ev.get("signature_matches") or []
            phrases = [m.get("matched", "") for m in matches[:5] if isinstance(m, dict)]
            if phrases:
                notes.append(f"matched known defacement phrasing: {', '.join(phrases)}")
            if ev.get("script_flip"):
                b_script = ev.get("baseline_dominant_script")
                c_script = ev.get("current_dominant_script")
                notes.append(f"dominant text script flipped: {b_script} → {c_script}")

        elif f.layer_key == "layer6_security_metadata":
            headers = ev.get("headers") or {}
            removed = headers.get("security_headers_removed") or []
            if removed:
                notes.append(f"removed security headers: {', '.join(removed[:5])}")
            added = headers.get("security_headers_added") or []
            if added:
                notes.append(f"added security headers: {', '.join(added[:5])}")
            tls = ev.get("tls") or {}
            if tls.get("fingerprint_changed"):
                notes.append("TLS certificate fingerprint changed")
            if tls.get("expired"):
                notes.append("TLS certificate is expired")

        elif f.layer_key == "layer7_cloaking":
            variants = ev.get("variants") or []
            divergent = [
                v.get("ua", "")
                for v in variants
                if isinstance(v, dict) and (v.get("similarity") or 1.0) < 0.8
            ]
            if divergent:
                ua_list = ", ".join(divergent[:3])
                notes.append(f"cloaking content divergence detected for User-Agents: {ua_list}")

        elif f.layer_key == "layer8_semantics":
            sim = ev.get("semantic_similarity")
            if sim is not None:
                notes.append(f"semantic similarity score is {sim}")
            aggression = ev.get("aggression_hits") or []
            if aggression:
                hits = ", ".join(
                    a.get("matched", "") for a in aggression[:5] if isinstance(a, dict)
                )
                notes.append(f"aggression lexicon hits: {hits}")

    return notes[:12]


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
