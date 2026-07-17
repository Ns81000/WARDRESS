"""Layer 8 — NLP/semantic analysis (§5).

Phase 2 requirement: a *local* keyword+sentiment pass. Implemented as:
- topic keyword shift: defacement-adjacent topic vocabulary (threats,
  bragging, ideology) appearing in new text where the baseline had none;
- a small lexicon-based sentiment/aggression scorer over the new visible
  text (no network, no model download at scan time);
- semantic drift via MiniLM embeddings (shared with layer 9's fusion
  features): cosine similarity between baseline and current visible
  text. The embedder is process-cached and CPU-only.

Optional Gemini/Ollama escalation (§8) is Phase 4 UI work; the plumbing
hook (`escalation` evidence key) records that it was not configured —
its absence must never block the local pass (master prompt: degrade
silently).
"""

import logging
import math
import re

from worker.detection.signatures import extract_visible_text
from worker.detection.types import PageData, layer_result

logger = logging.getLogger(__name__)

# Aggression/threat lexicon: graded weights, matched on new text only.
_AGGRESSION_LEXICON = {
    r"\bdestroy(?:ed)?\b": 0.2,
    r"\brevenge\b": 0.3,
    r"\bpay\s+the\s+price\b": 0.4,
    r"\bwe\s+will\s+(?:be\s+)?back\b": 0.4,
    r"\bno\s+one\s+is\s+safe\b": 0.5,
    r"\byou\s+(?:can'?t|cannot)\s+stop\s+us\b": 0.5,
    r"\bdeath\s+to\b": 0.6,
    r"\bwar\s+(?:on|against)\b": 0.3,
    r"\bincompetent\b": 0.2,
    r"\bshame\s+on\b": 0.3,
    r"\btraitors?\b": 0.3,
    r"\bcorrupt(?:ion)?\b": 0.2,
    r"\bregime\b": 0.2,
    r"\bmartyrs?\b": 0.3,
}

_TOPIC_KEYWORDS = {
    "breach_bragging": [r"\bbreach(?:ed)?\b", r"\bcompromis(?:e|ed)\b", r"\binfiltrat(?:e|ed)\b"],
    "credential_theft": [r"\bdatabase\s+dump(?:ed)?\b", r"\bleak(?:ed)?\s+(?:data|credentials)\b"],
    "defacement_meta": [
        r"\bindex\.(?:html?|php)\s+(?:changed|replaced)\b",
        r"\bmirror(?:ed)?\s+on\s+zone\b",
    ],
    "contact_defacer": [r"\bcontact\s+us\s+(?:at|on)\s+telegram\b", r"\bt\.me/[\w-]+"],
}

_AGGRESSION = [(re.compile(p, re.IGNORECASE), w) for p, w in _AGGRESSION_LEXICON.items()]
_TOPICS = {
    topic: [re.compile(p, re.IGNORECASE) for p in pats] for topic, pats in _TOPIC_KEYWORDS.items()
}

MAX_HITS = 25
_EMBED_CHAR_CAP = 5_000  # MiniLM truncates around 256 word pieces anyway


def _new_visible_text(baseline_html: str, current_html: str) -> str:
    from worker.detection.signatures import _new_text  # shared splitter

    return _new_text(extract_visible_text(baseline_html), extract_visible_text(current_html))


# --- MiniLM embedding, cached per worker process (CPU only, rule 3) ---

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    return _model


def embed_text(text: str) -> list[float] | None:
    """384-dim MiniLM embedding of (capped) text, or None when the model
    cannot be loaded (fresh container without the baked model and no
    network) — callers must treat None as 'feature unavailable'."""
    try:
        model = _get_model()
        return model.encode(text[:_EMBED_CHAR_CAP], show_progress_bar=False).tolist()
    except Exception as exc:  # model load/download failure must not kill the scan
        logger.warning("MiniLM embedding unavailable: %s", str(exc)[:200])
        return None


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return None
    return dot / (na * nb)


def layer8_semantics(baseline: PageData, current: PageData) -> dict:
    baseline_text = extract_visible_text(baseline.html)
    current_text = extract_visible_text(current.html)
    new_text = _new_visible_text(baseline.html, current.html)

    # 1. Aggression/threat lexicon on new text.
    aggression_hits: list[dict] = []
    aggression_weight = 0.0
    for pattern, weight in _AGGRESSION:
        for m in pattern.finditer(new_text):
            if len(aggression_hits) < MAX_HITS:
                aggression_hits.append({"matched": m.group(0)[:80], "weight": weight})
            aggression_weight += weight

    # 2. Topic keywords on new text.
    topic_hits: dict[str, list[str]] = {}
    for topic, patterns in _TOPICS.items():
        hits = []
        for pattern in patterns:
            hits.extend(m.group(0)[:80] for m in pattern.finditer(new_text))
        if hits:
            topic_hits[topic] = hits[:MAX_HITS]

    # 3. Semantic drift (MiniLM cosine) between full visible texts.
    semantic_similarity: float | None = None
    if baseline_text.strip() and current_text.strip():
        b_vec = embed_text(baseline_text)
        c_vec = embed_text(current_text)
        semantic_similarity = cosine_similarity(b_vec, c_vec)

    aggression_score = 1 - math.exp(-1.2 * aggression_weight) if aggression_weight else 0.0
    topic_score = min(0.7, 0.35 * len(topic_hits))
    drift_score = 0.0
    if semantic_similarity is not None:
        # MiniLM cosine ~1.0 for the same page with dynamic bits;
        # meaning-level rewrites drop well below 0.8.
        drift_score = max(0.0, min(1.0, (0.85 - semantic_similarity) / 0.85))

    score = max(aggression_score, topic_score, drift_score)
    evidence = {
        "aggression_hits": aggression_hits,
        "aggression_weight": round(aggression_weight, 2),
        "topic_hits": topic_hits,
        "semantic_similarity": (
            round(semantic_similarity, 4) if semantic_similarity is not None else None
        ),
        "semantic_drift_score": round(drift_score, 4),
        "new_text_chars": len(new_text),
        # §8 escalation: the scan task overwrites this dict for scans in
        # the ambiguous risk band when Gemini/Ollama is configured; the
        # local pass never depends on it (degrade silently).
        "escalation": {"status": "not evaluated (outside ambiguous band or not configured)"},
    }
    return layer_result(score, evidence)
