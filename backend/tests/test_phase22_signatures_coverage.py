"""Layer 5 coverage fixes (audit: "Layer 5 misses common leetspeak
variants of its strongest signatures, and script-flip requires >=60%
dominance plus samples only the first 20k chars").

Three mechanisms, each pinned at unit level plus one end-to-end proof:

1. Leetspeak-decoded second matching view (@/4->a, 3->e, 0->o, 1->i,
   5/$->s, 7->t) with span-preserving dedup against the raw view:
   evidence quotes stay verbatim page text and exact-substitution terms
   (gr33tz) do not double-count.
2. New-script inflow signal for partial takeovers that leave the page
   majority-Latin (the dominance-flip rule alone scores them 0.0).
3. Full-text script profiling (no default cap), so script content past
   the historical 20,000-char sample line participates in both rules.
"""

import pytest

from worker.detection.pipeline import run_detection
from worker.detection.signatures import (
    layer5_signatures,
    script_profile,
)
from worker.detection.types import PageData, ScanPageData

BASE_HTML = """
<html><head><title>Acme Corp</title></head><body>
<h1>Welcome to Acme</h1>
<p>We build reliable widgets for industry.</p>
<a href="/about">About</a> <a href="/contact">Contact</a>
<p>Trusted since 1999 with quality service and support.</p>
</body></html>
"""

ARABIC_BANNER = "تم اختراق هذا الموقع بالكامل من قبل فريق القراصنة"
CYRILLIC_BANNER = "Сайт взломан киберпартизанами, мы вернёмся"
CJK_BANNER = "このサイトはハッキングされた、私たちは戻ってきません"


def page(html: str = BASE_HTML, content_hash: str = "a" * 64) -> PageData:
    return PageData(html=html, final_url="https://acme.com/", content_hash=content_hash)


def scan_page(html: str) -> ScanPageData:
    return ScanPageData(html=html, final_url="https://acme.com/", content_hash="b" * 64)


def _inject_after_h1(html: str, snippet: str) -> str:
    return html.replace("<h1>Welcome to Acme</h1>", f"<h1>Welcome to Acme</h1>{snippet}")


def _alpha_only(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


# --- 1. leetspeak variants of strong signatures ------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "H@CK3D BY XYZ CREW",
        "PWN3D BY XYZ CREW",
        "0WNED BY XYZ CREW",
        "0WN3D BY XYZ CREW",
        "D3FAC3D BY XYZ CREW",
        "h@ck3d by xyz crew",
    ],
)
def test_leet_strong_variants_score_max(phrase: str) -> None:
    result = layer5_signatures(page(), page(_inject_after_h1(BASE_HTML, f"<div>{phrase}</div>")))
    assert result["score"] == 1.0
    assert result["evidence"]["signature_matches"]


def test_leet_evidence_quotes_verbatim_page_text() -> None:
    """The explain channel embeds `matched` phrases verbatim; leet hits
    must quote the ORIGINAL spelling, not the decoded view."""
    result = layer5_signatures(
        page(), page(_inject_after_h1(BASE_HTML, "<div>H@CK3D BY XYZ CREW</div>"))
    )
    matched = [m["matched"] for m in result["evidence"]["signature_matches"]]
    assert "H@CK3D BY" in matched
    assert not any("HACKED BY" == m for m in matched)


def test_leet_profanity_variant_registers() -> None:
    result = layer5_signatures(
        page(), page(BASE_HTML.replace("</body>", "<p>eat $h1t and leave</p></body>"))
    )
    assert len(result["evidence"]["profanity_matches"]) >= 1


def test_gr33tz_is_not_double_counted() -> None:
    """Exact-span dedup with raw priority: the standalone term keeps its
    medium-tier weight instead of summing greetz+gr33tz into a conclusive
    1.0 that would arm the fusion floor on its own."""
    result = layer5_signatures(
        page(), page(BASE_HTML.replace("</body>", "<p>GR33TZ from acme</p></body>"))
    )
    assert result["score"] == pytest.approx(0.55)


def test_h4cked_by_union_scores_max_with_both_views() -> None:
    """Overlapping-but-different spans are distinct matches: the literal
    h4ck3d hit plus the decoded hacked-by phrase hit."""
    result = layer5_signatures(
        page(), page(_inject_after_h1(BASE_HTML, "<div>H4CK3D BY CREW</div>"))
    )
    assert result["score"] == 1.0
    patterns = {m["pattern"] for m in result["evidence"]["signature_matches"]}
    assert any("4" in p for p in patterns)
    assert any(r"hacked\s+by" in p for p in patterns)


