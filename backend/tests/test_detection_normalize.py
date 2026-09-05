"""Automatic volatile-text normalization (PROMPT-002 Phase 8): unit tests
for worker/detection/normalize.py plus pipeline wiring tests proving the
pass feeds layers 2/3/5/8 on BOTH sides while layers 1/4/6/7 keep the raw
pages. Stored baselines are raw HTML — normalization happens at
comparison time on both sides, so the "backward compatible" claims below
are literally how the pipeline works.
"""

import re
import time

import pytest

from worker.detection import pipeline as pipeline_mod
from worker.detection.normalize import normalize_html, normalized_copy
from worker.detection.pipeline import run_detection
from worker.detection.types import PageData, ScanPageData
from worker.hashing import content_sha256

BASE_HTML = """<html><body>
<h1>Corporate Landing</h1>
<p>Report generated 2026-01-01T08:00:00Z.</p>
<p>Contact us any time.</p>
</body></html>"""

CURR_HTML = """<html><body>
<h1>Corporate Landing</h1>
<p>Report generated 2026-09-05T14:22:09.123+02:00.</p>
<p>Contact us any time.</p>
</body></html>"""


def _page(html: str, **kw) -> PageData:
    return PageData(html=html, content_hash=content_sha256(html), **kw)


def _scan_page(html: str, **kw) -> ScanPageData:
    return ScanPageData(html=html, content_hash=content_sha256(html), **kw)


# --- text-node patterns ---


def test_iso_datetime_variants_normalized() -> None:
    html, summary = normalize_html(
        "<p>2026-09-05T14:22:09Z 2026-09-05T14:22:09.123456+02:00 "
        "2026-09-05 14:22:09 2026-01-01T00:00:00Z</p>"
    )
    assert "2026-" not in html
    assert "14:22:09" not in html
    assert summary["iso_datetimes"] == 4
    assert "TIMESTAMP" in html


def test_iso_datetime_must_carry_time_component() -> None:
    # A date followed by non-time text is not a timestamp and must survive.
    html, summary = normalize_html("<p>2026-09-05Tel: 555-0100</p>")
    assert "2026-09-05" in html
    assert summary == {}


def test_date_only_normalized_with_plausible_ranges() -> None:
    html, summary = normalize_html("<p>Last updated 2026-09-05 thanks.</p>")
    assert "2026-09-05" not in html
    assert summary["iso_dates"] == 1


def test_implausible_dates_untouched() -> None:
    html, summary = normalize_html("<p>9999-99-99 2026-13-45 2026-00-01</p>")
    assert html == "<p>9999-99-99 2026-13-45 2026-00-01</p>"
    assert summary == {}


def test_uuids_normalized_both_cases() -> None:
    html, summary = normalize_html(
        "<p>id=550e8400-e29b-41d4-a716-446655440000 "
        "id=550E8400-E29B-41D4-A716-446655440000</p>"
    )
    assert "550e8400" not in html.lower()
    assert summary["uuids"] == 2


def test_uuid_lookalikes_untouched() -> None:
    html, summary = normalize_html(
        "<p>550e8400-e29b-41d4-a716-44665544000 (short) "
        "g550e8400-e29b-41d4-a716-446655440000 (glued)</p>"
    )
    assert summary.get("uuids", 0) == 0
    assert "550e8400" in html


def test_attack_evidence_around_volatile_tokens_survives() -> None:
    """The prime directive: injected words are never normalized — only the
    token itself is replaced, so signature/text evidence stays."""
    html, summary = normalize_html("<h1>HACKED BY XYZ — 2026-09-05T14:22:09Z — greetz to all</h1>")
    assert "HACKED BY XYZ" in html
    assert "greetz to all" in html
    assert "2026-09-05T14:22:09Z" not in html
    assert summary["iso_datetimes"] == 1


