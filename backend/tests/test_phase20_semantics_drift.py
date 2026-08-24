"""Layer 8 multi-window semantic comparison — closes the audit finding
"Layer 8 semantic drift is blind past a 5,000-char cap, near-zero in the
realistic cosine band, and English-only — non-English partial rewrites
score 0.0 end-to-end" (plan phase 20).

What was broken (re-verified by execution before this fix): the layer
embedded each side's ENTIRE visible text once, truncated to the first
5,000 characters — and the encoder itself only represents roughly the
first thousand of those, so any mutation confined beyond that window
measured similarity exactly 1.0 / drift exactly 0.0; similarities below
the old mapping's 0.85 knee scored near zero; and the keyword channels
were English-only.

Fix under test: bounded multi-window comparison (windows spread across
the WHOLE text, each matched against its best match on the other side,
length-weighted symmetric mean), a calibrated monotone piecewise-linear
drift mapping, and non-Latin defacement lexicon coverage.

Stub discipline: every fake embedder here applies the production
``_EMBED_CHAR_CAP`` truncation before vectorizing. That keeps the stubs
faithful to what production code feeds the encoder BOTH pre-fix (one
capped whole-text call) and post-fix (per-chunk calls, far under the
cap) — without it, an uncapped stub would silently detect beyond-cap
mutations under the OLD code and the failing-before proofs would be
vacuous.
"""

import hashlib
import math
import re
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import Alert, Scan, ScanFinding
from worker import scan_tasks
from worker.detection import semantics
from worker.detection.semantics import (
    _EMBED_CHAR_CAP,
    _MAX_CHUNKS_PER_SIDE,
    drift_from_similarity,
    layer8_semantics,
)
from worker.detection.types import PageData
from worker.fetcher import FetchResult

# --- hermetic embedder stubs -------------------------------------------------------


def _hashbag(text: str) -> list[float]:
    vec = [0.0] * 64
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        d = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(d[:4], "big") % 64
        vec[idx] += 1.0 if d[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _capped(embed):
    """Wrap an embedder with the production input truncation."""

    def wrapped(text: str):
        return embed(text[:_EMBED_CHAR_CAP])

    return wrapped


class ScriptedEmbedder:
    """Marker-keyed orthogonal-basis embedder with controllable failure
    modes: windows containing a ``none_marker`` return None (embedder
    outage/degenerate output), unmarked windows return the zero vector
    (cosine's documented degenerate case). Distinct markers map to
    distinct dimensions, so cross-marker similarity is exactly 0."""

    MARKERS = ("CORPTEXT", "HALFTEXT", "SPAMTEXT", "TAILMARK", "OTHERTEXT")

    def __init__(self, none_markers: tuple[str, ...] = ()):
        self.none_markers = none_markers
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        for marker in self.none_markers:
            if marker in text:
                return None
        vec = [0.0] * 64
        for i, marker in enumerate(self.MARKERS):
            if marker in text:
                vec[i * 7] += 1.0
        return vec


@pytest.fixture(autouse=True)
def no_network_embeddings(monkeypatch: pytest.MonkeyPatch):
    """Default seam state mirrors the other detection suites: the layer
    must degrade cleanly when no embedder exists. Embedding-specific
    tests re-patch this attribute with their own stub."""
    monkeypatch.setattr(semantics, "embed_text", lambda text: None)


def page(html: str) -> PageData:
    return PageData(html=html)


def _repeated(marker: str, target_chars: int) -> str:
    unit = f"<p>{marker} lorem ipsum dolor sit amet consectetur</p>"
    out = []
    size = 0
    while size < target_chars:
        out.append(unit)
        size += len(unit)
    return "".join(out)


def _run_layer(baseline_html: str, current_html: str) -> dict:
    return layer8_semantics(page(baseline_html), page(current_html))


# --- drift mapping -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("similarity", "expected"),
    [
        (1.0, 0.0),
        (0.999, 0.0),
        (0.93, 0.0),
        (0.90, 0.0),
        (0.85, 0.15),
        (0.83, 0.21),
        (0.80, 0.30),
        (0.65, 0.60),
        (0.50, 0.90),
        (0.49, 0.902),
        (0.20, 0.96),
        (0.00, 1.00),
        (-0.40, 1.00),
    ],
)
def test_drift_mapping_anchor_values(similarity: float, expected: float) -> None:
    """Exact anchor/segment values, including both plateau edges, both
    segment interiors, and clamped behavior for negative cosines (which
    real cross-lingual comparisons do produce)."""
    assert drift_from_similarity(similarity) == pytest.approx(expected, abs=1e-9)


