"""Layer-8 LLM escalation (§8): semantic second opinion for scans whose
fused risk lands in the ambiguous middle band — never every scan.

Decision rules (fail-safe by construction):
- Runs only when a provider is configured AND the fused risk is inside
  [ESCALATION_LOW, ESCALATION_HIGH) AND the scan actually changed.
- The LLM can only *raise* attention (changed -> flagged when it reports
  a confident defacement classification). It can never downgrade a
  flagged verdict or suppress an alert — a wrong or hostile model answer
  must not be able to blind the engine.
- Every outcome (ran, skipped, unavailable, unparseable reply) is
  recorded in the layer-8 finding's evidence under "escalation".
- Any failure degrades silently: the scan's local verdict stands.
"""

import logging

from app.llm import (
    LLMUnavailable,
    build_classification_prompt,
    parse_classification,
    resolve_provider,
)

logger = logging.getLogger(__name__)

# The ambiguous middle band of fused risk. Below it the local layers are
# confident enough in "benign"; above it they are confident enough in
# "defacement" for the threshold logic to act alone.
ESCALATION_LOW = 0.35
ESCALATION_HIGH = 0.75

# Only a confident defacement classification may upgrade the verdict.
UPGRADE_CONFIDENCE = 0.6


def should_escalate(risk: float, changed: bool) -> bool:
    return changed and ESCALATION_LOW <= risk < ESCALATION_HIGH


async def escalate_scan(
    db,
    *,
    site_url: str,
    risk: float,
    layer_scores: dict | None,
    new_text: str,
) -> dict:
    """Run the LLM classification. Returns the escalation evidence dict;
    shape: {"status": ..., "provider"?, "classification"?, "confidence"?,
    "rationale"?}. Never raises."""
    try:
        provider = await resolve_provider(db)
        if provider is None:
            return {"status": "not configured"}
        prompt = build_classification_prompt(
            site_url=site_url, risk_score=risk, layer_scores=layer_scores, new_text=new_text
        )
        reply = await provider.generate(prompt)
        parsed = parse_classification(reply)
        if parsed is None:
            logger.warning("LLM escalation reply was unparseable")
            return {"status": "unparseable reply", "provider": provider.kind}
        return {"status": "ok", "provider": provider.kind, **parsed}
    except LLMUnavailable as exc:
        # §8: degrade silently — log it, skip the semantic layer, continue.
        logger.info("LLM escalation unavailable: %s", exc)
        return {"status": f"unavailable: {exc}"}
    except Exception:
        logger.exception("LLM escalation failed unexpectedly")
        return {"status": "failed unexpectedly — see worker logs"}


def escalation_upgrades_verdict(escalation: dict) -> bool:
    """True when the classification is a confident defacement — the only
    case allowed to change anything, and only upward."""
    return (
        escalation.get("status") == "ok"
        and escalation.get("classification") == "defacement"
        and float(escalation.get("confidence") or 0.0) >= UPGRADE_CONFIDENCE
    )
