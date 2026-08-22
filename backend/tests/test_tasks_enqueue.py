"""Regression tests for the API-side enqueue-degradation contract (Phase 3).

Finding: a Redis outage surfaced through the producer's result-backend
machinery — send_task drives the result-consumer pubsub reconnect loop
*before* publishing, which burned ~60 s and then raised RuntimeError (not
kombu OperationalError), escaping _send's translation and therefore
_enqueue_or_fail's HTTPException-based recovery: requests hung ~64 s and
died as unhandled 500s while the just-committed row stayed stuck pending,
409-blocking its site until the stale window passed.

Pinned here:

- the API producer client has NO result backend (root cause stays shut —
  results are never consumed by the API process);
- any broker-outage-class enqueue failure becomes HTTPException 503 fast
  (never a bare RuntimeError), keeping _enqueue_or_fail's recovery live;
- with a genuinely dead broker the designed degradation holds end to end:
  rebaseline marks its committed row failed (never stranded pending) and
  bulk import reports per-row enqueue failure instead of a 500.
"""

import time
import uuid

import pytest
from celery import Celery
from celery.backends.base import DisabledBackend
from fastapi import HTTPException, status
from sqlalchemy import select

from app import services, tasks
from app.models import Baseline, BaselineStatus, Site
from app.tasks import _celery_client


def _dead_broker_client() -> Celery:
    client = Celery("wardress-test-dead-broker", broker="redis://127.0.0.1:1/0")
    # Mirror the production retry budget so failure latency matches reality.
    client.conf.broker_transport_options = {"max_retries": 2, "interval_start": 0.1}
    return client


class _ResultStorePoisonedClient:
    """Stands in for the pre-fix failure shape: celery's redis result backend
    raising its non-kombu escapee from inside send_task."""

    def send_task(self, name, args=None, **kwargs):
        raise RuntimeError(
            "Retry limit exceeded while trying to reconnect to the Celery "
            "result store backend. The Celery application must be restarted."
        )


# --- root cause pinned shut -------------------------------------------------


def test_api_producer_client_has_no_result_backend():
    """send_task consults the result backend before every publish; a backend
    there turns any outage into a ~60 s reconnect hang ending in RuntimeError.
    The producer must stay broker-only."""
    client = _celery_client()
    assert client.conf.result_backend is None
    assert isinstance(client.backend, DisabledBackend)


# --- _send degradation contract ---------------------------------------------


def test_send_dead_broker_maps_to_503_fast(monkeypatch):
    monkeypatch.setattr(tasks, "_client", _dead_broker_client())
    start = time.perf_counter()
    with pytest.raises(HTTPException) as excinfo:
        tasks._send("wardress.run_scan", [str(uuid.uuid4())])
    elapsed = time.perf_counter() - start
    assert excinfo.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "Task queue is unavailable" in excinfo.value.detail
    assert elapsed < 20  # the pre-fix result-store reconnect loop burned ~64 s


def test_send_translates_unexpected_enqueue_failure_to_503(monkeypatch):
    monkeypatch.setattr(tasks, "_client", _ResultStorePoisonedClient())
    with pytest.raises(HTTPException) as excinfo:
        tasks._send("wardress.capture_baseline", [str(uuid.uuid4())])
    assert excinfo.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# --- designed recovery through the real service/router chains ----------------


async def test_rebaseline_with_dead_broker_marks_row_failed_not_pending(db_factory, monkeypatch):
    """rebaseline_site commits its pending baseline before enqueuing; with the
    broker down the caller gets QueueUnavailableError AND the committed row is
    marked failed — not left pending to 409-block the site until staleness."""
    async with db_factory() as db:
        site = Site(name="q3-site", url="https://q3.example.com")
        db.add(site)
        await db.flush()
        db.add(
            Baseline(
                site_id=site.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="a" * 64,
            )
        )
        await db.commit()
        await db.refresh(site)
        site_id = site.id

    monkeypatch.setattr(tasks, "_client", _dead_broker_client())

    async with db_factory() as db:
        fresh = await db.get(Site, site_id)
        with pytest.raises(services.QueueUnavailableError):
            await services.rebaseline_site(db, fresh, actor=None, via="phase3-test")

    async with db_factory() as db:
        baselines = (await db.scalars(select(Baseline).where(Baseline.site_id == site_id))).all()
    assert len(baselines) == 2
    assert all(b.status != BaselineStatus.pending for b in baselines)
    new_row = next(b for b in baselines if b.status != BaselineStatus.ready)
    assert new_row.status == BaselineStatus.failed
    assert "queue was unavailable" in new_row.error


async def test_bulk_import_dead_broker_reports_enqueue_failure_per_row(
    client, auth_headers, monkeypatch
):
    """The bulk-import router catches only HTTPException around each enqueue;
    with the tasks layer translating every outage-class failure to 503, a dead
    broker yields the designed 200-with-details response, never a post-commit
    unhandled exception."""
    from app.routers import imports as imports_router

    monkeypatch.setattr(imports_router, "assert_url_allowed", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_client", _dead_broker_client())

    resp = await client.post(
        "/api/sites/bulk-import",
        headers=auth_headers,
        json={"csv_text": "http://127.0.0.1/q3-a,Q3 A\nhttp://127.0.0.1/q3-b,Q3 B"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2
    for row in body["results"]:
        assert row["status"] == "created"
        assert "could not be enqueued" in row["detail"]
