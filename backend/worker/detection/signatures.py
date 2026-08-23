"""Layer 5 — signature/keyword match (§5, stdlib re).

Three independent signals, all computed on *visible text* extracted from
the DOM (markup noise excluded) and only on content that is NEW relative
to the baseline — a security blog legitimately discussing these topics
in its baseline must not flag on every scan:

1. Signature phrases commonly seen on defaced pages (regex list),
   matched against the raw new text AND a conservative leetspeak
   decoding of it (@/4→a, 3→e, 0→o, 1→i, 5/$→s, 7→t) so routine
   defacement spellings ("H@CK3D BY", "PWN3D BY", "0WNED") cannot slip
   through. Matches are span-deduplicated across the two views with the
   raw view preferred, so evidence quotes stay verbatim page text and
   exact-substitution terms do not double-count.
2. Profanity burst — sudden appearance of strong profanity (same
   dual-view matching, so "$h1t"-style spellings register).
3. Script mixing — two complementary rules:
   a. Dominance flip: the dominant Unicode script of the whole page
      changed with a clear majority on both sides (a Latin page that is
      now mostly Arabic/Cyrillic).
   b. New-script inflow: the NEW text carries a substantial mass
      (absolute grace, both sides) of a script that was effectively
      absent from the baseline and dominates what was added — partial
      takeovers that leave the page majority-Latin but inject a
      foreign-script banner produce zero dominance signal and need
      this channel. Legitimate incremental updates never introduce a
      foreign script at this scale; incidental foreign fragments stay
      below the absolute grace, and sub-impact slices of large pages
      stay below the page-share floor.

Scores are graded, not binary: one weak keyword scores low; an explicit
"hacked by" phrase scores high on its own.
"""

import re
import unicodedata
from collections import Counter
from functools import cache

from worker.detection.dom import parse_html
from worker.detection.types import PageData, layer_result

MAX_MATCHES = 25

# Length-preserving leetspeak decoding used ONLY as a second matching
# view; every mapped source character becomes exactly one character, so
# match spans in the decoded text address the same positions in the raw
# text and evidence can always quote the original spelling.
_LEET_TRANSLATION = str.maketrans(
    {"@": "a", "4": "a", "3": "e", "0": "o", "1": "i", "5": "s", "$": "s", "7": "t"}
)

# New-script inflow gates. All three must hold for the inflow signal:
_BASELINE_ALPHA_FLOOR = 40  # baseline must be established enough to say a script was "absent"
_NEW_SCRIPT_MIN_CHARS = 40  # absolute grace: a name/date/stray quote never fires; a message does
_NEW_SCRIPT_BASELINE_EPSILON = 0.01  # baseline share below this counts as "effectively absent"
_NEW_SCRIPT_PAGE_SHARE = 0.05  # foreign mass must be a visible slice of the whole current page
_SCRIPT_SIGNAL_SCORE = 0.7  # shared slot for dominance flip and inflow

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


@cache
def _script_of_char(ch: str) -> str | None:
    """Coarse Unicode script bucket via unicodedata name prefixes —
    enough to detect 'page flipped from Latin to another script'.
    Memoized per character: pages repeat characters heavily and the
    Unicode database is immutable within a process."""
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


def script_profile(text: str, sample_cap: int | None = None) -> dict[str, float]:
    """Fractional distribution of Unicode scripts over alphabetic chars.

    Profiles the FULL text by default (a fixed cap made script content
    past the cap structurally invisible to the flip/inflow rules); pass
    `sample_cap` to restrict deliberately."""
    counts, total = _script_counts(text, sample_cap)
    if total == 0:
        return {}
    return {s: c / total for s, c in counts.items()}


def _script_counts(text: str, sample_cap: int | None = None) -> tuple[dict[str, int], int]:
    """Per-script alphabetic char counts. Counting runs over Counter(text)
    (C-speed) so only unique characters pay the classification cost."""
    source = text if sample_cap is None else text[:sample_cap]
    counts: dict[str, int] = {}
    total = 0
    for ch, n in Counter(source).items():
        s = _script_of_char(ch)
        if s is None:
            continue
        counts[s] = counts.get(s, 0) + n
        total += n
    return counts, total


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


