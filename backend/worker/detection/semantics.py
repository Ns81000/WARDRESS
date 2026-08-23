"""Layer 8 — NLP/semantic analysis (§5).

Phase 2 requirement: a *local* keyword+sentiment pass. Implemented as:
- topic keyword shift: defacement-adjacent topic vocabulary (threats,
  bragging, ideology) appearing in new text where the baseline had none;
- a small lexicon-based sentiment/aggression scorer over the new visible
  text (no network, no model download at scan time);
- semantic drift via MiniLM embeddings (shared with layer 9's fusion
  features). Both sides' visible text is compared REGION BY REGION:
  each side is split into bounded windows, embedded, and every window
  is matched against its best-matching window on the other side. A
  single whole-text embedding would be structurally blind past the
  encoder's input window (~the first thousand characters — measured),
  so mutations confined beyond it scored as perfectly identical. The
  length-weighted symmetric mean keeps the metric proportional to the
  affected content share (benign dynamic bits stay quiet), while
  best-match pairing keeps positional shifts from reading as drift.
  Beyond MAX_CHUNKS_PER_SIDE windows the layer samples windows evenly
  across the whole text instead of reading every character — bounded
  cost, and no region is ever invisible (unlike the single-window
  compare it replaces). The embedder is process-cached and CPU-only.

The aggression/topic lexicons cover English plus common non-Latin
defacement-campaign phrasings (Arabic/Russian/Chinese); they run on NEW
text only, so pages that always contained a term don't flag.

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
    # Non-English defacement phrasings (campaigns routinely deface in
    # Arabic/Russian/Chinese; the English-only lexicon scored those 0.0).
    # Specific multi-word forms only, mirroring the English entries'
    # false-positive posture — and still matched on NEW text only.
    r"تم\s+اختراق": 0.55,  # "(has) been hacked"
    r"القراصنة": 0.35,  # "the hackers"
    r"\bвзлома(?:н|о|ли)?\b": 0.35,  # hacked (ru)
    r"сайт\s+взломан": 0.55,  # "site hacked"
    r"мы\s+вернёмся": 0.4,  # "we will return"
    r"被黑": 0.45,  # "got hacked" (zh)
    r"已被入侵": 0.45,  # "has been intruded" (zh)
}

_TOPIC_KEYWORDS = {
    "breach_bragging": [r"\bbreach(?:ed)?\b", r"\bcompromis(?:e|ed)\b", r"\binfiltrat(?:e|ed)\b"],
    "credential_theft": [r"\bdatabase\s+dump(?:ed)?\b", r"\bleak(?:ed)?\s+(?:data|credentials)\b"],
    "defacement_meta": [
        r"\bindex\.(?:html?|php)\s+(?:changed|replaced)\b",
        r"\bmirror(?:ed)?\s+on\s+zone\b",
    ],
    "contact_defacer": [
        r"\bcontact\s+us\s+(?:at|on)\s+telegram\b",
        r"\bt\.me/[\w-]+",
        r"تواصل(?:وا)?\s+معنا",  # "contact us" (ar)
    ],
}

_AGGRESSION = [(re.compile(p, re.IGNORECASE), w) for p, w in _AGGRESSION_LEXICON.items()]
_TOPICS = {
    topic: [re.compile(p, re.IGNORECASE) for p in pats] for topic, pats in _TOPIC_KEYWORDS.items()
}

MAX_HITS = 25
_EMBED_CHAR_CAP = 5_000  # MiniLM truncates around 256 word pieces anyway

# Multi-window comparison bounds. _EMBED_CHUNK_CHARS keeps each window
# inside the encoder's real input window (measured: the model's output
# for the first ~900 characters is indistinguishable from its output for
# an entire 40k-character page — everything past that was invisible to
# the single-embedding compare this replaces). _MAX_CHUNKS_PER_SIDE
# bounds the encode budget; beyond ~14k covered characters the windows
# are spread across the whole text (sampling, not full reading).
_EMBED_CHUNK_CHARS = 600
_MAX_CHUNKS_PER_SIDE = 24

# Drift mapping anchors: (similarity stop, drift value), similarity
# descending. Piecewise-linear and monotone non-increasing. Anchored to
# measured bands: benign dynamic churn sits at cos >= ~0.93 even for
# single-sentence edits on small pages (silent); partial injections/SEO
# spam measure ~0.75-0.90 (graded signal — the old linear mapping scored
# that band ~0.0-0.06, i.e. inert); meaning-level rewrites land <= ~0.6
# (near-maximal). The exact-zero plateau at the top also pins the
# identical-text contract (sim == 1.0 => drift 0.0).
_DRIFT_ANCHORS: tuple[tuple[float, float], ...] = (
    (1.00, 0.00),
    (0.90, 0.00),
    (0.80, 0.30),
    (0.50, 0.90),
    (0.00, 1.00),
)


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


def _chunks(text: str) -> list[str]:
    """Windows spread across the WHOLE text.

    Short texts are one window (the whole text). Up to
    _MAX_CHUNKS_PER_SIDE * _EMBED_CHUNK_CHARS characters the windows
    tile/overlap and every character is inside some window; beyond that
    the same number of windows is spread evenly instead, so sampled
    coverage reaches the end of any page size."""
    n = min(_MAX_CHUNKS_PER_SIDE, max(1, math.ceil(len(text) / _EMBED_CHUNK_CHARS)))
    if n == 1:
        return [text]
    last_start = len(text) - _EMBED_CHUNK_CHARS
    starts = [round(i * last_start / (n - 1)) for i in range(n)]
    return [text[s : s + _EMBED_CHUNK_CHARS] for s in starts]


def _direction_similarity(
    sources: list[tuple[int, list[float] | None]],
    targets: list[tuple[int, list[float] | None]],
) -> tuple[float | None, float | None]:
    """Length-weighted mean of every source window's best-match cosine
    against all target windows, plus the worst per-window cosine seen.

    Returns (None, None) when no valid vector pair exists on the two
    sides (embedder unavailable/degenerate). Failed or degenerate single
    windows are excluded rather than fatal — partial embedder output
    still yields a signal over whatever was measured."""
    weighted = 0.0
    weight_total = 0
    worst: float | None = None
    for w_src, v_src in sources:
        if not v_src:
            continue
        best: float | None = None
        for _, v_dst in targets:
            if not v_dst:
                continue
            s = cosine_similarity(v_src, v_dst)
            if s is None:
                continue
            best = s if best is None else max(best, s)
        if best is None:
            continue
        weighted += w_src * best
        weight_total += w_src
        worst = best if worst is None else min(worst, best)
    if weight_total == 0:
        return None, None
    return weighted / weight_total, worst


def drift_from_similarity(similarity: float) -> float:
    """Map a semantic similarity to a drift score via _DRIFT_ANCHORS
    (piecewise-linear interpolation between descending similarity
    stops). Clamped to [0, 1]; sim >= 1.0 maps to exactly 0.0."""
    anchors = _DRIFT_ANCHORS
    top_sim, top_drift = anchors[0]
    if similarity >= top_sim:
        return top_drift
    for (hi_sim, hi_drift), (lo_sim, lo_drift) in zip(anchors, anchors[1:], strict=False):
        if similarity >= lo_sim:
            t = (hi_sim - similarity) / (hi_sim - lo_sim)
            return hi_drift + t * (lo_drift - hi_drift)
    return anchors[-1][1]


def _embedded_windows(text: str) -> list[tuple[int, list[float] | None]]:
    """(window length, embedding-or-None) per window. embed_text never
    raises (its own contract), so neither does this."""
    return [(len(chunk), embed_text(chunk)) for chunk in _chunks(text)]


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

    # 3. Semantic drift (MiniLM cosine) compared region by region.
    semantic_similarity: float | None = None
    min_chunk_similarity: float | None = None
    baseline_windows: list[tuple[int, list[float] | None]] = []
    current_windows: list[tuple[int, list[float] | None]] = []
    if baseline_text.strip() and current_text.strip():
        baseline_windows = _embedded_windows(baseline_text)
        current_windows = _embedded_windows(current_text)
        mean_current, worst_current = _direction_similarity(current_windows, baseline_windows)
        mean_baseline, worst_baseline = _direction_similarity(baseline_windows, current_windows)
        # Symmetric min: appended/rewritten content drops the current
        # side; deleted content drops the baseline side. Shared content
        # keeps both means high — the metric stays proportional to how
        # much of each page actually changed.
        direction_means = [m for m in (mean_current, mean_baseline) if m is not None]
        semantic_similarity = min(direction_means) if direction_means else None
        worst = [w for w in (worst_current, worst_baseline) if w is not None]
        min_chunk_similarity = min(worst) if worst else None

    aggression_score = 1 - math.exp(-1.2 * aggression_weight) if aggression_weight else 0.0
    topic_score = min(0.7, 0.35 * len(topic_hits))
    drift_score = 0.0
    if semantic_similarity is not None:
        drift_score = drift_from_similarity(semantic_similarity)

    score = max(aggression_score, topic_score, drift_score)
    evidence = {
        "aggression_hits": aggression_hits,
        "aggression_weight": round(aggression_weight, 2),
        "topic_hits": topic_hits,
        "semantic_similarity": (
            round(semantic_similarity, 4) if semantic_similarity is not None else None
        ),
        "semantic_drift_score": round(drift_score, 4),
        "semantic_chunks_baseline": len(baseline_windows),
        "semantic_chunks_current": len(current_windows),
        "semantic_min_chunk_similarity": (
            round(min_chunk_similarity, 4) if min_chunk_similarity is not None else None
        ),
        "new_text_chars": len(new_text),
        # §8 escalation: the scan task overwrites this dict for scans in
        # the ambiguous risk band when Gemini/Ollama is configured; the
        # local pass never depends on it (degrade silently).
        "escalation": {"status": "not evaluated (outside ambiguous band or not configured)"},
    }
    return layer_result(score, evidence)
