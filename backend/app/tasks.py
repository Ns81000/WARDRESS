"""Thin task-enqueue layer.

The API process must not import worker code (Playwright etc.), so tasks
are dispatched by name via a broker-only Celery client. Enqueue failures
(Redis down) are surfaced to the caller as HTTP 503 by the routers —
never a silent drop.
"""

import uuid

from celery import Celery
from fastapi import HTTPException, status
from kombu.exceptions import OperationalError

from app.config import get_settings

_client: Celery | None = None


def _celery_client() -> Celery:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Celery("wardress-api", broker=settings.redis_url, backend=settings.redis_url)
        _client.conf.update(
            task_serializer="json",
            accept_content=["json"],
            # Fail fast when Redis is unreachable instead of hanging the request.
            broker_transport_options={"max_retries": 2, "interval_start": 0.1},
        )
    return _client


def _send(name: str, args: list) -> None:
    try:
        _celery_client().send_task(name, args=args)
    except OperationalError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Task queue is unavailable — try again shortly",
        ) from exc


def enqueue_baseline_capture(baseline_id: uuid.UUID) -> None:
    _send("wardress.capture_baseline", [str(baseline_id)])


def enqueue_scan(scan_id: uuid.UUID) -> None:
    _send("wardress.run_scan", [str(scan_id)])


def enqueue_remediation(execution_id: uuid.UUID) -> None:
    _send("wardress.fire_remediation", [str(execution_id)])