def _collect_dual_view_hits(
    patterns: list[re.Pattern[str]], raw: str, decoded: str
) -> list[tuple[int, int, int]]:
    """Match every pattern against the raw text AND its leet-decoded view,
    returning [(pattern_index, start, end)] with cross-view duplicates
    removed. Spans are identical across views (the decoding is 1:1).

    A decoded-view hit is dropped ONLY when a raw-view hit at the same
    span decodes to the same text — that is literally the same term seen
    through both views (e.g. "gr33tz" matching \\bgr33tz\\b raw and
    \\bgreetz\\b decoded), which must not double-count into a conclusive
    score. Overlapping-but-distinct matches (e.g. standalone "h4ck3d"
    plus the decoded "hacked by" phrase spanning further) are different
    evidence and are all kept, exactly as unrelated patterns would be.
    """
    raw_hits: list[tuple[int, int, int]] = []
    for idx, pat in enumerate(patterns):
        for m in pat.finditer(raw):
            raw_hits.append((idx, m.start(), m.end()))
    raw_text_at_span = {(s, e): raw[s:e] for _, s, e in raw_hits}
    hits = list(raw_hits)
    for idx, pat in enumerate(patterns):
        for m in pat.finditer(decoded):
            s, e = m.start(), m.end()
            raw_counterpart = raw_text_at_span.get((s, e))
            if (
                raw_counterpart is not None
                and raw_counterpart.translate(_LEET_TRANSLATION) == decoded[s:e]
            ):
                continue
            hits.append((idx, s, e))
    return hits


def layer5_signatures(baseline: PageData, current: PageData) -> dict:
    baseline_text = extract_visible_text(baseline.html)
    current_text = extract_visible_text(current.html)
    new_text = _new_text(baseline_text, current_text)
    decoded_new_text = new_text.translate(_LEET_TRANSLATION)

    matches: list[dict] = []
    weight_sum = 0.0
    sig_patterns = [pat for pat, _ in _ALL_WEIGHTED]
    for idx, s, e in _collect_dual_view_hits(sig_patterns, new_text, decoded_new_text):
        pattern, weight = _ALL_WEIGHTED[idx]
        if len(matches) < MAX_MATCHES:
            matches.append(
                {
                    "pattern": pattern.pattern,
                    "matched": new_text[s:e][:120],
                    "weight": weight,
                }
            )
        weight_sum += weight

    profanity_hits: list[str] = []
    for _, s, e in _collect_dual_view_hits(_PROF, new_text, decoded_new_text):
        if len(profanity_hits) < MAX_MATCHES:
            profanity_hits.append(new_text[s:e][:40])

    # Script-mixing rule (a): dominance flip — compare dominant script of
    # the whole visible text.
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

    # Script-mixing rule (b): new-script inflow — the NEW text carries a
    # substantial mass of a script that was effectively absent from the
    # baseline (partial takeovers that leave the page majority-Latin
    # produce no dominance signal). The impact gate is the foreign share
    # OF THE WHOLE CURRENT PAGE rather than of the new-text blob: the
    # sentence-piece splitter glues unpunctuated injections together with
    # neighboring Latin fragments, so a new-text-relative fraction can
    # understate even a pure banner injection.
    b_counts, b_total = _script_counts(baseline_text)
    c_counts, c_total = _script_counts(current_text)
    n_counts, _n_total = _script_counts(new_text)
    scripts_added: list[str] = []
    if b_total >= _BASELINE_ALPHA_FLOOR:
        scripts_added = sorted(
            s
            for s, c in n_counts.items()
            if c > 0 and b_counts.get(s, 0) / b_total < _NEW_SCRIPT_BASELINE_EPSILON
        )
    added_chars = sum(n_counts[s] for s in scripts_added)
    page_share = added_chars / c_total if c_total else 0.0
    script_inflow = (
        bool(scripts_added)
        and added_chars >= _NEW_SCRIPT_MIN_CHARS
        and page_share >= _NEW_SCRIPT_PAGE_SHARE
    )

    signature_score = min(1.0, weight_sum)
    profanity_score = min(0.6, 0.25 * len(profanity_hits))
    flip_score = _SCRIPT_SIGNAL_SCORE if (script_flip or script_inflow) else 0.0
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
        "scripts_added": scripts_added,
        "new_script_chars": added_chars if scripts_added else 0,
        "new_script_page_share": round(page_share, 3) if scripts_added else 0.0,
        "script_inflow": script_inflow,
    }
    return layer_result(score, evidence)
