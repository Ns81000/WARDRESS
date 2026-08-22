"""End-to-end flagging coverage for realistic attacks — closes the audit
finding "Zero end-to-end flagging coverage for realistic attacks" (plan
phase 12, run after the Phases 6-10 detection/fusion fixes landed).

What was missing before this module (audit phase 11): the only task-body
flagged-verdict test used a multi-signal screamer; every realistic
single-vector class from the audit's measured table had no end-to-end
verdict coverage; the escalation band gate was monkeypatched out of
existence in the integration suite (fixed in place in
test_phase4_scan_integration.py this phase); and layer 8's primary
signal — embedding drift — never executed in any shipped test because
embed_text was mocked to None suite-wide.

This module drives the REAL _run_scan body over crafted HTML/screenshots
and asserts verdicts, alerts, and persisted per-layer evidence. Two
seams stay hermetic without hiding behavior:
- embeddings: a deterministic bag-of-signed-hashes stub returning REAL
  vectors (the audit's own suggested direction), so the cosine/drift
  math actually executes — unlike the None mock, which stays the default
  in the other suites because CI has no model cache;
- LLM transport: only where the test's subject is the band gate itself
  (the unconfigured-provider degradation path runs fully unmocked).

Scenario risk values quoted in comments were measured against the
deployed system immediately before being pinned.
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
from worker import scan_tasks
from worker.detection.semantics import cosine_similarity
from worker.detection.types import UAVariant
from worker.fetcher import FetchResult
from worker.hashing import content_sha256
from worker.llm_escalation import ESCALATION_HIGH, ESCALATION_LOW
from worker.probe import ProbeResult

BASELINE_HTML = (
    "<html><body><h1>Corporate homepage</h1>"
    "<p>Welcome to our site. Reliable services for your business every day.</p></body></html>"
)

# Scenario corpora measured before being pinned here.
REWRITE_TEXT = (
    "Hacked crew owns this server database dumped leaked credentials "
    "contact telegram channel pay the price no one is safe"
)
ARABIC_REWRITE_HTML = (
    "<html><body><p>تم اختراق هذا الموقع من قبل فريق القراصنة "
    "تواصلوا معنا عبر تليجرام</p></body></html>"
)


# --- hermetic REAL-vector embedding stub -----------------------------------------


_EMBED_DIM = 64


def _stub_embedding(text: str) -> list[float]:
    """Deterministic signed bag-of-hashes over ASCII word tokens. Unlike
    the suite-wide ``embed_text -> None`` mock this returns actual numeric
    vectors, so layer 8's cosine/drift branch executes end to end without
    downloading MiniLM. Token-free input yields the zero vector, which
    cosine_similarity treats as its documented degenerate case."""
    vec = [0.0] * _EMBED_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % _EMBED_DIM
        vec[idx] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def test_stub_embedding_contract():
    """The stub itself must behave like an embedder: identical text -> cos
    1.0, unrelated texts -> small |cos|, token-free text -> degenerate
    None (the layer's degrade path)."""
    a = _stub_embedding("alpha beta gamma delta epsilon")
    same = _stub_embedding("alpha beta gamma delta epsilon")
    assert cosine_similarity(a, same) == pytest.approx(1.0, abs=1e-9)
    unrelated = _stub_embedding("zeta eta theta iota kappa lambda")
    assert abs(cosine_similarity(a, unrelated)) <= 0.4
    assert cosine_similarity(a, _stub_embedding("تم اختراق")) is None


# --- task-body wiring (same seams as the other suites, but real vectors) ----------


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
        return ProbeResult()

    from worker.detection import semantics

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(scan_tasks, "store_artifacts", fake_store)
    monkeypatch.setattr(scan_tasks, "read_artifact_text", fake_read_text)
    monkeypatch.setattr(scan_tasks, "read_artifact_bytes", fake_read_bytes)
    monkeypatch.setattr(scan_tasks, "probe_site", fake_probe)
    # THE difference vs the other suites: real vectors, not None.
    monkeypatch.setattr(semantics, "embed_text", _stub_embedding)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send_task(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send_task)
    return calls


def _fetch_of(html: str, screenshot: bytes = b"\x89PNG-fake"):
    async def fake_fetch(url, *, allow_private_networks=False):
        return FetchResult(
            html=html,
            screenshot=screenshot,
            final_url="https://example.com/",
            http_status=200,
            headers={"content-type": "text/html"},
        )

    return fake_fetch


def _probe_with_variants(*variants: UAVariant):
    async def fake_probe(url, *, allow_private_networks=False):
        return ProbeResult(ua_variants=list(variants))

    return fake_probe


def _variant(ua_key: str, html: str) -> UAVariant:
    return UAVariant(ua_key=ua_key, html=html, http_status=200, content_hash=content_sha256(html))


async def _seed_ready_site(
    db_factory,
    tmp_path,
    *,
    flag_threshold: float = 0.5,
    baseline_html: str = BASELINE_HTML,
    screenshot: bytes = b"\x89PNG-fake",
):
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com", flag_threshold=flag_threshold)
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
    async with db_factory() as db:
        b = await db.get(Baseline, baseline.id)
        b.html_path = f"baselines/{baseline.id}/page.html"
        b.screenshot_path = f"baselines/{baseline.id}/screenshot.png"
        await db.commit()
    return site, baseline, scan


async def _finding(db_factory, scan_id, layer_key: str) -> ScanFinding:
    async with db_factory() as db:
        return await db.scalar(
            select(ScanFinding).where(
                ScanFinding.scan_id == scan_id, ScanFinding.layer_key == layer_key
            )
        )


async def _alert(db_factory, scan_id) -> Alert | None:
    async with db_factory() as db:
        return await db.scalar(select(Alert).where(Alert.scan_id == scan_id))


# --- single-vector attacks flag end to end ----------------------------------------


async def test_single_vector_new_script_domain_flags_end_to_end(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Audit Finding 4.2's row 'One injected <script> from a NEW domain'
    fused to 0.096 under the shipped seed fit — silent 'changed'. Under
    the fixed system it flags through the full task body."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    cur = BASELINE_HTML.replace(
        "</body>", "<script src='https://evil.example.net/x.js'></script></body>"
    )
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    alert = await _alert(db_factory, scan.id)
    assert alert is not None
    assert alert.risk_score is not None and 0.55 <= alert.risk_score <= 0.70  # measured 0.6335
    assert ("wardress.deliver_alert", [str(alert.id)]) in enqueued


async def test_hidden_spam_link_farm_flags_end_to_end(db_factory, monkeypatch, enqueued, tmp_path):
    """Audit Finding 4.2's hidden-spam class (inline display:none), which
    fused to ~0.004 pre-fix: thirty hidden links on fresh domains now
    flag through the task body (measured 0.7926)."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    links = "".join(f'<a href="https://spam{i}.example.net/l">deal</a>' for i in range(30))
    cur = BASELINE_HTML.replace("</body>", f'<div style="display:none">{links}</div></body>')
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score >= 0.7
    assert ("wardress.deliver_alert", [str(alert.id)]) in enqueued


async def test_conclusive_signature_flags_via_rule_floor(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Strong-tier signature text is 'essentially conclusive on its own'
    (layer 5's contract): the Phase 7 floor must make it uncancellable
    end to end, with the rule recorded in the persisted fusion evidence."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    cur = BASELINE_HTML.replace("</body>", "<h1>HACKED BY CYBER WARRIORS CREW</h1></body>")
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score >= ESCALATION_HIGH  # measured 1.0; floor 0.90
    fusion_row = await _finding(db_factory, scan.id, "layer9_fusion")
    applied = [r["rule"] for r in fusion_row.evidence["rule_floor"]["applied"]]
    assert "conclusive_signature_text" in applied


async def test_severe_cloaking_flags_via_rule_floor(db_factory, monkeypatch, enqueued, tmp_path):
    """Crawlers served a different site: layer 7 divergence >= 0.85 must
    flag through the Phase 7 floor even when the primary fetch is
    byte-identical to the baseline (content layers hash-gated — the
    cloaking channel is independent of them by design, Phases 6+7)."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    spam_page = "<html><body><h1>Cheap pills casino</h1><p>spam spam spam links</p></body></html>"
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(BASELINE_HTML))
    monkeypatch.setattr(
        scan_tasks,
        "probe_site",
        _probe_with_variants(
            _variant("desktop_chrome", BASELINE_HTML),
            _variant("googlebot", spam_page),
        ),
    )

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score >= ESCALATION_HIGH  # measured ~1.0
    l2 = await _finding(db_factory, scan.id, "layer2_dom_structure")
    assert l2.skipped is True  # identical primary hash gates content layers...
    l7 = await _finding(db_factory, scan.id, "layer7_cloaking")
    assert l7.score >= 0.85  # ...while the crawler-facing divergence still decides
    fusion_row = await _finding(db_factory, scan.id, "layer9_fusion")
    applied = [r["rule"] for r in fusion_row.evidence["rule_floor"]["applied"]]
    assert "severe_cloaking" in applied


