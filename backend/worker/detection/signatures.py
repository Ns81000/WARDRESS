"""Layer 5 — signature/keyword match (§5, stdlib re).

Three independent signals, all computed on *visible text* extracted from
the DOM (markup noise excluded) and only on content that is NEW relative
to the baseline — a security blog legitimately discussing these topics
in its baseline must not flag on every scan:

1. Signature phrases commonly seen on defaced pages (regex list).
2. Profanity burst — sudden appearance of strong profanity.
3. Script mixing — the dominant Unicode script of the text changing
   (e.g. a Latin-script page suddenly mostly Arabic/Cyrillic), which is
   a well-documented characteristic of mass-defacement campaigns.

Scores are graded, not binary: one weak keyword scores low; an explicit
"hacked by" phrase scores high on its own.
"""

import re
import unicodedata

from worker.detection.dom import parse_html
from worker.detection.types import PageData, layer_result

MAX_MATCHES = 25

# Signature patterns with per-pattern weights. Strong patterns are
# essentially conclusive on their own; weak ones need corroboration.
_SIGNATURES_STRONG = [
    r"\bhacked\s+by\b",
    r"\bowned\s+by\b",
    r"\bpwned\s+by\b",
    r"\bdefaced\s+by\b",
    r"\bh4ck3d\b",
    r"\bhack3d\b",
    r"\bwas\s+here\b.{0,40}\b(hacker|team|crew|cyber)\b",
    r"\b(cyber|dark|ghost|shadow)\s?(army|team|crew|squad)\b.{0,60}\b(hacked|owned|defaced)\b",
]
_SIGNATURES_MEDIUM = [
    r"\byour\s+(?:security|system|website|site)\s+(?:is|was)\s+(?:low|weak|breached|compromised)\b",
    r"\bsecurity\s+breached\b",
    r"\bgreetz\b",
    r"\bgr33tz\b",
    r"\bfree\s+palestine\b.{0,80}\bhacked\b",
    r"\bwe\s+are\s+(?:anonymous|legion)\b",
    r"\bexpect\s+us\b",
    r"\byou\s+(?:have\s+been|got)\s+(?:hacked|owned|pwned)\b",
    r"\bmess\s+with\s+the\s+best\b",
    r"\bit\s+was\s+(?:too\s+)?easy\b.{0,60}\b(admin|security|server)\b",
]
_SIGNATURES_WEAK = [
    r"\bh[a4]ck[e3]r\b",
    r"\bkill\s?swit?ch\b",
    r"\broot(?:ed)?\s+access\b",
    r"\badmin\s+panel\s+(?:breached|accessed)\b",
    r"\bsql\s+injection\b",
    r"\bzero\s?day\b",
]

_PROFANITY = [
    r"\bf+u+c+k+(?:e+d+|i+n+g+)?\b",
    r"\bs+h+i+t+\b",
    r"\bb+i+t+c+h+(?:e+s+)?\b",
    r"\ba+s+s+h+o+l+e+s?\b",
    r"\bc+u+n+t+s?\b",
    r"\bm+o+t+h+e+r+f+u+c+k+e+r+s?\b",
]

_STRONG = [(re.compile(p, re.IGNORECASE | re.DOTALL), 1.0) for p in _SIGNATURES_STRONG]
_MEDIUM = [(re.compile(p, re.IGNORECASE | re.DOTALL), 0.55) for p in _SIGNATURES_MEDIUM]
_WEAK = [(re.compile(p, re.IGNORECASE | re.DOTALL), 0.25) for p in _SIGNATURES_WEAK]
_PROF = [re.compile(p, re.IGNORECASE) for p in _PROFANITY]

_ALL_WEIGHTED = _STRONG + _MEDIUM + _WEAK


def extract_visible_text(html_text: str) -> str:
    """Visible text content of a page: DOM text nodes minus script/style.
    Falls back to a tag-stripping regex when no DOM can be built."""
    root = parse_html(html_text)
    if root is None:
        return re.sub(r"<[^>]*>", " ", html_text or "")
    parts: list[str] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag.lower() in ("script", "style", "noscript", "template"):
            continue
        if el.text and el.text.strip():
            parts.append(el.text.strip())
        if el.tail and el.tail.strip():
            parts.append(el.tail.strip())
    return " ".join(parts)


