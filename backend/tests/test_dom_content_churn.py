"""Layer 2 content-aware churn weighting (PROMPT-002 Phase 10).

Layer 2's generic churn term (`churn_score * 0.6`) treats every added or
removed element equally, so legitimate publishing churn — new articles, feed
refreshes, redesigns that only touch content containers — can land at 0.4-0.6
where the positive-coefficient fusion model (layer-2 coefficient 1.286) weighs
it as mild attack evidence. The refinement classifies the churn: when every
churning tag is an ordinary content element the churn contribution is weighted
down (0.2); churn touching infrastructure (script/iframe/form/link, interactive
controls) or any tag outside the content list keeps the full weight — unknown
tags fail safe toward detection. The sensitive-tag boost (new scripts, iframes,
hidden elements) is untouched and still dominates via max().

Measured pre-change (1003-element baseline, layer2_dom_structure):
- 120 new articles/p/ul/li/h2 (churn 720): 0.5009  -> post-change 0.1671
- 120 new scripts:                 1.0   (unchanged — sensitive saturates)
- news + 1 removed <link> (mixed): 0.5016 (unchanged — full weight)
- 100 new <marquee> (unknown tag): full weight (unchanged)
- script wrapped in a <div>:       0.5034 (sensitive boost, wrapper-agnostic)
- identical pages:                 0.0    (unchanged)

Failing-before proof (Rule 3): this file was run against the UNMODIFIED tree —
7 failed / 2 passed. Failing: the two content-churn tests (score 0.5009 = full
weight; churn_class/churn_weight evidence keys absent), the
content-vs-infrastructure ordering test (content OUTSCORED infra), the
mixed-churn guard (classified content — classification machinery absent), the
infrastructure/unknown-tag guards (new evidence keys absent, though their score
assertions already held), and the no-churn guard (churn_class key absent).
Passing on both trees — failing-before inherently N/A, they pin pre-existing
correct behavior: test_wrapped_script_still_boosts_sensitive_score (the
sensitive boost was already wrapper-agnostic) and
test_hidden_content_farm_in_content_tags_still_scores_high (Phase 23's pin).
"""

import hashlib
import math

import pytest

from worker.detection.dom import layer2_dom_structure
from worker.detection.types import PageData

ROWS = "".join(f'<div class="item"><p>Item {i} text</p></div>' for i in range(500))
BASE = f"<html><head><title>Acme</title></head><body><h1>Acme</h1>{ROWS}</body></html>"


def page(html: str) -> PageData:
    return PageData(
        html=html,
        final_url="https://acme.com/",
        content_hash=hashlib.sha256(html.encode()).hexdigest(),
    )


def _news(n: int = 120) -> str:
    return "".join(
        f'<article class="post"><h2>Headline {i}</h2><p>Body text {i}.</p>'
        f"<ul><li>Tag A</li><li>Tag B</li></ul></article>"
        for i in range(n)
    )


def _expected_churn_contribution(result: dict, weight: float) -> float:
    ev = result["evidence"]
    churn = ev["structural_churn"]
    total = max(ev["baseline_elements"], ev["current_elements"], 1)
    return min(1.0, churn / (0.5 * total)) * weight


def test_content_only_churn_gets_reduced_weight() -> None:
    """A pure publishing delta (new articles) must weigh less than the same
    structural magnitude of infrastructure churn. Pre-change this exact
    scenario scored 0.5009 (full 0.6 weight); post-change the churn
    contribution is weighted 0.2."""
    result = layer2_dom_structure(page(BASE), page(BASE.replace("</body>", _news() + "</body>")))
    ev = result["evidence"]
    assert ev["churn_class"] == "content"
    assert ev["churn_weight"] == pytest.approx(0.2)
    assert result["score"] == pytest.approx(_expected_churn_contribution(result, 0.2))
    # Measured 0.1671 post-change (pre-change 0.5009): clear of the 0.35
    # material-change band on churn evidence alone.
    assert result["score"] < 0.35


def test_content_only_removal_churn_also_gets_reduced_weight() -> None:
    """Archived/deleted articles are the same benign class: removal churn
    confined to content tags classifies content and is weighted down."""
    with_news = BASE.replace("</body>", _news() + "</body>")
    result = layer2_dom_structure(page(with_news), page(BASE))
    ev = result["evidence"]
    assert ev["churn_class"] == "content"
    assert result["score"] == pytest.approx(_expected_churn_contribution(result, 0.2))