async def test_visual_asset_swap_flags_end_to_end(db_factory, monkeypatch, enqueued, tmp_path):
    """Audit Finding 4.1/4.2's asset-swap class through the task body: a
    server-side banner replacement under a trivially-wiggled DOM must
    produce a flagged verdict and a real alert (pre-fix it fused ~0.035)."""
    from PIL import Image, ImageDraw

    w, h = 683, 400

    def render(swaps=()):
        img = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([0, h - 40, w, h], fill=(235, 235, 235))
        for box, rgb in swaps:
            d.rectangle(box, fill=rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    _, baseline, scan = await _seed_ready_site(db_factory, tmp_path, screenshot=render())
    wiggle_html = BASELINE_HTML.replace(
        "<h1>Corporate homepage</h1>", "<h1>Corporate homepage</h1><!--x-->"
    )
    defaced_png = render([((0, 24, w, h // 2), (10, 10, 10))])
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(wiggle_html, screenshot=defaced_png))

    verdict = await scan_tasks._run_scan(scan.id)
    l4 = await _finding(db_factory, scan.id, "layer4_visual_diff")
    assert l4.score is not None and l4.score > 0.3  # fixture validity (Phase 10's bar)
    assert verdict == "flagged"
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score >= 0.5
    assert ("wardress.deliver_alert", [str(alert.id)]) in enqueued


# --- layer 8's drift signal executes with real vectors -----------------------------


async def test_semantic_rewrite_flags_with_real_vector_embeddings(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """The finding's 'embeddings mocked off suite-wide' gap: this is the
    first shipped test where layer 8 computes actual cosine similarity.
    A full meaning rewrite flags end to end via the drift channel."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    cur = f"<html><body><p>{REWRITE_TEXT}</p></body></html>"
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    l8 = await _finding(db_factory, scan.id, "layer8_semantics")
    similarity = l8.evidence["semantic_similarity"]
    assert isinstance(similarity, float) and similarity < 0.85  # measured -0.11
    assert l8.evidence["semantic_drift_score"] > 0.0  # measured 1.0
    alert = await _alert(db_factory, scan.id)
    assert alert is not None and alert.risk_score >= 0.5


async def test_identical_visible_text_zero_drift_control(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Control for the drift channel: flipped bytes but IDENTICAL visible
    text must measure similarity exactly 1.0 / drift exactly 0.0 and stay
    below both the escalation band and the material-change bar."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    cur = BASELINE_HTML.replace(
        "<h1>Corporate homepage</h1>", "<h1>Corporate homepage</h1><!--x-->"
    )
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "changed"
    l8 = await _finding(db_factory, scan.id, "layer8_semantics")
    assert l8.evidence["semantic_similarity"] == pytest.approx(1.0, abs=1e-9)
    assert l8.evidence["semantic_drift_score"] == 0.0
    row = await _alert(db_factory, scan.id)
    assert row is None
    async with db_factory() as db:
        s = await db.get(Scan, scan.id)
        assert s.risk_score < ESCALATION_LOW  # measured 0.2236


async def test_non_latin_rewrite_flags_via_script_flip_while_embeddings_degrade(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Token-free embedding input degrades to similarity=None without
    crashing (the documented degenerate path) while the Unicode script-
    flip channel still catches the takeover end to end."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(ARABIC_REWRITE_HTML))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    l8 = await _finding(db_factory, scan.id, "layer8_semantics")
    assert l8.evidence["semantic_similarity"] is None  # degraded, not crashed
    assert l8.evidence["semantic_drift_score"] == 0.0
    l5 = await _finding(db_factory, scan.id, "layer5_signatures")
    assert l5.evidence["script_flip"] is True  # measured l5=0.7, fused 0.9984


# --- named-expectation pins for honest residuals + band edges ----------------------


async def test_known_domain_lone_script_changed_and_escalation_eligible(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Audit Finding 4.2's row 'One injected <script>, already-known
    domain': pinned post-fix behavior — sub-threshold ('changed') but
    inside the escalation band, so the semantic second opinion is
    eligible. The LLM transport runs FULLY UNMOCKED against an empty AI
    config: escalate_scan must degrade to 'not configured' and record it
    in layer 8's persisted evidence without touching the verdict."""
    known = '<script src="https://cdn.example-site.com/lib.js"></script>'
    tracker = "<script src='https://cdn.example-site.com/tracker.js'></script>"
    base_html = BASELINE_HTML.replace("</body>", f"{known}</body>")
    _, _, scan = await _seed_ready_site(db_factory, tmp_path, baseline_html=base_html)
    cur = base_html.replace("</body>", f"{tracker}</body>")
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    assert await scan_tasks._run_scan(scan.id) == "changed"  # measured 0.4174
    async with db_factory() as db:
        s = await db.get(Scan, scan.id)
        assert ESCALATION_LOW <= s.risk_score < ESCALATION_HIGH  # escalation-eligible
        assert s.risk_score < 0.5
    l8 = await _finding(db_factory, scan.id, "layer8_semantics")
    assert l8.evidence["escalation"]["status"] == "not configured"
    assert await _alert(db_factory, scan.id) is None
    assert enqueued == []


async def test_benign_dynamic_noise_stays_below_material_bar(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """A rotating counter flips the hash but must stay below BOTH the
    material-change cadence bar and the escalation band's lower edge —
    through the REAL should_escalate (no patch): escalation is never
    consulted, no alert fires, nothing is enqueued."""
    _, _, scan = await _seed_ready_site(db_factory, tmp_path)
    cur = BASELINE_HTML.replace("</body>", "<p>Visitor #42</p></body>")
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_of(cur))

    async def must_not_run(db, **kwargs):
        pytest.fail("escalation consulted for sub-band benign noise")

    monkeypatch.setattr(scan_tasks, "escalate_scan", must_not_run)

    assert await scan_tasks._run_scan(scan.id) == "changed"
    async with db_factory() as db:
        s = await db.get(Scan, scan.id)
        assert s.risk_score < MATERIAL_CHANGE_RISK  # measured 0.2901 vs bar 0.35
    assert await _alert(db_factory, scan.id) is None
    assert enqueued == []
