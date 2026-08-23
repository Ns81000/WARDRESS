"""Phase 24 — degradation-signaling gap (audit finding: "Capture/probe
degradation is indistinguishable from 'no change' in the fused feature
vector").

Before this phase a lost screenshot artifact, a dead metadata probe, or a
crashed layer produced numerically identical downstream behavior to a
genuinely identical measurement: layer_result(0.0, note) for capture
failures, feature 0.0 for every skip, full intercept regardless of how
much evidence existed. This module pins the fix:

- capture/probe failures emit degraded_result (score None, skipped,
  degraded=True) — visually/cloaking/metadata/pipeline levels;
- fusion treats degraded channels as UNKNOWN: known contributions stay
  exact, the intercept shrinks proportionally to remaining evidence mass,
  and the uplift saturates at _UNMEASURED_RISK_CEIL so degradation lowers
  confidence without manufacturing alarms;
- structural gate skips (identical content hash) remain PROOFS of zero:
  full confidence mass, byte-identical arithmetic;
- the scan summary carries the degraded flag, powering the site-detail
  consecutive-degradation count and the fleet-wide health aggregate.
"""

import io
import math
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from app.scanning import MATERIAL_CHANGE_RISK
from worker.detection import pipeline as pipeline_mod
from worker.detection.cloaking import layer7_cloaking
from worker.detection.fusion import (
    _UNMEASURED_RISK_CEIL,
    FEATURE_KEYS,
    get_fusion_model,
    layer9_fusion,
)
from worker.detection.metadata import layer6_security_metadata
from worker.detection.pipeline import run_detection
from worker.detection.types import PageData, ScanPageData, UAVariant, layer_result
from worker.hashing import content_sha256
from worker.llm_escalation import ESCALATION_LOW

HTML = "<html><body><h1>Acme</h1><p>Reliable widgets.</p></body></html>"
W, H = 683, 400

TLS = {
    "fingerprint_sha256": "a" * 64,
    "not_after": "2027-01-01T00:00:00+00:00",
    "expired": False,
    "subject": "CN=acme.com",
    "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
}
HEADERS = {"content-security-policy": "default-src 'self'"}
ROBOTS = "User-agent: *\nDisallow:"


def _png(color=(250, 250, 250)) -> bytes:
    img = Image.new("RGB", (W, H), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _base(**kw) -> PageData:
    d = dict(html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML))
    d.update(kw)
    return PageData(**d)


def _cur(**kw) -> ScanPageData:
    d = dict(html=HTML, final_url="https://acme.com/", content_hash=content_sha256(HTML))
    d.update(kw)
    return ScanPageData(**d)


def _variant(ua_key: str, html: str) -> UAVariant:
    return UAVariant(ua_key=ua_key, html=html, http_status=200, content_hash=content_sha256(html))


def _healthy_pages(shot: bytes | None = None):
    """A fully-provisioned capture pair: TLS/headers/robots on both sides,
    usable UA variants, optional real screenshots."""
    shot = shot if shot is not None else _png()
    variants = [_variant(k, HTML) for k in ("desktop_chrome", "googlebot", "mobile_safari")]
    base_kwargs = dict(tls=dict(TLS), headers=dict(HEADERS), robots_txt=ROBOTS, screenshot=shot)
    return (
        _base(**base_kwargs),
        _cur(ua_variants=variants, **base_kwargs),
    )


# --- layer emission level ----------------------------------------------------------


def test_missing_screenshot_is_degraded_not_measured_zero() -> None:
    from worker.detection.visual import layer4_visual_diff

    result = layer4_visual_diff(_base(screenshot=b""), _cur(screenshot=_png((10, 10, 10))))
    assert result["score"] is None
    assert result["skipped"] is True
    assert result["degraded"] is True
    assert result["evidence"]["baseline_screenshot_ok"] is False


def test_corrupt_screenshot_is_degraded() -> None:
    from worker.detection.visual import layer4_visual_diff

    result = layer4_visual_diff(
        _base(screenshot=b"\x89PNG-fake"), _cur(screenshot=_png((10, 10, 10)))
    )
    assert result["score"] is None
    assert result["skipped"] is True
    assert result["degraded"] is True


