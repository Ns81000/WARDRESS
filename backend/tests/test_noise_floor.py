"""PROMPT-002 Phase 11 — verdict noise floor (`worker.scan_tasks.NOISE_FLOOR`).

Root cause: the `changed` verdict fired on ANY nonzero layer score from a
non-skipped layer, so a benign dynamic site whose layers never fully zero
out (a rounding-tracked timestamp here, a residue there) read "changed"
every scan at near-zero fused risk — operator-trust noise. The verdict now
treats layer scores at or below NOISE_FLOOR (0.02) as silence.

The floor is verdict-only by design:
- it never touches the fused risk score (fusion reads raw layer scores),
- it never touches `flagged` (risk >= site.flag_threshold, evaluated
  independently and checked first),
- it cannot hide real attacks: the rule-based floors in fusion
  (layer 5/7 >= 0.85 -> 0.90, layer 3 >= 0.55 -> 0.40) bypass it entirely,
  and every attack scenario in the fusion training dataset measures
  > 0.02 on at least one non-skipped layer (re-measured with the current
  layer code during Phase 11; see the implementation log).

Layer behavior is stubbed here (`run_detection` replaced by a spec-driven
fake): what's under test is the verdict decision in `_run_scan`, not the
layers themselves. Failing-before proof (run against the unmodified tree,
Phase 11 session): the two sub-floor scenarios read "changed" under the old
any-nonzero rule; the behavior guards below passed before and after and are
documented as N/A failing-before.
"""

import uuid
from contextlib import asynccontextmanager

import pytest

from app.models import Baseline, BaselineStatus, Scan, Site
from worker import scan_tasks
from worker.detection.pipeline import LAYERS
from worker.fetcher import FetchResult
from worker.hashing import content_sha256
from worker.probe import ProbeResult

HTML = "<html><body><h1>Welcome</h1></body></html>"
BASELINE_HTML = "<html><body><h1>Original</h1></body></html>"


def _fetch_result(html: str = HTML) -> FetchResult:
    return FetchResult(
        html=html,
        screenshot=b"\x89PNG-fake",
        final_url="https://example.com/",
        http_status=200,
        headers={"content-type": "text/html"},
    )


def _stub_detection(monkeypatch: pytest.MonkeyPatch, results: dict) -> None:
    """Replace the pipeline with a spec-driven fake. Sync on purpose: the
    task body runs it via asyncio.to_thread."""

    def fake_run_detection(baseline, current, suppression):
        return results

    monkeypatch.setattr(scan_tasks, "run_detection", fake_run_detection)


def _results(scores: dict[str, float], *, fusion: float, skipped: set[str] | None = None) -> dict:
    skipped = set(skipped or ())
    out: dict = {}
    for _number, key in LAYERS:
        if key == "layer9_fusion":
            out[key] = {"score": fusion, "evidence": {"model": "stub"}}
        else:
            out[key] = {
                "score": scores.get(key, 0.0),
                "skipped": key in skipped,
                "evidence": {},
            }
    return out


@pytest.fixture(autouse=True)
def wire_worker(monkeypatch: pytest.MonkeyPatch, db_factory, tmp_path):
    """Point the task body at the test DB, a temp artifacts dir, and an
    empty metadata probe (same wiring as test_scan_tasks)."""

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

    async def fake_fetch(url: str, *, allow_private_networks: bool = False) -> FetchResult:
        return _fetch_result()

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(scan_tasks, "store_artifacts", fake_store)
    monkeypatch.setattr(scan_tasks, "read_artifact_text", fake_read_text)
    monkeypatch.setattr(scan_tasks, "read_artifact_bytes", fake_read_bytes)
    monkeypatch.setattr(scan_tasks, "probe_site", fake_probe)
    monkeypatch.setattr(scan_tasks, "fetch_page", fake_fetch)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send_task(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send_task)
    return calls


async def _seed(db_factory, *, flag_threshold: float = 0.5):
    async with db_factory() as db:
        site = Site(
            name="Example", url="https://example.com/", flag_threshold=flag_threshold
        )
        db.add(site)
        await db.commit()
        await db.refresh(site)
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash=content_sha256(BASELINE_HTML),
        )
        db.add(baseline)
        await db.commit()
        await db.refresh(baseline)
        scan = Scan(site_id=site.id, baseline_id=baseline.id)
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        return site, baseline, scan


async def _get_scan(db_factory, scan_id: uuid.UUID) -> Scan:
    async with db_factory() as db:
        return await db.get(Scan, scan_id)


# --- failing-before: the sub-floor scenarios the old rule read as "changed" ---


