"""Worker task-body tests: baseline capture and scan state machines.
The network fetch, metadata probe, and artifact store are stubbed — what's
under test is row state handling: success, fetch failure, missing
prerequisites, idempotence, and the never-stuck-in-flight guarantee.
Layer behavior is covered in test_detection_*; live queue/browser
behavior by the compose-stack verification."""

import uuid
from contextlib import asynccontextmanager

import pytest

from app.models import Baseline, BaselineStatus, Scan, ScanFinding, ScanStatus, Site
from worker import scan_tasks
from worker.fetcher import FetchError, FetchResult
from worker.hashing import content_sha256
from worker.probe import ProbeResult

HTML = "<html><body><h1>Welcome</h1></body></html>"


def _fetch_result(html: str = HTML) -> FetchResult:
    return FetchResult(
        html=html,
        screenshot=b"\x89PNG-fake",
        final_url="https://example.com/",
        http_status=200,
        headers={"content-type": "text/html"},
    )


@pytest.fixture(autouse=True)
def wire_worker(monkeypatch: pytest.MonkeyPatch, db_factory, tmp_path):
    """Point the task bodies at the test DB, a temp artifacts dir, an
    empty metadata probe, and embedding-free semantics."""

    @asynccontextmanager
    async def fake_task_session():
        async with db_factory() as session:
            yield session

    def fake_store(kind: str, record_id: str, html: str, screenshot: bytes):
        d = tmp_path / kind / record_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "page.html").write_text(html, encoding="utf-8")
        (d / "screenshot.png").write_bytes(screenshot)
        return f"{kind}/{record_id}/page.html", f"{kind}/{record_id}/screenshot.png"

    def fake_read_text(rel_path):
        if not rel_path:
            return None
        p = tmp_path / rel_path
        return p.read_text(encoding="utf-8") if p.exists() else None

    def fake_read_bytes(rel_path):
        if not rel_path:
            return None
        p = tmp_path / rel_path
        return p.read_bytes() if p.exists() else None

    async def fake_probe(url: str, *, allow_private_networks: bool = False) -> ProbeResult:
        return ProbeResult()

    from worker.detection import semantics

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(scan_tasks, "store_artifacts", fake_store)
    monkeypatch.setattr(scan_tasks, "read_artifact_text", fake_read_text)
    monkeypatch.setattr(scan_tasks, "read_artifact_bytes", fake_read_bytes)
    monkeypatch.setattr(scan_tasks, "probe_site", fake_probe)
    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