def test_cloaking_probe_dead_is_degraded() -> None:
    result = layer7_cloaking(_base(), _cur())
    assert result["score"] is None
    assert result["skipped"] is True
    assert result["degraded"] is True


def test_cloaking_unusable_reference_is_degraded() -> None:
    dead_ref = UAVariant(ua_key="desktop_chrome", http_status=500)
    bot = _variant("googlebot", "<html><body>spam</body></html>")
    result = layer7_cloaking(_base(), _cur(ua_variants=[dead_ref, bot]))
    assert result["score"] is None
    assert result["skipped"] is True
    assert result["degraded"] is True
    assert "reference" in result["evidence"]["reason"]


def test_cloaking_bot_blocked_variants_stay_measured() -> None:
    """Target-side refusal (bot blocking) is an observation, not our
    measurement breaking: reference usable + rotated variants refused ->
    still a measured 0.0 (never degraded)."""
    blocked = UAVariant(ua_key="googlebot", html="", http_status=403, content_hash="")
    errored = UAVariant(ua_key="mobile_safari", error="ConnectTimeout")
    result = layer7_cloaking(
        _base(), _cur(ua_variants=[_variant("desktop_chrome", HTML), blocked, errored])
    )
    assert result["score"] == 0.0
    assert not result.get("degraded")
    assert result.get("skipped") is not True


def test_metadata_fully_dark_probe_is_degraded() -> None:
    result = layer6_security_metadata(_base(), _cur())
    assert result["score"] is None
    assert result["skipped"] is True
    assert result["degraded"] is True


def test_metadata_http_site_absent_tls_is_measured_zero() -> None:
    """A plain-HTTP site genuinely has no TLS: absent cert data on both
    http:// sides is the measured truth, not a broken probe."""
    b = _base(final_url="http://acme.com/", tls=None, headers=dict(HEADERS), robots_txt=ROBOTS)
    c = _cur(final_url="http://acme.com/", tls=None, headers=dict(HEADERS), robots_txt=ROBOTS)
    result = layer6_security_metadata(b, c)
    assert result["score"] == 0.0
    assert not result.get("degraded")


def test_metadata_partial_probe_still_measures() -> None:
    """TLS channel dark but headers comparable: partial measurement wins —
    the layer scores what it can see (existing contract)."""
    b = _base(tls=None, headers=dict(HEADERS), robots_txt=ROBOTS)
    c = _cur(tls=None, headers=dict(HEADERS), robots_txt=ROBOTS)
    result = layer6_security_metadata(b, c)
    assert result["score"] == 0.0
    assert not result.get("degraded")


def test_metadata_robots_signal_rescues_a_dark_probe() -> None:
    """A real robots.txt change carries signal even when TLS and headers
    could not be captured — the layer must not degrade away real
    evidence."""
    b = _base(tls=None, headers={}, robots_txt="User-agent: *")
    c = _cur(tls=None, headers={}, robots_txt="User-agent: *\nDisallow: /private")
    result = layer6_security_metadata(b, c)
    assert result["score"] is not None and result["score"] > 0.0
    assert not result.get("degraded")


# --- fusion arithmetic -------------------------------------------------------------


def _model():
    return get_fusion_model()


def test_full_evidence_math_unchanged() -> None:
    """With nothing unmeasured, fusion is byte-identical to the deployed
    formula: sigmoid(fsum(coef*x) + intercept)."""
    model = _model()
    xs = {"layer1_hash": 1.0, "layer3_link_audit": 0.4, "layer8_semantics": 0.2}
    results = {k: {"score": xs.get(k, 0.0), "evidence": {}} for k in FEATURE_KEYS}
    out = layer9_fusion(results)
    z = math.fsum(c * xs.get(k, 0.0) for k, c in zip(FEATURE_KEYS, model.coefficients, strict=True))
    expected = 1.0 / (1.0 + math.exp(-(z + model.intercept)))
    assert out["score"] == pytest.approx(expected, abs=1e-9)
    assert out["evidence"].get("unmeasured") is None
    assert out["evidence"]["confidence_mass"] == pytest.approx(1.0)