def test_drift_mapping_is_monotone_non_increasing() -> None:
    scores = [drift_from_similarity(s / 100) for s in range(120, -60, -1)]
    assert all(a <= b + 1e-12 for a, b in zip(scores, scores[1:], strict=False))


def test_drift_mapping_zero_only_on_the_plateau() -> None:
    """The identical-text contract: anything >= the top plateau edge maps
    to EXACTLY 0.0, and the first nonzero step is strictly positive."""
    assert drift_from_similarity(1.0) == 0.0
    assert drift_from_similarity(0.91) == 0.0
    assert drift_from_similarity(0.89) > 0.0


# --- hole 1: mutations beyond the legacy single-embedding window --------------------


def test_spam_beyond_legacy_embed_cap_is_detected() -> None:
    """THE headline regression: ~17k characters of spam appended to a
    ~7k-character page — entirely beyond the 5,000-character legacy
    embed cap. Pre-fix this measured similarity exactly 1.0 / drift
    exactly 0.0; post-fix the mutated regions register."""
    embedder = ScriptedEmbedder()
    monkey_target = _capped(embedder)
    semantics.embed_text = monkey_target  # noqa: F841 - seam re-patch

    baseline_html = f"<html><body>{_repeated('CORPTEXT', 7000)}</body></html>"
    current_html = (
        f"<html><body>{_repeated('CORPTEXT', 7000)}{_repeated('SPAMTEXT', 17000)}</body></html>"
    )
    result = _run_layer(baseline_html, current_html)
    ev = result["evidence"]
    assert result["score"] >= 0.15
    assert ev["semantic_similarity"] < 0.85
    assert ev["semantic_drift_score"] >= 0.15
    assert ev["semantic_chunks_baseline"] > 1  # multi-window path engaged
    assert ev["semantic_chunks_current"] > ev["semantic_chunks_baseline"]


def test_page_tail_beyond_the_window_budget_is_still_measured() -> None:
    """Beyond MAX_CHUNKS_PER_SIDE windows the layer samples evenly
    instead of reading every character — so even the END of a huge page
    lands inside some window. Pins the sampling property honestly: the
    tail mismatch is VISIBLE in the per-window diagnostic while the
    aggregate stays proportional (a sub-proportional tail edit must not
    manufacture a large drift score by itself)."""
    embedder = ScriptedEmbedder()
    semantics.embed_text = _capped(embedder)

    baseline_html = f"<html><body>{_repeated('CORPTEXT', 240000)}</body></html>"
    current_html = (
        f"<html><body>{_repeated('CORPTEXT', 240000)}{_repeated('TAILMARK', 700)}</body></html>"
    )
    result = _run_layer(baseline_html, current_html)
    ev = result["evidence"]
    assert ev["semantic_chunks_current"] == _MAX_CHUNKS_PER_SIDE
    assert ev["semantic_min_chunk_similarity"] is not None
    assert ev["semantic_min_chunk_similarity"] < 0.35  # tail window measured the mutation
    assert ev["semantic_similarity"] >= 0.90  # aggregate stays proportional


def test_identical_multichunk_text_measures_exact_zero_drift() -> None:
    """Control: identical LONG texts (>1 window per side) must measure
    similarity ~1.0 and drift EXACTLY 0.0 through the multi-window path,
    preserving the shipped identical-page contract."""
    semantics.embed_text = _capped(_hashbag)
    body = _repeated("CORPTEXT", 20000)
    result = _run_layer(
        f"<html><body>{body}</body></html>",
        f"<html><body>{body}</body></html>",
    )
    ev = result["evidence"]
    assert result["score"] == 0.0
    assert ev["semantic_similarity"] == pytest.approx(1.0, abs=1e-9)
    assert ev["semantic_drift_score"] == 0.0
    assert ev["semantic_chunks_baseline"] > 1


def test_pure_positional_shift_is_not_flagged_as_drift() -> None:
    """Guard against the redesign introducing shift sensitivity: moving
    content downward (banner prepended, nothing removed) keeps every
    window's BEST MATCH intact, so the metric stays silent."""
    semantics.embed_text = _capped(_hashbag)
    body = _repeated("CORPTEXT", 9000)
    result = _run_layer(
        f"<html><body>{body}</body></html>",
        f"<html><body><h1>FLASH SALE BANNER</h1>{body}</body></html>",
    )
    assert result["score"] == 0.0