@pytest.fixture
def fetch_calls(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    async def fake_fetch(url: str, *, allow_private_networks: bool = False) -> FetchResult:
        calls.append(url)
        return _fetch_result()

    monkeypatch.setattr(scan_tasks, "fetch_page", fake_fetch)
    return calls


async def _make_site(db_factory, **overrides) -> Site:
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com/", **overrides)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _make_baseline(db_factory, site_id: uuid.UUID, **overrides) -> Baseline:
    async with db_factory() as db:
        baseline = Baseline(site_id=site_id, **overrides)
        db.add(baseline)
        await db.commit()
        await db.refresh(baseline)
        return baseline


async def _get(db_factory, model, row_id: uuid.UUID):
    async with db_factory() as db:
        return await db.get(model, row_id)


# --- baseline capture ---


async def test_capture_success(db_factory, fetch_calls) -> None:
    site = await _make_site(db_factory)
    baseline = await _make_baseline(db_factory, site.id)

    assert await scan_tasks._capture_baseline(baseline.id) == "ready"

    row = await _get(db_factory, Baseline, baseline.id)
    assert row.status is BaselineStatus.ready
    assert row.is_current is True
    assert row.content_hash == content_sha256(HTML)
    assert row.html_path and row.screenshot_path
    assert row.capture_meta["http_status"] == 200
    assert row.captured_at is not None
    assert row.error is None
    assert fetch_calls == ["https://example.com/"]


async def test_capture_demotes_previous_current(db_factory, fetch_calls) -> None:
    site = await _make_site(db_factory)
    old = await _make_baseline(
        db_factory, site.id, status=BaselineStatus.ready, is_current=True, content_hash="a" * 64
    )
    new = await _make_baseline(db_factory, site.id)

    assert await scan_tasks._capture_baseline(new.id) == "ready"

    assert (await _get(db_factory, Baseline, old.id)).is_current is False
    assert (await _get(db_factory, Baseline, new.id)).is_current is True


async def test_capture_fetch_failure_marks_failed(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_fetch(url: str, *, allow_private_networks: bool = False):
        raise FetchError("Fetch failed: site unreachable")

    monkeypatch.setattr(scan_tasks, "fetch_page", failing_fetch)
    site = await _make_site(db_factory)
    baseline = await _make_baseline(db_factory, site.id)

    assert await scan_tasks._capture_baseline(baseline.id) == "failed"

    row = await _get(db_factory, Baseline, baseline.id)
    assert row.status is BaselineStatus.failed
    assert "unreachable" in row.error
    assert row.is_current is False


async def test_capture_refuses_http_error_page(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """An error page (503, 404…) must never become the trusted baseline —
    it would make a later identical error page compare as 'clean'."""

    async def error_fetch(url: str, *, allow_private_networks: bool = False) -> FetchResult:
        result = _fetch_result("<html><h1>503 Service Temporarily Unavailable</h1></html>")
        result.http_status = 503
        return result

    monkeypatch.setattr(scan_tasks, "fetch_page", error_fetch)
    site = await _make_site(db_factory)
    baseline = await _make_baseline(db_factory, site.id)

    assert await scan_tasks._capture_baseline(baseline.id) == "failed"

    row = await _get(db_factory, Baseline, baseline.id)
    assert row.status is BaselineStatus.failed
    assert "503" in row.error
    assert row.is_current is False
    assert row.content_hash is None


async def test_scan_of_error_page_still_completes(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scans are observations, not trust anchors: fetching an error page
    during a scan completes normally (and flags the content change)."""

    async def error_fetch(url: str, *, allow_private_networks: bool = False) -> FetchResult:
        result = _fetch_result("<html><h1>503 Service Temporarily Unavailable</h1></html>")
        result.http_status = 503
        return result

    monkeypatch.setattr(scan_tasks, "fetch_page", error_fetch)
    site, baseline = await _ready_site_and_baseline(db_factory)
    scan = await _make_scan(db_factory, site.id, baseline.id)

    assert await scan_tasks._run_scan(scan.id) in ("changed", "flagged")
    row = await _get(db_factory, Scan, scan.id)
    assert row.status is ScanStatus.completed
    assert row.verdict.value in ("changed", "flagged")


async def test_capture_missing_row(db_factory, fetch_calls) -> None:
    assert await scan_tasks._capture_baseline(uuid.uuid4()) == "baseline-row-missing"
    assert fetch_calls == []


async def test_capture_already_done_is_idempotent(db_factory, fetch_calls) -> None:
    """acks_late redelivery after a crash re-runs the task; a finished
    baseline must not be re-captured or demoted."""
    site = await _make_site(db_factory)
    baseline = await _make_baseline(
        db_factory, site.id, status=BaselineStatus.ready, is_current=True, content_hash="a" * 64
    )
    assert await scan_tasks._capture_baseline(baseline.id) == "baseline-already-ready"
    assert fetch_calls == []


async def test_capture_site_deleted_before_start(db_factory, fetch_calls) -> None:
    site = await _make_site(db_factory)
    baseline = await _make_baseline(db_factory, site.id)
    async with db_factory() as db:
        await db.execute(Site.__table__.delete().where(Site.__table__.c.id == site.id))
        await db.commit()

    assert await scan_tasks._capture_baseline(baseline.id) == "site-missing"
    row = await _get(db_factory, Baseline, baseline.id)
    assert row.status is BaselineStatus.failed
    assert fetch_calls == []


# --- scans ---


async def _ready_site_and_baseline(db_factory, baseline_html: str = HTML):
    site = await _make_site(db_factory)
    baseline = await _make_baseline(
        db_factory,
        site.id,
        status=BaselineStatus.ready,
        is_current=True,
        content_hash=content_sha256(baseline_html),
    )
    return site, baseline


async def _make_scan(db_factory, site_id, baseline_id, **overrides) -> Scan:
    async with db_factory() as db:
        scan = Scan(site_id=site_id, baseline_id=baseline_id, **overrides)
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        return scan


async def test_scan_clean(db_factory, fetch_calls) -> None:
    site, baseline = await _ready_site_and_baseline(db_factory)
    scan = await _make_scan(db_factory, site.id, baseline.id)

    assert await scan_tasks._run_scan(scan.id) == "clean"

    row = await _get(db_factory, Scan, scan.id)
    assert row.status is ScanStatus.completed
    assert row.verdict.value == "clean"
    assert row.layer_scores["layer1_hash"]["score"] == 0.0
    assert row.risk_score is not None and row.risk_score < 0.5
    assert row.started_at is not None and row.finished_at is not None
    # Per-layer findings persisted, one row per layer incl. skips (§5).
    async with db_factory() as db:
        findings = (
            await db.execute(ScanFinding.__table__.select().where(ScanFinding.scan_id == scan.id))
        ).all()
    assert len(findings) == 9
    by_key = {f.layer_key: f for f in findings}
    assert by_key["layer1_hash"].evidence["identical"] is True
    # Identical hash gates the content layers; the skip reason is logged.
    assert by_key["layer2_dom_structure"].skipped is True
    assert "gated by layer 1" in by_key["layer2_dom_structure"].evidence["reason"]
    assert by_key["layer9_fusion"].score is not None


async def test_scan_changed(db_factory, fetch_calls) -> None:
    site, baseline = await _ready_site_and_baseline(
        db_factory, baseline_html="<html><body>original</body></html>"
    )
    scan = await _make_scan(db_factory, site.id, baseline.id)

    verdict = await scan_tasks._run_scan(scan.id)
    assert verdict in ("changed", "flagged")

    row = await _get(db_factory, Scan, scan.id)
    assert row.verdict.value == verdict
    assert row.layer_scores["layer1_hash"]["score"] == 1.0
    assert row.content_hash == content_sha256(HTML)
    assert row.risk_score is not None


async def test_scan_fetch_failure(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_fetch(url: str, *, allow_private_networks: bool = False):
        raise FetchError("Fetch failed: timeout")

    monkeypatch.setattr(scan_tasks, "fetch_page", failing_fetch)
    site, baseline = await _ready_site_and_baseline(db_factory)
    scan = await _make_scan(db_factory, site.id, baseline.id)

    assert await scan_tasks._run_scan(scan.id) == "failed"

    row = await _get(db_factory, Scan, scan.id)
    assert row.status is ScanStatus.failed
    assert row.verdict.value == "error"
    assert "timeout" in row.error
    assert row.finished_at is not None


async def test_scan_missing_baseline(db_factory, fetch_calls) -> None:
    site = await _make_site(db_factory)
    scan = await _make_scan(db_factory, site.id, None)

    assert await scan_tasks._run_scan(scan.id) == "missing-prereqs"
    row = await _get(db_factory, Scan, scan.id)
    assert row.status is ScanStatus.failed
    assert fetch_calls == []


async def test_scan_already_completed_is_idempotent(db_factory, fetch_calls) -> None:
    site, baseline = await _ready_site_and_baseline(db_factory)
    scan = await _make_scan(db_factory, site.id, baseline.id, status=ScanStatus.completed)

    assert await scan_tasks._run_scan(scan.id) == "scan-already-completed"
    assert fetch_calls == []


async def test_scan_missing_row(db_factory, fetch_calls) -> None:
    assert await scan_tasks._run_scan(uuid.uuid4()) == "scan-row-missing"
    assert fetch_calls == []


# --- never-stuck guarantees (unexpected failure paths) ---


async def test_mark_baseline_failed_only_touches_inflight(db_factory) -> None:
    site = await _make_site(db_factory)
    stuck = await _make_baseline(db_factory, site.id, status=BaselineStatus.capturing)
    done = await _make_baseline(
        db_factory, site.id, status=BaselineStatus.ready, is_current=True, content_hash="a" * 64
    )

    await scan_tasks._mark_baseline_failed(stuck.id, "boom")
    await scan_tasks._mark_baseline_failed(done.id, "boom")

    assert (await _get(db_factory, Baseline, stuck.id)).status is BaselineStatus.failed
    # A finished row is never overwritten by the failure handler.
    assert (await _get(db_factory, Baseline, done.id)).status is BaselineStatus.ready


async def test_mark_scan_failed_only_touches_inflight(db_factory) -> None:
    site, baseline = await _ready_site_and_baseline(db_factory)
    stuck = await _make_scan(db_factory, site.id, baseline.id, status=ScanStatus.running)
    done = await _make_scan(db_factory, site.id, baseline.id, status=ScanStatus.completed)

    await scan_tasks._mark_scan_failed(stuck.id, "boom")
    await scan_tasks._mark_scan_failed(done.id, "boom")

    assert (await _get(db_factory, Scan, stuck.id)).status is ScanStatus.failed
    assert (await _get(db_factory, Scan, done.id)).status is ScanStatus.completed


def test_task_wrapper_rejects_bad_id() -> None:
    assert scan_tasks.capture_baseline("not-a-uuid") == "bad-id"
    assert scan_tasks.run_scan("not-a-uuid") == "bad-id"


def test_task_wrapper_survives_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception the task body didn't anticipate must not propagate
    (Celery would retry/redeliver forever with acks_late) — the wrapper
    marks the row failed and returns."""
    marked: list = []

    async def exploding(_id):
        raise RuntimeError("disk full")

    async def record_mark(row_id, message):
        marked.append((row_id, message))

    monkeypatch.setattr(scan_tasks, "_capture_baseline", exploding)
    monkeypatch.setattr(scan_tasks, "_mark_baseline_failed", record_mark)
    assert scan_tasks.capture_baseline(str(uuid.uuid4())) == "error"
    assert len(marked) == 1

    monkeypatch.setattr(scan_tasks, "_run_scan", exploding)
    monkeypatch.setattr(scan_tasks, "_mark_scan_failed", record_mark)
    assert scan_tasks.run_scan(str(uuid.uuid4())) == "error"
    assert len(marked) == 2


async def test_scan_applies_stored_suppression_rules(
    db_factory, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end through the task body: suppression rules stored for the
    site are loaded and applied — a change confined to a suppressed
    element yields zero content-layer scores, and the suppression is
    recorded in the persisted findings."""
    from app.models import SuppressionRule, SuppressionRuleType

    baseline_html = '<html><body><h1>Site</h1><div id="counter">Visitor #1</div></body></html>'
    current_html = '<html><body><h1>Site</h1><div id="counter">Visitor #2</div></body></html>'

    async def fake_fetch(url: str, *, allow_private_networks: bool = False) -> FetchResult:
        return _fetch_result(current_html)

    monkeypatch.setattr(scan_tasks, "fetch_page", fake_fetch)

    site, baseline = await _ready_site_and_baseline(db_factory, baseline_html=baseline_html)
    # The content layers read the baseline HTML artifact from disk.
    d = tmp_path / "baselines" / str(baseline.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(baseline_html, encoding="utf-8")
    async with db_factory() as db:
        row = await db.get(Baseline, baseline.id)
        row.html_path = f"baselines/{baseline.id}/page.html"
        db.add(
            SuppressionRule(
                site_id=site.id,
                type=SuppressionRuleType.css_selector,
                value="#counter",
            )
        )
        await db.commit()

    scan = await _make_scan(db_factory, site.id, baseline.id)
    verdict = await scan_tasks._run_scan(scan.id)
    assert verdict in ("clean", "changed")  # never flagged

    async with db_factory() as db:
        findings = (
            await db.execute(ScanFinding.__table__.select().where(ScanFinding.scan_id == scan.id))
        ).all()
    by_key = {f.layer_key: f for f in findings}
    # Bytes changed (layer 1 fires) but every content layer sees the
    # suppressed pair and scores zero.
    assert by_key["layer1_hash"].score == 1.0
    assert by_key["layer2_dom_structure"].score == 0.0
    assert by_key["layer5_signatures"].score == 0.0
    assert "suppression_applied" in by_key["layer2_dom_structure"].evidence
    assert "suppression" in by_key["layer9_fusion"].evidence

    row = await _get(db_factory, Scan, scan.id)
    assert row.risk_score is not None and row.risk_score < 0.5


async def test_scan_survives_broken_suppression_load(
    db_factory, fetch_calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure while loading suppression rules must degrade to 'no
    suppression', never fail the scan (rule 6)."""

    # Patch one level down: build_suppression exploding inside the loader.
    monkeypatch.setattr(
        scan_tasks, "build_suppression", lambda rules: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    site, baseline = await _ready_site_and_baseline(db_factory)
    scan = await _make_scan(db_factory, site.id, baseline.id)

    assert await scan_tasks._run_scan(scan.id) == "clean"
    row = await _get(db_factory, Scan, scan.id)
    assert row.status is ScanStatus.completed
