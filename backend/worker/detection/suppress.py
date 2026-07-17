"""Suppression rules applied inside the detection pipeline (§5).

Users mark known-dynamic page regions as ignorable; the pipeline honors
them so they stop producing false positives:
- css_selector — matching DOM subtrees are removed from BOTH sides of
  the comparison before the structure/text layers (2/3/5/8) run.
- regex — matching text is removed from DOM text nodes on both sides
  (dynamic counters, timestamps, session ids).
- bbox — a region of the screenshot the visual layer (4) masks to a
  uniform fill on both sides before comparing. Stored as "x,y,w,h"
  fractions (0-1) of the BASELINE capture the user drew on; the visual
  layer converts through the baseline's pixel size and applies the same
  pixel rect to both captures, so a current capture that grew taller
  keeps the mask over the same content instead of drifting down.

Every applied (or unusable) rule is recorded in the affected layers'
evidence — a suppressed signal must stay auditable, never invisible.

Rules are validated at the API boundary, but the worker still fails
safe per rule: one unusable stored rule is skipped with a note, never
allowed to break a scan (master prompt rule 6).
"""

import logging
import re
from dataclasses import dataclass, field, replace

from lxml import html as lxml_html
from lxml.cssselect import CSSSelector, SelectorError

from worker.detection.dom import parse_html
from worker.detection.types import PageData

logger = logging.getLogger(__name__)

# A bbox rule's value: "x,y,w,h" as fractions (0-1) of the baseline capture.
_BBOX_RE = re.compile(r"^(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$")


@dataclass
class Suppression:
    """Plain-data view of a site's suppression rules — the pipeline never
    sees ORM rows (same rule as the layers themselves)."""

    css_selectors: list[str] = field(default_factory=list)
    regexes: list[str] = field(default_factory=list)
    bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    # Rules that could not be applied (with reasons) — carried into
    # evidence so a silently-skipped rule is impossible.
    unusable: list[dict] = field(default_factory=list)

    @property
    def has_content_rules(self) -> bool:
        return bool(self.css_selectors or self.regexes)

    def summary(self) -> dict:
        out: dict = {}
        if self.css_selectors:
            out["css_selectors"] = self.css_selectors[:20]
        if self.regexes:
            out["regexes"] = self.regexes[:20]
        if self.bboxes:
            out["bboxes"] = [list(b) for b in self.bboxes[:20]]
        if self.unusable:
            out["unusable_rules"] = self.unusable[:20]
        return out


def parse_bbox_value(value: str) -> tuple[float, float, float, float] | None:
    """Parse a stored bbox rule value; None (not an exception) when the
    stored value is unusable — the caller records it and moves on."""
    m = _BBOX_RE.match((value or "").strip())
    if not m:
        return None
    x, y, w, h = (float(g) for g in m.groups())
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) or w <= 0.0 or h <= 0.0:
        return None
    if x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
        return None
    return x, y, w, h


def build_suppression(rules: list[tuple[str, str]]) -> Suppression:
    """Build the pipeline's Suppression from stored (type, value) pairs,
    failing safe per rule."""
    supp = Suppression()
    for rule_type, value in rules:
        if rule_type == "css_selector":
            try:
                CSSSelector(value)
            except SelectorError as exc:
                supp.unusable.append({"type": rule_type, "value": value[:200], "reason": str(exc)})
                continue
            supp.css_selectors.append(value)
        elif rule_type == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                supp.unusable.append({"type": rule_type, "value": value[:200], "reason": str(exc)})
                continue
            supp.regexes.append(value)
        elif rule_type == "bbox":
            bbox = parse_bbox_value(value)
            if bbox is None:
                supp.unusable.append(
                    {"type": rule_type, "value": value[:200], "reason": "not a valid bbox"}
                )
                continue
            supp.bboxes.append(bbox)
        else:
            supp.unusable.append(
                {"type": rule_type, "value": value[:200], "reason": "unknown rule type"}
            )
    return supp


def _apply_to_html(html: str, supp: Suppression) -> str:
    """Remove suppressed subtrees and text from one page's HTML. Returns
    the original string untouched when nothing applies or no DOM can be
    built (the layers' own degraded-input handling covers that case)."""
    if not supp.has_content_rules or not html.strip():
        return html
    root = parse_html(html)
    if root is None:
        return html

    for sel in supp.css_selectors:
        try:
            for el in CSSSelector(sel)(root):
                # drop_tree keeps the element's tail text — removing a
                # banner must not swallow the text that follows it.
                if el.getparent() is not None:
                    el.drop_tree()
        except Exception:
            # Validated at save time; a runtime surprise (exotic markup)
            # skips this rule for this scan rather than failing the layer.
            logger.warning("CSS suppression rule failed to apply: %r", sel)

    for pattern in supp.regexes:
        compiled = re.compile(pattern)
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.text:
                el.text = compiled.sub("", el.text)
            if el.tail:
                el.tail = compiled.sub("", el.tail)

    try:
        return lxml_html.tostring(root, encoding="unicode")
    except Exception:
        logger.exception("Could not serialize suppressed DOM; using original")
        return html


def suppressed_copy(page: PageData, supp: Suppression) -> PageData:
    """A shallow copy of the page with suppression applied to its HTML —
    handed to the content layers (2/3/5/8) instead of the original."""
    return replace(page, html=_apply_to_html(page.html, supp))
