"""Optional LLM intelligence layer (§8): Gemini (`gemini-flash-latest`)
and Ollama (OpenAI-compatible local endpoint).

Used for exactly two things:
(a) semantic classification of scans whose fused risk lands in the
    ambiguous middle band (worker, scan pipeline) — never every scan;
(b) the "Explain this incident" button (API + Telegram bot).

Hard rules (master prompt §8):
- One model string (``GEMINI_MODEL``) everywhere: ``gemini-flash-latest``,
  Google's stable alias for the current flash model (the previously
  pinned ``gemini-2.5-flash`` was retired for new API keys in 2026).
- Rate limiting via aiolimiter, tuned conservatively under the free
  tier (~8 requests/minute), plus a per-process daily budget and
  exponential backoff on HTTP 429.
- **Silent degradation**: a missing/invalid key, exhausted quota, or a
  dead endpoint raises LLMUnavailable, which every caller treats as
  "feature unavailable" — it can never block or crash a scan.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from aiolimiter import AsyncLimiter

from app.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-flash-latest"

# Conservative token bucket: the published free-tier ceilings shift, so
# stay well below them (§8 assumes ~8 req/min, ~200/day). Both limits are
# per process; escalations only fire in the ambiguous band, so real
# volume is a small fraction of scan volume.
_gemini_limiter = AsyncLimiter(8, 60)
_DAILY_BUDGET = 200
_daily_state = {"day": None, "count": 0}

_REQUEST_TIMEOUT = 30
_MAX_OUTPUT_CHARS = 4_000


class LLMUnavailable(Exception):
    """The optional LLM could not answer (unconfigured, bad key, quota,
    network). Callers degrade silently — this is not an error state."""


def _budget_exhausted() -> bool:
    today = datetime.now(UTC).date()
    if _daily_state["day"] != today:
        _daily_state["day"] = today
        _daily_state["count"] = 0
    return _daily_state["count"] >= _DAILY_BUDGET


def _budget_spend() -> None:
    _daily_state["count"] += 1


def _is_rate_limit(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code == 429 or "429" in str(exc)[:200]


async def gemini_generate(api_key: str, prompt: str) -> str:
    """One gemini-flash-latest call. Raises LLMUnavailable on any failure."""
    if not api_key:
        raise LLMUnavailable("no API key configured")
    if _budget_exhausted():
        raise LLMUnavailable("daily request budget exhausted")
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover — pinned dependency
        raise LLMUnavailable("google-genai SDK unavailable") from exc

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _gemini_limiter:
                _budget_spend()
                client = genai.Client(api_key=api_key)
                try:
                    response = await client.aio.models.generate_content(
                        model=GEMINI_MODEL, contents=prompt
                    )
                finally:
                    await client.aio.aclose()
            text = (response.text or "").strip()
            if not text:
                raise LLMUnavailable("Gemini returned an empty response")
            return text[:_MAX_OUTPUT_CHARS]
        except LLMUnavailable:
            raise
        except Exception as exc:
            last_exc = exc
            if _is_rate_limit(exc) and attempt < 2:
                # Exponential backoff on 429 (§8).
                await asyncio.sleep(2**attempt * 2)
                continue
            break
    logger.warning("Gemini call failed: %s", str(last_exc)[:200])
    raise LLMUnavailable(f"Gemini call failed: {type(last_exc).__name__}") from last_exc


async def ollama_generate(base_url: str, model: str | None, prompt: str) -> str:
    """One chat call against Ollama's OpenAI-compatible endpoint.
    Raises LLMUnavailable on any failure."""
    if not model:
        raise LLMUnavailable("no Ollama model configured")
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                url,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            body = resp.json()
        text = (body["choices"][0]["message"]["content"] or "").strip()
        if not text:
            raise LLMUnavailable("Ollama returned an empty response")
        return text[:_MAX_OUTPUT_CHARS]
    except LLMUnavailable:
        raise
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("Ollama call failed: %s", str(exc)[:200])
        raise LLMUnavailable(f"Ollama call failed: {type(exc).__name__}") from exc


# --- Settings test calls (§7: cheap confirmation endpoints) ---


async def gemini_test_call(api_key: str) -> tuple[bool, str]:
    try:
        await gemini_generate(api_key, "Reply with the single word: ok")
        return True, f"Key works — {GEMINI_MODEL} answered"
    except LLMUnavailable as exc:
        return False, f"Gemini test failed: {exc}"


async def ollama_test_call(base_url: str, model: str | None) -> tuple[bool, str]:
    try:
        await ollama_generate(base_url, model, "Reply with the single word: ok")
        return True, f"Ollama works — {model} answered"
    except LLMUnavailable as exc:
        return False, f"Ollama test failed: {exc}"


# --- Provider resolution (DB settings are the source of truth) ---


@dataclass
class LLMProvider:
    kind: str  # "gemini" | "ollama"
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    async def generate(self, prompt: str) -> str:
        if self.kind == "gemini":
            return await gemini_generate(self.api_key, prompt)
        return await ollama_generate(self.base_url, self.model, prompt)


async def resolve_provider(db) -> LLMProvider | None:
    """The configured+enabled provider, Gemini preferred (cloud opt-in
    beats local when the user enabled both), or None. Env vars act as
    bootstrap defaults when no DB row exists yet."""
    from app.settings_store import GEMINI_KEY, OLLAMA_KEY, load_setting

    settings = get_settings()
    g = await load_setting(db, GEMINI_KEY)
    if g is None and settings.gemini_api_key:
        g = {"api_key": settings.gemini_api_key, "enabled": True}
    if g and g.get("api_key") and g.get("enabled", True):
        return LLMProvider(kind="gemini", api_key=g["api_key"])

    o = await load_setting(db, OLLAMA_KEY)
    if o is None and settings.enable_ollama:
        o = {"enabled": True, "base_url": settings.ollama_base_url, "model": None}
    if o and o.get("enabled") and o.get("model"):
        return LLMProvider(
            kind="ollama",
            base_url=o.get("base_url") or settings.ollama_base_url,
            model=o["model"],
        )
    return None


# --- Prompt builders (shared by worker escalation, API explain, bot) ---

_NEW_TEXT_SAMPLE_CHARS = 2_000

LAYER_LABELS = {
    "layer1_hash": "Content hash comparison",
    "layer2_dom_structure": "DOM structure diff",
    "layer3_link_audit": "Link/script audit",
    "layer4_visual_diff": "Visual screenshot diff",
    "layer5_signatures": "Known defacement signatures",
    "layer6_security_metadata": "TLS/security-header metadata",
    "layer7_cloaking": "Cloaking (per-user-agent divergence)",
    "layer8_semantics": "Semantic text analysis",
}


def _summarize_layers(layer_scores: dict | None) -> str:
    if not layer_scores:
        return "(no layer scores recorded)"
    lines = []
    for key, label in LAYER_LABELS.items():
        entry = layer_scores.get(key)
        if entry is None:
            continue
        if entry.get("skipped"):
            lines.append(f"- {label}: skipped")
        else:
            lines.append(f"- {label}: {round((entry.get('score') or 0.0) * 100)}%")
    return "\n".join(lines)


def build_classification_prompt(
    *, site_url: str, risk_score: float, layer_scores: dict | None, new_text: str
) -> str:
    """Prompt for the ambiguous-band escalation: a strict-JSON verdict."""
    sample = new_text.strip()[:_NEW_TEXT_SAMPLE_CHARS] or "(no new visible text)"
    return (
        "You are assisting a website-integrity monitoring system. A monitored "
        "page changed, and the automated detection layers scored the change as "
        "ambiguous. Classify whether the change looks like a website defacement "
        "(unauthorized replacement/vandalism of page content) or a legitimate "
        "content update.\n\n"
        f"Monitored URL: {site_url}\n"
        f"Fused risk score: {round(risk_score * 100)}%\n"
        f"Per-layer scores:\n{_summarize_layers(layer_scores)}\n\n"
        f"New visible text on the page (sample):\n---\n{sample}\n---\n\n"
        "Respond with ONLY a JSON object, no markdown fences, shaped exactly:\n"
        '{"classification": "defacement" | "benign" | "unclear", '
        '"confidence": 0.0-1.0, "rationale": "<one or two sentences>"}'
    )


def build_explain_prompt(
    *,
    site_name: str,
    site_url: str,
    verdict: str,
    risk_score: float,
    flag_threshold: float,
    layer_scores: dict | None,
    findings_notes: list[str],
) -> str:
    notes = "\n".join(f"- {n}" for n in findings_notes) or "- (no notable evidence recorded)"
    return (
        "You are the explanation feature of a self-hosted website-integrity "
        "monitoring dashboard. Summarize this scan for a site owner in plain "
        "English: what changed, why the system scored it the way it did, and "
        "what a sensible next step is. Be concrete, calm, and short (3-6 "
        "sentences, no markdown, no emoji, no bullet lists).\n\n"
        f"Site: {site_name} ({site_url})\n"
        f"Verdict: {verdict}\n"
        f"Fused risk: {round(risk_score * 100)}% (alert threshold "
        f"{round(flag_threshold * 100)}%)\n"
        f"Per-layer scores:\n{_summarize_layers(layer_scores)}\n\n"
        f"Notable evidence:\n{notes}"
    )


def parse_classification(text: str) -> dict | None:
    """Parse the strict-JSON classification reply; None when malformed
    (the caller records the escalation as unusable, never crashes)."""
    candidate = text.strip()
    # Models occasionally wrap JSON in fences despite instructions.
    fence = re.search(r"\{.*\}", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    classification = parsed.get("classification")
    if classification not in ("defacement", "benign", "unclear"):
        return None
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    rationale = str(parsed.get("rationale") or "")[:500]
    return {"classification": classification, "confidence": confidence, "rationale": rationale}
