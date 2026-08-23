"""Phase 19 proofs: concurrent alert acknowledgements.

The docstring contract ("first ack wins — the bot and dashboard may race;
a re-ack records no second audit row") was enforced by check-then-set on
a session-local attribute, so N simultaneous acks all passed the check,
each recorded an audit row, and whichever committed last overwrote the
attribution. Concurrency tests drive the real app / real services against
real Postgres; the commit-window shim only guarantees the racers overlap,
while post-fix outcomes are arbitrated by the conditional UPDATE's
rowcount (Postgres re-evaluates ``acknowledged_at IS NULL`` when a losing
writer's lock wait ends), not by the shim.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AuditLog, Scan, ScanStatus, Site
from app.services import acknowledge_alert


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee racers overlap: every commit waits, so all participants
    pass their checks before any of them commits."""
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.5)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


async def _seed_alert(db_factory, name: str) -> uuid.UUID:
    async with db_factory() as db:
        site = Site(name=name, url=f"http://127.0.0.1/{name}")
        db.add(site)
        await db.flush()
        scan = Scan(site_id=site.id, status=ScanStatus.completed)
        db.add(scan)
        await db.flush()
        alert = Alert(site_id=site.id, scan_id=scan.id, risk_score=0.9)
        db.add(alert)
        await db.commit()
        return alert.id


# --- Finding: Concurrent alert acknowledgements -----------------------------


async def _race_acks(client, headers_a, headers_b, alert_id, racers: int = 4) -> None:
    """Barrier-synchronized ack burst against one alert (all 200 expected)."""
    barrier = asyncio.Barrier(racers)

    async def racer(headers):
        async with barrier:
            resp = await client.post(f"/api/alerts/{alert_id}/ack", headers=headers)
            assert resp.status_code == 200, resp.text

    await asyncio.gather(*[racer(headers_a if i % 2 else headers_b) for i in range(racers)])


class TestConcurrentAckRace:
    async def test_concurrent_acks_single_winner_single_audit_row(
        self, client, auth_headers, analyst_headers, db_factory, widen_commit_window
    ):
        alert_ids = [await _seed_alert(db_factory, f"p19-ack-race-{i}") for i in range(3)]
        for alert_id in alert_ids:
            await _race_acks(client, auth_headers, analyst_headers, alert_id)

        async with db_factory() as db:
            for alert_id in alert_ids:
                audits = (
                    await db.scalars(
                        select(AuditLog).where(
                            AuditLog.action == "alert.acknowledge",
                            AuditLog.target_id == str(alert_id),
                        )
                    )
                ).all()
                assert len(audits) == 1, f"alert {alert_id}: {len(audits)} audit rows"
                row = await db.get(Alert, alert_id)
                # Attribution is coherent: the recorded acker IS the winner,
                # not whichever racer happened to commit last.
                assert row.acknowledged_by == audits[0].actor_id
                assert row.acknowledged_via == "dashboard"

    async def test_every_response_reflects_the_one_committed_state(
        self, client, auth_headers, analyst_headers, db_factory, widen_commit_window
    ):
        """Response honesty under the race: no responder may report an ack
        that the database does not hold (pre-fix, each loser echoed its own
        overwritten-but-doomed values while another racer's commit won)."""
        alert_id = await _seed_alert(db_factory, "p19-ack-honesty")
        barrier = asyncio.Barrier(4)

        async def racer(headers):
            async with barrier:
                resp = await client.post(f"/api/alerts/{alert_id}/ack", headers=headers)
                assert resp.status_code == 200, resp.text
                return resp.json()

        bodies = await asyncio.gather(
            *[racer(auth_headers if i % 2 else analyst_headers) for i in range(4)]
        )
        stamps = {b["acknowledged_at"] for b in bodies}
        assert len(stamps) == 1, stamps
        assert all(b["acknowledged_via"] == "dashboard" for b in bodies)

        async with db_factory() as db:
            row = await db.get(Alert, alert_id)
        # Compare instants (JSON may render the UTC instant with a different
        # offset spelling than datetime.isoformat()).
        parsed = {datetime.fromisoformat(s) for s in stamps}
        assert row.acknowledged_at is not None
        assert parsed == {row.acknowledged_at.astimezone(UTC)}

    async def test_mixed_surface_race_bot_vs_dashboard_single_winner(
        self, db_factory, admin_user, widen_commit_window
    ):
        """Dashboard-vs-bot (the exact pair the docstring names): one atomic
        claim arbitrates across surfaces, including the bot's actor=None +
        actor_label shape."""
        alert_id = await _seed_alert(db_factory, "p19-ack-mixed")
        barrier = asyncio.Barrier(2)

        async def racer(kind: str) -> str:
            async with barrier:
                async with db_factory() as db:
                    row = await db.get(Alert, alert_id)
                    if kind == "bot":
                        await acknowledge_alert(
                            db, row, actor=None, actor_label="telegram-bot", via="telegram"
                        )
                    else:
                        await acknowledge_alert(db, row, actor=admin_user, via="dashboard")
                    return row.acknowledged_via

        vias = await asyncio.gather(racer("bot"), racer("dashboard"))
        # Exactly one committed state exists; every caller observes it
        # (pre-fix the two surfaces disagreed — last writer won).
        assert len(set(vias)) == 1, vias

        async with db_factory() as db:
            audits = (
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "alert.acknowledge",
                        AuditLog.target_id == str(alert_id),
                    )
                )
            ).all()
            row = await db.get(Alert, alert_id)
        assert len(audits) == 1
        if row.acknowledged_via == "telegram":
            assert row.acknowledged_by is None
            assert audits[0].actor_email == "telegram-bot"
        else:
            assert row.acknowledged_by == admin_user.id
            assert audits[0].actor_email == admin_user.email

    async def test_reack_after_race_still_idempotent(
        self, client, auth_headers, analyst_headers, db_factory, widen_commit_window
    ):
        """Behavior-preservation guard (true before and after): once the
        winning ack has landed, further acks change nothing and add no
        audit rows."""
        alert_id = await _seed_alert(db_factory, "p19-ack-reack")
        await _race_acks(client, auth_headers, analyst_headers, alert_id)
        resp = await client.post(f"/api/alerts/{alert_id}/ack", headers=analyst_headers)
        assert resp.status_code == 200

        async with db_factory() as db:
            audits = (
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "alert.acknowledge",
                        AuditLog.target_id == str(alert_id),
                    )
                )
            ).all()
            row = await db.get(Alert, alert_id)
            after = (row.acknowledged_at, row.acknowledged_by, row.acknowledged_via)
        assert len(audits) == 1
        # The late ack changed nothing.
        resp2 = await client.post(f"/api/alerts/{alert_id}/ack", headers=analyst_headers)
        assert resp2.status_code == 200
        async with db_factory() as db:
            row = await db.get(Alert, alert_id)
            final = (row.acknowledged_at, row.acknowledged_by, row.acknowledged_via)
            total_audits = (
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "alert.acknowledge",
                        AuditLog.target_id == str(alert_id),
                    )
                )
            ).all()
        assert final == after
        assert len(total_audits) == 1
