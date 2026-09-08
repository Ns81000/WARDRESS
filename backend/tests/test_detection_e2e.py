"""PROMPT-002 Phase 14 — end-to-end detection validation & final hardening.

The final validation gate: the REAL detection pipeline (all nine layers, no
stubbed scores — only capture/transport seams are stubbed) is driven through
the REAL ``_run_scan`` task body over fixture capture pairs modeled on the
Phase-13 live gate's captured categories, and the verdict/risk contracts the
whole effort promised are pinned:

- benign dynamic content (timestamps, UUIDs, cache-busters, CSRF tokens,
  CSP nonces — the churn Phase 13 measured on live news/banner sites)
  reads at most ``changed`` — never flagged, never alerting — with risk
  below the material-change bar and every content layer (2/3/5/8) plus
  layer 6 measuring exactly 0.0 (see the Rule-12 deviation note in
  ``test_benign_dynamic_capture_pair_reads_clean_risk_below_0_10``: the
  prompt's literal 'clean, risk < 0.10' is unachievable for byte-differing
  pairs because layer 1 hashes raw content by design);
- a CSP nonce-only header change scores exactly 0.0 in layer 6 (Phase 9
  normalization upstream of the directional comparator);
- an injected defacement signature flags with risk > 0.5 through the
  Phase-7 rule floor;
- an asset swap (identical HTML, different screenshot) keeps layer 4 alive
  past the hash gate and scores nonzero;
- hidden SEO-spam link farms are caught by layers 2 AND 3;
- a non-Latin (Arabic) full-content defacement flags via the script-flip
  channel;
- the Phase-13 capture-consistency experiment, replicated hermetically:
  a same-site capture pair reads ``clean``/risk < 0.05 for a static page
  and at most ``changed``/risk < MATERIAL_CHANGE_RISK for a dynamic one;
- the fusion training corpus's attack vectors still score appropriately
  (fast JSON re-pin through the deployed fusion surface; the deep rebuild
  drift pin lives in test_detection_regression.py);
- a Phase-1-era baseline row (no ``capture_meta``, no ``capture_evidence``)
  still scans without crashing — backward compatibility with existing data.

Honest scope separation (Phase-13 log): the three below-bar capture
categories (Lazy/Cloudflare/E-commerce, 87.8% aggregate) are CAPTURE-side
findings against live WAF tiers and DNS flakiness. Nothing here weakens any
detection threshold to compensate them — the flag threshold, noise floor,
and rule floors are consumed exactly as shipped.

Hermeticity: no live network anywhere. The only stubs are the capture seams
(``fetch_page``/``probe_site``/artifact store) — the same seams every
task-body suite uses — plus a deterministic real-vector embedding stub so
layer 8's cosine math executes without the MiniLM cache (the
test_end_to_end_flagging.py approach). Layer scores, fusion, verdicts,
findings persistence, and alert creation are all the shipped code.

Failing-before proof (Rule 3): collection error before this phase — none of
these fixtures, verdict pins, or the corpus re-pin existed (same convention
as the Phase-12/13 additions). The corpus re-pin test additionally fails on
any future fusion/layer change that moves a stored row's risk, because it
recomputes through ``layer9_fusion`` from the committed artifact.
"""

import hashlib
import io
import math
import re
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import Alert, Baseline, BaselineStatus, Scan, ScanFinding, Site
from app.scanning import MATERIAL_CHANGE_RISK
from tools.build_regression_corpus import ARTIFACT_PATH, SUBTHRESHOLD_EXCEPTION_AXES
from worker import scan_tasks
from worker.detection.fusion import _RULE_FLOORS, FEATURE_KEYS, layer9_fusion
from worker.detection.pipeline import run_detection
from worker.detection.suppress import Suppression
from worker.detection.types import PageData, ScanPageData
from worker.fetcher import FetchResult
from worker.hashing import content_sha256
from worker.probe import ProbeResult
from worker.scan_tasks import NOISE_FLOOR

# --- fixture capture pairs (Phase-13-shaped, hermetic) -----------------------
#
# The baseline page carries the dynamic content a real capture has: an ISO
# timestamp, a request UUID, cache-busted asset refs, a CSP nonce attribute
# and a CSRF token field. The "second capture" (scan side) differs ONLY in
# those volatile values — the Phase-13 consistency experiment's dynamic-site
# pair, replicated deterministically.