def test_content_churn_reduced_vs_same_size_infrastructure_churn() -> None:
    """Equal structural magnitude, opposite classification: 120 dropped
    <link> tags (infrastructure) keep the full weight while 120 articles'
    worth of content churn weighs less. Pre-change the content side actually
    OUTSCORED the infrastructure side (0.5009 vs 0.1282) — the refinement
    must invert that ordering, never just shift both."""
    infra = layer2_dom_structure(
        page(BASE.replace("</head>", "".join(
            f'<link rel="stylesheet" href="/a{i}.css">' for i in range(120)
        ) + "</head>")),
        page(BASE),
    )
    # Same structural magnitude: 20 articles x 6 elements = 120 content
    # elements vs 120 removed <link> tags. Pre-change both scored the full
    # 0.6 weight (content actually OUTSCORED infra 0.5009 vs 0.1282 at a
    # larger magnitude); the refinement must put content strictly below.
    content = layer2_dom_structure(
        page(BASE), page(BASE.replace("</body>", _news(20) + "</body>"))
    )
    assert infra["evidence"]["churn_class"] == "infrastructure"
    assert infra["score"] == pytest.approx(_expected_churn_contribution(infra, 0.6))
    assert content["score"] < infra["score"]


def test_infrastructure_churn_keeps_full_weight() -> None:
    """Guard (failing-before N/A): churn touching infrastructure tags scores
    EXACTLY as the pre-change formula — the refinement only ever reduces the
    content-only case."""
    infra = layer2_dom_structure(
        page(BASE.replace("</head>", "".join(
            f'<link rel="stylesheet" href="/a{i}.css">' for i in range(120)
        ) + "</head>")),
        page(BASE),
    )
    ev = infra["evidence"]
    assert ev["churn_class"] == "infrastructure"
    assert ev["churn_weight"] == pytest.approx(0.6)
    assert infra["score"] == pytest.approx(_expected_churn_contribution(infra, 0.6))


def test_mixed_content_and_infrastructure_churn_not_weakened() -> None:
    """Guard: a page that adds 120 articles AND loses one <link> tag is
    classified infrastructure and scores the full-weight value byte-for-byte
    with the pre-change computation — mixed churn never dilutes the
    infrastructure signal."""
    baseline = BASE.replace("</head>", '<link rel="stylesheet" href="/a.css"></head>')
    # The current scan drops the <link> AND adds 120 articles' worth of
    # content elements — one infrastructure delta poisons the whole batch.
    current = BASE.replace("</body>", _news() + "</body>")
    result = layer2_dom_structure(page(baseline), page(current))
    ev = result["evidence"]
    assert ev["churn_class"] == "infrastructure"
    assert ev["churn_weight"] == pytest.approx(0.6)
    assert result["score"] == pytest.approx(_expected_churn_contribution(result, 0.6))


def test_no_churn_scores_unchanged() -> None:
    """Guard: static sites — no tag deltas — score exactly 0.0 regardless of
    classification machinery, and a text-only swap inside an existing tag
    produces no churn at all."""
    identical = layer2_dom_structure(page(BASE), page(BASE))
    assert identical["score"] == 0.0
    assert identical["evidence"]["churn_class"] == "none"

    text_only = BASE.replace("Item 7 text", "Item 7 REPLACED")
    assert text_only != BASE
    result = layer2_dom_structure(page(BASE), page(text_only))
    assert result["score"] == 0.0
    assert result["evidence"]["structural_churn"] == 0


def test_wrapped_script_still_boosts_sensitive_score() -> None:
    """Safety constraint: an attacker hiding a <script> inside a content
    <div> still triggers the sensitive-tag boost — content-type awareness
    only ever reduces the churn term, never sensitive-element detection."""
    injected = BASE.replace(
        "</body>",
        '<div class="post"><p>innocent</p>'
        '<script src="https://evil.example/x.js"></script></div></body>',
    )
    result = layer2_dom_structure(page(BASE), page(injected))
    ev = result["evidence"]
    assert ev["script_count"]["current"] == ev["script_count"]["baseline"] + 1
    # Measured 0.5034 = 1 - exp(-0.7 * 1): the sensitive boost, untouched.
    assert result["score"] >= 0.5
    assert result["score"] == pytest.approx(1 - math.exp(-0.7))


def test_unknown_tags_keep_full_weight() -> None:
    """Guard: tags outside the content list — legacy (<marquee>) or custom
    elements — fail safe toward detection and keep the full churn weight."""
    marquee = "".join(f"<marquee>slide {i}</marquee>" for i in range(100))
    result = layer2_dom_structure(page(BASE), page(BASE.replace("</body>", marquee + "</body>")))
    ev = result["evidence"]
    assert ev["churn_class"] == "infrastructure"
    assert ev["churn_weight"] == pytest.approx(0.6)
    assert result["score"] == pytest.approx(_expected_churn_contribution(result, 0.6))


def test_hidden_content_farm_in_content_tags_still_scores_high() -> None:
    """Guard: hidden-element detection is untouched — a farm of hidden
    <div>s (content tags) still hits the sensitive boost at >= 0.95 even
    though its tag churn now classifies as content (Phase 23's pin)."""
    farm = "".join(
        '<div class="row" style="display:none"><p>spam</p></div>' for _ in range(12)
    )
    result = layer2_dom_structure(page(BASE), page(BASE.replace("</body>", farm + "</body>")))
    ev = result["evidence"]
    assert ev["hidden_count"]["current"] - ev["hidden_count"]["baseline"] == 12
    assert result["score"] >= 0.95
