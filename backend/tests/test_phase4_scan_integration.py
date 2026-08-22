"""Phase 4 scan-pipeline integration: alert creation on flagged scans
and the LLM escalation hook. Same stubbing pattern as test_scan_tasks —
no network, no queue, in-memory DB."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import Alert, Baseline, BaselineStatus, Scan, ScanFinding, Site
from worker import scan_tasks
from worker.fetcher import FetchResult
from worker.hashing import content_sha256
from worker.probe import ProbeResult

BASELINE_HTML = "<html><body><h1>Corporate homepage</h1><p>Welcome to our site.</p></body></html>"
DEFACED_HTML = (
    "<html><body><h1>HACKED BY xTest</h1><p>gr33tz to the crew. We are legion. Expect us."
    "</p><script src='https://evil.example.net/x.js'></script></body></html>"
)


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
    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture Celery task enqueues instead of touching Redis."""
    calls: list = []

    def fake_send_task(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send_task)
    return calls


def _fetch(html: str):
    async def fake_fetch(url, *, allow_private_networks=False):
        return FetchResult(
            html=html,
            screenshot=b"\x89PNG-fake",
            final_url="https://example.com/",
            http_status=200,
            headers={"content-type": "text/html"},
        )

    return fake_fetch


async def _flaggable_scan(db_factory):
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com", flag_threshold=0.5)
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash=content_sha256(BASELINE_HTML),
        )
        db.add(baseline)
        await db.flush()
        # Store the baseline HTML artifact where fake_read_text finds it.
        scan = Scan(site_id=site.id, baseline_id=baseline.id)
        db.add(scan)
        await db.commit()
        return site, baseline, scan


async def _write_baseline_artifacts(tmp_path, baseline_id, html):
    d = tmp_path / "baselines" / str(baseline_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(html, encoding="utf-8")
    (d / "screenshot.png").write_bytes(b"\x89PNG-fake")


async def _set_baseline_paths(db_factory, baseline_id):
    async with db_factory() as db:
        b = await db.scalar(select(Baseline).where(Baseline.id == baseline_id))
        b.html_path = f"baselines/{baseline_id}/page.html"
        b.screenshot_path = f"baselines/{baseline_id}/screenshot.png"
        await db.commit()


async def test_flagged_scan_creates_alert_and_enqueues_delivery(
    db_factory, monkeypatch, tmp_path, enqueued
):
    site, baseline, scan = await _flaggable_scan(db_factory)
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch(DEFACED_HTML))

    assert await scan_tasks._run_scan(scan.id) == "flagged"

    async with db_factory() as db:
        alert = await db.scalar(select(Alert).where(Alert.scan_id == scan.id))
        assert alert is not None
        assert alert.site_id == site.id
        assert alert.risk_score is not None and alert.risk_score >= 0.5
    assert ("wardress.deliver_alert", [str(alert.id)]) in enqueued


async def test_clean_scan_creates_no_alert(db_factory, monkeypatch, tmp_path, enqueued):
    site, baseline, scan = await _flaggable_scan(db_factory)
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch(BASELINE_HTML))

    assert await scan_tasks._run_scan(scan.id) == "clean"
    async with db_factory() as db:
        assert await db.scalar(select(Alert)) is None
    assert enqueued == []


async def test_alert_enqueue_failure_never_fails_scan(db_factory, monkeypatch, tmp_path):
    """Redis down at alert time: the scan still completes flagged; the
    alert failure is logged and swallowed (rule 6)."""
    site, baseline, scan = await _flaggable_scan(db_factory)
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch(DEFACED_HTML))

    def broken_send_task(name, args=None, **kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", broken_send_task)
    assert await scan_tasks._run_scan(scan.id) == "flagged"
    async with db_factory() as db:
        row = await db.scalar(select(Scan).where(Scan.id == scan.id))
        assert row.verdict.value == "flagged"  # scan outcome unaffected


async def test_flagged_redelivery_does_not_duplicate_alert(
    db_factory, monkeypatch, tmp_path, enqueued
):
    """acks_late redelivery reruns the whole scan body; the unique
    scan_id alert row must be reused, not duplicated."""
    site, baseline, scan = await _flaggable_scan(db_factory)
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch(DEFACED_HTML))

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    # Simulate redelivery: reset the scan to running and run again.
    async with db_factory() as db:
        row = await db.scalar(select(Scan).where(Scan.id == scan.id))
        from app.models import ScanStatus

        row.status = ScanStatus.running
        await db.commit()
    assert await scan_tasks._run_scan(scan.id) == "flagged"
    async with db_factory() as db:
        alerts = (await db.scalars(select(Alert).where(Alert.scan_id == scan.id))).all()
        assert len(alerts) == 1


# --- escalation wiring ---

