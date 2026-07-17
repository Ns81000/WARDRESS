"""Alert creation + delivery (Celery task, §8).

Scan completion (scan_tasks) creates the Alert row and enqueues
`wardress.deliver_alert` as a *separate task* — alert delivery must
never block or crash a scan, so it does not run inside the scan task
body at all. Delivery failures become alert_deliveries rows with
status=failed and a user-safe detail, visible in the dashboard.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.alerting import build_alert_content, deliver_to_channel
from app.config import get_settings
from app.crypto import DecryptionError, decrypt_json
from app.models import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    NotificationChannel,
    Scan,
    Site,
    ensure_utc,
)
from app.settings_store import SMTP_KEY, TELEGRAM_KEY, load_setting
from worker.celery_app import celery_app
from worker.db import task_session

logger = logging.getLogger(__name__)

# Human labels for the alert's "top signals" list (§5 layer table).
LAYER_LABELS = {
    "layer1_hash": "Content hash",
    "layer2_dom_structure": "DOM structure",
    "layer3_link_audit": "Links and scripts",
    "layer4_visual_diff": "Visual appearance",
    "layer5_signatures": "Known signatures",
    "layer6_security_metadata": "Security metadata",
    "layer7_cloaking": "Cloaking",
    "layer8_semantics": "Content semantics",
}

TOP_SIGNALS = 4


def top_layers_from_scores(layer_scores: dict | None) -> list[dict]:
    """Highest-scoring non-skipped layers, for the alert body."""
    if not layer_scores:
        return []
    rows = [
        {"label": LAYER_LABELS.get(key, key), "score": float(entry.get("score") or 0.0)}
        for key, entry in layer_scores.items()
        if key in LAYER_LABELS and not entry.get("skipped") and (entry.get("score") or 0.0) > 0.0
    ]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:TOP_SIGNALS]


def _channel_config(channel: NotificationChannel) -> dict | None:
    try:
        return decrypt_json(channel.config_encrypted)
    except DecryptionError:
        return None


async def _deliver_alert(alert_id: uuid.UUID) -> str:
    async with task_session() as db:
        alert = await db.scalar(select(Alert).where(Alert.id == alert_id))
        if alert is None:
            return "alert-row-missing"
        # Idempotence under acks_late redelivery: if any delivery rows
        # already exist, a previous run got far enough — don't double-send.
        existing = await db.scalar(
            select(AlertDelivery).where(AlertDelivery.alert_id == alert.id).limit(1)
        )
        if existing is not None:
            return "already-delivered"

        site = await db.scalar(select(Site).where(Site.id == alert.site_id))
        scan = await db.scalar(select(Scan).where(Scan.id == alert.scan_id))
        if site is None or scan is None:
            return "prereqs-missing"

        channels = (
            await db.scalars(
                select(NotificationChannel)
                .where(
                    NotificationChannel.is_active.is_(True),
                    or_(
                        NotificationChannel.site_id.is_(None),
                        NotificationChannel.site_id == site.id,
                    ),
                )
                .order_by(NotificationChannel.created_at)
            )
        ).all()
        if not channels:
            logger.info("Alert %s: no active notification channels configured", alert.id)
            return "no-channels"

        now = datetime.now(UTC)
        muted_until = ensure_utc(site.muted_until)
        muted = muted_until is not None and muted_until > now

        smtp = await load_setting(db, SMTP_KEY)
        telegram = await load_setting(db, TELEGRAM_KEY)

        content = build_alert_content(
            site_name=site.name,
            site_url=site.url,
            risk_score=scan.risk_score,
            flag_threshold=site.flag_threshold,
            top_layers=top_layers_from_scores(scan.layer_scores),
            scan_id=str(scan.id),
            site_id=str(site.id),
            detected_at=(scan.finished_at or now).strftime("%Y-%m-%d %H:%M UTC"),
            base_url=get_settings().public_base_url,
        )

        sent = failed = skipped = 0
        for channel in channels:
            delivery = AlertDelivery(
                alert_id=alert.id,
                channel_id=channel.id,
                channel_name=channel.name,
                channel_type=channel.type.value,
            )
            if muted:
                delivery.status = AlertDeliveryStatus.skipped
                mute_display = muted_until.strftime("%Y-%m-%d %H:%M UTC")
                delivery.detail = f"Site alerts muted until {mute_display}"
                skipped += 1
            else:
                config = _channel_config(channel)
                if config is None:
                    delivery.status = AlertDeliveryStatus.failed
                    delivery.detail = (
                        "Channel configuration could not be decrypted — re-save the channel"
                    )
                    failed += 1
                else:
                    ok, detail = await deliver_to_channel(
                        channel.type.value, config, content, smtp=smtp, telegram=telegram
                    )
                    delivery.status = AlertDeliveryStatus.sent if ok else AlertDeliveryStatus.failed
                    delivery.detail = None if ok else detail
                    if ok:
                        sent += 1
                    else:
                        failed += 1
                        logger.warning(
                            "Alert %s delivery to %r (%s) failed: %s",
                            alert.id,
                            channel.name,
                            channel.type.value,
                            detail,
                        )
            delivery.finished_at = datetime.now(UTC)
            db.add(delivery)
            # Commit per channel: a crash mid-loop keeps what already
            # happened, and the idempotence guard prevents re-sends.
            await db.commit()

        logger.info(
            "Alert %s delivered: %d sent, %d failed, %d skipped", alert.id, sent, failed, skipped
        )
        return f"sent={sent} failed={failed} skipped={skipped}"


@celery_app.task(name="wardress.deliver_alert")
def deliver_alert(alert_id: str) -> str:
    """Deliver one alert to every applicable channel. Failures are rows,
    not exceptions — this task never propagates an error into Celery
    retry storms or scan state."""
    try:
        parsed = uuid.UUID(alert_id)
    except ValueError:
        logger.error("deliver_alert got a non-UUID id: %r", alert_id)
        return "bad-id"
    try:
        return asyncio.run(_deliver_alert(parsed))
    except Exception:
        logger.exception("Unexpected error delivering alert %s", alert_id)
        return "error"
