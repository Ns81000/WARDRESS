"""Automatic pre-comparison normalization of universally-volatile TEXT.

Structural sibling of suppress.py, but automatic and universal: it runs
for every site on every comparison (nothing to configure) and replaces
only patterns that cannot plausibly be attack evidence (the prime
directive — when in doubt, a pattern is left for the layers to score):

- ISO 8601 timestamps ("2026-09-05T14:22:09Z", fractional-second and
  space-separator variants) and date-only stamps ("2026-09-05");
- UUIDs (canonical 8-4-4-4-12 hex, either case) in text nodes;
- cache-busting query values on well-known parameter names ("?v=…",
  "?_=…" — value-shape-guarded, so "?v=3" or "?t=legal" survive);
- UUID-shaped values in ANY query parameter (request-scoped request/
  correlation ids; URL PATHS are never touched — a path UUID is resource
  identity, and its changing means the page really links somewhere else);
- CSRF/token nonce values, matched only by a pinned attribute-name list
  (the `nonce` attribute, hidden inputs whose NAME is a token name, and
  csrf-token metas). Inline `style` and ordinary values are never touched.

Headline text, injected words, signatures, profanity — never matched.
A defacement banner that happens to contain a timestamp keeps every
character except the timestamp itself.

Scope is exactly the content layers (2/3/5/8): the pipeline hands them
normalized copies of BOTH sides, so a timestamp that differs between
baseline and scan compares equal instead of manufacturing a delta, and a
cache-busted asset URL no longer reads as a new/removed reference.
Everything else stays raw:

- Layer 1 always hashes the ORIGINAL content — the hash is the
  tamper-evidence anchor (bytes changed is a fact, not noise) and is
  never fed normalized text.
- Layer 4 compares pixels; layers 6/7 read transport data: raw.
- HTTP headers are a separate, later concern (Phase 9) — not touched.
- <script>/<style> inner text is not normalized: no content layer reads
  it, so substituting there would be churn without signal.

Baselines are stored raw; normalization happens at comparison time on
both sides, so stored baselines benefit without re-capture and stay
comparable with new scans (backward compatible by construction).

Safety: every pattern is linear (no nested quantifiers, no ambiguous
alternations — stdlib re cannot backtrack catastrophically on them), and
each is applied per text node / per attribute value / per query
parameter, which bounds every match call. The whole pass fails open:
an empty, unparseable, or oversized document is returned untouched and
the layers' own degraded-input handling covers it. Replacements are
recorded as counts in the receiving layers' evidence
(`normalization_applied`) so the pass is auditable, never invisible.
"""

import logging
import re
from dataclasses import replace

from lxml import html as lxml_html

from worker.detection.dom import parse_html
from worker.detection.types import PageData

logger = logging.getLogger(__name__)


# Fail-open size cap: a document this large is either a capture accident
# or hostile; either way the normalization pass skips it rather than
# spending unbounded time in the worker (the layers still run on the raw
# spending unbounded time in the worker (the layers still run on the raw
# HTML — the cap costs nothing but the churn it would have removed).
_MAX_HTML_CHARS = 5_000_000

# Fixed placeholder words: unmatchable by every pattern below (no digits,
# no dashes), so the pass is idempotent by construction, and none of them
# can collide with a signature, profanity, or topic pattern.
_TIMESTAMP_PLACEHOLDER = "TIMESTAMP"
_UUID_PLACEHOLDER = "UUID"
_CACHEBUST_PLACEHOLDER = "CACHEBUST"
_NONCE_PLACEHOLDER = "NONCE"

# ISO 8601 datetime: full date + time (T or space separator), optional
# fractional seconds and zone. The time component is REQUIRED — a bare
# "2026-09-05" is not a timestamp and is handled by the narrower
# date-only pattern below (which validates month/day ranges).
_ISO_DATETIME_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"(?![0-9A-Za-z])"
)

# Date-only ISO stamp with plausible month/day ranges. Applied AFTER the
# datetime pattern (a datetime contains a date prefix).
_ISO_DATE_RE = re.compile(
    r"(?<![0-9A-Za-z])\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?![0-9A-Za-z])"
)