def test_baseline_leet_term_still_never_flags_on_rescan() -> None:
    blog = BASE_HTML.replace(
        "</body>", "<article>Analysis: H@CK3D BY crews explained here</article></body>"
    )
    assert layer5_signatures(page(blog), page(blog))["score"] == 0.0


# --- 2. new-script inflow -----------------------------------------------------


def test_partial_arabic_injection_fires_inflow() -> None:
    cur = _inject_after_h1(
        BASE_HTML, f"<section><h2>{ARABIC_BANNER}</h2><p>{ARABIC_BANNER}</p></section>"
    )
    result = layer5_signatures(page(), page(cur))
    assert result["score"] == pytest.approx(0.7)
    ev = result["evidence"]
    assert ev["script_flip"] is False  # page stays majority-Latin: no dominance flip
    assert ev["script_inflow"] is True
    assert ev["scripts_added"] == ["ARABIC"]
    assert ev["new_script_chars"] >= 40


@pytest.mark.parametrize("banner", [CYRILLIC_BANNER, CJK_BANNER])
def test_other_script_injections_fire(banner: str) -> None:
    cur = _inject_after_h1(BASE_HTML, f"<div>{banner} {banner}</div>")
    result = layer5_signatures(page(), page(cur))
    assert result["score"] == pytest.approx(0.7)
    assert result["evidence"]["script_inflow"] is True


def test_inflow_absolute_grace_boundary() -> None:
    small = _alpha_only(ARABIC_BANNER)
    quiet = _inject_after_h1(BASE_HTML, f"<div>{small[:39]}</div>")
    firing = _inject_after_h1(BASE_HTML, f"<div>{small[:40]}</div>")
    # 39 alpha chars: inside the grace on ANY page size.
    assert layer5_signatures(page(), page(quiet))["score"] == 0.0
    # 40 alpha chars on this small fixture clears grace AND page share.
    assert layer5_signatures(page(), page(firing))["evidence"]["script_inflow"] is True


def test_incidental_foreign_fragment_among_edits_stays_quiet() -> None:
    """A stray short foreign fragment riding along ordinary edits must
    not fire: the absolute grace rejects it outright."""
    edited = BASE_HTML.replace(
        "<p>We build reliable widgets for industry.</p>",
        "<p>We build reliable industrial widgets for modern industry every day.</p><p>مرحبا</p>",
    )
    result = layer5_signatures(page(), page(edited))
    assert result["score"] == 0.0


def test_tiny_foreign_fragment_on_large_page_stays_quiet() -> None:
    """Below-grace mass is quiet regardless of page size; and even above
    grace, a sub-page-share slice on a big page stays quiet (page-share
    gate)."""
    filler = "Filler paragraph about reliable widgets and quality. " * 400  # ~22k alpha chars
    big = BASE_HTML.replace(
        "<p>We build reliable widgets for industry.</p>",
        f"<p>{filler}</p><p>{ARABIC_BANNER[:45]}</p>",
    )
    assert layer5_signatures(page(), page(big))["score"] == 0.0


def test_unestablished_baseline_blocks_inflow_signal() -> None:
    """A near-empty baseline cannot declare a script 'absent'; the inflow
    channel deliberately stays silent there (dominance flip covers real
    takeovers of stub pages)."""
    stub_base = BASE_HTML.replace("<p>We build reliable widgets for industry.</p>", "").replace(
        "<p>Trusted since 1999 with quality service and support.</p>", ""
    )  # tiny but >0 alpha chars? keep under floor
    stub_base = "<html><body><h1>Acme</h1></body></html>"
    cur = stub_base.replace("</h1>", "</h1>" + f"<p>{_alpha_only(ARABIC_BANNER)}</p>")
    result = layer5_signatures(page(stub_base), page(cur))
    assert result["evidence"]["script_inflow"] is False
    # Dominance flip legitimately fires instead: LATIN stub -> mostly ARABIC.
    assert result["evidence"]["script_flip"] is True
    assert result["score"] == pytest.approx(0.7)


def test_dominance_flip_path_unchanged() -> None:
    arabic = (
        BASE_HTML.replace("<h1>Welcome to Acme</h1>", "<h1>" + ARABIC_BANNER + "</h1>")
        .replace("<p>We build reliable widgets for industry.</p>", "<p>" + ARABIC_BANNER + "</p>")
        .replace('<a href="/about">About</a> <a href="/contact">Contact</a>', "")
    )
    result = layer5_signatures(page(), page(arabic))
    assert result["evidence"]["script_flip"] is True
    assert result["score"] >= 0.7