def test_second_half_of_page_deleted_is_detected() -> None:
    """Deletion direction: the symmetric aggregate must catch content
    REMOVED beyond the legacy window (pre-fix: first 5,000 chars
    identical => similarity 1.0 => blind)."""
    semantics.embed_text = _capped(ScriptedEmbedder())
    kept = _repeated("CORPTEXT", 7000)
    deleted = _repeated("HALFTEXT", 7000)
    result = _run_layer(
        f"<html><body>{kept}{deleted}</body></html>",
        f"<html><body>{kept}</body></html>",
    )
    ev = result["evidence"]
    assert ev["semantic_similarity"] < 0.80
    assert result["score"] >= 0.25


# --- embedder degradation semantics --------------------------------------------------


def test_partial_embedder_failure_keeps_valid_windows() -> None:
    """Windows whose embedding failed are excluded from the aggregation
    instead of poisoning it; whatever was measured still yields a
    signal (and never raises)."""
    embedder = ScriptedEmbedder(none_markers=("SPAMTEXT",))
    semantics.embed_text = _capped(embedder)
    baseline_html = f"<html><body>{_repeated('CORPTEXT', 2500)}</body></html>"
    current_html = (
        f"<html><body>{_repeated('CORPTEXT', 2500)}{_repeated('SPAMTEXT', 2500)}</body></html>"
    )
    result = _run_layer(baseline_html, current_html)
    ev = result["evidence"]
    assert ev["semantic_similarity"] is not None  # valid windows carried the compare
    assert ev["semantic_chunks_current"] > ev["semantic_chunks_baseline"]


def test_all_windows_degraded_degrades_to_none() -> None:
    """No valid vector anywhere => similarity None / drift 0.0 / score
    0.0 — the documented 'feature unavailable' path, unchanged."""
    embedder = ScriptedEmbedder(none_markers=tuple(ScriptedEmbedder.MARKERS))
    semantics.embed_text = _capped(embedder)
    body = _repeated("CORPTEXT", 3000)
    result = _run_layer(
        f"<html><body>{body}</body></html>",
        f"<html><body>{body} extra words</body></html>",
    )
    ev = result["evidence"]
    assert ev["semantic_similarity"] is None
    assert ev["semantic_drift_score"] == 0.0
    assert result["score"] == 0.0


def test_encode_budget_is_bounded_on_huge_pages() -> None:
    """Cost bound: a 100k-char page pair performs at most
    2 x MAX_CHUNKS_PER_SIDE embedder calls, regardless of page size —
    and at least one per side, so a dead chunker/embedder cannot pass
    vacuously (positive evidence the sampled windows really embedded)."""

    class Counting:
        def __init__(self):
            self.calls = 0

        def __call__(self, text):
            self.calls += 1
            return _hashbag(text)

    counting = Counting()
    semantics.embed_text = counting
    body = _repeated("CORPTEXT", 100000)
    _run_layer(f"<html><body>{body}</body></html>", f"<html><body>{body}!</body></html>")
    assert counting.calls <= 2 * _MAX_CHUNKS_PER_SIDE
    assert counting.calls >= 2


# --- hole 3: non-English defacement vocabulary --------------------------------------


@pytest.mark.parametrize(
    ("phrase", "min_score"),
    [
        ("تم اختراق هذا الموقع من قبل القراصنة", 0.5),  # "this site has been hacked by hackers"
        ("Сайт взломан. Мы вернёмся.", 0.5),  # "site hacked. we will return."
        ("这个网站已被入侵", 0.3),  # "this site has been intruded"
    ],
)
def test_non_english_defacement_lexicon_fires(phrase: str, min_score: float) -> None:
    """Partial non-Latin takeovers previously scored 0.0 through this
    layer end to end (English-only lexicons + window-blind embeddings);
    the added campaign phrasings now carry graded signal on NEW text."""
    result = _run_layer(
        _page_html := "<html><body><p>Welcome to our reliable services site.</p></body></html>",
        f"<html><body><p>Welcome to our reliable services site.</p><p>{phrase}</p></body></html>",
    )
    assert result["score"] >= min_score
    assert result["evidence"]["aggression_hits"]


