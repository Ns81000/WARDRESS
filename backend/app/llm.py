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
from datetime import UTC, datetime, timedelta

import httpx
from aiolimiter import AsyncLimiter

from app.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-flash-latest"

# Conservative token bucket: the published free-tier ceilings shift, so
# stay well below them (§8 assumes ~8 req/min, ~200/day). Both limits are
# per key (multi-key pool) and per process; escalations only fire in the
# ambiguous band, so real volume is a small fraction of scan volume.
_PER_KEY_RATE = (8, 60)  # requests, seconds
_DAILY_BUDGET = 200  # per key
# Legacy single-key path (gemini_generate) keeps its own limiter/budget.
_gemini_limiter = AsyncLimiter(*_PER_KEY_RATE)
_daily_state = {"day": None, "count": 0}

# Cooldown ladder applied to a key after consecutive quota failures:
# 1 min, then 5, then 30 (repeats at 30). Success resets the strike count.
_COOLDOWN_STEPS_SECONDS = (60, 300, 1800)

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


# --- Multi-key rotation pool (robustness + quota headroom) ---------------
#
# Multiple Gemini keys are pooled behind one interface. A request tries
# healthy keys round-robin; a key that hits a quota/429 (or any transient
# error) is cooled down on the ladder above and the request fails over to
# the next key. `LLMUnavailable` is raised only when *every* key is cooling
# down or over budget — the silent-degradation contract (§8) is preserved:
# scans and the explain feature treat that identically to "no key".
#
# Per-key state lives in a module-level registry keyed by the key string so
# health survives pool rebuilds (a fresh KeyPool is constructed from DB
# settings on every request, but the limiter/cooldown/budget persist).


class _KeyState:
    """Live health for one API key (rate limiter, daily budget, cooldown)."""

    __slots__ = ("api_key", "limiter", "day", "count", "strikes", "cooldown_until", "last_used")

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.limiter = AsyncLimiter(*_PER_KEY_RATE)
        self.day: object = None
        self.count = 0
        self.strikes = 0
        self.cooldown_until: datetime | None = None
        self.last_used: datetime | None = None

    def _roll_day(self) -> None:
        today = datetime.now(UTC).date()
        if self.day != today:
            self.day = today
            self.count = 0

    def available(self) -> bool:
        self._roll_day()
        if self.cooldown_until is not None and datetime.now(UTC) < self.cooldown_until:
            return False
        return self.count < _DAILY_BUDGET

    def spend(self) -> None:
        self._roll_day()
        self.count += 1
        self.last_used = datetime.now(UTC)

    def penalize(self) -> None:
        """Apply the next cooldown step and bump the strike count."""
        step = _COOLDOWN_STEPS_SECONDS[min(self.strikes, len(_COOLDOWN_STEPS_SECONDS) - 1)]
        self.strikes += 1
        self.cooldown_until = datetime.now(UTC) + timedelta(seconds=step)

    def reset(self) -> None:
        """A success clears the cooldown ladder."""
        self.strikes = 0
        self.cooldown_until = None

    def health(self) -> str:
        self._roll_day()
        if self.cooldown_until is not None and datetime.now(UTC) < self.cooldown_until:
            return "cooldown"
        if self.count >= _DAILY_BUDGET:
            return "exhausted"
        return "healthy"


_key_states: dict[str, _KeyState] = {}


def _state_for(api_key: str) -> _KeyState:
    st = _key_states.get(api_key)
    if st is None:
        st = _KeyState(api_key)
        _key_states[api_key] = st
    return st


def keys_from_setting(g: dict | None) -> list[dict]:
    """Normalize the stored Gemini payload to a key list. Accepts both the
    new pool shape ``{keys: [{id, api_key, label}], enabled}`` and the legacy
    single-key shape ``{api_key, enabled}`` (auto-wrapped as a one-key pool)."""
    if not g or not g.get("enabled", True):
        return []
    keys = g.get("keys")
    if isinstance(keys, list):
        return [k for k in keys if isinstance(k, dict) and k.get("api_key")]
    legacy = g.get("api_key")
    if legacy:
        return [{"id": "legacy", "api_key": legacy, "label": "default"}]
    return []