# Canonical UUID, either case, delimited by non-alphanumerics so a
# longer hex blob containing a UUID shape is left alone.
_UUID_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Za-z])"
)

# Well-known cache-buster parameter names (lowercased). Deliberately
# narrow — "r"/"s"/"d"-style single letters are ambiguous (referrer,
# section, day) and stay out.
_CACHE_BUST_PARAMS = frozenset(
    {
        "_",
        "v",
        "ver",
        "version",
        "rev",
        "t",
        "ts",
        "time",
        "timestamp",
        "cb",
        "cachebust",
        "cachebuster",
        "nocache",
        "rand",
        "random",
    }
)

# A cache-buster value must LOOK volatile before it is replaced: a
# multi-digit number, a hex run, or an opaque alnum token. This is what
# keeps "?v=3" (a real version) and "?t=legal" (a tab name) untouched.
_VOLATILE_VALUE_RE = re.compile(r"^(?:\d{4,}|[0-9A-Fa-f]{8,}|[A-Za-z0-9_-]{12,})$")

# name=value pairs inside a URL query; the value stops at &, #, or end.
_QUERY_PARAM_RE = re.compile(r"([?&])([^=&#]+)=([^&#]*)")

# URL attributes of exactly the reference kinds layer 3 collects. Only
# these are query-normalized — nothing else reads URLs today.
_REF_TAGS = frozenset({"a", "script", "link", "iframe", "form"})
_URL_ATTRS = frozenset({"href", "src", "action"})

# Token/nonce attribute names (HTML parsing lowercases them). This list
# is intentionally pinned: "style" and ordinary values must NEVER be
# matched (layer 2's hidden-element detection resolves inline styles).
_TOKEN_ATTRS = frozenset(
    {
        "nonce",
        "csrf",
        "csrf_token",
        "csrftoken",
        "csrfmiddlewaretoken",
        "_csrf",
        "authenticity_token",
        "_token",
        "token",
        "xsrf",
        "xsrf_token",
        "requestverificationtoken",
        "__requestverificationtoken",
        "captcha_token",
        "recaptcha_token",
    }
)

# <meta name="…"> elements that carry the CSRF token in `content`.
_TOKEN_META_NAMES = frozenset({"csrf-token", "csrf", "csrf_token"})

# Inner text of these tags is code, not visible text; no content layer
# reads it, so it is never normalized.
_SKIP_TEXT_TAGS = frozenset({"script", "style"})

_SUMMARY_KEYS = (
    "iso_datetimes",
    "iso_dates",
    "uuids",
    "cache_bust_query_values",
    "uuid_query_values",
    "token_attribute_values",
)


def _sub_counts(
    text: str,
    pattern: re.Pattern[str],
    placeholder: str,
    key: str,
    counts: dict[str, int],
) -> str:
    if not text:
        return text
    out, n = pattern.subn(placeholder, text)
    if n:
        counts[key] += n
    return out


def _normalize_text(text: str, counts: dict[str, int]) -> str:
    # Order matters: the datetime pattern consumes the date prefix of a
    # timestamp, so the date-only pattern never sees it.
    text = _sub_counts(text, _ISO_DATETIME_RE, _TIMESTAMP_PLACEHOLDER, "iso_datetimes", counts)
    text = _sub_counts(text, _ISO_DATE_RE, _TIMESTAMP_PLACEHOLDER, "iso_dates", counts)
    return _sub_counts(text, _UUID_RE, _UUID_PLACEHOLDER, "uuids", counts)


