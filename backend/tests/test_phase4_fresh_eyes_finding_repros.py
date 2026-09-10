"""PROMPT-003 Audit Phase 4 — detection-side finding repros (characterization).

These tests document behaviors found by the Phase 4 fresh-eyes detection audit
(PROMPT-003-IMPLEMENTATION-LOG.md, Audit Phase 4 entry). They are NOT
regression gates: each asserts the CURRENT (finding) behavior so the
remediation prompt has a deterministic repro to flip after fixing. Each test
names its finding ID. Diagnosis only — no production code was changed.
"""

import pytest

from worker.detection.dom import layer2_dom_structure
from worker.detection.fusion import layer9_fusion
from worker.detection.metadata import layer6_security_metadata
from worker.detection.pipeline import run_detection
from worker.detection.signatures import _new_text, extract_visible_text, layer5_signatures
from worker.detection.semantics import layer8_semantics
from worker.detection.suppress import build_suppression, suppressed_copy
from worker.detection.types import PageData, ScanPageData
from worker.hashing import content_sha256

UNPUNCTUATED_BASE = (
    "<html><body><div id=nav>home products pricing contact fuck spammers</div>"
    "<div id=main>welcome to the acme corporation industrial solutions homepage "
    "today we ship quality worldwide</div></body></html>"
)


def _pair(base_html: str, current_html: str) -> tuple[PageData, ScanPageData]:
    b = PageData(
        html=base_html, final_url="https://acme.com/", content_hash=content_sha256(base_html)
    )
    c = ScanPageData(
        html=current_html, final_url="https://acme.com/",
        content_hash=content_sha256(current_html),
    )
    return b, c


class TestAUDIT4x1NewTextGranularity:
    """AUDIT-4-1: pages without sentence punctuation make _new_text return the
    WHOLE current page, so 'new-text-only' lexicons score baseline-present
    vocabulary (profanity / aggression words) on any benign edit."""

    def test_new_text_is_the_whole_page_when_unpunctuated(self) -> None:
        current = UNPUNCTUATED_BASE.replace("ship quality", "ship premium quality")
        b, c = _pair(UNPUNCTUATED_BASE, current)
        new = _new_text(extract_visible_text(UNPUNCTUATED_BASE), extract_visible_text(current))
        assert new == extract_visible_text(current)  # whole page reads as "new"
    def test_baseline_present_profanity_scores_on_benign_edit(self) -> None:
        current = UNPUNCTUATED_BASE.replace("ship quality", "ship premium quality")
        b, c = _pair(UNPUNCTUATED_BASE, current)
        r5 = layer5_signatures(b, c)
        assert r5["score"] == 0.25  # the word "fuck" was always in the baseline



    def test_baseline_present_aggression_scores_on_benign_edit(self) -> None:
        base = (
            "<html><body><p>markets rallied today as the central bank held rates steady "
            "analysts blamed corruption in the energy regime for price spikes "
            "war on inflation continues</p></body></html>"
        )
        current = base.replace("rallied today", "rallied sharply today")
        b, c = _pair(base, current)
        r8 = layer8_semantics(b, c)
        assert r8["evidence"]["aggression_hits"]  # all three words were in the baseline
        assert r8["score"] > 0.5

    def test_full_pipeline_flags_the_benign_edit(self) -> None:
        current = UNPUNCTUATED_BASE.replace("ship quality", "ship premium quality")
        b, c = _pair(UNPUNCTUATED_BASE, current)
        results = run_detection(b, c)
        # Default flag_threshold is 0.5: this benign edit is FLAGGED (alert +
        # remediation) at fused risk ~0.857.
        assert results["layer9_fusion"]["score"] > 0.5


