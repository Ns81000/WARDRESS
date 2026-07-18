"""Suppression rules (§5): worker-side application in the detection
pipeline. API-side CRUD/validation lives in test_sites_phase3.py."""

import io

from PIL import Image

from worker.detection.suppress import (
    Suppression,
    build_suppression,
    parse_bbox_value,
    suppressed_copy,
)
from worker.detection.types import PageData, ScanPageData
from worker.hashing import content_sha256

BASE_HTML = """<html><body>
<h1>Corporate Landing</h1>
<div id="visitor-counter">Visitor #41</div>
<p>Welcome to our site. Session id: abc123def</p>
</body></html>"""

CURR_HTML = """<html><body>
<h1>Corporate Landing</h1>
<div id="visitor-counter">Visitor #42</div>
<p>Welcome to our site. Session id: zzz999yyy</p>
</body></html>"""


def _page(html: str, **kw) -> PageData:
    return PageData(html=html, content_hash=content_sha256(html), **kw)


def _scan_page(html: str, **kw) -> ScanPageData:
    return ScanPageData(html=html, content_hash=content_sha256(html), **kw)


def _png(width: int, height: int, color: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _png_with_box(width: int, height: int, bg: int, box_color: int, box) -> bytes:
    img = Image.new("L", (width, height), bg)
    img.paste(box_color, box)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- build_suppression: per-rule fail-safe ---


def test_build_suppression_groups_by_type() -> None:
    supp = build_suppression(
        [
            ("css_selector", "#visitor-counter"),
            ("regex", r"Session id: \w+"),
            ("bbox", "0.1,0.1,0.2,0.2"),
        ]
    )
    assert supp.css_selectors == ["#visitor-counter"]
    assert supp.regexes == [r"Session id: \w+"]
    assert supp.bboxes == [(0.1, 0.1, 0.2, 0.2)]
    assert supp.unusable == []
    assert supp.has_content_rules


def test_build_suppression_records_unusable_rules() -> None:
    supp = build_suppression(
        [
            ("css_selector", "div[["),  # unparseable selector
            ("regex", "(unclosed"),  # invalid regex
            ("bbox", "2,2,1,1"),  # out of range
            ("bbox", "not-a-bbox"),
            ("mystery", "x"),  # unknown type
        ]
    )
    assert supp.css_selectors == []
    assert supp.regexes == []
    assert supp.bboxes == []
    assert len(supp.unusable) == 5
    assert all("reason" in u for u in supp.unusable)


def test_parse_bbox_value_bounds() -> None:
    assert parse_bbox_value("0,0,1,1") == (0.0, 0.0, 1.0, 1.0)
    assert parse_bbox_value("0.25,0.5,0.5,0.25") == (0.25, 0.5, 0.5, 0.25)
    assert parse_bbox_value("0.9,0.9,0.2,0.05") is None  # extends past edge
    assert parse_bbox_value("0,0,0,0.5") is None  # zero width
    assert parse_bbox_value("") is None
    assert parse_bbox_value("a,b,c,d") is None


# --- HTML application ---


def test_css_selector_removes_subtree_both_sides() -> None:
    supp = build_suppression([("css_selector", "#visitor-counter")])
    b = suppressed_copy(_page(BASE_HTML), supp)
    c = suppressed_copy(_page(CURR_HTML), supp)
    assert "Visitor #" not in b.html
    assert "Visitor #" not in c.html
    # The rest of the page survives, including text after the removed div.
    assert "Corporate Landing" in b.html
    assert "Welcome to our site" in c.html


def test_regex_removes_matching_text() -> None:
    supp = build_suppression([("regex", r"Session id: \w+")])
    b = suppressed_copy(_page(BASE_HTML), supp)
    c = suppressed_copy(_page(CURR_HTML), supp)
    assert "abc123def" not in b.html
    assert "zzz999yyy" not in c.html
    assert "Welcome to our site" in b.html


def test_regex_catastrophic_backtracking_times_out_not_hangs() -> None:
    """HIGH: a stored regex with catastrophic backtracking must not stall the
    worker. The timeout-guarded substitution skips the rule (recording it as
    unusable) instead of running unbounded — master prompt rule 6."""
    import time

    # "(a|a)+$" against a long non-matching text node is the classic
    # exponential-backtracking case for a backtracking engine.
    evil_pattern = r"(a|a)+$"
    supp = build_suppression([("regex", evil_pattern)])
    assert supp.regexes == [evil_pattern]  # compiles fine, so it's "usable"

    long_text = "a" * 60 + "!"
    page = _page(f"<html><body><p>{long_text}</p></body></html>")

    start = time.time()
    out = suppressed_copy(page, supp)
    elapsed = time.time() - start

    # Bounded by the per-substitution timeout (a few seconds), not unbounded.
    assert elapsed < 10, f"suppression ran {elapsed:.1f}s — timeout guard failed"
    # The rule was recorded as unusable rather than silently dropped, and the
    # text survives (nothing was removed because the rule couldn't run).
    assert any(u["reason"] == "timed out during application" for u in supp.unusable)
    assert long_text in out.html


def test_suppressed_copy_untouched_without_rules() -> None:
    page = _page(BASE_HTML)
    out = suppressed_copy(page, Suppression())
    assert out.html == BASE_HTML
    # Original page object is never mutated.
    assert page.html == BASE_HTML


def test_suppressed_copy_handles_unparseable_page() -> None:
    page = _page("")
    supp = build_suppression([("css_selector", "#x")])
    assert suppressed_copy(page, supp).html == ""


# --- pipeline integration ---


def test_pipeline_suppression_silences_dynamic_change() -> None:
    """The canonical §5 case: only suppressed content changed between
    baseline and scan — the content layers must score 0.0 while layer 1
    still reports that bytes changed (tamper evidence is never hidden)."""
    from worker.detection.pipeline import run_detection

    supp = build_suppression([("css_selector", "#visitor-counter"), ("regex", r"Session id: \w+")])
    results = run_detection(_page(BASE_HTML), _scan_page(CURR_HTML), supp)

    assert results["layer1_hash"]["score"] == 1.0  # bytes did change
    assert results["layer2_dom_structure"]["score"] == 0.0
    assert results["layer3_link_audit"]["score"] == 0.0
    assert results["layer5_signatures"]["score"] == 0.0
    # Suppression is recorded in the affected layers' evidence.
    assert "suppression_applied" in results["layer2_dom_structure"]["evidence"]
    assert "suppression" in results["layer9_fusion"]["evidence"]


def test_pipeline_suppression_does_not_mask_real_change() -> None:
    """A rule for one region must not blind the layers to changes
    elsewhere on the page."""
    from worker.detection.pipeline import run_detection

    defaced = CURR_HTML.replace("Corporate Landing", "HACKED BY MIDNIGHT CREW")
    supp = build_suppression([("css_selector", "#visitor-counter")])
    results = run_detection(_page(BASE_HTML), _scan_page(defaced), supp)

    assert results["layer5_signatures"]["score"] >= 0.9
    matched = [
        m["matched"].lower() for m in results["layer5_signatures"]["evidence"]["signature_matches"]
    ]
    assert any("hacked by" in m for m in matched)


def test_pipeline_without_suppression_unchanged_behavior() -> None:
    """No rules -> identical behavior to Phase 2 (regression guard)."""
    from worker.detection.pipeline import run_detection

    results = run_detection(_page(BASE_HTML), _scan_page(CURR_HTML))
    # The visitor counter and session id differences register.
    assert results["layer1_hash"]["score"] == 1.0
    assert "suppression_applied" not in results["layer2_dom_structure"]["evidence"]
    assert "suppression" not in results["layer9_fusion"]["evidence"]


# --- visual bbox masking ---


def test_bbox_mask_silences_region_change() -> None:
    from worker.detection.visual import layer4_visual_diff

    # Same 200x200 white page; the current capture has a black box in the
    # top-left quadrant (a rotating ad, say).
    b = _page("x", screenshot=_png(200, 200, 255))
    c = _page("y", screenshot=_png_with_box(200, 200, 255, 0, (0, 0, 100, 100)))

    unmasked = layer4_visual_diff(b, c)
    assert unmasked["score"] > 0.1  # the change is clearly visible

    masked = layer4_visual_diff(b, c, suppress_bboxes=[(0.0, 0.0, 0.5, 0.5)])
    assert masked["score"] < 0.02  # masked region compares equal
    assert masked["evidence"]["suppressed_regions"] == [[0.0, 0.0, 0.5, 0.5]]


def test_bbox_mask_keeps_changes_outside_region() -> None:
    from worker.detection.visual import layer4_visual_diff

    b = _page("x", screenshot=_png(200, 200, 255))
    # Change in the bottom-right, mask over the top-left: still visible.
    c = _page("y", screenshot=_png_with_box(200, 200, 255, 0, (100, 100, 200, 200)))
    masked = layer4_visual_diff(b, c, suppress_bboxes=[(0.0, 0.0, 0.5, 0.5)])
    assert masked["score"] > 0.1


def test_bbox_mask_anchored_to_baseline_geometry() -> None:
    """A current capture that grew taller must keep the mask over the
    same content (baseline-anchored pixels), not drift down with the new
    page height. The changed region sits at baseline rows 40-100; the
    rule covers baseline rows 0-100 (y 0-0.5 of the 200px baseline). On
    a 400px-tall current capture a height-relative mask would cover rows
    0-200 and also hide a change at rows 150-200 — the baseline-anchored
    mask must NOT hide that one."""
    from worker.detection.visual import layer4_visual_diff

    b = _page("x", screenshot=_png(200, 200, 255))
    # Taller current page: suppressed change inside baseline rows 0-100,
    # plus a real change at rows 150-200 (outside the anchored mask).
    img = Image.new("L", (200, 400), 255)
    img.paste(0, (0, 40, 200, 100))  # inside the rule -> masked
    img.paste(0, (0, 150, 200, 200))  # outside the rule -> must register
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    c = _page("y", screenshot=buf.getvalue())

    masked = layer4_visual_diff(b, c, suppress_bboxes=[(0.0, 0.0, 1.0, 0.5)])
    assert masked["score"] > 0.05  # rows 150-200 still count

    # And the region the user actually suppressed is silent: same tall
    # page with ONLY the in-rule change.
    img2 = Image.new("L", (200, 400), 255)
    img2.paste(0, (0, 40, 200, 100))
    buf2 = io.BytesIO()
    img2.save(buf2, format="PNG")
    c2 = _page("y", screenshot=buf2.getvalue())
    masked2 = layer4_visual_diff(b, c2, suppress_bboxes=[(0.0, 0.0, 1.0, 0.5)])
    # SSIM compares the shared top region; the only difference there is
    # masked out, so the remaining signal is the height-tail seen by the
    # perceptual hashes only.
    assert masked2["score"] < masked["score"]
    assert masked2["evidence"]["ssim"] > 0.99