# A deterministic mid-band scenario: one injected script on a brand-new
# external domain. Under the deployed refit + rule floors this fuses to
# ~0.63 — inside [ESCALATION_LOW, ESCALATION_HIGH) but below a raised
# threshold — so the REAL should_escalate band gate engages (the old
# screamer fixture fuses ~1.0, above the band, which is exactly why these
# tests used to patch the gate out of existence; audit finding "Zero
# end-to-end flagging coverage for realistic attacks").
MIDBAND_HTML_SUFFIX = "<script src='https://midband.example.net/x.js'></script>"


def _fetch_midband():
    return _fetch(BASELINE_HTML.replace("</body>", MIDBAND_HTML_SUFFIX + "</body>"))


async def test_ambiguous_scan_runs_escalation_and_can_upgrade(
    db_factory, monkeypatch, tmp_path, enqueued
):
    """A changed scan whose fused risk lands in the ambiguous band consults
    the LLM through the unmocked should_escalate gate; a confident
    defacement classification upgrades the verdict to flagged and the
    outcome lands in layer 8's stored evidence."""
    from worker.llm_escalation import ESCALATION_HIGH, ESCALATION_LOW

    site, baseline, scan = await _flaggable_scan(db_factory)
    async with db_factory() as db:
        s = await db.scalar(select(Site).where(Site.id == site.id))
        s.flag_threshold = 1.0  # keep the local verdict below the threshold
        await db.commit()
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_midband())

    seen: dict = {}

    async def fake_escalate(db, *, site_url, risk, layer_scores, new_text):
        seen["risk"] = risk
        assert site_url == "https://example.com"
        assert layer_scores is not None and "layer9_fusion" in layer_scores
        return {
            "status": "ok",
            "provider": "gemini",
            "classification": "defacement",
            "confidence": 0.9,
            "rationale": "clear defacement phrasing",
        }

    monkeypatch.setattr(scan_tasks, "escalate_scan", fake_escalate)

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    # The real band gate decided to escalate: only in-band risks arrive.
    assert ESCALATION_LOW <= seen["risk"] < ESCALATION_HIGH
    async with db_factory() as db:
        finding = await db.scalar(
            select(ScanFinding).where(
                ScanFinding.scan_id == scan.id, ScanFinding.layer_key == "layer8_semantics"
            )
        )
        assert finding.evidence["escalation"]["classification"] == "defacement"
        alert = await db.scalar(select(Alert).where(Alert.scan_id == scan.id))
        assert alert is not None  # the upgrade produced a real alert


async def test_escalation_benign_does_not_upgrade(db_factory, monkeypatch, tmp_path, enqueued):
    """Same mid-band scenario through the real gate; a confident BENIGN
    classification must leave the local changed verdict standing."""
    site, baseline, scan = await _flaggable_scan(db_factory)
    async with db_factory() as db:
        s = await db.scalar(select(Site).where(Site.id == site.id))
        s.flag_threshold = 1.0
        await db.commit()
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch_midband())

    async def benign_escalate(db, **kwargs):
        return {"status": "ok", "provider": "gemini", "classification": "benign", "confidence": 1.0}

    monkeypatch.setattr(scan_tasks, "escalate_scan", benign_escalate)
    verdict = await scan_tasks._run_scan(scan.id)
    assert verdict == "changed"  # below the 1.0 threshold, not upgraded
    async with db_factory() as db:
        assert await db.scalar(select(Alert)) is None


async def test_escalation_failure_never_fails_scan(db_factory, monkeypatch, tmp_path, enqueued):
    """escalate_scan itself catches everything, but even a hypothetical
    escape must not take the scan down — the wrapper try in _run_scan's
    caller marks failure; here we assert the documented contract that a
    raising escalation is impossible via the module's own API."""
    from worker.llm_escalation import escalate_scan as real_escalate

    class ExplodingDB:
        def __getattr__(self, name):
            raise RuntimeError("db exploded")

    result = await real_escalate(
        ExplodingDB(), site_url="https://example.com", risk=0.5, layer_scores=None, new_text=""
    )
    assert result["status"].startswith(("failed", "unavailable", "not configured"))


async def test_flagged_scan_skips_escalation(db_factory, monkeypatch, tmp_path, enqueued):
    """Above-threshold scans never consult the LLM — it can only raise
    attention, and attention is already raised."""
    site, baseline, scan = await _flaggable_scan(db_factory)
    await _write_baseline_artifacts(tmp_path, baseline.id, BASELINE_HTML)
    await _set_baseline_paths(db_factory, baseline.id)
    monkeypatch.setattr(scan_tasks, "fetch_page", _fetch(DEFACED_HTML))

    async def must_not_run(db, **kwargs):
        pytest.fail("escalation ran for an already-flagged scan")

    monkeypatch.setattr(scan_tasks, "escalate_scan", must_not_run)
    assert await scan_tasks._run_scan(scan.id) == "flagged"