def _normalize_url(url: str, counts: dict[str, int]) -> str:
    head, sep, tail = url.partition("?")
    if not sep:
        return url

    def repl(m: re.Match[str]) -> str:
        name, value = m.group(2), m.group(3)
        if name.lower() in _CACHE_BUST_PARAMS and _VOLATILE_VALUE_RE.match(value):
            counts["cache_bust_query_values"] += 1
            return f"{m.group(1)}{name}={_CACHEBUST_PLACEHOLDER}"
        if _UUID_RE.match(value):
            counts["uuid_query_values"] += 1
            return f"{m.group(1)}{name}={_UUID_PLACEHOLDER}"
        return m.group(0)

    # Run the param regex over sep+tail so the FIRST parameter (right
    # after the "?") is seen too — tail alone starts with the name.
    return head + _QUERY_PARAM_RE.sub(repl, sep + tail)


def _normalize_attributes(root: lxml_html.HtmlElement, counts: dict[str, int]) -> None:
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag in _REF_TAGS:
            for attr in _URL_ATTRS & set(el.attrib.keys()):
                value = el.get(attr) or ""
                new = _normalize_url(value, counts)
                if new != value:
                    el.set(attr, new)
        for attr, value in list(el.attrib.items()):
            # The placeholder check keeps the pass idempotent: the rule
            # would otherwise "replace" its own NONCE placeholder forever.
            if attr.lower() in _TOKEN_ATTRS and value and value != _NONCE_PLACEHOLDER:
                el.set(attr, _NONCE_PLACEHOLDER)
                counts["token_attribute_values"] += 1
        if tag == "input":
            name = (el.get("name") or "").lower()
            value = el.get("value") or ""
            if name in _TOKEN_ATTRS and value and value != _NONCE_PLACEHOLDER:
                el.set("value", _NONCE_PLACEHOLDER)
                counts["token_attribute_values"] += 1
        elif tag == "meta":
            name = (el.get("name") or "").lower()
            content = el.get("content") or ""
            if name in _TOKEN_META_NAMES and content and content != _NONCE_PLACEHOLDER:
                el.set("content", _NONCE_PLACEHOLDER)
                counts["token_attribute_values"] += 1


def _normalize_tree(root: lxml_html.HtmlElement, counts: dict[str, int]) -> bool:
    _normalize_attributes(root, counts)
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.lower() in _SKIP_TEXT_TAGS:
            continue
        if el.text:
            el.text = _normalize_text(el.text, counts)
        if el.tail:
            el.tail = _normalize_text(el.tail, counts)
    return any(counts.values())


def _summarize(counts: dict[str, int]) -> dict[str, int]:
    return {k: v for k in _SUMMARY_KEYS if (v := counts.get(k, 0)) > 0}


def normalize_html(html: str) -> tuple[str, dict[str, int]]:
    """Normalize one page's HTML. Returns (html, summary) where the
    summary counts replacements by category (empty when nothing matched —
    and then the ORIGINAL string is returned untouched, so a clean page
    pays one parse and is handed to the layers byte-for-byte)."""
    counts: dict[str, int] = dict.fromkeys(_SUMMARY_KEYS, 0)
    if not html or not html.strip() or len(html) > _MAX_HTML_CHARS:
        return html, {}
    root = parse_html(html)
    if root is None:
        return html, {}
    try:
        changed = _normalize_tree(root, counts)
    except Exception:  # fail open — never let the pass break a scan (rule 6)
        logger.exception("Volatile-text normalization failed; using original HTML")
        return html, {}
    if not changed:
        return html, {}
    try:
        return lxml_html.tostring(root, encoding="unicode"), _summarize(counts)
    except Exception:
        logger.exception("Could not serialize normalized DOM; using original")
        return html, {}


def normalized_copy(page: PageData) -> tuple[PageData, dict[str, int]]:
    """A copy of the page with volatile text normalized — handed to the
    content layers (2/3/5/8) by the pipeline instead of the original.
    Every other field (hash, screenshot, headers, TLS, …) is untouched."""
    html, summary = normalize_html(page.html)
    return replace(page, html=html), summary


def merge_summaries(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    """Element-wise sum of two replacement summaries (one per side)."""
    merged: dict[str, int] = {}
    for key in (*_SUMMARY_KEYS, *a, *b):
        total = a.get(key, 0) + b.get(key, 0)
        if total > 0:
            merged[key] = total
    return merged