class KeyPool:
    """A rotating pool of Gemini keys sharing one gemini-flash-latest call
    path. Used by the explain feature, the worker escalation, and the agent."""

    def __init__(self, keys: list[dict]) -> None:
        self.keys = [k for k in keys if k.get("api_key")]

    def __bool__(self) -> bool:
        return bool(self.keys)

    async def call(self, *, contents, config=None):
        """Run one generate_content across the pool, returning the raw SDK
        response. Fails over across keys on quota/transient errors. Raises
        LLMUnavailable when no key can serve the request."""
        if not self.keys:
            raise LLMUnavailable("no API key configured")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover — pinned dependency
            raise LLMUnavailable("google-genai SDK unavailable") from exc

        last_exc: Exception | None = None
        served = 0
        for entry in self.keys:
            st = _state_for(entry["api_key"])
            if not st.available():
                continue
            served += 1
            try:
                async with st.limiter:
                    st.spend()
                    client = genai.Client(api_key=st.api_key)
                    try:
                        response = await client.aio.models.generate_content(
                            model=GEMINI_MODEL, contents=contents, config=config
                        )
                    finally:
                        await client.aio.aclose()
                st.reset()
                return response
            except Exception as exc:  # noqa: BLE001 — classify then fail over
                last_exc = exc
                st.penalize()
                if _is_rate_limit(exc):
                    logger.info("Gemini key hit quota — cooling down, trying next key")
                continue
        if served == 0:
            raise LLMUnavailable("all Gemini keys are cooling down or over budget")
        raise LLMUnavailable(
            f"Gemini call failed on all keys: {type(last_exc).__name__ if last_exc else 'unknown'}"
        )

    async def generate(self, prompt: str) -> str:
        """Plain-text convenience wrapper over :meth:`call`."""
        response = await self.call(contents=prompt)
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise LLMUnavailable("Gemini returned an empty response")
        return text[:_MAX_OUTPUT_CHARS]

    def health_snapshot(self) -> list[dict]:
        """Per-key health for the Settings UI (no secrets)."""
        out = []
        for entry in self.keys:
            st = _state_for(entry["api_key"])
            out.append(
                {
                    "id": entry.get("id"),
                    "label": entry.get("label") or "",
                    "hint": _key_hint(entry["api_key"]),
                    "health": st.health(),
                    "used_today": st.count,
                    "daily_budget": _DAILY_BUDGET,
                    "last_used": st.last_used.isoformat() if st.last_used else None,
                }
            )
        return out


def _key_hint(secret: str, keep: int = 6) -> str:
    if len(secret) <= keep:
        return "…"
    return secret[:keep] + "…" + secret[-2:]


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
    api_key: str = ""  # legacy single-key (kept for compatibility)
    base_url: str = ""
    model: str = ""
    pool: "KeyPool | None" = None

    async def generate(self, prompt: str) -> str:
        if self.kind == "gemini":
            if self.pool:
                return await self.pool.generate(prompt)
            return await gemini_generate(self.api_key, prompt)
        return await ollama_generate(self.base_url, self.model, prompt)


async def resolve_provider(db) -> LLMProvider | None:
    """The configured+enabled provider, Gemini preferred (cloud opt-in
    beats local when the user enabled both), or None. Env vars act as
    bootstrap defaults when no DB row exists yet. Gemini rides the
    multi-key rotation pool (a legacy single-key row is a one-key pool)."""
    from app.settings_store import GEMINI_KEY, OLLAMA_KEY, load_setting

    settings = get_settings()
    g = await load_setting(db, GEMINI_KEY)
    if g is None and settings.gemini_api_key:
        g = {"api_key": settings.gemini_api_key, "enabled": True}
    keys = keys_from_setting(g)
    if keys:
        return LLMProvider(kind="gemini", api_key=keys[0]["api_key"], pool=KeyPool(keys))

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
