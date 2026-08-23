"""Layer 2 hidden-element counting: technique-independent detection (Phase 23).

Finding: `_is_hidden` inspected only the element's own `hidden` attribute and
inline style substring markers, so hiding via a stylesheet class
(`.row{display:none}`), opacity:0, font-size:0, or offscreen positioning was
invisible — measured pre-fix: 30 hidden spam links counted 30/30 inline but
0/30 for every other technique, and a single hidden paragraph scored layer 2
0.5034 inline vs churn-only ~0.15 for the non-inline variants of the same
payload.

The fix resolves each element against the page's own <style> blocks (a
conservative CSS subset: last-compound selector subjects, no pseudo-class or
attribute selectors, @-blocks skipped whole, document-order cascade with
inline-last) and recognizes opacity:0, font-size:0, negative absolute/fixed
offsets, text-indent <= -100px, and translate px components <= -500px. Every
counted element carries an audit-trail reason ('hidden-attribute',
'inline-style', or the deciding rule's subject) in additive evidence.

The failing-before proof for this module ran formally via `git stash push --
worker/detection/dom.py` (see the fix log): the committed file fails at
collection against the stashed tree (`_HiddenContext` absent) and the
headline scenarios measure hidden deltas of 0 there.
"""

import hashlib

import pytest

from worker.detection.dom import (
    _MIN_NEGATIVE_TEXT_INDENT,
    _MIN_NEGATIVE_TRANSLATE_PX,
    _HiddenContext,
    _parse_declarations,
    _selector_subjects,
    _stylesheet_rules,
    layer2_dom_structure,
    parse_html,
)
from worker.detection.pipeline import run_detection
from worker.detection.types import PageData

ROWS = "".join(
    f'<div class="product"><h3>Widget {i}</h3><p>Reliable industrial widget {i}.</p>'
    f'<a href="/products/{i}">Details</a></div>'
    for i in range(30)
)
BASE = f"""<html><head><title>Acme Corp</title>
<link rel="stylesheet" href="/styles.css">
<script src="https://cdn.acme.com/app.js"></script>
<style>
body {{ font-family: sans-serif; }}
.product {{ padding: 8px; }}
</style>
</head><body>
<h1>Welcome to Acme</h1>
<p>We build reliable widgets for industry.</p>
{ROWS}
<a href="/about">About</a> <a href="/contact">Contact</a>
<form action="/search"><input name="q"></form>
</body></html>"""


def page(html: str) -> PageData:
    return PageData(
        html=html,
        final_url="https://acme.com/",
        content_hash=hashlib.sha256(html.encode()).hexdigest(),
    )


def _layer(base_html: str, cur_html: str) -> dict:
    return layer2_dom_structure(page(base_html), page(cur_html))


def _hidden_delta(result: dict) -> int:
    counts = result["evidence"]["hidden_count"]
    return counts["current"] - counts["baseline"]


def _farm(rows: int = 12) -> str:
    anchor = '<a href="https://spam.example/x">About Contact widgets reliable Details Order</a>'
    return "".join(f'<div class="row">{anchor}</div>' for _ in range(rows))


# --- headline: technique-independent counting -------------------------------


@pytest.mark.parametrize(
    ("label", "current"),
    [
        (
            "wrapper_inline",
            BASE.replace("</body>", '<div style="display:none">' + _farm() + "</div></body>"),
        ),
        (
            "per_row_stylesheet",
            BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
                "</body>", _farm() + "</body>"
            ),
        ),
        (
            "opacity_inline",
            BASE.replace("</body>", '<div style="opacity:0">' + _farm() + "</div></body>"),
        ),
        (
            "offscreen_inline",
            BASE.replace(
                "</body>",
                '<div style="position:absolute;left:-9999px;top:-9999px">'
                + _farm()
                + "</div></body>",
            ),
        ),
    ],
)
def test_hidden_link_farm_counted_regardless_of_technique(label: str, current: str) -> None:
    result = _layer(BASE, current)
    assert _hidden_delta(result) >= 1
    assert result["score"] > 0.4


