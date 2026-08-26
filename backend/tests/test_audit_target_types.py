"""Audit target_type filter contract (PROMPT-001 WS-D).

The frontend dropdown offers every record_audit target_type literal; this
pins the backend side: rows written with the three types that were missing
from the dropdown (ai_provider, ai_task, scan) are retrievable through
GET /api/audit-log?target_type=... — equality filtering works for any
value, so no backend change is required.
"""

import pytest
from sqlalchemy import select

from app.audit import record_audit
from app.models import User


async def _seed(db_factory, admin_user: User, target_type: str) -> None:
    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.id == admin_user.id))
        record_audit(
            db,
            actor=user,
            action=f"probe.{target_type}",
            target_type=target_type,
            target_id="t-1",
            target_label=f"probe {target_type}",
            after={"probe": True},
        )
        await db.commit()


@pytest.mark.parametrize("target_type", ["ai_provider", "ai_task", "scan"])
async def test_missing_from_dropdown_types_are_filterable(
    client, auth_headers, db_factory, admin_user, target_type
):
    await _seed(db_factory, admin_user, target_type)
    # a decoy row of another type must not leak into the filtered result
    await _seed(db_factory, admin_user, "site")

    resp = await client.get(
        "/api/audit-log", params={"target_type": target_type}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(entry["target_type"] == target_type for entry in body["items"])
    assert any(entry["action"] == f"probe.{target_type}" for entry in body["items"])