async def test_all_layers_at_or_below_floor_reads_clean(db_factory, monkeypatch) -> None:
    """Every non-skipped layer at or below the floor => verdict "clean",
    exactly the timestamp-churn + CSP-residue shape that motivated the
    floor. Failing-before: the old any-nonzero rule returned "changed"."""
    _stub_detection(
        monkeypatch,
        _results(
            {
                "layer2_dom_structure": 0.02,
                "layer4_visual_diff": 0.015,
                "layer6_security_metadata": 0.01,
            },
            fusion=0.012,
        ),
    )
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "clean"

    row = await _get_scan(db_factory, scan.id)
    assert row.verdict.value == "clean"
    # The floor is verdict-only: the fused risk is stored verbatim.
    assert row.risk_score == pytest.approx(0.012)


async def test_layer_score_exactly_at_floor_is_silence(db_factory, monkeypatch) -> None:
    """Boundary pin: the comparison is strict (score > NOISE_FLOOR), so a
    layer sitting exactly AT the floor counts as silence. Failing-before:
    the old rule fired on any nonzero score."""
    _stub_detection(
        monkeypatch,
        _results({"layer2_dom_structure": scan_tasks.NOISE_FLOOR}, fusion=0.01),
    )
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "clean"


# --- behavior guards (pass before AND after; N/A failing-before) ---


async def test_layer_score_just_above_floor_reads_changed(db_factory, monkeypatch) -> None:
    """A layer just above the floor still reads "changed" — the floor must
    not flatten the verdict scale beyond sub-noise residue."""
    _stub_detection(
        monkeypatch,
        _results({"layer2_dom_structure": scan_tasks.NOISE_FLOOR + 0.01}, fusion=0.03),
    )
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "changed"


async def test_conclusive_signature_flagged_regardless_of_floor(
    db_factory, monkeypatch, enqueued
) -> None:
    """A strong-tier signature (layer 5 = 0.90; the rule floor's conclusive
    tier) reads "flagged" with every other layer sub-noise — the floor can
    never launder strong attack evidence into "clean"."""
    _stub_detection(monkeypatch, _results({"layer5_signatures": 0.90}, fusion=0.90))
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    assert enqueued, "flagged scan must still enqueue alert delivery"


async def test_floor_never_affects_flagging(db_factory, monkeypatch, enqueued) -> None:
    """flagged is computed from fused risk vs the site's flag_threshold,
    independent of `changed`: a threshold-0 site flags even when every
    layer is sub-noise and the changed-rule would read clean."""
    _stub_detection(monkeypatch, _results({"layer2_dom_structure": 0.005}, fusion=0.008))
    _site, _baseline, scan = await _seed(db_factory, flag_threshold=0.0)

    assert await scan_tasks._run_scan(scan.id) == "flagged"
    row = await _get_scan(db_factory, scan.id)
    assert row.risk_score == pytest.approx(0.008)


async def test_skipped_layers_never_contribute_to_changed(db_factory, monkeypatch) -> None:
    """Skipped (structurally gated) layers are excluded from the changed
    rule no matter what their nominal score field holds."""
    _stub_detection(
        monkeypatch,
        _results({}, fusion=0.0, skipped={"layer2_dom_structure", "layer4_visual_diff"}),
    )
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "clean"


async def test_degraded_layers_do_not_manufacture_changed(db_factory, monkeypatch) -> None:
    """A degraded (unmeasured) channel reports score 0.0 and must not trip
    the changed rule; the uncertainty uplift lives in fusion risk only."""
    results = _results({}, fusion=0.20)
    results["layer4_visual_diff"] = {
        "score": 0.0,
        "skipped": False,
        "degraded": True,
        "evidence": {},
    }
    _stub_detection(monkeypatch, results)
    _site, _baseline, scan = await _seed(db_factory)

    assert await scan_tasks._run_scan(scan.id) == "clean"
    row = await _get_scan(db_factory, scan.id)
    assert row.risk_score == pytest.approx(0.20)


# --- docs pin (Rule 13 verifiable-copy: the doc names the constants, the
# test makes either side's drift fail loudly) ---


def test_detection_layers_doc_noise_floor_matches_module():
    from pathlib import Path

    from app.scanning import MATERIAL_CHANGE_RISK
    from worker.scan_tasks import NOISE_FLOOR

    text = (
        Path(__file__).resolve().parents[2] / "docs" / "detection-layers.mdx"
    ).read_text(encoding="utf-8")
    assert f"`NOISE_FLOOR = {NOISE_FLOOR:.2f}`" in text
    assert f"`MATERIAL_CHANGE_RISK = {MATERIAL_CHANGE_RISK:.2f}`" in text