def test_per_row_class_hiding_counts_every_row() -> None:
    current = BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
        "</body>", _farm(30) + "</body>"
    )
    result = _layer(BASE, current)
    assert _hidden_delta(result) == 30
    assert result["score"] >= 0.99


def test_class_hiding_scores_like_equivalent_inline_hiding() -> None:
    # Same 30 elements, same hiding property, different channel: the count
    # and therefore the sensitive boost must match (churn differs only by
    # the extra <style> tag on the sheet side).
    rows = _farm(30)
    inline = BASE.replace(
        "</body>",
        "".join(f'<div style="display:none"><div class="row">{r}</div></div>' for r in [rows])
        + "</body>",
    )
    inline_per_row = BASE.replace(
        "</body>",
        rows.replace('<div class="row">', '<div class="row" style="display:none">') + "</body>",
    )
    sheet = BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
        "</body>", rows + "</body>"
    )
    s_inline = _layer(BASE, inline_per_row)["score"]
    s_sheet = _layer(BASE, sheet)["score"]
    assert abs(s_inline - s_sheet) <= 0.05
    wrapper = _layer(BASE, inline)
    # The single-wrapper variant counts ONE hidden element: still detected,
    # deliberately weaker — per-element semantics are consistent across channels.
    assert 0 < _hidden_delta(wrapper) == 1


# --- individual mechanisms ---------------------------------------------------


@pytest.mark.parametrize(
    "style",
    [
        "opacity:0",
        "opacity:0.0",
        "font-size:0",
        "font-size:0px",
        "position:absolute;left:-9999px",
        "position:fixed;top:-10px",
        "text-indent:-9999px",
        "transform:translate(-9999px,0)",
    ],
)
def test_non_display_inline_hiding_styles_count(style: str) -> None:
    current = BASE.replace("</body>", f'<p style="{style}">buy cheap seo</p></body>')
    assert _hidden_delta(_layer(BASE, current)) == 1


def test_visibility_values_count() -> None:
    current = BASE.replace("<style>", "<style>\n.collapse-row { visibility: collapse; }").replace(
        "</body>",
        '<p style="visibility:hidden">one</p>'
        '<table><tr class="collapse-row"><td>x</td></tr></table></body>',
    )
    assert _hidden_delta(_layer(BASE, current)) == 2


def test_translate_percentage_not_counted() -> None:
    # Carousel slides legitimately sit one slide-width away: percentage
    # translates must stay invisible to the counter.
    current = BASE.replace(
        "</body>", '<div style="transform:translateX(-100%)"><p>slide</p></div></body>'
    )
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_small_negative_indent_not_counted() -> None:
    boundary = int(abs(_MIN_NEGATIVE_TEXT_INDENT)) - 1
    current = BASE.replace("</body>", f'<p style="text-indent:-{boundary}px">clip</p></body>')
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_moderate_translate_not_counted() -> None:
    px = int(abs(_MIN_NEGATIVE_TRANSLATE_PX)) - 50
    current = BASE.replace(
        "</body>", f'<div style="transform:translate(-{px}px)"><p>peek</p></div></body>'
    )
    assert _hidden_delta(_layer(BASE, current)) == 0


# --- stylesheet resolution rules ---------------------------------------------


def test_id_selector_counts() -> None:
    current = BASE.replace("<style>", "<style>\n#promo { display: none; }").replace(
        "</body>", '<div id="promo">seo spam</div></body>'
    )
    assert _hidden_delta(_layer(BASE, current)) == 1


def test_compound_and_multi_class_selectors() -> None:
    current = BASE.replace(
        "<style>", "<style>\ndiv.a.b { display: none; }\n.d { display: none; }"
    ).replace("</body>", '<div class="a b">x</div><span class="c d">y</span></body>')
    assert _hidden_delta(_layer(BASE, current)) == 2