def test_script_and_style_text_untouched() -> None:
    html, summary = normalize_html(
        "<script>var t = new Date('2026-09-05T14:22:09Z');</script>"
        "<style>.ts::after{content:'2026-09-05'}</style>"
    )
    assert "2026-09-05T14:22:09Z" in html
    assert "2026-09-05" in html
    assert summary == {}


def test_code_block_text_is_normalized() -> None:
    """<pre>/<code> content is visible text; volatile tokens there
    (timestamps, UUIDs) are as volatile as anywhere else and can never be
    attack evidence by themselves. A bare URL in TEXT (not an attribute)
    is deliberately left alone: URL normalization is scoped to the
    attributes the link-audit layer actually reads."""
    html, summary = normalize_html(
        "<pre><code>curl example.com/?_=1735689600&at=2026-09-05T14:22:09Z</code></pre>"
    )
    assert "2026-09-05T14:22:09Z" not in html
    assert "1735689600" in html
    assert summary == {"iso_datetimes": 1}



# --- URL attributes (query only; path/domain/fragment preserved) ---


def test_cache_bust_query_values_normalized() -> None:
    html, summary = normalize_html(
        '<script src="/app.js?_=1735689600123"></script>'
        '<link href="/style.css?v=1699999999">'
    )
    assert "1735689600123" not in html
    assert "1699999999" not in html
    assert summary["cache_bust_query_values"] == 2


def test_meaningful_query_values_untouched() -> None:
    html, _ = normalize_html('<a href="/search?page=2&t=legal&v=3&redirect=https://evil.com/x?cb=1">')
    assert "/search?page=2&t=legal&v=3&redirect=https://evil.com/x?cb=1" in html


def test_uuid_query_value_normalized_any_param_path_uuid_untouched() -> None:
    html, summary = normalize_html(
        '<a href="/files/550e8400-e29b-41d4-a716-446655440000/download'
        '?request=9509db11-567f-4ae1-a3f2-7e19c07a49c1&x=1"></a>'
    )
    # Path keeps resource identity; the request-scoped query UUID is churn.
    assert "/files/550e8400-e29b-41d4-a716-446655440000/download" in html
    assert "9509db11" not in html
    assert summary["uuid_query_values"] == 1


def test_fragment_and_queryless_urls_untouched() -> None:
    html, summary = normalize_html('<a href="/docs#section-550e8400"></a><a href="/x"></a>')
    assert "/docs#section-550e8400" in html
    assert summary == {}


# --- token/nonce attribute values ---


def test_token_attribute_values_replaced() -> None:
    html, summary = normalize_html(
        '<script nonce="abc123">var x=1;</script>'
        '<input type="hidden" name="csrfmiddlewaretoken" value="tok7en123">'
        '<meta name="csrf-token" content="metatok999">'
        '<input type="email" name="email" value="a@b.c">'
    )
    assert "abc123" not in html
    assert "tok7en123" not in html
    assert "metatok" not in html
    assert 'value="a@b.c"' in html  # unrelated values untouched
    assert summary["token_attribute_values"] == 3


def test_style_attribute_never_touched() -> None:
    """Layer 2's hidden-element detection resolves inline styles; the pass
    must not perturb them (or anything outside the pinned token names)."""
    html, summary = normalize_html(
        '<div style="opacity:0">x</div><input name="csrf_token" value="v1">'
    )
    assert 'style="opacity:0"' in html
    assert summary["token_attribute_values"] == 1


# --- fail-open behavior and bounds ---


def test_empty_and_unparseable_fail_open() -> None:
    assert normalize_html("") == ("", {})
    assert normalize_html("   \n\t ") == ("   \n\t ", {})


