"""Layers 2 & 3 — DOM structural diff and link/script audit (§5, lxml).

Layer 2 compares tag-tree structure: tag counts, tree depth, and the
counts that matter most for defacement detection — <script>, <iframe>,
and hidden elements. Hidden-element detection is technique-independent:
it counts the `hidden` attribute, the element's own inline style, and
rules from the page's own <style> blocks resolved onto each element
(display/visibility, opacity:0, font-size:0, offscreen positioning).
External stylesheet bytes are not part of the captured DOM string, so
only embedded <style> text can be resolved here.

Layer 3 diffs the *sets* of external references: <script src>, <a href>,
plus stylesheet/iframe/form targets — new external domains appearing on
a page are a classic injection signal.

Both parse with lxml's HTMLParser, which recovers from arbitrarily broken
markup without raising (verified against docs-cache/lxml-parsing.html:
"It will not raise an exception on parser errors"). A page that fails to
produce a tree at all (e.g. empty string) is reported in evidence, not
raised.
"""

import math
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

from lxml import etree
from lxml import html as lxml_html

from worker.detection.types import PageData, layer_result

# Cap list-shaped evidence so a pathological page can't balloon the
# findings row (full artifacts remain on disk for manual inspection).
MAX_EVIDENCE_ITEMS = 50


def _safe_hostname(url: str | None) -> str:
    """Lowercased hostname, or "" for a falsy/malformed URL.

    `urlparse(...).hostname` raises ValueError on inputs like
    "http://[::1" (unterminated IPv6 literal). Layer 3 must never lose the
    whole layer to a single bad reference URL (rule 6 fail-safe), so any
    parse failure degrades to an empty host rather than propagating.
    """
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


# --- hidden-element detection -------------------------------------------------
# An element counts as hidden when a rendering-suppressing declaration reaches
# it through any of the channels attackers and frameworks actually use: the
# `hidden` attribute, its own style attribute, or a rule in one of the page's
# <style> blocks. The stylesheet resolver intentionally supports a conservative
# subset: selector subjects are the LAST simple compound of a descendant
# sequence (`.side .ad` matches every `.ad`); pseudo-classes and attribute
# selectors are skipped (their applicability is conditional); @-blocks
# (@media/@supports/@keyframes/...) are skipped whole so print/responsive
# styles never manufacture hidden counts; within matching rules the cascade is
# approximated by document order (last declaration per property wins), with the
# inline style overriding all sheet declarations as in real CSS.

