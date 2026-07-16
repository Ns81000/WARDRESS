"""Celery application instance.

Phase 0: broker wiring only, with a single self-test task so
`docker compose up` can prove worker <-> redis connectivity.
"""

import os

from celery import Celery

celery_app = Celery(
    "wardress",
    broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
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
)


@celery_app.task(name="wardress.ping")
def ping() -> str:
    """Connectivity self-test used by Phase 0 stack verification."""
    return "pong"
