"""Capture health surfaces (PROMPT-002 Phase 7).

Unit tests for the challenge-gate evidence contract (`_wait_out_challenge`
returns detected/resolved booleans; a persistent challenge raises and
stores no evidence at all) and API tests for the re-baseline hint (site
detail compares the baseline's recorded capture-method version against
the current capture flow's — absence is unknown, never old) and the
fleet capture-quality summary (rows predating capture evidence stay
uncounted, never zeroed into a bucket).
"""

import time
import uuid

import pytest

from app.capture import CAPTURE_METHOD_VERSION
from app.models import Baseline, BaselineStatus, Scan, ScanStatus, ScanVerdict, Site
from worker.fetcher import CHALLENGE_WAIT_MS, _ChallengeUnsolvedError, _wait_out_challenge

# --- challenge-gate evidence (unit, no browser) ------------------------------


class _TitlePage:
    """Minimal Page double: each evaluate() yields the next title (the
    challenge probe reads only title + marker class)."""

    def __init__(self, titles: list[str]) -> None:
        self._titles = titles
        self._index = 0

    async def evaluate(self, *_args, **_kwargs) -> dict:
        title = self._titles[min(self._index, len(self._titles) - 1)]
        self._index += 1
        return {"title": title, "marker": False}

    async def wait_for_timeout(self, _ms: int) -> None:
        return None


async def test_wait_out_challenge_no_challenge_returns_negative_evidence() -> None:
    """A page with no challenge markers records detected=False and
    resolved=False — the honest 'nothing happened' evidence."""
    evidence = await _wait_out_challenge(
        _TitlePage(["normal site"]),
        [],
        fallback_response=None,
        deadline=time.monotonic() + CHALLENGE_WAIT_MS / 1000,
        wait_ms=CHALLENGE_WAIT_MS,
    )
    assert evidence == {
        "cloudflare_challenge_detected": False,
        "cloudflare_challenge_resolved": False,
    }


async def test_wait_out_challenge_cleared_challenge_returns_resolved_evidence() -> None:
    """A challenge that auto-solves during the wait records both the
    detection and the resolution (the Phase-2 behavior itself is pinned
    by test_cloudflare_detection.py; this pins the evidence contract)."""
    evidence = await _wait_out_challenge(
        _TitlePage(["Just a moment...", "Real Site"]),
        [],
        fallback_response=None,
        deadline=time.monotonic() + CHALLENGE_WAIT_MS / 1000,
        wait_ms=CHALLENGE_WAIT_MS,
    )
    assert evidence == {
        "cloudflare_challenge_detected": True,
        "cloudflare_challenge_resolved": True,
    }


async def test_wait_out_challenge_persistent_challenge_raises_and_stores_nothing() -> None:
    """A challenge that never clears raises the hard capture failure —
    so no challenge evidence with resolved=False can ever be stored on a
    row (the Phase-2 contract: challenge state never becomes content)."""
    with pytest.raises(_ChallengeUnsolvedError) as excinfo:
        await _wait_out_challenge(
            _TitlePage(["Just a moment..."]),
            [],
            fallback_response=None,
            deadline=time.monotonic() + CHALLENGE_WAIT_MS / 1000,
            wait_ms=100,
        )
    assert "bot protection" in str(excinfo.value).lower()


def test_capture_method_version_is_a_positive_int() -> None:
    """The migration gate must be a version number that can only move
    forward — the re-baseline hint's comparison depends on it."""
    assert isinstance(CAPTURE_METHOD_VERSION, int)
    assert CAPTURE_METHOD_VERSION >= 1


# --- re-baseline hint (site detail API) --------------------------------------


async def _make_site_with_baseline(db_factory, capture_meta: dict | None) -> uuid.UUID:
    async with db_factory() as db:
        site = Site(name="Hint", url="https://hint.example.com/")
        db.add(site)
        await db.flush()
        db.add(
            Baseline(
                site_id=site.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="a" * 64,
                capture_meta=capture_meta,
            )
        )
        await db.commit()
        return site.id


async def test_site_detail_flags_baseline_older_than_current_capture_method(
    client, auth_headers, db_factory
) -> None:
    site_id = await _make_site_with_baseline(
        db_factory, {"capture_method_version": CAPTURE_METHOD_VERSION - 1}
    )
    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baseline_capture_method_version"] == CAPTURE_METHOD_VERSION - 1
    assert body["current_capture_method_version"] == CAPTURE_METHOD_VERSION
    assert body["needs_rebaseline"] is True


async def test_site_detail_current_method_baseline_does_not_hint(
    client, auth_headers, db_factory
) -> None:
    site_id = await _make_site_with_baseline(
        db_factory, {"capture_method_version": CAPTURE_METHOD_VERSION}
    )
    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["needs_rebaseline"] is False


async def test_site_detail_pre_versioning_baseline_is_unknown_and_never_hints(
    client, auth_headers, db_factory
) -> None:
    """A baseline that predates versioning has no recorded version —
    absence is unknown, never treated as old (no false hint)."""
    site_id = await _make_site_with_baseline(db_factory, {})
    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baseline_capture_method_version"] is None
    assert body["needs_rebaseline"] is False


async def test_site_detail_no_baseline_reports_no_hint(client, auth_headers, db_factory) -> None:
    async with db_factory() as db:
        site = Site(name="NoBaseline", url="https://nobaseline.example.com/")
        db.add(site)
        await db.commit()
        site_id = site.id
    resp = await client.get(f"/api/sites/{site_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["baseline_capture_method_version"] is None
    assert body["needs_rebaseline"] is False


# --- fleet capture-quality summary (health API) ------------------------------


async def test_health_details_capture_quality_summary(client, auth_headers, db_factory) -> None:
    async with db_factory() as db:
        site = Site(name="Q", url="https://quality.example.com/")
        db.add(site)
        await db.flush()
        db.add(
            Scan(
                site_id=site.id,
                status=ScanStatus.completed,
                verdict=ScanVerdict.clean,
                capture_evidence={
                    "capture_quality": "degraded",
                    "capture_method_version": CAPTURE_METHOD_VERSION,
                },
            )
        )
        db.add(
            Scan(
                site_id=site.id,
                status=ScanStatus.completed,
                verdict=ScanVerdict.changed,
                capture_evidence={"capture_quality": "full"},
            )
        )
        # Predates capture evidence — uncounted, NOT zeroed into a bucket.
        db.add(
            Scan(
                site_id=site.id,
                status=ScanStatus.completed,
                verdict=ScanVerdict.clean,
                capture_evidence=None,
            )
        )
        await db.commit()

    resp = await client.get("/api/health/details", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    summary = resp.json()["capture_quality_summary"]
    assert summary.get("degraded") == 1
    assert summary.get("full") == 1
    assert sum(summary.values()) == 2