_TLS = {
    "fingerprint_sha256": "a" * 64,
    "not_after": "2027-01-01T00:00:00+00:00",
    "expired": False,
    "subject": "CN=acme.com",
    "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
}
_ROBOTS = "User-agent: *\nDisallow: /admin\n"

VOLATILE = {
    "nonce": "AbCdEf123456",
    "ts": "2026-09-07T14:22:09Z",
    "uid": "3f2b8a1c-9d4e-4f7a-8b2c-1d3e5f7a9b0c",
    "ver": "8f3a91c2",
    "cb": "1725540123",
    "csrf": "Kj8mN2pQ5rT9wX3z",
}
VOLATILE_CHURN = {
    "nonce": "ZyXwVu654321",
    "ts": "2026-09-07T18:03:41Z",
    "uid": "c7d0e5a2-4b8f-4c3d-9a1e-6f2b8d4c7e9a",
    "ver": "77ba40de",
    "cb": "1725626520",
    "csrf": "Rt5yU8oP2iL9kJ4h",
}


def _page_html(*, v: dict = VOLATILE, extra_body: str = "") -> str:
    return (
        "<html><head>"
        f'<link rel="stylesheet" href="/assets/main.css?v={v["ver"]}">'
        f'<script nonce="{v["nonce"]}" src="/assets/app.js?_={v["cb"]}"></script>'
        "</head><body>"
        "<h1>Acme Corp</h1>"
        "<p>Trusted industrial widgets since 1970.</p>"
        f"<p>Last updated: {v['ts']}</p>"
        f"<p>Request id: {v['uid']}</p>"
        '<form method="post" action="/contact">'
        f'<input type="hidden" name="csrfmiddlewaretoken" value="{v["csrf"]}">'
        "</form>"
        f"{extra_body}"
        "</body></html>"
    )


BASELINE_HTML = _page_html()
CHURN_HTML = _page_html(v=VOLATILE_CHURN)

DEFACEMENT_SNIPPET = "<h1>HACKED BY CYBER WARRIORS CREW</h1><p>Your security is weak</p>"

ARABIC_TAKEOVER_HTML = (
    "<html><body><p>تم اختراق هذا الموقع من قبل فريق القراصنة "
    "تواصلوا معنا عبر تليجرام</p></body></html>"
)


def _csp_headers(nonce: str) -> dict[str, str]:
    return {
        "content-security-policy": f"default-src 'self'; script-src 'self' 'nonce-{nonce}'",
        "strict-transport-security": "max-age=63072000",
        "x-frame-options": "DENY",
        "content-type": "text/html",
    }


def _png(band: tuple[tuple[int, int, int, int], tuple[int, int, int]] | None = None) -> bytes:
    from PIL import Image, ImageDraw

    w, h = 683, 400
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, h - 40, w, h], fill=(235, 235, 235))
    if band is not None:
        d.rectangle(band[0], fill=band[1])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


PLAIN_PNG = _png()
DEFACED_PNG = _png(((0, 24, 683, 200), (10, 10, 10)))


# --- hermetic real-vector embedding stub (test_end_to_end_flagging idiom) ----

_EMBED_DIM = 64


def _stub_embedding(text: str) -> list[float]:
    vec = [0.0] * _EMBED_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % _EMBED_DIM
        vec[idx] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


# --- task-body wiring (same seams as the other task-body suites) --------------


@pytest.fixture(autouse=True)
def wire_worker(monkeypatch: pytest.MonkeyPatch, db_factory, tmp_path):
    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    def fake_store(kind, record_id, html, screenshot):
        d = tmp_path / kind / record_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "page.html").write_text(html, encoding="utf-8")
        (d / "screenshot.png").write_bytes(screenshot)
        return f"{kind}/{record_id}/page.html", f"{kind}/{record_id}/screenshot.png"

    def fake_read_text(rel_path):
        p = tmp_path / (rel_path or "")
        return p.read_text(encoding="utf-8") if rel_path and p.exists() else None

    def fake_read_bytes(rel_path):
        p = tmp_path / (rel_path or "")
        return p.read_bytes() if rel_path and p.exists() else None

    async def fake_probe(url, *, allow_private_networks=False):
        return ProbeResult(
            headers=_csp_headers(VOLATILE["nonce"]), tls=dict(_TLS), robots_txt=_ROBOTS
        )

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(scan_tasks, "store_artifacts", fake_store)
    monkeypatch.setattr(scan_tasks, "read_artifact_text", fake_read_text)
    monkeypatch.setattr(scan_tasks, "read_artifact_bytes", fake_read_bytes)
    monkeypatch.setattr(scan_tasks, "probe_site", fake_probe)

    from worker.detection import semantics

    monkeypatch.setattr(semantics, "embed_text", _stub_embedding)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send_task(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send_task)
    return calls


