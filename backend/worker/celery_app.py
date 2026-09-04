"""Celery application instance.

Broker wiring plus the scan/baseline task modules. Task bodies live in
worker/scan_tasks.py.
"""

import os

from celery import Celery

celery_app = Celery(
    "wardress",
    broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    include=[
        "worker.scan_tasks",
        "worker.beat_tasks",
        "worker.alert_tasks",
        "worker.remediation_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Scan tasks are long-running (Playwright); acknowledge late so a
    # crashed worker never silently drops a scan.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Hard backstop: a wedged browser must not hold a worker slot forever.
    # Fetch/probe-level timeouts (worker/fetcher.py, worker/probe.py) fire
    # long before these. Phase 2 raised them (was 180/240): a scan now runs
    # the metadata probe + nine layers + MiniLM inference after the fetch.
    # Phase 6 raised them again (was 300/360): the capture's transient-
    # failure retry adds a full reduced attempt (worker/fetcher.py, worst
    # case ~264s) before a probe whose per-request timeouts are sequential
    # (~90s worst) and detection (~30s worst) — see the budget note in
    # worker/stealth.py's retry section. Both stay well under the
    # 10-minute stale-in-flight cutoff the API and Beat dispatcher use
    # (app/scanning.py).
    task_soft_time_limit=420,
    task_time_limit=480,
)


@celery_app.task(name="wardress.ping")
def ping() -> str:
    """Connectivity self-test used by Phase 0 stack verification."""
    return "pong"