_STYLE_TEXT_CAP = 1_000_000
_HIDE_DISPLAY_VALUES = {"none"}
_HIDE_VISIBILITY_VALUES = {"hidden", "collapse"}
_OFFSCREEN_POSITIONS = {"absolute", "fixed"}
_MIN_NEGATIVE_TEXT_INDENT = -100.0
_MIN_NEGATIVE_TRANSLATE_PX = -500.0
_NON_RENDERING_TAGS = frozenset(
    {
        "html",
        "head",
        "body",
        "meta",
        "link",
        "title",
        "base",
        "script",
        "style",
        "template",
        "noscript",
    }
)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECL_RE = re.compile(r"([a-zA-Z_-]+)\s*:\s*([^;]*)")
_LENGTH_VALUE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:%|[a-z]*)\s*$", re.IGNORECASE)
_TRANSLATE_PX_RE = re.compile(r"translate(?:[xyz])?\(\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _parse_declarations(text: str | None) -> dict[str, str]:
    """`prop: value; …` → dict; lowercase/whitespace-normalized, `!important`
    stripped. Tolerates garbage — unparsable chunks simply contribute nothing."""
    if not text:
        return {}
    decls: dict[str, str] = {}
    for prop, value in _DECL_RE.findall(text):
        value = value.split("!", 1)[0]
        value = re.sub(r"\s+", "", value).lower()
        if value:
            decls[prop.strip().lower()] = value
    return decls


def _selector_subjects(header: str) -> list[dict] | None:
    """Parse a rule header's selector list into compound subjects (the final
    simple selector of each descendant sequence). None when the header uses
    machinery we deliberately don't resolve."""
    header = " ".join(header.split())
    if not header or ":" in header or "[" in header:
        return None
    subjects: list[dict] = []
    for part in header.split(","):
        tokens = [t for t in part.split() if t not in (">", "+", "~")]
        if not tokens:
            return None
        subject: dict = {"tag": None, "classes": frozenset(), "id": None}
        classes: set[str] = set()
        i = 0
        while i < len(tokens[-1]):
            ch = tokens[-1][i]
            if ch == "*":
                i += 1
            elif ch in ".#":
                j = i + 1
                while j < len(tokens[-1]) and tokens[-1][j] in _NAME_CHARS:
                    j += 1
                if j == i + 1:
                    return None
                name = tokens[-1][i + 1 : j]
                if ch == ".":
                    classes.add(name)
                elif subject["id"] is not None:
                    return None
                else:
                    subject["id"] = name
                i = j
            elif ch.isalpha():
                j = i
                while j < len(tokens[-1]) and tokens[-1][j] in _NAME_CHARS:
                    j += 1
                if subject["tag"] is not None:
                    return None
                subject["tag"] = tokens[-1][i:j].lower()
                i = j
            else:
                return None
        subject["classes"] = frozenset(classes)
        subjects.append(subject)
    return subjects


def _matching_brace(text: str, open_idx: int) -> int:
    depth = 0
    for k in range(open_idx, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(text)


def _stylesheet_rules(css_text: str) -> list[tuple[dict, dict[str, str]]]:
    """(subject, declarations) pairs from top-level rules; comments and whole
    @-blocks are skipped. Never raises — garbage CSS yields no rules."""
    try:
        css_text = _CSS_COMMENT_RE.sub(" ", css_text)
        rules: list[tuple[dict, dict[str, str]]] = []
        i = 0
        while i < len(css_text):
            brace = css_text.find("{", i)
            if brace == -1:
                break
            header = css_text[i:brace].strip()
            close = _matching_brace(css_text, brace)
            body = css_text[brace + 1 : close]
            i = close + 1
            if header.startswith("@"):
                continue
            decls = _parse_declarations(body)
            if not decls:
                continue
            subjects = _selector_subjects(header)
            if not subjects:
                continue
            for subject in subjects:
                rules.append((subject, decls))
        return rules
    except Exception:
        return []


def _css_length(value: str | None) -> float | None:
    """Signed numeric prefix of a CSS length/number ("−9999px" → −9999.0);
    None when absent or unparsable."""
    if not value:
        return None
    m = _LENGTH_VALUE_RE.match(value)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _decisive_hidden_property(state: dict[str, str]) -> str | None:
    """The property that hides the element, or None. Order encodes
    precedence among independent hiding mechanisms."""
    if state.get("display") in _HIDE_DISPLAY_VALUES:
        return "display"
    if state.get("visibility") in _HIDE_VISIBILITY_VALUES:
        return "visibility"
    opacity = _css_length(state.get("opacity"))
    if opacity is not None and opacity <= 0:
        return "opacity"
    font_size = _css_length(state.get("font-size"))
    if font_size is not None and font_size == 0:
        return "font-size"
    if state.get("position") in _OFFSCREEN_POSITIONS:
        for side in ("left", "top", "right", "bottom"):
            offset = _css_length(state.get(side))
            if offset is not None and offset < 0:
                return f"position:{side}"
    indent = _css_length(state.get("text-indent"))
    if indent is not None and indent <= _MIN_NEGATIVE_TEXT_INDENT:
        return "text-indent"
    transform = state.get("transform")
    if transform:
        for m in _TRANSLATE_PX_RE.finditer(transform):
            if float(m.group(1)) <= _MIN_NEGATIVE_TRANSLATE_PX:
                return "transform"
    return None


def _subject_label(subject: dict) -> str:
    label = subject["tag"] or ""
    if subject["id"]:
        label += f"#{subject['id']}"
    label += "".join(f".{c}" for c in sorted(subject["classes"]))
    return label or "*"


class _HiddenContext:
    """Per-page resolution of 'is this element visually hidden?' against the
    page's own <style> blocks plus each element's own attributes."""

    def __init__(self, root: etree._Element | None) -> None:
        self._rule_subjects: list[dict] = []
        self._rule_decls: list[dict[str, str]] = []
        self._by_class: dict[str, list[int]] = {}
        self._by_id: dict[str, list[int]] = {}
        self._by_tag: dict[str, list[int]] = {}
        self._wildcard: list[int] = []
        self.stylesheet_chars = 0
        self._build(root)

    def _build(self, root: etree._Element | None) -> None:
        chunks: list[str] = []
        if root is not None:
            for el in root.iter():
                if isinstance(el.tag, str) and el.tag.lower() == "style" and el.text:
                    chunks.append(el.text)
        css = "".join(chunks)[:_STYLE_TEXT_CAP]
        self.stylesheet_chars = len(css)
        for subject, decls in _stylesheet_rules(css):
            idx = len(self._rule_subjects)
            self._rule_subjects.append(subject)
            self._rule_decls.append(decls)
            tag = subject["tag"]
            if tag:
                self._by_tag.setdefault(tag, []).append(idx)
            for cls in subject["classes"]:
                self._by_class.setdefault(cls, []).append(idx)
            if subject["id"]:
                self._by_id.setdefault(subject["id"], []).append(idx)
            if not tag and not subject["classes"] and not subject["id"]:
                self._wildcard.append(idx)

    @staticmethod
    def _subject_matches(el: etree._Element, subject: dict) -> bool:
        """Full compound-subject match: tag AND id AND every class present.
        The per-field indexes are only a pre-filter; this decides."""
        if subject["tag"] and el.tag.lower() != subject["tag"]:
            return False
        if subject["id"] and el.get("id") != subject["id"]:
            return False
        if subject["classes"]:
            classes = set((el.get("class") or "").split())
            if not subject["classes"].issubset(classes):
                return False
        return True

    def _candidate_rules(self, el: etree._Element) -> list[int]:
        idxs: set[int] = set(self._wildcard)
        cls = el.get("class")
        if cls:
            for c in cls.split():
                idxs.update(self._by_class.get(c, ()))
        eid = el.get("id")
        if eid:
            idxs.update(self._by_id.get(eid, ()))
        idxs.update(self._by_tag.get(el.tag.lower(), ()))
        return sorted(i for i in idxs if self._subject_matches(el, self._rule_subjects[i]))

    def hidden_reason(self, el: etree._Element) -> str | None:
        """None when the element renders normally (or isn't rendered at all,
        e.g. metadata tags); otherwise a short reason for the audit trail —
        'hidden-attribute', 'inline-style', or the deciding rule's subject."""
        if not isinstance(el.tag, str):
            return None
        tag = el.tag.lower()
        if tag in _NON_RENDERING_TAGS:
            return None
        if tag == "input" and (el.get("type") or "").strip().lower() == "hidden":
            return None
        if el.get("hidden") is not None:
            return "hidden-attribute"
        sources: list[tuple[str, dict[str, str]]] = []
        for idx in self._candidate_rules(el):
            sources.append((_subject_label(self._rule_subjects[idx]), self._rule_decls[idx]))
        inline = _parse_declarations(el.get("style"))
        if inline:
            sources.append(("inline-style", inline))
        state: dict[str, tuple[str, str]] = {}
        for label, decls in sources:
            for prop, value in decls.items():
                state[prop] = (label, value)
        decisive = _decisive_hidden_property({p: v for p, (_, v) in state.items()})
        if decisive is None:
            return None
        return state.get(decisive, ("inline-style", ""))[0]


def parse_html(text: str) -> etree._Element | None:
    """Parse (possibly broken) HTML into a tree, or None if libxml2 could
    not recover anything at all. Never raises on content."""
    if not text or not text.strip():
        return None
    try:
        parser = lxml_html.HTMLParser(recover=True)
        root = lxml_html.document_fromstring(text, parser=parser)
        return root
    except (etree.ParserError, etree.XMLSyntaxError, ValueError):
        return None


def _tree_stats(root: etree._Element | None) -> dict:
    if root is None:
        return {
            "parse_failed": True,
            "total_elements": 0,
            "max_depth": 0,
            "tag_counts": {},
            "script_count": 0,
            "iframe_count": 0,
            "hidden_count": 0,
            "stylesheet_chars": 0,
            "hidden_by": {},
        }
    ctx = _HiddenContext(root)
    tag_counts: Counter[str] = Counter()
    script_count = iframe_count = hidden_count = 0
    hidden_by: Counter[str] = Counter()
    max_depth = 0
    stack: list[tuple[etree._Element, int]] = [(root, 1)]
    while stack:
        el, depth = stack.pop()
        if not isinstance(el.tag, str):  # comments / processing instructions
            continue
        tag = el.tag.lower()
        tag_counts[tag] += 1
        max_depth = max(max_depth, depth)
        if tag == "script":
            script_count += 1
        elif tag == "iframe":
            iframe_count += 1
        reason = ctx.hidden_reason(el)
        if reason:
            hidden_count += 1
            hidden_by[reason] += 1
        for child in el:
            stack.append((child, depth + 1))
    return {
        "parse_failed": False,
        "total_elements": sum(tag_counts.values()),
        "max_depth": max_depth,
        "tag_counts": dict(tag_counts),
        "script_count": script_count,
        "iframe_count": iframe_count,
        "hidden_count": hidden_count,
        "stylesheet_chars": ctx.stylesheet_chars,
        "hidden_by": dict(hidden_by),
    }


def _added_removed(before: Counter, after: Counter) -> tuple[dict, dict]:
    added = {t: after[t] - before.get(t, 0) for t in after if after[t] > before.get(t, 0)}
    removed = {t: before[t] - after.get(t, 0) for t in before if before[t] > after.get(t, 0)}
    return added, removed


def layer2_dom_structure(baseline: PageData, current: PageData) -> dict:
    """Tag-tree diff with weighted attention on script/iframe/hidden
    deltas. Score grows with the fraction of the tree that changed and
    jumps on new scripts/iframes/hidden elements."""
    b_root = parse_html(baseline.html)
    c_root = parse_html(current.html)
    b = _tree_stats(b_root)
    c = _tree_stats(c_root)

    if b["parse_failed"] and c["parse_failed"]:
        return layer_result(
            0.0, {"note": "neither page produced a DOM tree", "baseline": b, "current": c}
        )
    if b["parse_failed"] != c["parse_failed"]:
        # One side has a DOM and the other doesn't — a drastic change.
        return layer_result(
            1.0,
            {
                "note": "one side failed to parse as HTML",
                "baseline_parse_failed": b["parse_failed"],
                "current_parse_failed": c["parse_failed"],
            },
        )

    b_tags = Counter(b["tag_counts"])
    c_tags = Counter(c["tag_counts"])
    added, removed = _added_removed(b_tags, c_tags)
    churn = sum(added.values()) + sum(removed.values())
    total = max(b["total_elements"], c["total_elements"], 1)

    # Baseline structural churn, saturating: half the tree changed -> ~1.0.
    churn_score = min(1.0, churn / (0.5 * total))

    # Sensitive-tag deltas get a dedicated boost — one injected <script>
    # on a 1000-element page is tiny churn but a big signal.
    new_scripts = max(0, c["script_count"] - b["script_count"])
    new_iframes = max(0, c["iframe_count"] - b["iframe_count"])
    new_hidden = max(0, c["hidden_count"] - b["hidden_count"])
    sensitive = new_scripts + new_iframes + new_hidden
    sensitive_score = 1 - math.exp(-0.7 * sensitive) if sensitive else 0.0

    depth_delta = abs(c["max_depth"] - b["max_depth"])

    score = max(churn_score * 0.6, sensitive_score)
    evidence = {
        "baseline_elements": b["total_elements"],
        "current_elements": c["total_elements"],
        "tags_added": dict(sorted(added.items(), key=lambda kv: -kv[1])[:MAX_EVIDENCE_ITEMS]),
        "tags_removed": dict(sorted(removed.items(), key=lambda kv: -kv[1])[:MAX_EVIDENCE_ITEMS]),
        "script_count": {"baseline": b["script_count"], "current": c["script_count"]},
        "iframe_count": {"baseline": b["iframe_count"], "current": c["iframe_count"]},
        "hidden_count": {"baseline": b["hidden_count"], "current": c["hidden_count"]},
        "hidden_detection": {
            "stylesheet_chars": {
                "baseline": b["stylesheet_chars"],
                "current": c["stylesheet_chars"],
            },
            "hidden_by": {"baseline": b["hidden_by"], "current": c["hidden_by"]},
        },
        "max_depth": {"baseline": b["max_depth"], "current": c["max_depth"], "delta": depth_delta},
        "structural_churn": churn,
    }
    return layer_result(score, evidence)


def _norm_ref(base_url: str, ref: str) -> str | None:
    """Resolve a href/src against the page URL and normalize; returns None
    for refs that aren't comparable links (javascript:, data:, fragments)."""
    ref = (ref or "").strip()
    if not ref or ref.startswith("#"):
        return None
    lower = ref.lower()
    if lower.startswith(("javascript:", "data:", "mailto:", "tel:", "about:")):
        return None
    try:
        absolute = urljoin(base_url or "", ref)
        parsed = urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https", ""):
        return None
    # Drop fragments; keep query (defacers love ?redirect= additions).
    return absolute.split("#", 1)[0]


def _collect_refs(page: PageData) -> dict[str, set[str]]:
    root = parse_html(page.html)
    refs: dict[str, set[str]] = {
        "script_src": set(),
        "a_href": set(),
        "link_href": set(),
        "iframe_src": set(),
        "form_action": set(),
    }
    if root is None:
        return refs
    base = page.final_url
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag == "script":
            r = _norm_ref(base, el.get("src") or "")
            if r:
                refs["script_src"].add(r)
        elif tag == "a":
            r = _norm_ref(base, el.get("href") or "")
            if r:
                refs["a_href"].add(r)
        elif tag == "link":
            r = _norm_ref(base, el.get("href") or "")
            if r:
                refs["link_href"].add(r)
        elif tag == "iframe":
            r = _norm_ref(base, el.get("src") or "")
            if r:
                refs["iframe_src"].add(r)
        elif tag == "form":
            r = _norm_ref(base, el.get("action") or "")
            if r:
                refs["form_action"].add(r)
    return refs


def _domains(urls: set[str]) -> set[str]:
    out = set()
    for u in urls:
        host = _safe_hostname(u)
        if host:
            out.add(host)
    return out


def layer3_link_audit(baseline: PageData, current: PageData) -> dict:
    """Diff <script src>/<a href>/link/iframe/form reference sets against
    the baseline. New external *domains* — especially for scripts,
    iframes, and form targets — dominate the score."""
    b_refs = _collect_refs(baseline)
    c_refs = _collect_refs(current)

    evidence: dict = {}
    new_domains_weighted = 0.0
    total_new_refs = 0
    baseline_domains = _domains(set().union(*b_refs.values())) if any(b_refs.values()) else set()
    page_host = _safe_hostname(current.final_url or baseline.final_url)
    known_domains = baseline_domains | ({page_host} if page_host else set())

    # form_action/script/iframe pointing at a never-seen domain is the
    # strongest injection signal; plain <a href> the weakest.
    weights = {
        "script_src": 1.0,
        "iframe_src": 1.0,
        "form_action": 1.0,
        "link_href": 0.6,
        "a_href": 0.35,
    }

    for kind in b_refs:
        added = sorted(c_refs[kind] - b_refs[kind])
        removed = sorted(b_refs[kind] - c_refs[kind])
        added_new_domain = sorted({u for u in added if _safe_hostname(u) not in known_domains})
        total_new_refs += len(added)
        new_domains_weighted += weights[kind] * len(_domains(set(added_new_domain)))
        evidence[kind] = {
            "added": added[:MAX_EVIDENCE_ITEMS],
            "removed": removed[:MAX_EVIDENCE_ITEMS],
            "added_count": len(added),
            "removed_count": len(removed),
            "added_new_domains": added_new_domain[:MAX_EVIDENCE_ITEMS],
        }

    # Each weighted new domain contributes strongly and saturates.
    domain_score = 1 - math.exp(-0.9 * new_domains_weighted) if new_domains_weighted else 0.0
    # Same-domain churn matters less but isn't free.
    churn_score = min(0.4, 0.02 * total_new_refs)
    score = max(domain_score, churn_score)

    evidence["new_external_domain_weight"] = round(new_domains_weighted, 3)
    evidence["total_added_refs"] = total_new_refs
    return layer_result(score, evidence)