class TestAUDIT4x2MetadataProbeTransient:
    """AUDIT-4-2/4-3: layer 6 reads capture-side transients as measured
    evidence-of-change instead of degrading, and scores a static expired cert
    on every scan."""

    def test_tls_probe_transient_scores_06_measured(self) -> None:
        b = PageData(
            html=UNPUNCTUATED_BASE, final_url="https://acme.com/",
            content_hash=content_sha256(UNPUNCTUATED_BASE),
            tls={"fingerprint_sha256": "a" * 64},
        )
        c = ScanPageData(
            html=UNPUNCTUATED_BASE, final_url="https://acme.com/",
            content_hash=content_sha256(UNPUNCTUATED_BASE), tls=None,
        )
        r6 = layer6_security_metadata(b, c)
        assert r6["score"] == 0.6
        assert not r6.get("degraded")  # measured evidence, not a dark channel

    def test_tls_transient_plus_byte_churn_enters_escalation_band(self) -> None:
        skip = {"score": None, "skipped": True, "evidence": {"reason": "gated"}}
        r6 = layer6_security_metadata(
            PageData(tls={"fingerprint_sha256": "a" * 64}),
            ScanPageData(tls=None),
        )
        results = {
            "layer1_hash": {"score": 1.0, "evidence": {}},
            "layer2_dom_structure": dict(skip),
            "layer3_link_audit": dict(skip),
            "layer4_visual_diff": {"score": 0.0, "evidence": {}},
            "layer5_signatures": dict(skip),
            "layer6_security_metadata": r6,
            "layer7_cloaking": {"score": 0.0, "evidence": {}},
            "layer8_semantics": dict(skip),
        }
        risk = layer9_fusion(results)["score"]
        assert risk >= 0.40  # LLM escalation band AND MATERIAL_CHANGE_RISK bar

    def test_permanently_expired_cert_scores_every_scan(self) -> None:
        tls = {"fingerprint_sha256": "a" * 64, "expired": True, "issuer": "X", "subject": "Y"}
        b, c = _pair(UNPUNCTUATED_BASE, UNPUNCTUATED_BASE)
        b.tls, c.tls = tls, dict(tls)  # identical, unchanged between scans
        r6 = layer6_security_metadata(b, c)
        assert r6["score"] >= 0.5  # a static property scored as change evidence


class TestAUDIT4x4SuppressionTimeoutAsymmetry:
    """AUDIT-4-4: a regex rule that times out mid-document is applied to a
    different element range on each side — the suppression itself manufactures
    the delta it was meant to silence."""

    LONG_A = "a" * 80  # (a|aa)+b backtracks past any timeout on this input
    PAT = r"(a|aa)+b|Session id: \d+"

    def test_partial_application_manufactures_delta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from worker.detection import suppress as suppress_mod

        monkeypatch.setattr(suppress_mod, "_REGEX_TIMEOUT_SECONDS", 0.3)
        base_html = f"<div><p>{self.LONG_A}</p><p>Session id: 12345 shared tail text</p></div>"
        cur_html = f"<div><p>Session id: 12345 shared tail text</p><p>{self.LONG_A}</p></div>"
        supp_b = build_suppression([("regex", self.PAT)])
        supp_c = build_suppression([("regex", self.PAT)])
        sb = suppressed_copy(PageData(html=base_html), supp_b)
        sc = suppressed_copy(PageData(html=cur_html), supp_c)
        # Baseline timed out before reaching the session-id node: it is kept.
        assert "Session id: 12345" in sb.html
        # Current applied the rule to the session-id node first: it is removed.
        assert "Session id: 12345" not in sc.html
        assert supp_c.unusable  # the timeout is recorded — but the delta was already made


class TestAUDIT4x5EmptyCurrentCapture:
    """AUDIT-4-5: layer 2 emits a MEASURED 1.0 when one side has no DOM, with
    no degraded-path symmetry to the pipeline's baseline_html_missing guard."""

    def test_one_side_unparseable_is_measured_1(self) -> None:
        b, _ = _pair(UNPUNCTUATED_BASE, UNPUNCTUATED_BASE)
        c = ScanPageData(html="", final_url="https://acme.com/", content_hash="0" * 64)
        r2 = layer2_dom_structure(b, c)
        assert r2["score"] == 1.0
        assert not r2.get("degraded") and not r2.get("skipped")


class TestAUDIT4x6Layer3RemovalBlind:
    """AUDIT-4-6: removal-only reference changes (e.g. an attacker stripping
    the page's scripts) score 0.0 — additions carry all the weight."""

    def test_all_scripts_removed_scores_zero(self) -> None:
        base = (
            '<html><body><script src="https://cdn.vendor.com/x.js"></script>'
            "<p>hello</p></body></html>"
        )
        b, c = _pair(base, "<html><body><p>hello</p></body></html>")
        results = run_detection(b, c)
        r3 = results["layer3_link_audit"]
        assert r3["score"] == 0.0
        assert r3["evidence"]["script_src"]["removed_count"] == 1  # seen, not scored
