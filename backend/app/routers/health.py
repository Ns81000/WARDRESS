"""Operational health / status (§7 /api/health, §11 status page).

Three surfaces:
- `GET /api/health/live` — unauthenticated liveness for the compose
  healthcheck. Cheap, no DB: "is the process answering HTTP".
- `GET /api/health` — unauthenticated readiness: process + DB reachable.
  Kept backward-compatible ({"status": "ok", ...}) since Phase 0's
  compose healthcheck curls it.
- `GET /api/health/details` — authenticated rich status powering the
  dashboard: queue depth, scan latency, DB size, worker/beat/bot
  liveness, uptime. Every probe is individually fail-safe — the status
  page must render even when a dependency is down (that is the point).
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.models import Scan, ScanStatus, Site, ensure_utc
from app.schemas import HealthComponent, HealthDetails

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["operations"])

DB = Annotated[AsyncSession, Depends(get_db)]

_STARTED_AT = time.monotonic()

# The Beat dispatcher ticks every 60s; if the newest scheduled scan's
# next_scan_at math implies no tick within this window, flag beat as
# degraded. We infer liveness from Redis + a heuristic rather than a
# heartbeat row to keep Beat dumb (Phase 2 decision).
_BEAT_STALE = timedelta(minutes=5)


def _uptime_seconds() -> int:
    return int(time.monotonic() - _STARTED_AT)


async def _db_ok(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Unauthenticated process liveness — no dependencies touched."""
    return {"status": "ok"}


@router.get("")
async def readiness(db: DB) -> dict[str, str]:
    """Unauthenticated readiness (process + DB). Backward-compatible with
    the Phase 0 compose healthcheck, which curls /api/health."""
    if await _db_ok(db):
        return {"status": "ok", "service": "wardress-api"}
    return {"status": "degraded", "service": "wardress-api", "detail": "database unreachable"}


def _redis_component() -> HealthComponent:
    """Ping Redis via the broker connection. Fail-safe. Runs in a thread
    (sync redis client) — see health_details."""
    try:
        import redis

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            client.ping()
            return HealthComponent(status="ok")
        finally:
            client.close()
    except Exception as exc:
        return HealthComponent(status="down", detail=f"{type(exc).__name__}")


def _queue_depth() -> int | None:
    """Approximate broker queue depth (length of the default Celery
    'celery' list in Redis). None if it cannot be read."""
    try:
        import redis

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            return int(client.llen("celery"))
        finally:
            client.close()
    except Exception:
        return None


def _worker_component() -> HealthComponent:
    """Ask Celery for live workers via a control ping (short timeout).
    Uses the API's broker-only client (app/tasks.py) — the API process
    never imports worker code."""
    try:
        from app.tasks import _celery_client

        replies = _celery_client().control.ping(timeout=2.0)
        if replies:
            return HealthComponent(status="ok", detail=f"{len(replies)} worker(s)")
        return HealthComponent(status="down", detail="no workers responded")
    except Exception as exc:
        return HealthComponent(status="unknown", detail=f"{type(exc).__name__}")


def _dispatch_heartbeat() -> datetime | None:
    """Last Beat dispatch tick, written to Redis by the dispatcher task
    (worker/beat_tasks.py). Proves Beat is scheduling AND a worker is
    executing. None when unreadable/absent."""
    try:
        import redis

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            raw = client.get("wardress:heartbeat:dispatch")
        finally:
            client.close()
        if raw is None:
            return None
        return datetime.fromisoformat(raw.decode("utf-8"))
    except Exception:
        return None


async def _db_size_bytes(db: AsyncSession) -> int | None:
    """Total database size in bytes (Postgres only; None on SQLite)."""
    try:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            return int(await db.scalar(text("SELECT pg_database_size(current_database())")) or 0)
    except Exception:
        logger.debug("Could not read DB size", exc_info=True)
    return None


@router.get("/details", response_model=HealthDetails)
async def health_details(user: CurrentUser, db: DB) -> HealthDetails:
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    db_up = await _db_ok(db)
    sites_total = 0
    scans_last_24h = 0
    avg_scan_seconds: float | None = None
    last_scan_at: datetime | None = None
    last_dispatch_tick_at: datetime | None = None

    if db_up:
        sites_total = int(await db.scalar(select(func.count()).select_from(Site)) or 0)
        scans_last_24h = int(
            await db.scalar(
                select(func.count()).select_from(Scan).where(Scan.created_at >= day_ago)
            )
            or 0
        )
        # Mean wall-clock of completed scans in the last 24h.
        durations = (
            await db.execute(
                select(Scan.started_at, Scan.finished_at).where(
                    Scan.status == ScanStatus.completed,
                    Scan.finished_at.is_not(None),
                    Scan.started_at.is_not(None),
                    Scan.created_at >= day_ago,
                )
            )
        ).all()
        spans = [
            (ensure_utc(f) - ensure_utc(s)).total_seconds()
            for s, f in durations
            if s is not None and f is not None
        ]
        if spans:
            avg_scan_seconds = round(sum(spans) / len(spans), 2)
        last_scan_at = ensure_utc(await db.scalar(select(func.max(Scan.finished_at))))

    last_dispatch_tick_at = await asyncio.to_thread(_dispatch_heartbeat)

    components: dict[str, HealthComponent] = {
        "database": HealthComponent(status="ok" if db_up else "down"),
        # Sync clients (redis-py, Celery control) run in threads so the
        # event loop never blocks on a wedged broker.
        "redis": await asyncio.to_thread(_redis_component),
        "worker": await asyncio.to_thread(_worker_component),
    }
    queue_depth = await asyncio.to_thread(_queue_depth)

    # Overall status: down if DB or Redis is down; degraded if a worker is
    # missing; ok otherwise.
    overall = "ok"
    if components["database"].status == "down" or components["redis"].status == "down":
        overall = "down"
    elif components["worker"].status in ("down", "unknown"):
        overall = "degraded"

    return HealthDetails(
        status=overall,
        uptime_seconds=_uptime_seconds(),
        queue_depth=queue_depth,
        db_size_bytes=await _db_size_bytes(db) if db_up else None,
        sites_total=sites_total,
        scans_last_24h=scans_last_24h,
        avg_scan_seconds=avg_scan_seconds,
        last_scan_at=last_scan_at,
        last_dispatch_tick_at=last_dispatch_tick_at,
        components=components,
    )