def test_arabic_contact_phrase_counts_as_contact_topic() -> None:
    result = _run_layer(
        "<html><body><p>Welcome to our reliable services site.</p></body></html>",
        "<html><body><p>Welcome to our reliable services site.</p>"
        "<p>تواصلوا معنا عبر التليجرام</p></body></html>",
    )
    assert "contact_defacer" in result["evidence"]["topic_hits"]


def test_lexicon_stays_new_text_only() -> None:
    """A page that ALWAYS contained the phrases must not flag — same
    baseline-present guard the English entries have always had."""
    html = (
        "<html><body><p>تم اختراق هذا الموقع من قبل القراصنة Сайт взломан "
        "这个网站已被入侵</p></body></html>"
    )
    result = _run_layer(html, html)
    assert result["score"] == 0.0
    assert result["evidence"]["aggression_hits"] == []


# --- end-to-end: the audit's 17k-char row flags through the task body ----------------


BASELINE_HTML = (
    "<html><body><h1>Corporate homepage</h1>"
    "<p>Welcome to our site. Reliable services for your business every day.</p></body></html>"
)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send_task(name, args=None, **kwargs):
        calls.append((name, args))

    monkeypatch.setattr(scan_tasks.celery_app, "send_task", fake_send_task)
    return calls


async def test_seo_spam_beyond_legacy_cap_flags_end_to_end(
    db_factory, monkeypatch, enqueued, tmp_path
):
    """Audit Finding 4.3's measured miss ('SEO-spam text block beyond
    layer-8's embed cap ... every content layer 0.0') driven through the
    REAL task body: the appended spam block now registers in layer 8 and
    the scan flags."""
    from worker.hashing import content_sha256

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

    async def fake_probe(url, *, allow_private_networks=False):
        from worker.probe import ProbeResult

        return ProbeResult()

    async def fake_fetch(url, *, allow_private_networks=False):
        return FetchResult(
            html=CURRENT_HTML,
            screenshot=b"\x89PNG-fake",
            final_url="https://example.com/",
            http_status=200,
            headers={"content-type": "text/html"},
        )

    from app.models import Baseline, BaselineStatus, Site
    from worker.detection import semantics as semantics_module

    monkeypatch.setattr(scan_tasks, "task_session", fake_task_session)
    monkeypatch.setattr(scan_tasks, "store_artifacts", fake_store)
    monkeypatch.setattr(scan_tasks, "read_artifact_text", fake_read_text)
    monkeypatch.setattr(scan_tasks, "read_artifact_bytes", lambda p: None)
    monkeypatch.setattr(scan_tasks, "probe_site", fake_probe)
    # Real numeric vectors (Phase-12 convention), production-capped input.
    monkeypatch.setattr(semantics_module, "embed_text", _capped(_hashbag))

    spam_block = (
        "cheap seo spam casino pills links buy now best odds online casino "
        "pharmacy no prescription payday loans replica watches "
    ) * 550  # ~29k visible characters appended below the fold
    CURRENT_HTML = (
        "<html><body><h1>Corporate homepage</h1>"
        "<p>Welcome to our site. Reliable services for your business every day.</p>"
        f"<div>{spam_block}</div></body></html>"
    )

    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com")
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
        scan = Scan(site_id=site.id, baseline_id=baseline.id)
        db.add(scan)
        await db.commit()

    d = tmp_path / "baselines" / str(baseline.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "page.html").write_text(BASELINE_HTML, encoding="utf-8")
    (d / "screenshot.png").write_bytes(b"\x89PNG-fake")
    async with db_factory() as db:
        b = await db.get(Baseline, baseline.id)
        b.html_path = f"baselines/{baseline.id}/page.html"
        b.screenshot_path = f"baselines/{baseline.id}/screenshot.png"
        await db.commit()

    assert await scan_tasks._run_scan(scan.id) == "flagged"

    async with db_factory() as db:
        finding = await db.scalar(
            select(ScanFinding).where(
                ScanFinding.scan_id == scan.id, ScanFinding.layer_key == "layer8_semantics"
            )
        )
        alert = await db.scalar(select(Alert).where(Alert.scan_id == scan.id))
        s = await db.get(Scan, scan.id)
    assert finding is not None
    sim = finding.evidence["semantic_similarity"]
    assert isinstance(sim, float) and sim < 0.90
    assert finding.evidence["semantic_drift_score"] > 0.15
    assert alert is not None and alert.risk_score >= 0.5
    assert s.risk_score >= 0.5
