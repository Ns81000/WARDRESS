"""Detection layers 2-5 unit tests: DOM structure, link audit, visual
diff, signatures. Every §5 contract point: {score 0-1, evidence dict},
graceful handling of malformed/empty/non-HTML content, and the specific
signals each layer exists to catch."""

import io

from PIL import Image

from worker.detection.dom import layer2_dom_structure, layer3_link_audit, parse_html
from worker.detection.signatures import (
    extract_visible_text,
    layer5_signatures,
    script_profile,
)
from worker.detection.types import PageData
from worker.detection.visual import layer4_visual_diff

BASE_HTML = """
<html><head><title>Acme Corp</title>
<link rel="stylesheet" href="/styles.css">
<script src="https://cdn.acme.com/app.js"></script>
</head><body>
<h1>Welcome to Acme</h1>
<p>We build reliable widgets for industry.</p>
<a href="/about">About</a> <a href="/contact">Contact</a>
<form action="/search"><input name="q"></form>
</body></html>
"""


def page(html: str = BASE_HTML, **kwargs) -> PageData:
    defaults = {"final_url": "https://acme.com/", "content_hash": "x" * 64}
    defaults.update(kwargs)
    return PageData(html=html, **defaults)


def _png_bytes(color: tuple[int, int, int], size=(320, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _score(result: dict) -> float:
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["evidence"], dict)
    return result["score"]


# --- layer 2: DOM structure ---


def test_layer2_identical_dom_scores_zero() -> None:
    assert _score(layer2_dom_structure(page(), page())) == 0.0


def test_layer2_injected_script_scores_high() -> None:
    injected = BASE_HTML.replace(
        "</body>", '<script src="https://evil.example/x.js"></script></body>'
    )
    result = layer2_dom_structure(page(), page(injected))
    assert _score(result) >= 0.4
    assert result["evidence"]["script_count"]["current"] == 2


def test_layer2_hidden_elements_counted() -> None:
    hidden = BASE_HTML.replace(
        "</body>",
        '<div style="display:none">seo spam</div><div hidden>more</div></body>',
    )
    result = layer2_dom_structure(page(), page(hidden))
    assert result["evidence"]["hidden_count"]["current"] == 2
    assert _score(result) > 0.0


def test_layer2_full_replacement_scores_near_one() -> None:
    defaced = "<html><body><h1>OWNED</h1><marquee>gone</marquee></body></html>"
    assert _score(layer2_dom_structure(page(), page(defaced))) >= 0.6


def test_layer2_malformed_html_recovers() -> None:
    broken = "<html><body><div><p>unclosed<span>mess"
    result = layer2_dom_structure(page(), page(broken))
    assert _score(result) > 0.0  # different content, no crash


def test_layer2_empty_current_page() -> None:
    result = layer2_dom_structure(page(), page(""))
    assert _score(result) == 1.0  # one side has no DOM at all
    assert result["evidence"]["current_parse_failed"] is True


def test_layer2_both_empty() -> None:
    assert _score(layer2_dom_structure(page(""), page(""))) == 0.0


def test_layer2_non_html_content() -> None:
    result = layer2_dom_structure(page('{"json": "payload"}'), page("plain text here"))
    # libxml2 wraps stray text in <html><body><p> — comparable, tiny diff.
    assert _score(result) < 0.3


def test_parse_html_handles_garbage() -> None:
    assert parse_html("") is None
    assert parse_html("   \n  ") is None
    assert parse_html("\x00\x01\x02") is not None or parse_html("\x00\x01\x02") is None  # no raise


# --- layer 3: link audit ---


def test_layer3_no_changes() -> None:
    assert _score(layer3_link_audit(page(), page())) == 0.0


def test_layer3_new_external_script_domain_scores_high() -> None:
    injected = BASE_HTML.replace(
        "</head>", '<script src="https://malware.example/inject.js"></script></head>'
    )
    result = layer3_link_audit(page(), page(injected))
    assert _score(result) >= 0.5
    assert "https://malware.example/inject.js" in result["evidence"]["script_src"]["added"]
    assert result["evidence"]["script_src"]["added_new_domains"]


def test_layer3_same_domain_links_score_low() -> None:
    extra = BASE_HTML.replace("</body>", '<a href="/new-page">New</a></body>')
    result = layer3_link_audit(page(), page(extra))
    assert 0.0 < _score(result) < 0.2


def test_layer3_form_action_hijack_detected() -> None:
    hijacked = BASE_HTML.replace('action="/search"', 'action="https://phish.example/collect"')
    result = layer3_link_audit(page(), page(hijacked))
    assert _score(result) >= 0.5
    assert result["evidence"]["form_action"]["added_new_domains"]


def test_layer3_ignores_fragments_and_js_urls() -> None:
    noise = BASE_HTML.replace(
        "</body>", '<a href="#top">Top</a><a href="javascript:void(0)">x</a></body>'
    )
    assert _score(layer3_link_audit(page(), page(noise))) == 0.0


def test_layer3_relative_urls_resolved_against_final_url() -> None:
    moved = page(BASE_HTML, final_url="https://mirror.acme.com/")
    result = layer3_link_audit(page(), moved)
    # Same relative refs resolve to a different host -> added refs, but the
    # page host itself is known -> not "new external domains".
    assert result["evidence"]["a_href"]["added_count"] >= 1
    assert not result["evidence"]["a_href"]["added_new_domains"]


# --- layer 4: visual diff ---


def test_layer4_identical_screenshots() -> None:
    shot = _png_bytes((250, 250, 250))
    result = layer4_visual_diff(page(screenshot=shot), page(screenshot=shot))
    assert _score(result) < 0.02
    assert result["evidence"]["ssim"] > 0.99


def test_layer4_completely_different_screenshots() -> None:
    result = layer4_visual_diff(
        page(screenshot=_png_bytes((255, 255, 255))),
        page(screenshot=_png_bytes((0, 0, 0))),
    )
    assert _score(result) > 0.5
    assert result["evidence"]["ssim"] < 0.5


def test_layer4_missing_screenshot_degrades() -> None:
    result = layer4_visual_diff(page(screenshot=b""), page(screenshot=_png_bytes((0, 0, 0))))
    assert _score(result) == 0.0
    assert result["evidence"]["baseline_screenshot_ok"] is False


def test_layer4_corrupt_png_degrades() -> None:
    result = layer4_visual_diff(
        page(screenshot=b"not a png at all"), page(screenshot=_png_bytes((0, 0, 0)))
    )
    assert _score(result) == 0.0
    assert "note" in result["evidence"]


def test_layer4_different_heights_compared() -> None:
    short = _png_bytes((250, 250, 250), size=(320, 480))
    tall = _png_bytes((250, 250, 250), size=(320, 960))
    result = layer4_visual_diff(page(screenshot=short), page(screenshot=tall))
    # Same content, page grew — white padding keeps the score low.
    assert _score(result) < 0.3


# --- layer 5: signatures ---


def test_layer5_clean_page_scores_zero() -> None:
    assert _score(layer5_signatures(page(), page())) == 0.0


def test_layer5_hacked_by_scores_max() -> None:
    defaced = BASE_HTML.replace("<h1>Welcome to Acme</h1>", "<h1>HACKED BY XYZ CREW</h1>")
    result = layer5_signatures(page(), page(defaced))
    assert _score(result) == 1.0
    assert any("hacked" in m["matched"].lower() for m in result["evidence"]["signature_matches"])


def test_layer5_leetspeak_variant_detected() -> None:
    defaced = BASE_HTML.replace("</body>", "<p>y0u g0t h4ck3d lol</p></body>")
    result = layer5_signatures(page(), page(defaced))
    assert _score(result) >= 0.5


def test_layer5_baseline_content_never_flags() -> None:
    """A security blog whose baseline already says 'hacked by' must not
    flag on an unchanged rescan (new-text-only matching)."""
    blog = BASE_HTML.replace(
        "</body>", "<article>Analysis: the site was defaced by attackers…</article></body>"
    )
    assert _score(layer5_signatures(page(blog), page(blog))) == 0.0


def test_layer5_script_flip_detected() -> None:
    arabic = (
        BASE_HTML.replace("<h1>Welcome to Acme</h1>", "<h1>تم الاختراق بواسطة فريق الأمن</h1>")
        .replace(
            "<p>We build reliable widgets for industry.</p>",
            "<p>هذا الموقع تحت السيطرة الكاملة الآن وسيتم استعادته قريبا</p>",
        )
        .replace('<a href="/about">About</a> <a href="/contact">Contact</a>', "")
    )
    result = layer5_signatures(page(), page(arabic))
    assert result["evidence"]["script_flip"] is True
    assert _score(result) >= 0.7


def test_layer5_profanity_burst() -> None:
    rude = BASE_HTML.replace("</body>", "<p>fuck this shit company</p></body>")
    result = layer5_signatures(page(), page(rude))
    assert _score(result) >= 0.4
    assert len(result["evidence"]["profanity_matches"]) == 2


def test_layer5_handles_undecodable_content() -> None:
    weird = "<html><body>\udcff\udcfe mixed \x00 bytes</body></html>"
    result = layer5_signatures(page(), page(weird))
    assert 0.0 <= result["score"] <= 1.0  # no crash


def test_extract_visible_text_strips_script_style() -> None:
    text = extract_visible_text(
        "<html><body><p>visible</p><script>var hidden=1;</script><style>.x{}</style></body></html>"
    )
    assert "visible" in text
    assert "hidden" not in text


def test_script_profile_latin() -> None:
    profile = script_profile("Hello world this is a Latin page")
    assert profile["LATIN"] > 0.9


def test_script_profile_empty() -> None:
    assert script_profile("12345 !!! ...") == {}