def test_gate_skips_are_proofs_with_full_confidence() -> None:
    """An identical-DOM rescan with a fully healthy capture: DOM layers are
    gate-skipped as PROOFS of zero — no unmeasured keys, confidence mass
    exactly 1.0, and the historical fused value for this shape."""
    base, cur = _healthy_pages()
    results = run_detection(base, cur)
    assert results["layer1_hash"]["score"] == 0.0
    for key in (
        "layer2_dom_structure",
        "layer3_link_audit",
        "layer5_signatures",
        "layer8_semantics",
    ):
        assert results[key]["skipped"] is True
        assert not results[key].get("degraded")
    fusion = results["layer9_fusion"]
    assert fusion["evidence"].get("unmeasured", []) == []
    assert fusion["evidence"]["confidence_mass"] == pytest.approx(1.0)
    # Historical quiet-rescan reading under full evidence.
    assert fusion["score"] == pytest.approx(0.0927, abs=0.003)


def test_lost_screenshot_distinguishable_from_identical_pixels() -> None:
    """THE headline property: a rescan whose screenshots were lost must not
    produce the same fused risk as one whose pixels were measured
    identical — and its uplift stays inside the uncertainty ceiling."""
    shot = _png()
    base, cur = _healthy_pages(shot=shot)
    control = run_detection(base, cur)["layer9_fusion"]["score"]

    base_d, cur_d = _healthy_pages(shot=shot)
    base_d.screenshot = b""
    cur_d.screenshot = b""
    degraded = run_detection(base_d, cur_d)

    l4 = degraded["layer4_visual_diff"]
    assert l4["degraded"] is True
    fusion = degraded["layer9_fusion"]
    assert fusion["score"] > control, "a dark visual channel must read differently"
    assert fusion["score"] <= max(control, _UNMEASURED_RISK_CEIL) + 1e-9
    assert fusion["evidence"]["unmeasured"] == ["layer4_visual_diff"]
    assert 0.0 < fusion["evidence"]["confidence_mass"] < 1.0


def test_catastrophic_blinding_capped_below_alarm_bars() -> None:
    """Every channel dark except the hash: the uncertainty adjustment
    saturates at the ceiling — never past the material-change bar /
    escalation floor, never into flag territory, whether the one visible
    channel reads clean or flipped."""
    dark = {
        k: {"score": None, "skipped": True, "degraded": True, "evidence": {"reason": "dark"}}
        for k in FEATURE_KEYS
        if k != "layer1_hash"
    }
    for hash_score in (0.0, 1.0):
        results = {**dark, "layer1_hash": {"score": hash_score, "evidence": {}}}
        out = layer9_fusion(results)
        assert out["score"] == pytest.approx(_UNMEASURED_RISK_CEIL)
        assert out["evidence"]["uncertainty_capped"] is True


def test_floors_bind_despite_partial_degradation() -> None:
    """Conclusive signature evidence keeps its uncancellable floor while
    other channels are dark — and degradation never LOWERS a high
    conservative reading (the cap is max(assume-zero, ceiling))."""
    results = {
        "layer1_hash": {"score": 1.0, "evidence": {}},
        "layer2_dom_structure": {"score": 0.0, "evidence": {}},
        "layer3_link_audit": {"score": 0.0, "evidence": {}},
        "layer4_visual_diff": {
            "score": None,
            "skipped": True,
            "degraded": True,
            "evidence": {"reason": "dark"},
        },
        "layer5_signatures": {"score": 1.0, "evidence": {}},
        "layer6_security_metadata": {"score": 0.0, "evidence": {}},
        "layer7_cloaking": {
            "score": None,
            "skipped": True,
            "degraded": True,
            "evidence": {"reason": "dark"},
        },
        "layer8_semantics": {"score": 0.0, "evidence": {}},
    }
    out = layer9_fusion(results)
    assert out["score"] >= 0.90  # conclusive_signature_text floor
    applied = [r["rule"] for r in out["evidence"]["rule_floor"]["applied"]]
    assert "conclusive_signature_text" in applied