def test_descendant_sequence_matches_final_compound() -> None:
    current = BASE.replace("<style>", "<style>\n.side .ad { display: none; }").replace(
        "</body>",
        '<section class="side"><div class="ad">s</div></section><div class="ad">t</div></body>',
    )
    # Documented over-match: the ancestor condition is not evaluated.
    assert _hidden_delta(_layer(BASE, current)) == 2


def test_pseudo_and_attribute_selectors_skipped() -> None:
    sheet = (
        "\n.x:hover { display: none; }"
        "\n.y[data-k] { display: none; }"
        "\n.z::before { display: none; }"
    )
    current = BASE.replace("<style>", "<style>" + sheet).replace(
        "</body>",
        '<div class="x">a</div><div class="y" data-k="1">b</div><div class="z">c</div></body>',
    )
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_media_blocks_skipped_whole() -> None:
    current = BASE.replace(
        "<style>",
        "<style>\n@media print {\n.product { display: none; }\n.row { display: none; }\n}",
    )
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_comments_do_not_hide() -> None:
    current = BASE.replace("<style>", "<style>\n/* .product { display: none; } */")
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_cascade_last_declaration_wins() -> None:
    current = BASE.replace(
        "<style>", "<style>\n.x { display: none; }\n.x { display: block; }"
    ).replace("</body>", '<div class="x">hi</div></body>')
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_inline_style_overrides_stylesheet() -> None:
    current = BASE.replace("<style>", "<style>\n.y { display: none; }").replace(
        "</body>", '<div class="y" style="display:inline">hi</div></body>'
    )
    assert _hidden_delta(_layer(BASE, current)) == 0


def test_case_and_whitespace_normalized() -> None:
    current = BASE.replace("<style>", "<style>\n.X { DISPLAY : NONE }").replace(
        "</body>", '<div class="X">hi</div></body>'
    )
    assert _hidden_delta(_layer(BASE, current)) == 1
    legacy = BASE.replace("</body>", '<p style="DISPLAY : NONE">x</p></body>')
    assert _hidden_delta(_layer(BASE, legacy)) == 1


# --- false-positive guards ----------------------------------------------------


def test_non_rendering_elements_never_count() -> None:
    current = BASE.replace(
        "<form>", '<form><input type="HIDDEN" name="csrf" value="a"><input type="hidden" name="b">'
    ).replace("<head>", "<head>")
    current = current.replace("</title>", "</title>").replace(
        "</head>", '<meta name="x" content="y"></head>'
    )
    styled_head = BASE.replace(
        "<style>", "<style>\ntitle { display: none; }\nmeta { display: none; }"
    )
    assert _hidden_delta(_layer(BASE, styled_head)) == 0


_SR_ONLY_RULE = (
    "\n.sr-only { position: absolute; width: 1px; height: 1px;"
    " overflow: hidden; clip: rect(0 0 0 0); }"
)


def test_sr_only_baseline_parity_produces_no_delta() -> None:
    base_sr = BASE.replace("<style>", "<style>" + _SR_ONLY_RULE).replace(
        "</body>", '<span class="sr-only">Skip to content</span></body>'
    )
    cur_sr = base_sr.replace(
        "We build reliable widgets for industry.", "We build reliable industrial widgets."
    )
    result = _layer(base_sr, cur_sr)
    assert _hidden_delta(result) == 0


def test_malformed_css_never_raises_and_inline_still_counts() -> None:
    for garbage in (
        "{{{ <<< ]]> .unclosed { display",
        "/* unterminated comment .x{display:none}",
        ".bad:pseudo{display:none}",
        "} } } stray",
    ):
        broken = BASE.replace("<style>", "<style>" + garbage)
        result = _layer(BASE, broken)
        assert 0.0 <= result["score"] <= 1.0
    probe = broken.replace("</body>", '<div class="row">z</div></body>')
    assert _hidden_delta(_layer(broken, probe)) == 0  # garbage produced no rules


