"""Unified LLM layer — one litellm call-site for every provider (§8).

Replaces the old two-provider design (a bespoke Gemini multi-key ``KeyPool``
plus a hand-rolled Ollama httpx client) with a single, catalog-driven layer
built on **litellm**:

- Each AI *task* (``explanation`` / ``agent_chat``) is resolved from the
  ``ai_task_assignments`` row into a :class:`litellm.Router`. Multiple API keys
  on one provider become multiple Router deployments sharing a ``model_name``,
  which reproduces the old pool's behaviour — automatic rotation, rate-limit
  aware selection, cooldown-on-failure, failover — with a maintained library
  instead of ~300 lines of hand-rolled state.
- An optional per-task fallback model (possibly on a *different* provider) is
  wired through the Router's ``fallbacks`` list, generalising redundancy across
  providers with no bespoke pooling code.
- Tool/function calling is provider-agnostic via litellm's OpenAI-style
  ``tools`` parameter, so the agent is no longer Gemini-only.

The silent-degradation contract is unchanged: any failure (unconfigured, bad
key, quota, network, malformed reply) raises :class:`LLMUnavailable`, which
every caller treats as "feature unavailable" — it can never block or crash a
scan.

Routers are cached per provider-config generation (keyed on the rows'
``updated_at``) so cooldown state persists across requests, yet a Settings
change takes effect immediately with no restart.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm import Router
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_catalog import (
    OLLAMA_TYPE,
    litellm_model_string,
)
from app.crypto import DecryptionError, decrypt_json
from app.models import AiProvider, AiTaskAssignment, AiTaskType

logger = logging.getLogger(__name__)

# litellm globals (set once): drop provider-unsupported params instead of
# erroring (e.g. temperature on models that forbid it), stay quiet, no phone-home.
litellm.drop_params = True
litellm.telemetry = False
litellm.suppress_debug_info = True

# Redact anything resembling an API key/token from a string before it is
# logged. Provider auth errors frequently echo the offending key (or a prefix)
# in the exception message; those messages flow to persistent logs / SIEM /
# support tickets, so scrub before writing. Covers common vendor prefixes
# (OpenAI sk-, Google AIza) and any long base64/hex-ish run.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),        # OpenAI / Anthropic style
    re.compile(r"AIza[A-Za-z0-9_\-]{10,}"),      # Google API keys
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),       # any long opaque token/hash
]


def _scrub_secrets(text: str) -> str:
    """Replace anything that looks like a credential with ``[REDACTED]``."""
    if not text:
        return text
    scrubbed = text
    for pat in _SECRET_PATTERNS:
        scrubbed = pat.sub("[REDACTED]", scrubbed)
    return scrubbed

_REQUEST_TIMEOUT = 30
_MAX_OUTPUT_CHARS = 4_000
# Conservative per-key request-rate hint (the old pool used ~8/min). litellm's
# Router uses rpm for rate-limit-aware deployment selection.
_PER_KEY_RPM = 8
# Cooldown a deployment after this many failures in a minute; matches the old
# "penalize on first quota/transient error" behaviour closely (0 = first fail).
_ALLOWED_FAILS = 0
_COOLDOWN_SECONDS = 60
_NUM_RETRIES = 2


class LLMUnavailable(Exception):
    """The optional LLM could not answer (unconfigured, bad key, quota,
    network). Callers degrade silently — this is not an error state."""


def _key_hint(secret: str, keep: int = 6) -> str:
    if len(secret) <= keep:
        return "…"
    return secret[:keep] + "…" + secret[-2:]


# --- Provider credential handling ----------------------------------------


def provider_api_keys(provider: AiProvider) -> list[str]:
    """Decrypt a provider's stored API keys. Returns [] when the provider has
    no credentials (e.g. a local Ollama daemon) or the blob is undecryptable
    (rotated key) — treated as unconfigured, never a crash."""
    if not provider.credentials_encrypted:
        return []
    try:
        blob = decrypt_json(provider.credentials_encrypted)
    except DecryptionError:
        logger.warning(
            "AI provider %s credentials undecryptable — treating as keyless", provider.id
        )
        return []
    keys = blob.get("api_keys")
    if isinstance(keys, list):
        return [k for k in keys if isinstance(k, str) and k]
    single = blob.get("api_key")
    return [single] if isinstance(single, str) and single else []


def _litellm_api_base(provider: AiProvider) -> str | None:
    """The ``api_base`` to hand litellm for this provider, or None to use
    litellm's provider default. Ollama uses the native chat API, so any
    legacy OpenAI-compatible ``/v1`` suffix is stripped."""
    base = (provider.base_url or "").strip()
    if provider.provider_type == OLLAMA_TYPE:
        from app.ai_ollama import DEFAULT_OLLAMA_BASE_URL

        base = base or DEFAULT_OLLAMA_BASE_URL
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base or "http://localhost:11434"
    return base or None


def _deployments(provider: AiProvider, model_id: str, alias: str) -> list[dict]:
    """One Router deployment per API key (rotation), all sharing ``alias`` as
    ``model_name``. A keyless provider (local Ollama) yields one deployment."""
    model_str = litellm_model_string(provider.provider_type, model_id)
    api_base = _litellm_api_base(provider)
    keys = provider_api_keys(provider) or [None]
    deployments: list[dict] = []
    for key in keys:
        params: dict[str, Any] = {"model": model_str, "timeout": _REQUEST_TIMEOUT}
        if key:
            params["api_key"] = key
        if api_base:
            params["api_base"] = api_base
        if key:  # only meaningful when a key exists to rate-limit against
            params["rpm"] = _PER_KEY_RPM
        deployments.append({"model_name": alias, "litellm_params": params})
    return deployments


# --- Router build + per-config-generation cache --------------------------

_PRIMARY_ALIAS = "primary"
_FALLBACK_ALIAS = "fallback"

# Cache: signature -> ResolvedTask. Keyed on the config rows' updated_at so a
# Settings edit invalidates it immediately (no restart) while cooldown state
# persists across requests within one config generation. An OrderedDict gives
# LRU eviction (see resolve_task) instead of a full-clear cliff, and an
# asyncio.Lock serialises access so concurrent coroutines can't corrupt it.
_router_cache: OrderedDict[str, ResolvedTask] = OrderedDict()
_router_cache_lock = asyncio.Lock()
_ROUTER_CACHE_MAX = 32


def _signature(*parts: Any) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ResolvedTask:
    """A task bound to a ready-to-call litellm Router."""

    task: str
    router: Router
    label: str  # short provider-type tag stored as scan.explanation_provider / audit
    supports_tools: bool
    model_string: str  # the litellm model string of the primary (for capability checks)
    _sig: str = field(default="", repr=False)

    async def _acompletion(self, **kwargs) -> Any:
        try:
            return await self.router.acompletion(model=_PRIMARY_ALIAS, **kwargs)
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — every provider/litellm error degrades
            scrubbed = _scrub_secrets(str(exc)[:200])
            logger.info("LLM task %s failed [%s]: %s", self.task, type(exc).__name__, scrubbed)
            raise LLMUnavailable(f"{type(exc).__name__}: {_scrub_secrets(str(exc)[:120])}") from exc

    async def generate(self, prompt: str) -> str:
        """Plain-text completion (explain / escalation / rolling summary)."""
        resp = await self._acompletion(messages=[{"role": "user", "content": prompt}])
        text = _extract_text(resp)
        if not text:
            raise LLMUnavailable("model returned an empty response")
        return text[:_MAX_OUTPUT_CHARS]

    async def acompletion(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> Any:
        """Full completion (agent turn) — returns the raw litellm response so
        the engine can read tool_calls / content."""
        kwargs: dict[str, Any] = {"messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        return await self._acompletion(**kwargs)


def _extract_text(resp: Any) -> str:
    try:
        return (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        return ""


def _supports_tools(provider_type: str, model_string: str) -> bool:
    """Whether the resolved task can do tool/function calling — the agent-chat
    capability flag the engine reads.

    For catalog providers litellm's static registry is authoritative. For Ollama
    and custom OpenAI-compatible endpoints litellm's registry has no entry and
    returns False even for genuinely tool-capable models, so we trust the
    assignment-time gate instead (``resolve_tool_capability`` probed Ollama's
    ``/api/show`` and refused a non-tool model; a custom endpoint is trusted).
    The engine still degrades cleanly if a tool call fails at runtime."""
    from app.ai_catalog import OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE

    if provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE):
        return True
    try:
        return bool(litellm.supports_function_calling(model=model_string))
    except Exception:  # noqa: BLE001 — an unknown model must degrade, not crash resolution
        return False


def _build_router(
    primary: AiProvider,
    primary_model: str,
    fallback: AiProvider | None,
    fallback_model: str | None,
) -> Router:
    model_list = _deployments(primary, primary_model, _PRIMARY_ALIAS)
    fallbacks = None
    if fallback is not None and fallback_model:
        model_list += _deployments(fallback, fallback_model, _FALLBACK_ALIAS)
        fallbacks = [{_PRIMARY_ALIAS: [_FALLBACK_ALIAS]}]
    return Router(
        model_list=model_list,
        routing_strategy="simple-shuffle",
        num_retries=_NUM_RETRIES,
        cooldown_time=_COOLDOWN_SECONDS,
        allowed_fails=_ALLOWED_FAILS,
        fallbacks=fallbacks,
        set_verbose=False,
    )


async def _load_provider(db: AsyncSession, provider_id) -> AiProvider | None:
    if provider_id is None:
        return None
    return await db.scalar(select(AiProvider).where(AiProvider.id == provider_id))


async def resolve_task(db: AsyncSession, task: str | AiTaskType) -> ResolvedTask | None:
    """Resolve one AI task to a ready Router, or None when unconfigured. Reads
    the ``ai_task_assignments`` row, loads the primary (and optional fallback)
    provider, and returns a cached :class:`ResolvedTask` when the config is
    unchanged. Never raises for config problems — returns None."""
    task_value = task.value if isinstance(task, AiTaskType) else str(task)
    assignment = await db.scalar(
        select(AiTaskAssignment).where(AiTaskAssignment.task == task_value)
    )
    if assignment is None or assignment.provider_id is None or not assignment.model_id:
        return None

    primary = await _load_provider(db, assignment.provider_id)
    if primary is None or not primary.enabled:
        return None
    fallback = await _load_provider(db, assignment.fallback_provider_id)
    if fallback is not None and not fallback.enabled:
        fallback = None
    fb_model = assignment.fallback_model_id if fallback is not None else None

    sig = _signature(
        task_value,
        primary.id,
        primary.updated_at,
        assignment.model_id,
        assignment.updated_at,
        fallback.id if fallback else None,
        fallback.updated_at if fallback else None,
        fb_model,
    )
    async with _router_cache_lock:
        cached = _router_cache.get(sig)
        if cached is not None:
            _router_cache.move_to_end(sig)  # LRU: mark most-recently used
            return cached

    # Build the Router *outside* the lock — it can do network/validation work
    # and must not serialise every concurrent resolve behind one coroutine.
    try:
        router = _build_router(primary, assignment.model_id, fallback, fb_model)
    except Exception:  # noqa: BLE001 — a bad config must degrade, not crash
        # ERR-3: actionable log — include the model/provider so misconfig is
        # diagnosable from the error message alone.
        logger.exception(
            "Failed to build router for task %s (provider=%s, model=%s)",
            task_value,
            primary.provider_type,
            assignment.model_id,
        )
        return None

    model_string = litellm_model_string(primary.provider_type, assignment.model_id)
    resolved = ResolvedTask(
        task=task_value,
        router=router,
        label=primary.provider_type[:32],
        supports_tools=_supports_tools(primary.provider_type, model_string),
        model_string=model_string,
        _sig=sig,
    )

    async with _router_cache_lock:
        # A concurrent coroutine may have built and stored the same sig while
        # we were building — prefer the already-cached one to keep cooldown
        # state shared, and discard our just-built duplicate.
        existing = _router_cache.get(sig)
        if existing is not None:
            _router_cache.move_to_end(sig)
            return existing
        _router_cache[sig] = resolved
        _router_cache.move_to_end(sig)
        # LRU eviction: drop the oldest entries one at a time (preserving the
        # cooldown/retry state of every surviving router) instead of a
        # full-clear cliff that would trigger a thundering-herd rebuild.
        while len(_router_cache) > _ROUTER_CACHE_MAX:
            _router_cache.popitem(last=False)
    return resolved


def clear_router_cache() -> None:
    """Drop cached Routers (tests; also called when providers are deleted).

    Not awaited under the lock: called from sync paths (tests, provider-delete
    hooks) where no concurrent ``resolve_task`` is expected. Reassigning clears
    atomically at the Python-object level.
    """
    _router_cache.clear()


# --- One-off provider validation (cheap live call) -----------------------


async def validate_provider_call(
    provider: AiProvider, model_id: str
) -> tuple[bool, str]:
    """A cheap real completion to confirm a provider+model actually works.
    Returns (ok, human message). Never raises."""
    try:
        router = _build_router(provider, model_id, None, None)
        resp = await router.acompletion(
            model=_PRIMARY_ALIAS,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=16,
        )
        text = _extract_text(resp)
        if text:
            return True, f"{provider.label} answered ({model_id})"
        return False, "Provider returned an empty response"
    except Exception as exc:  # noqa: BLE001 — validation surfaces the error text
        return False, f"{type(exc).__name__}: {_scrub_secrets(str(exc)[:160])}"


# --- Prompt builders (shared by worker escalation, API explain, bot) -----
# Unchanged from the previous implementation — provider-agnostic already.

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
    # CB-4: try the full text as JSON first (common case: model replies with
    # only the JSON object). Fall back to a non-greedy first-object regex if
    # the model wraps it in prose.
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            pass  # use parsed below
        else:
            return None
    except json.JSONDecodeError:
        # Non-greedy: prefer the first {...} span, not the widest.
        fence = re.search(r"\{.*?\}", candidate, re.DOTALL)
        if not fence:
            return None
        try:
            parsed = json.loads(fence.group(0))
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