def test_crash_isolated_layer_counts_as_unmeasured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crashed layer is a DARK channel, not a zero: fusion discounts its
    missing mass relative to the same scan with the layer measuring 0.0."""
    _stub_embeddings(monkeypatch)

    def exploding(baseline, current):
        raise RuntimeError("parser exploded")

    def measuring_zero(baseline, current):
        return layer_result(0.0, {})

    base, cur = _healthy_pages()
    changed = HTML.replace("Reliable widgets.", "Reliable widgets today.")
    cur = _cur(
        ua_variants=cur.ua_variants,
        **{k: getattr(cur, k) for k in ("tls", "headers", "robots_txt", "screenshot")},
        html=changed,
        content_hash=content_sha256(changed),
    )

    monkeypatch.setitem(pipeline_mod._LAYER_FUNCS, "layer3_link_audit", exploding)
    crashed = run_detection(base, cur)
    assert crashed["layer3_link_audit"]["degraded"] is True
    assert "layer3_link_audit" in crashed["layer9_fusion"]["evidence"]["unmeasured"]
    crashed_score = crashed["layer9_fusion"]["score"]

    monkeypatch.setitem(pipeline_mod._LAYER_FUNCS, "layer3_link_audit", measuring_zero)
    measured = run_detection(base, cur)
    assert not measured["layer3_link_audit"].get("skipped")
    assert crashed_score > measured["layer9_fusion"]["score"], (
        "an unmeasured channel must raise uncertainty relative to a measured zero"
    )
    assert crashed_score <= max(measured["layer9_fusion"]["score"], _UNMEASURED_RISK_CEIL) + 1e-9


def test_baseline_artifact_loss_marks_content_layers_degraded() -> None:
    baseline = _base(html="", content_hash="0" * 64)
    results = run_detection(baseline, _cur())
    l2 = results["layer2_dom_structure"]
    assert l2["skipped"] is True
    assert l2["degraded"] is True
    assert "artifact unavailable" in l2["evidence"]["reason"]


def _stub_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermeticity: changed-DOM pipeline tests would otherwise invoke the
    real MiniLM loader. The None stub is the suite's documented degraded
    mode; the drift channel contributes 0 either way for these scenarios."""
    from worker.detection import semantics

    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


