"""Layers 2 & 3 — DOM structural diff and link/script audit (§5, lxml).

Layer 2 compares tag-tree structure: tag counts, tree depth, and the
counts that matter most for defacement detection — <script>, <iframe>,
and hidden elements (display:none / visibility:hidden / hidden attr).

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
from collections import Counter
from urllib.parse import urljoin, urlparse

from lxml import etree
from lxml import html as lxml_html

from worker.detection.types import PageData, layer_result

# Cap list-shaped evidence so a pathological page can't balloon the
# findings row (full artifacts remain on disk for manual inspection).
MAX_EVIDENCE_ITEMS = 50

_HIDDEN_STYLE_MARKERS = ("display:none", "display: none", "visibility:hidden", "visibility: hidden")


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


def _is_hidden(el: etree._Element) -> bool:
    if el.get("hidden") is not None:
        return True
    style = (el.get("style") or "").lower().replace(" ", "")
    return any(m.replace(" ", "") in style for m in _HIDDEN_STYLE_MARKERS)


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
        }
    tag_counts: Counter[str] = Counter()
    script_count = iframe_count = hidden_count = 0
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
        if _is_hidden(el):
            hidden_count += 1
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
        host = urlparse(u).hostname
        if host:
            out.add(host.lower())
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
    page_host = (urlparse(current.final_url or baseline.final_url).hostname or "").lower()
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
        added_new_domain = sorted(
            {u for u in added if (urlparse(u).hostname or "").lower() not in known_domains}
        )
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
