"""Alert history + acknowledgement (§6/§7 /api/alerts).

Alerts are created by the worker when a scan is flagged; this router
serves the dashboard's alert feed (with per-channel delivery outcomes —
failed deliveries must be *visible*) and handles acks from the UI.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import record_audit
from app.db import get_db
from app.deps import AnalystUser, CurrentUser
from app.models import Alert, Site, utcnow
from app.schemas import AlertDeliveryOut, AlertDetailOut, AlertOut, AlertPage

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

DB = Annotated[AsyncSession, Depends(get_db)]


def _detail(alert: Alert, site_name: str | None) -> AlertDetailOut:
    return AlertDetailOut(
        **AlertOut.model_validate(alert).model_dump(),
        site_name=site_name,
        deliveries=[AlertDeliveryOut.model_validate(d) for d in alert.deliveries],
    )


@router.get("", response_model=AlertPage)
async def list_alerts(
    user: CurrentUser,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    unacknowledged_only: bool = False,
) -> AlertPage:
    query = select(Alert)
    if unacknowledged_only:
        query = query.where(Alert.acknowledged_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    alerts = (
        await db.scalars(
            query.options(selectinload(Alert.deliveries))
            .order_by(Alert.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    site_ids = {a.site_id for a in alerts}
    names: dict[uuid.UUID, str] = {}
    if site_ids:
        rows = (await db.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids)))).all()
        names = {row[0]: row[1] for row in rows}
    return AlertPage(
        items=[_detail(a, names.get(a.site_id)) for a in alerts],
        total=int(total or 0),
        offset=offset,
        limit=limit,
    )


@router.get("/{alert_id}", response_model=AlertDetailOut)
async def get_alert(alert_id: uuid.UUID, user: CurrentUser, db: DB) -> AlertDetailOut:
    alert = await db.scalar(
        select(Alert).options(selectinload(Alert.deliveries)).where(Alert.id == alert_id)
    )
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    site = await db.scalar(select(Site).where(Site.id == alert.site_id))
    return _detail(alert, site.name if site else None)


@router.post("/{alert_id}/ack", response_model=AlertDetailOut)
async def acknowledge_alert(alert_id: uuid.UUID, user: AnalystUser, db: DB) -> AlertDetailOut:
    """Idempotent: acking an already-acked alert returns it unchanged
    (first ack wins — the bot and the dashboard may race)."""
    alert = await db.scalar(
        select(Alert).options(selectinload(Alert.deliveries)).where(Alert.id == alert_id)
    )
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if alert.acknowledged_at is None:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = user.id
        alert.acknowledged_via = "dashboard"
        record_audit(
            db,
            actor=user,
            action="alert.acknowledge",
            target_type="alert",
            target_id=alert.id,
            target_label=f"Alert {str(alert.id)[:8]}",
            after={"risk_score": alert.risk_score, "via": "dashboard"},
        )
        await db.commit()
    site = await db.scalar(select(Site).where(Site.id == alert.site_id))
    return _detail(alert, site.name if site else None)