def test_degraded_quiet_scan_stays_below_all_alarm_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Benign dynamic noise captured through broken sensors (corrupt
    screenshot, dead probe): uplifted versus full evidence, yet below the
    escalation floor and the material-change bar — capture failures must
    lower confidence, never manufacture alarms."""
    _stub_embeddings(monkeypatch)
    noisy = HTML.replace("</body>", "<p>Visitor #42</p></body>")
    b = _base(tls=None, headers={}, robots_txt=None, screenshot=b"broken")
    c = _cur(
        tls=None,
        headers={},
        robots_txt=None,
        screenshot=b"broken",
        html=noisy,
        content_hash=content_sha256(noisy),
    )
    results = run_detection(b, c)
    risk = results["layer9_fusion"]["score"]
    assert risk < ESCALATION_LOW
    assert risk < MATERIAL_CHANGE_RISK
    assert risk < 0.5


def test_uncertainty_ceiling_coherence_tripwire() -> None:
    """The ceiling only works while it sits under the alarm bars; if those
    constants move, revisit _UNMEASURED_RISK_CEIL deliberately."""
    assert _UNMEASURED_RISK_CEIL < MATERIAL_CHANGE_RISK
    assert MATERIAL_CHANGE_RISK <= ESCALATION_LOW


def test_model_artifact_binding_unchanged() -> None:
    """Guard: this phase touches consumption, not the fitted artifact."""
    model = _model()
    assert model.dataset_sha256  # provenance binding intact
    assert all(c >= 0.0 for c in model.coefficients)


# --- surfacing aggregates ----------------------------------------------------------


def test_summary_helper_records_degraded_flag() -> None:
    from worker.scan_tasks import _summarize_layer_scores

    results = {
        "layer1_hash": {"score": 0.0, "evidence": {}},
        "layer4_visual_diff": {
            "score": None,
            "skipped": True,
            "degraded": True,
            "evidence": {"reason": "r"},
        },
        "layer2_dom_structure": {
            "score": None,
            "skipped": True,
            "evidence": {"reason": "gated by layer 1"},
        },
    }
    summary = _summarize_layer_scores(results)
    assert summary["layer1_hash"] == {"score": 0.0, "skipped": False, "degraded": False}
    assert summary["layer4_visual_diff"] == {"score": None, "skipped": True, "degraded": True}
    assert summary["layer2_dom_structure"]["degraded"] is False


async def test_site_detail_consecutive_degraded_scans(client, auth_headers, db_factory):
    """The detail endpoint counts the leading run of degraded scans
    (newest first); a clean scan breaks the streak; sites without scans
    report 0."""
    import uuid

    from app.models import Baseline, BaselineStatus, Scan, ScanStatus, Site

    async with db_factory() as db:
        site = Site(name="Deg", url=f"https://deg-{uuid.uuid4().hex[:8]}.example")
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="c" * 64,
        )
        db.add(baseline)
        await db.flush()

        def mk(degraded: bool, minutes_ago: int) -> Scan:
            return Scan(
                site_id=site.id,
                baseline_id=baseline.id,
                status=ScanStatus.completed,
                verdict=None,
                layer_scores={
                    "layer4_visual_diff": (
                        {"score": None, "skipped": True, "degraded": True}
                        if degraded
                        else {"score": 0.0, "skipped": False, "degraded": False}
                    )
                },
                risk_score=0.1,
                created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            )

        db.add(mk(False, 30))  # oldest
        await db.flush()
        db.add(mk(True, 20))
        await db.flush()
        db.add(mk(True, 10))  # newest
        await db.commit()
        site_id = site.id

    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["consecutive_degraded_scans"] == 2

    # Break the streak with a fresh clean scan (newest by created_at).
    async with db_factory() as db:
        s = Scan(
            site_id=site_id,
            status=ScanStatus.completed,
            layer_scores={
                "layer4_visual_diff": {"score": 0.0, "skipped": False, "degraded": False}
            },
            risk_score=0.1,
            created_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        db.add(s)
        await db.commit()

    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.json()["consecutive_degraded_scans"] == 0


async def test_health_details_reports_sites_with_degraded_latest_scan(
    client, auth_headers, db_factory, monkeypatch
):
    """Fleet aggregate: only each site's LATEST completed scan in the
    window decides membership; older degraded scans do not count once the
    newest capture healed."""
    from app.models import Baseline, BaselineStatus, Scan, ScanStatus, Site
    from app.routers import health as health_router
    from app.schemas import HealthComponent

    monkeypatch.setattr(health_router, "_redis_component", lambda: HealthComponent(status="ok"))
    monkeypatch.setattr(
        health_router, "_worker_component", lambda: HealthComponent(status="ok", detail="w")
    )
    monkeypatch.setattr(health_router, "_queue_depth", lambda: 0)
    monkeypatch.setattr(health_router, "_dispatch_heartbeat", lambda: None)

    DEGRADED = {"layer4_visual_diff": {"score": None, "skipped": True, "degraded": True}}
    CLEAN = {"layer4_visual_diff": {"score": 0.0, "skipped": False, "degraded": False}}

    async with db_factory() as db:
        site_bad = Site(name="Bad", url="https://bad-h24.example")
        site_good = Site(name="Good", url="https://good-h24.example")
        db.add_all([site_bad, site_good])
        await db.flush()
        for site in (site_bad, site_good):
            bl = Baseline(
                site_id=site.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="d" * 64,
            )
            db.add(bl)
            await db.flush()

        now = datetime.now(UTC)

        def scan_for(site, scores, minutes_ago: int) -> Scan:
            return Scan(
                site_id=site.id,
                status=ScanStatus.completed,
                layer_scores=scores,
                created_at=now - timedelta(minutes=minutes_ago),
            )

        # bad: degraded older, degraded NEWEST -> counted
        db.add(scan_for(site_bad, DEGRADED, 30))
        await db.flush()
        db.add(scan_for(site_bad, DEGRADED, 10))
        # good: degraded older, clean NEWEST -> not counted
        db.add(scan_for(site_good, DEGRADED, 30))
        await db.flush()
        db.add(scan_for(site_good, CLEAN, 10))
        await db.commit()

    resp = await client.get("/api/health/details", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["sites_with_degraded_scans"] == 1