def _script_of_char(ch: str) -> str | None:
    """Coarse Unicode script bucket via unicodedata name prefixes —
    enough to detect 'page flipped from Latin to another script'."""
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    for script in (
        "LATIN",
        "ARABIC",
        "CYRILLIC",
        "GREEK",
        "HEBREW",
        "DEVANAGARI",
        "THAI",
        "HANGUL",
        "HIRAGANA",
        "KATAKANA",
        "CJK",
        "BENGALI",
        "TAMIL",
        "GEORGIAN",
        "ARMENIAN",
    ):
        if name.startswith(script):
            return script
    return "OTHER"


def script_profile(text: str, sample_cap: int = 20_000) -> dict[str, float]:
    """Fractional distribution of Unicode scripts over alphabetic chars."""
    counts: dict[str, int] = {}
    total = 0
    for ch in text[:sample_cap]:
        s = _script_of_char(ch)
        if s is None:
            continue
        counts[s] = counts.get(s, 0) + 1
        total += 1
    if total == 0:
        return {}
    return {s: c / total for s, c in counts.items()}


def _dominant(profile: dict[str, float]) -> tuple[str | None, float]:
    if not profile:
        return None, 0.0
    script = max(profile, key=lambda k: profile[k])
    return script, profile[script]


def _new_text(baseline_text: str, current_text: str) -> str:
    """Text lines present now but not in the baseline — signature and
    profanity checks run on new content only, so pages that always
    contained a term don't flag on every scan."""
    base_lines = {ln.strip() for ln in baseline_text.splitlines() if ln.strip()}

    # Visible text extraction returns one long line; split on sentences too.
    def pieces(text: str) -> list[str]:
        out = []
        for line in text.splitlines():
            out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip())
        return out

    base_pieces = {p for p in pieces(baseline_text)}
    return " ".join(p for p in pieces(current_text) if p not in base_pieces and p not in base_lines)


def layer5_signatures(baseline: PageData, current: PageData) -> dict:
    baseline_text = extract_visible_text(baseline.html)
    current_text = extract_visible_text(current.html)
    new_text = _new_text(baseline_text, current_text)

    matches: list[dict] = []
    weight_sum = 0.0
    for pattern, weight in _ALL_WEIGHTED:
        for m in pattern.finditer(new_text):
            if len(matches) < MAX_MATCHES:
                matches.append(
                    {
                        "pattern": pattern.pattern,
                        "matched": m.group(0)[:120],
                        "weight": weight,
                    }
                )
            weight_sum += weight

    profanity_hits: list[str] = []
    for pattern in _PROF:
        for m in pattern.finditer(new_text):
            if len(profanity_hits) < MAX_MATCHES:
                profanity_hits.append(m.group(0)[:40])

    # Script-mixing: compare dominant script of the whole visible text.
    b_profile = script_profile(baseline_text)
    c_profile = script_profile(current_text)
    b_dom, b_frac = _dominant(b_profile)
    c_dom, c_frac = _dominant(c_profile)
    script_flip = (
        b_dom is not None
        and c_dom is not None
        and b_dom != c_dom
        and b_frac >= 0.6  # baseline had a clear dominant script
        and c_frac >= 0.6  # and so does the current page — a real flip
    )

    signature_score = min(1.0, weight_sum)
    profanity_score = min(0.6, 0.25 * len(profanity_hits))
    flip_score = 0.7 if script_flip else 0.0
    score = max(signature_score, profanity_score, flip_score)

    evidence = {
        "signature_matches": matches,
        "signature_weight_sum": round(weight_sum, 2),
        "profanity_matches": profanity_hits,
        "script_flip": script_flip,
        "baseline_dominant_script": b_dom,
        "current_dominant_script": c_dom,
        "baseline_script_profile": {k: round(v, 3) for k, v in b_profile.items()},
        "current_script_profile": {k: round(v, 3) for k, v in c_profile.items()},
        "new_text_chars": len(new_text),
    }
    return layer_result(score, evidence)