def test_benign_dynamic_edits_stay_zero() -> None:
    ad = BASE_HTML.replace(
        "</body>",
        '<div class="ad">Today only: widgets 20 percent off while stock lasts</div></body>',
    )
    counter = BASE_HTML.replace("</body>", "<p>Visitor #48291</p></body>")
    assert layer5_signatures(page(), page(ad))["score"] == 0.0
    assert layer5_signatures(page(), page(counter))["score"] == 0.0


# --- 3. full-text script profiling --------------------------------------------


def test_script_profile_default_covers_past_old_cap() -> None:
    latin_prefix = "Reliable industrial widgets and quality service. " * 460  # > 20k alpha chars
    tail = (_alpha_only(ARABIC_BANNER) + " ") * 30
    text = latin_prefix + tail
    profile = script_profile(text)  # default args: full text
    assert profile["LATIN"] > 0.9
    assert profile.get("ARABIC", 0.0) > 0.01


def test_script_profile_explicit_cap_still_honored() -> None:
    latin_prefix = "Reliable industrial widgets and quality service. " * 460
    tail = (_alpha_only(ARABIC_BANNER) + " ") * 300
    text = latin_prefix + tail
    capped = script_profile(text, sample_cap=len(latin_prefix))
    assert "ARABIC" not in capped
    full = script_profile(text)
    assert full.get("ARABIC", 0.0) > 0.05


def test_layer5_sees_beyond_cap_script_content() -> None:
    """End-to-end at the layer level: Arabic appended after >20k Latin
    chars participates in the inflow rule (historically invisible)."""
    latin_body = "Sentence about reliable industrial widgets and quality. " * 420
    big_base = BASE_HTML.replace(
        "<p>We build reliable widgets for industry.</p>", f"<p>{latin_body}</p>"
    )
    cur = big_base + f"<div>{' '.join([ARABIC_BANNER] * 80)}</div>"
    result = layer5_signatures(page(big_base), page(cur))
    assert result["evidence"]["script_inflow"] is True
    assert result["score"] == pytest.approx(0.7)


# --- evidence contract --------------------------------------------------------


def test_inflow_evidence_keys_and_shapes() -> None:
    cur = _inject_after_h1(BASE_HTML, f"<div>{ARABIC_BANNER} {ARABIC_BANNER}</div>")
    ev = layer5_signatures(page(), page(cur))["evidence"]
    assert isinstance(ev["scripts_added"], list) and ev["scripts_added"] == ["ARABIC"]
    assert ev["new_script_chars"] > 0
    assert 0.0 < ev["new_script_page_share"] <= 1.0
    assert ev["script_inflow"] is True


def test_no_new_scripts_zeroed_diagnostics() -> None:
    ad = BASE_HTML.replace("</body>", "<p>An ordinary English sentence added today.</p></body>")
    ev = layer5_signatures(page(), page(ad))["evidence"]
    assert ev["scripts_added"] == []
    assert ev["new_script_chars"] == 0
    assert ev["new_script_page_share"] == 0.0
    assert ev["script_inflow"] is False


# --- end-to-end through pipeline + deployed fusion model ----------------------


def test_partial_injection_flags_end_to_end_through_pipeline() -> None:
    """THE headline proof: a partial non-Latin takeover that leaves the
    page majority-Latin — measured by the audit at fused risk 0.041 with
    every layer at 0.0 — now carries real layer-5 evidence and flags at
    the default threshold through the deployed refit model."""
    cur = _inject_after_h1(
        BASE_HTML,
        f"<section><h2>{ARABIC_BANNER}</h2><p>{ARABIC_BANNER} {ARABIC_BANNER}</p></section>",
    )
    results = run_detection(page(), scan_page(cur), None)
    l5 = results["layer5_signatures"]
    assert not l5.get("skipped", False)
    assert l5["score"] == pytest.approx(0.7)
    risk = results["layer9_fusion"]["score"]
    assert risk >= 0.5


def test_clean_rescan_pipeline_control_unchanged() -> None:
    results = run_detection(page(), scan_page(BASE_HTML), None)
    l5 = results["layer5_signatures"]
    if l5.get("skipped"):
        pytest.fail("identical-hash gating of layer 5 changed unexpectedly")
    assert l5["score"] == 0.0