def test_unparseable_fragment_returns_original(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker.detection import normalize as norm

    monkeypatch.setattr(norm, "parse_html", lambda text: None)
    html = "<p>x</p>"
    assert normalize_html(html) == (html, {})


def test_oversized_document_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker.detection import normalize as norm

    monkeypatch.setattr(norm, "_MAX_HTML_CHARS", 10)
    html = "<p>2026-09-05T14:22:09Z</p>"
    assert normalize_html(html) == (html, {})


def test_no_matches_returns_original_html() -> None:
    html = "<html><body><h1>Static page</h1></body></html>"
    out, summary = normalize_html(html)
    assert out == html
    assert summary == {}


def test_idempotence() -> None:
    once, _ = normalize_html(
        "<p>2026-09-05T14:22:09Z "
        "<a href='/x?v=1699999999&request=550e8400-e29b-41d4-a716-446655440000'>l</a>"
        "<input name='csrf_token' value='abc'></p>"
    )
    twice, summary2 = normalize_html(once)
    assert twice == once
    assert summary2 == {}


def test_summary_counts_and_merge() -> None:
    from worker.detection.normalize import merge_summaries

    html = "<p>2026-09-05 550e8400-e29b-41d4-a716-446655440000</p>"
    _, summary = normalize_html(html)
    assert summary == {"iso_dates": 1, "uuids": 1}
    assert merge_summaries({}, summary) == summary
    assert merge_summaries({"iso_dates": 2}, summary) == {"iso_dates": 3, "uuids": 1}


def test_normalized_copy_leaves_other_fields_alone() -> None:
    page = _page(BASE_HTML, final_url="https://acme.com/", headers={"x": "y"})
    copy, summary = normalized_copy(page)
    assert copy.html != page.html  # timestamp replaced
    assert copy.final_url == "https://acme.com/"
    assert copy.headers == {"x": "y"}
    assert copy.content_hash == page.content_hash  # raw digest untouched
    assert summary["iso_datetimes"] == 1


def test_adversarial_input_stays_linear() -> None:
    """Every pattern is linear (no nested quantifiers/ambiguous
    alternations), so even a ~1.7MB adversarial document must complete
    quickly — a generous wall-clock bound, not a micro-benchmark."""
    adversarial = ("9" * 4000 + "-" + "a" * 4000 + "<p>x</p>") * 125
    started = time.monotonic()
    _, summary = normalize_html(f"<p>{adversarial}</p>")
    elapsed = time.monotonic() - started
    assert summary == {}
    assert elapsed < 10.0


# --- pinned surface sanity ---


def test_pinned_pattern_lists_are_not_accidentally_empty() -> None:
    from worker.detection import normalize as norm

    for pattern in (
        norm._ISO_DATETIME_RE,
        norm._ISO_DATE_RE,
        norm._UUID_RE,
        norm._QUERY_PARAM_RE,
        norm._VOLATILE_VALUE_RE,
    ):
        assert isinstance(pattern, re.Pattern)
    assert len(norm._CACHE_BUST_PARAMS) >= 10
    assert len(norm._TOKEN_ATTRS) >= 10
    assert "style" not in norm._TOKEN_ATTRS
    assert "value" not in norm._TOKEN_ATTRS


# --- pipeline wiring ---


def test_timestamp_only_change_is_quiet_in_content_layers() -> None:
    """Backward-compat proof: the baseline is stored RAW (pre-Phase-8
    layout), the scan is fresh; comparison-time normalization on BOTH
    sides makes a timestamp-only delta silent in every content layer while
    layer 1 still reports the raw-byte change."""
    results = run_detection(
        _page(BASE_HTML, final_url="https://acme.com/"),
        _scan_page(CURR_HTML, final_url="https://acme.com/"),
    )
    assert results["layer1_hash"]["score"] == 1.0  # raw bytes DID change
    assert results["layer2_dom_structure"]["score"] == 0.0
    assert results["layer3_link_audit"]["score"] == 0.0
    assert results["layer5_signatures"]["score"] == 0.0
    assert results["layer8_semantics"]["evidence"]["aggression_hits"] == []
    assert results["layer2_dom_structure"]["evidence"]["normalization_applied"] == {
        "iso_datetimes": 2
    }


def test_cache_bust_only_change_is_quiet_in_layer3() -> None:
    base = '<html><body><script src="/app.js?_=1735689600123"></script></body></html>'
    curr = '<html><body><script src="/app.js?_=1735689600999"></script></body></html>'
    results = run_detection(
        _page(base, final_url="https://acme.com/"),
        _scan_page(curr, final_url="https://acme.com/"),
    )
    layer3 = results["layer3_link_audit"]
    assert layer3["evidence"]["total_added_refs"] == 0
    assert layer3["score"] == 0.0
    assert layer3["evidence"]["normalization_applied"] == {"cache_bust_query_values": 2}


def test_no_volatile_tokens_no_evidence_key() -> None:
    """Regression guard mirroring the suppression contract: the key is
    additive evidence, present only when the pass did something."""
    html = "<html><body><h1>Static page</h1></body></html>"
    results = run_detection(
        _page(html, final_url="https://acme.com/"),
        _scan_page(html.replace("Static", "Modified"), final_url="https://acme.com/"),
    )
    for key in (
        "layer2_dom_structure",
        "layer3_link_audit",
        "layer5_signatures",
        "layer8_semantics",
    ):
        assert "normalization_applied" not in results[key]["evidence"]


def test_injected_signatures_still_flag_despite_normalization() -> None:
    base = "<html><body><h1>Welcome</h1></body></html>"
    curr = "<html><body><h1>HACKED BY XYZ 2026-09-05T14:22:09Z</h1></body></html>"
    results = run_detection(
        _page(base, final_url="https://acme.com/"),
        _scan_page(curr, final_url="https://acme.com/"),
    )
    assert results["layer5_signatures"]["score"] >= 1.0
    matches = results["layer5_signatures"]["evidence"]["signature_matches"]
    assert matches and "HACKED BY" in matches[0]["matched"]


def test_user_suppression_regex_runs_before_normalization() -> None:
    """A user rule that targets the literal volatile text must still fire —
    proving suppression sees the RAW text (normalization runs after). The
    rule matches both sides' raw timestamps and strips them, so the pass
    then has nothing left to normalize."""
    from worker.detection.suppress import build_suppression

    results = run_detection(
        _page(BASE_HTML, final_url="https://acme.com/"),
        _scan_page(CURR_HTML, final_url="https://acme.com/"),
        suppression=build_suppression([("regex", r"generated \d{4}-\d{2}-\d{2}T\S+")]),
    )
    layer5 = results["layer5_signatures"]
    assert "suppression_applied" in layer5["evidence"]  # the raw-text rule fired
    assert "normalization_applied" not in layer5["evidence"]  # nothing left to normalize


def test_non_content_layers_receive_raw_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple[str, str]] = {}
    originals = {
        key: pipeline_mod._LAYER_FUNCS[key]
        for key in ("layer6_security_metadata", "layer7_cloaking")
    }

    def make_spy(name, fn):
        def spy(b, c):
            captured[name] = (b.html, c.html)
            return fn(b, c)

        return spy

    for key, fn in originals.items():
        monkeypatch.setitem(pipeline_mod._LAYER_FUNCS, key, make_spy(key, fn))
    run_detection(
        _page(BASE_HTML, final_url="https://acme.com/"),
        _scan_page(CURR_HTML, final_url="https://acme.com/"),
    )
    assert captured["layer6_security_metadata"] == (BASE_HTML, CURR_HTML)
    assert captured["layer7_cloaking"] == (BASE_HTML, CURR_HTML)


def test_baseline_html_missing_gates_before_normalization() -> None:
    baseline = _page("", final_url="https://acme.com/")
    baseline.content_hash = "0" * 64
    results = run_detection(
        baseline,
        _scan_page(CURR_HTML, final_url="https://acme.com/"),
    )
    assert results["layer2_dom_structure"]["skipped"] is True
    assert "artifact unavailable" in results["layer2_dom_structure"]["evidence"]["reason"]