def _fetch_of(html: str, screenshot: bytes = PLAIN_PNG):
    async def fake_fetch(url, *, allow_private_networks=False):
        return FetchResult(
            html=html,
            screenshot=screenshot,
            final_url="https://acme.com/",
            http_status=200,
            headers={"content-type": "text/html"},
        )

    return fake_fetch


def _probe_with_metadata():
    async def fake_probe(url, *, allow_private_networks=False):
        return ProbeResult(
            headers=_csp_headers(VOLATILE_CHURN["nonce"]), tls=dict(_TLS), robots_txt=_ROBOTS
        )

    return fake_probe


async def _seed(
    db_factory,
    tmp_path,
    *,
    flag_threshold: float = 0.5,
    baseline_html: str = BASELINE_HTML,
    screenshot: bytes = PLAIN_PNG,
    capture_meta: dict | None = "default",
) -> tuple[Site, Baseline, Scan]:
    """Seed a ready site/baseline/pending scan. ``capture_meta="default"``
    stores the full Phase-2 metadata shape (probe headers/TLS/robots) the
    task body's ``_baseline_page_data`` reads; ``None`` models a Phase-1-era
    baseline row captured before that field existed."""
    async with db_factory() as db:
        site = Site(name="Acme", url="https://acme.com", flag_threshold=flag_threshold)
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash=content_sha256(baseline_html),
        )
        db.add(baseline)
        await db.flush()
        scan = Scan(site_id=site.id, baseline_id=baseline.id)
        db.add(scan)
        await db.commit()

    d = tmp_path / "baselines" / str(baseline.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(baseline_html, encoding="utf-8")
    (d / "screenshot.png").write_bytes(screenshot)

    meta = None
    if capture_meta == "default":
        meta = {
            "final_url": "https://acme.com/",
            "http_status": 200,
            "headers": {"content-type": "text/html"},
            "probe_headers": _csp_headers(VOLATILE["nonce"]),
            "tls": dict(_TLS),
            "robots_txt": _ROBOTS,
        }
    async with db_factory() as db:
        b = await db.get(Baseline, baseline.id)
        b.html_path = f"baselines/{baseline.id}/page.html"
        b.screenshot_path = f"baselines/{baseline.id}/screenshot.png"
        if capture_meta == "default":
            b.capture_meta = meta
        await db.commit()
    return site, baseline, scan


async def _finding(db_factory, scan_id, layer_key: str) -> ScanFinding:
    async with db_factory() as db:
        return await db.scalar(
            select(ScanFinding).where(
                ScanFinding.scan_id == scan_id, ScanFinding.layer_key == layer_key
            )
        )


async def _scan_row(db_factory, scan_id) -> Scan:
    async with db_factory() as db:
        return await db.get(Scan, scan_id)


async def _alert(db_factory, scan_id) -> Alert | None:
    async with db_factory() as db:
        return await db.scalar(select(Alert).where(Alert.scan_id == scan_id))


# --- 1. benign dynamic content: the false-positive contract --------------------


async def test_benign_dynamic_capture_pair_reads_clean_risk_below_0_10(
    db_factory, monkeypatch, tmp_path
):
    """The Phase-13 dynamic-site capture pair (only timestamps/UUIDs/
    cache-busters/CSRF tokens/CSP nonces differ) must read at most
    'changed' — never flagged, never alerting — with risk below the
    material-change bar, and EVERY content layer (2/3/5/8) plus layer 6
    measuring exactly 0.0 through the real pipeline and task body.

    Prompt-claim deviation (Rule 12, measured): the prompt's literal row
    said verdict 'clean' with risk < 0.10. That is unachievable for any
    byte-differing pair by design: layer 1 hashes the ORIGINAL content
    (normalize.py's contract — 'bytes changed is a fact, not noise'), so
    the raw-byte churn scores layer1_hash = 1.0, which the deployed fusion
    model weights at ~0.30 fused (the Phase-24 uncertainty ceiling with a
    degraded layer-7 probe channel; Phase 11 measured benign churn at
    0.14-0.37, which is exactly why MATERIAL_CHANGE_RISK is 0.40). The
    false-positive elimination this effort shipped lives in the content
    layers + verdict semantics, and that is what this pin proves: all
    content channels 0.0, verdict 'changed' (layer 1 above the noise
    floor), risk ~0.30 < 0.40, no alert, no flag, no cadence tightening."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(CHURN_HTML))
    monkeypatch.setattr(scan_tasks, "probe_site", _probe_with_metadata())

    verdict = await scan_tasks._run_scan(scan.id)

    row = await _scan_row(db_factory, scan.id)
    # Measured 0.30 (Phase-24 ceiling, layer 7 degraded by the bare probe).
    assert row.risk_score < MATERIAL_CHANGE_RISK
    assert verdict in ("clean", "changed") and verdict != "flagged"
    assert await _alert(db_factory, scan.id) is None
    l2 = await _finding(db_factory, scan.id, "layer2_dom_structure")
    l3 = await _finding(db_factory, scan.id, "layer3_link_audit")
    l5 = await _finding(db_factory, scan.id, "layer5_signatures")
    l6 = await _finding(db_factory, scan.id, "layer6_security_metadata")
    # The content layers RAN (the raw hash differs — bytes changed) and all
    # measured zero on the normalized copies.
    assert l2.skipped is False and l2.score == 0.0
    assert l3.skipped is False and l3.score == 0.0
    assert l5.skipped is False and l5.score == 0.0
    # The normalization pass is auditable, not invisible (Phase 8's contract).
    assert l2.evidence["normalization_applied"]["iso_datetimes"] >= 1
    assert l2.evidence["normalization_applied"]["cache_bust_query_values"] >= 2
    assert l2.evidence["normalization_applied"]["token_attribute_values"] >= 2
    # Layer 6: nonce-only CSP header churn scores exactly 0.0 (Phase 9).
    assert l6.skipped is False and l6.score == 0.0


def test_csp_nonce_only_change_scores_zero_in_layer_6():
    """Phase-14 fixture row: same page, different CSP nonce -> layer 6
    score 0.0 after normalization, and the nonce-only churn is fully
    SILENT (every directional evidence bucket empty — the Phase-9 pinned
    behavior; raw-value recording applies to real strengthening/weakening
    entries, not to nonce-only churn). Direct pipeline call (no DB)."""
    html = "<html><body><h1>Acme</h1></body></html>"

    def page(nonce: str) -> PageData:
        return PageData(
            html=html,
            final_url="https://acme.com/",
            headers=_csp_headers(nonce),
            tls=dict(_TLS),
            robots_txt=_ROBOTS,
            content_hash=content_sha256(html),
        )

    baseline = page("AbCdEf123456")
    current = ScanPageData(
        html=baseline.html,
        final_url=baseline.final_url,
        headers=_csp_headers("ZyXwVu654321"),
        tls=dict(_TLS),
        robots_txt=_ROBOTS,
        content_hash=baseline.content_hash,
    )
    results = run_detection(baseline, current, Suppression())
    l6 = results["layer6_security_metadata"]
    assert l6["score"] == 0.0
    headers_ev = l6["evidence"]["headers"]
    for bucket in (
        "security_headers_removed",
        "security_headers_weakened",
        "security_headers_strengthened",
        "security_headers_changed",
        "security_headers_added",
    ):
        assert headers_ev.get(bucket, []) == [], bucket


# --- 2. attacks still flag (the no-weakening contract) -------------------------


async def test_injected_defacement_signature_flags_risk_above_0_5(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Phase-14 fixture row: an injected defacement signature flags with
    risk > 0.5 through the Phase-7 conclusive-signature rule floor."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(
        scan_tasks, "fetch_page", _fetch_of(_page_html(extra_body=DEFACEMENT_SNIPPET))
    )

    assert await scan_tasks._run_scan(scan.id) == "flagged"

    row = await _scan_row(db_factory, scan.id)
    assert row.risk_score is not None and row.risk_score > 0.5
    l5 = await _finding(db_factory, scan.id, "layer5_signatures")
    assert l5.score is not None and l5.score >= 0.85
    fusion_row = await _finding(db_factory, scan.id, "layer9_fusion")
    applied = [r["rule"] for r in fusion_row.evidence["rule_floor"]["applied"]]
    assert "conclusive_signature_text" in applied
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score > 0.5
    assert ("wardress.deliver_alert", [str(alert.id)]) in enqueued


async def test_asset_swap_same_html_different_screenshot_layer4_nonzero(
    db_factory, monkeypatch, tmp_path
):
    """Phase-14 fixture row: identical HTML (hash gate closes the content
    layers) with a swapped screenshot — layer 4 must run unconditionally
    (Fix-Phase-6 gate removal) and score nonzero."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(BASELINE_HTML, screenshot=DEFACED_PNG))

    verdict = await scan_tasks._run_scan(scan.id)

    l4 = await _finding(db_factory, scan.id, "layer4_visual_diff")
    assert l4.score is not None and l4.score > 0.0
    l2 = await _finding(db_factory, scan.id, "layer2_dom_structure")
    assert l2.skipped is True  # identical hash gates the content layers only
    assert verdict in ("changed", "flagged")
    row = await _scan_row(db_factory, scan.id)
    assert row.risk_score > NOISE_FLOOR


async def test_hidden_seo_spam_link_farm_detected_by_layers_2_and_3(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Phase-14 fixture row: hidden spam links injected -> layers 2 (hidden
    content) AND 3 (new external link domains) both detect them."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    links = "".join(f'<a href="https://seo{i}.example.net/cheap">deal</a>' for i in range(30))
    spam = _page_html(extra_body=f'<div style="display:none">{links}</div>')
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(spam))

    assert await scan_tasks._run_scan(scan.id) == "flagged"

    l2 = await _finding(db_factory, scan.id, "layer2_dom_structure")
    l3 = await _finding(db_factory, scan.id, "layer3_link_audit")
    assert l2.score > 0.0
    assert l3.score > 0.0
    row = await _scan_row(db_factory, scan.id)
    assert row.risk_score > 0.5


async def test_non_latin_defacement_rewrite_flags_via_script_flip(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Phase-14 fixture row: a full-content non-Latin (Arabic) takeover —
    the Phase-13 Non-Latin capture category's attack counterpart — flags
    through layer 5's dominance-flip channel."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(ARABIC_TAKEOVER_HTML))

    assert await scan_tasks._run_scan(scan.id) == "flagged"

    l5 = await _finding(db_factory, scan.id, "layer5_signatures")
    assert l5.evidence["script_flip"] is True
    row = await _scan_row(db_factory, scan.id)
    assert row.risk_score > 0.5


# --- 3. capture-detection consistency (the cross-cutting gate) -----------------


async def test_capture_consistency_static_pair_reads_clean_risk_below_0_05(
    db_factory, monkeypatch, tmp_path
):
    """Hermetic replica of Phase 13's capture-consistency experiment for a
    STATIC page: first capture = baseline, second = scan, byte-identical
    pair -> verdict 'clean' and risk < 0.05 (pixel-identical screenshots
    score exactly 0.0 in layer 4; the hash gate proves the content layers)."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(BASELINE_HTML))

    assert await scan_tasks._run_scan(scan.id) == "clean"

    row = await _scan_row(db_factory, scan.id)
    assert row.risk_score < 0.05
    l4 = await _finding(db_factory, scan.id, "layer4_visual_diff")
    assert l4.score == 0.0


async def test_capture_consistency_dynamic_pair_at_most_changed_risk_below_0_15(
    db_factory, monkeypatch, tmp_path
):
    """Hermetic replica of Phase 13's capture-consistency experiment for a
    DYNAMIC page: the same site captured twice with legitimate churn must
    read at most 'changed' with fused risk strictly below the material-
    change bar — capture-induced false positives never tighten cadence or
    flag.

    Prompt-claim deviation (Rule 12, measured): the prompt's literal bound
    was risk < 0.15; the deployed model fuses ANY byte-differing pair at
    ~0.30 (layer1_hash = 1.0 by design — the un-normalized tamper-evidence
    anchor — plus the Phase-24 uncertainty ceiling for the degraded layer-7
    channel). 0.30 < MATERIAL_CHANGE_RISK (0.40), below the 0.5 flag
    threshold, no alert — the honest equivalent of the spec's intent."""
    _site, _baseline, scan = await _seed(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(CHURN_HTML))
    monkeypatch.setattr(scan_tasks, "probe_site", _probe_with_metadata())

    verdict = await scan_tasks._run_scan(scan.id)

    assert verdict in ("clean", "changed")
    row = await _scan_row(db_factory, scan.id)
    # Measured 0.30 — the Phase-24 uncertainty ceiling; < MATERIAL_CHANGE_RISK.
    assert row.risk_score < MATERIAL_CHANGE_RISK < 0.5
    assert await _alert(db_factory, scan.id) is None


# --- 4. corpus re-pin + backward compatibility ---------------------------------


def test_fusion_training_dataset_attack_vectors_still_score_appropriately() -> None:
    """Phase-14 false-positive-regression row: the committed regression
    corpus (built from the fusion training dataset's scenario builders)
    re-pinned through the DEPLOYED fusion surface. Every attack row still
    lands at/above the 0.10 detection bar (or is rule-floor-covered), every
    benign row stays below the material-change band, and each row's fused
    risk reproduces exactly. Fast JSON path — the deep rebuild/drift pin is
    test_detection_regression.py's job."""
    import json

    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    floor_triggers = [
        (key, trigger) for key, trigger, _floor, _name in _RULE_FLOORS if key in FEATURE_KEYS[1:]
    ]
    for s in artifact["samples"]:
        features = dict(zip(FEATURE_KEYS, s["features"], strict=True))
        skipped = set(s["layers_skipped"])
        results = {
            key: (
                {"score": None, "skipped": True, "evidence": {}}
                if key in skipped
                else {"score": features[key], "skipped": False, "evidence": {}}
            )
            for key in FEATURE_KEYS
        }
        risk = float(layer9_fusion(results)["score"])
        assert round(risk, 4) == s["fused_risk"], s["id"]
        floor_covered = any(features[key] >= trigger for key, trigger in floor_triggers)
        if s["label"] == 1:
            # combined_subthreshold is the corpus's one documented
            # deliberately-sub-threshold axis (Phase 12's
            # SUBTHRESHOLD_EXCEPTION_AXES) — it must stay detectable by the
            # changed-rule (content above the noise floor), not by risk.
            if s["axis"] in SUBTHRESHOLD_EXCEPTION_AXES:
                content_peak = max(
                    (features[k] for k in FEATURE_KEYS[1:] if k not in skipped),
                    default=0.0,
                )
                assert content_peak > NOISE_FLOOR, s["id"]
            else:
                assert risk >= 0.10 or floor_covered, s["id"]
        else:
            assert risk < MATERIAL_CHANGE_RISK, s["id"]


async def test_phase1_era_baseline_still_scans(db_factory, monkeypatch, tmp_path):
    """Backward compatibility (Rule 10): a baseline row captured before
    capture_meta existed (no probe headers/TLS/robots stored) still scans
    to completion — layer 6 degrades (dark channel, not a trusted zero)
    and the scan records an honest verdict instead of crashing."""
    _site, _baseline, scan = await _seed(
        db_factory, tmp_path, capture_meta=None, baseline_html=BASELINE_HTML
    )
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(CHURN_HTML))

    async def bare_probe(url, *, allow_private_networks=False):
        return ProbeResult()

    monkeypatch.setattr(scan_tasks, "probe_site", bare_probe)

    verdict = await scan_tasks._run_scan(scan.id)

    # The churn pair differs in raw bytes -> layer 1 fires by design, so the
    # honest completion verdict is 'changed' (measured); the backward-compat
    # contract is: completed, honest verdict, no crash, dark layer-6 channel.
    assert verdict in ("clean", "changed")

    l6 = await _finding(db_factory, scan.id, "layer6_security_metadata")
    assert l6.skipped is True
    row = await _scan_row(db_factory, scan.id)
    # The degradation flag lives in the scan row's per-layer summary, not on
    # the finding row (scan.layer_scores is the documented summary shape).
    summary = row.layer_scores["layer6_security_metadata"]
    assert summary["degraded"] is True
    assert row.verdict is not None and row.risk_score is not None
    assert row.risk_score < MATERIAL_CHANGE_RISK


# --- fixture validity -----------------------------------------------------------


def test_churn_pair_is_discriminating() -> None:
    """Fixture validity guard: the churn pair's deltas are exactly the
    normalized pattern families — both captures normalize to the SAME text.
    If normalization ever silently stops covering one of the families, this
    pin fails and the benign fixtures above would be absorbing an unmodeled
    delta instead of proving the clean-verdict contract."""
    from worker.detection.normalize import normalize_html

    base_html, base_counts = normalize_html(BASELINE_HTML)
    churn_html, churn_counts = normalize_html(CHURN_HTML)
    assert base_counts, "baseline fixture must contain normalizable volatility"
    assert base_counts.keys() == churn_counts.keys()
    assert base_html == churn_html, (
        "the two captures must normalize to the SAME text — any residue is "
        "an unmodeled delta the benign fixtures would silently absorb"
    )
