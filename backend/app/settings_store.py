"""Typed access to the encrypted app_settings rows.

One row per integration ("smtp", "telegram", "gemini", "ollama"), each a
Fernet-encrypted JSON object. Readers must treat a missing row, an
undecryptable row (rotated CREDENTIALS_ENCRYPTION_KEY), or a malformed
blob identically: the integration is *unconfigured* — log and degrade,
never raise into a scan or a request handler.

The API writes through `save_setting`; the worker and bot only read.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import DecryptionError, decrypt_json, encrypt_json
from app.models import AppSetting

logger = logging.getLogger(__name__)

SMTP_KEY = "smtp"
TELEGRAM_KEY = "telegram"
GEMINI_KEY = "gemini"
OLLAMA_KEY = "ollama"


async def load_setting(db: AsyncSession, key: str) -> dict | None:
    """Decrypted settings dict, or None when absent/undecryptable."""
    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row is None:
        return None
    try:
        return decrypt_json(row.value_encrypted)
    except DecryptionError:
        logger.warning(
            "Settings row %r could not be decrypted (rotated key?) — treating as unconfigured",
            key,
        )
        return None


async def save_setting(db: AsyncSession, key: str, value: dict) -> None:
    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row is None:
        db.add(AppSetting(key=key, value_encrypted=encrypt_json(value)))
    else:
        row.value_encrypted = encrypt_json(value)
        row.updated_at = datetime.now(UTC)
    await db.commit()


async def delete_setting(db: AsyncSession, key: str) -> None:
    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row is not None:
        await db.delete(row)
        await db.commit()