# --- evidence contract ---------------------------------------------------------


def test_evidence_carries_audit_trail_and_preserved_shapes() -> None:
    current = BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
        "</body>", _farm(5) + '<div hidden>attr</div><span style="display:none">inl</span></body>'
    )
    result = _layer(BASE, current)
    ev = result["evidence"]
    assert set(ev["hidden_count"]) == {"baseline", "current"}
    by = ev["hidden_detection"]["hidden_by"]["current"]
    assert by[".row"] == 5
    assert by["hidden-attribute"] == 1
    assert by["inline-style"] == 1
    assert ev["hidden_detection"]["stylesheet_chars"]["current"] > 0


def test_no_style_blocks_behaves_like_legacy_path() -> None:
    bare = BASE.replace(
        "<style>\nbody { font-family: sans-serif; }\n.product { padding: 8px; }\n</style>", ""
    )
    current = bare.replace("</body>", '<div hidden>a</div><p style="display:none">b</p></body>')
    result = _layer(bare, current)
    assert _hidden_delta(result) == 2
    assert result["evidence"]["hidden_detection"]["stylesheet_chars"]["current"] == 0


def test_parse_helpers_unit_contract() -> None:
    ctx = _HiddenContext(
        parse_html("<html><head><style>.q{display:none}</style></head><body></body></html>")
    )
    assert ctx.stylesheet_chars > 0
    el = [
        e
        for e in parse_html('<p class="q">z</p>').iter()
        if isinstance(e.tag, str) and e.tag == "p"
    ][0]
    assert ctx.hidden_reason(el) == ".q"
    assert _parse_declarations("DISPLAY : NONE !important;color:red") == {
        "display": "none",
        "color": "red",
    }
    rules = _stylesheet_rules("@media print {.a{display:none}} .b{display:none}")
    assert len(rules) == 1
    assert rules[0][0]["classes"] == frozenset({"b"})
    subjects = _selector_subjects(".side .ad, ul > li.item")
    assert subjects is not None and len(subjects) == 2
    assert subjects[0]["classes"] == frozenset({"ad"})
    assert subjects[1]["tag"] == "li" and "item" in subjects[1]["classes"]
    assert _selector_subjects("a:hover") is None
    assert _selector_subjects("[data-x]") is None


# --- pipeline-level integration -------------------------------------------------


def test_pipeline_sees_stylesheet_hidden_farm_end_to_end() -> None:
    current = BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
        "</body>", _farm(12) + "</body>"
    )
    det = run_detection(page(BASE), page(current))
    l2 = det["layer2_dom_structure"]
    assert not l2.get("skipped")
    assert _hidden_delta(l2) == 12
    assert l2["evidence"]["hidden_detection"]["hidden_by"]["current"][".row"] == 12
    assert l2["score"] >= 0.95
    # The same payload hidden per-row inline must land in the same regime —
    # technique is the only variable between attacker variants (equal counts).
    inline_current = BASE.replace(
        "</body>",
        _farm(12).replace('<div class="row">', '<div class="row" style="display:none">')
        + "</body>",
    )
    inline_det = run_detection(page(BASE), page(inline_current))
    assert abs(inline_det["layer2_dom_structure"]["score"] - l2["score"]) <= 0.05


def test_suppression_still_removes_hidden_farm_before_extraction() -> None:
    from worker.detection.suppress import Suppression

    current = BASE.replace("<style>", "<style>\n.row { display: none; }").replace(
        "</body>", _farm(12) + "</body>"
    )
    supp = Suppression(css_selectors=[".row"])
    det = run_detection(page(BASE), page(current), suppression=supp)
    l2 = det["layer2_dom_structure"]
    assert _hidden_delta(l2) == 0
    assert "suppression_applied" in l2["evidence"]
