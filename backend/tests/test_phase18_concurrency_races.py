"""Phase 18 proofs: scan/baseline concurrency races.

Two defect classes, one mechanism family:

- Concurrent scan-now through the stale-supersede path: every racer
  passed the check-then-set window, the DB index picked one winner, and
  every loser's IntegrityError escaped as an unhandled 500 with its
  staged audit row silently rolled back.
- Rebaseline had no in-flight uniqueness backstop at all: concurrent
  rebaselines all succeeded and each enqueued a full capture of the same
  site.

Concurrency tests drive the real app / real services against real
Postgres; the commit-window shim only guarantees the racers overlap,
while post-fix outcomes are arbitrated by the conditional-UPDATE claims
and the partial unique indexes in the database, not by the shim.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Baseline, BaselineStatus, Scan, ScanStatus, Site, utcnow
from app.services import ConflictError, trigger_scan_now

BACKEND_DIR = Path(__file__).resolve().parents[1]

SUPERSEDED_SCAN_ERROR = "Scan never completed — superseded by a new scan"
SUPERSEDED_CAPTURE_ERROR = "Capture never completed — superseded by a new capture"
MIGRATION_REPAIR_MARKER = "duplicate repaired during upgrade"


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee racers overlap: every commit waits, so all participants
    pass their checks before any of them commits (post-fix the DB still
    arbitrates via row locks and unique indexes)."""
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.5)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


async def _seed_site(db_factory, name: str) -> "Site":
    async with db_factory() as db:
        site = Site(name=name, url=f"http://127.0.0.1/{name}")
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _seed_ready_baseline(db_factory, site_id: uuid.UUID) -> None:
    async with db_factory() as db:
        db.add(
            Baseline(
                site_id=site_id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="a" * 64,
                captured_at=utcnow(),
            )
        )
        await db.commit()


async def _seed_stale_scan(db_factory, site_id: uuid.UUID) -> None:
    async with db_factory() as db:
        db.add(
            Scan(
                site_id=site_id,
                status=ScanStatus.running,
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db.commit()


# --- Finding: Concurrent scan-now through the stale-supersede path ---------


class TestScanNowStaleSupersedeRace:
    async def test_concurrent_scan_now_single_winner_no_integrity_escape(
        self, client, auth_headers, db_factory, widen_commit_window
    ):
        site = await _seed_site(db_factory, "p18-scan-race")
        await _seed_ready_baseline(db_factory, site.id)
        await _seed_stale_scan(db_factory, site.id)

        barrier = asyncio.Barrier(8)

        async def racer():
            async with barrier:
                # An unhandled app error propagates through ASGITransport
                # instead of becoming a response — pre-fix this is exactly
                # where the losers' IntegrityError surfaced (uvicorn would
                # have rendered it as a 500).
                return await client.post(f"/api/sites/{site.id}/scan-now", headers=auth_headers)

        responses = await asyncio.gather(*[racer() for _ in range(8)])
        codes = sorted(r.status_code for r in responses)
        assert codes.count(202) == 1, codes
        assert codes.count(409) == 7, codes

        async with db_factory() as db:
            states = (
                await db.execute(
                    text(
                        "SELECT status::text, count(*) FROM scans"
                        " WHERE site_id = :s GROUP BY status"
                    ),
                    {"s": str(site.id)},
                )
            ).all()
            audits = await db.scalar(
                text("SELECT count(*) FROM audit_log WHERE action = 'scan.now' AND target_id = :s"),
                {"s": str(site.id)},
            )
            superseded = (
                await db.scalars(select(Scan.error).where(Scan.error == SUPERSEDED_SCAN_ERROR))
            ).all()
        assert {status: int(n) for status, n in states} == {
            "pending": 1,
            "failed": 1,
        }
        assert audits == 1
        assert len(superseded) == 1

    async def test_service_level_insert_race_backstopped(
        self, db_factory, admin_user, widen_commit_window
    ):
        """The pure backstop primitive: two service callers pass the
        in-flight check before either commits; the loser's unique-index
        violation must surface as ConflictError, never as a raw
        IntegrityError."""
        site = await _seed_site(db_factory, "p18-scan-backstop")
        await _seed_ready_baseline(db_factory, site.id)

        barrier = asyncio.Barrier(2)
        outcomes: list[str] = []

        async def racer():
            async with barrier:
                pass
            async with db_factory() as db:
                try:
                    await trigger_scan_now(db, site, actor=admin_user, via="test")
                except ConflictError:
                    outcomes.append("conflict")
                except IntegrityError:
                    outcomes.append("raw-integrity-error")
                else:
                    outcomes.append("won")

        await asyncio.gather(*[racer() for _ in range(2)])
        assert sorted(outcomes) == ["conflict", "won"], outcomes

    async def test_sequential_stale_supersede_unchanged(self, client, auth_headers, db_factory):
        """Behavior-preservation guard (true before and after): a single
        scan-now still recovers a stale in-flight scan with the exact
        documented failure record."""
        site = await _seed_site(db_factory, "p18-scan-seq")
        await _seed_ready_baseline(db_factory, site.id)
        stale_created = datetime.now(UTC) - timedelta(hours=1)
        async with db_factory() as db:
            db.add(Scan(site_id=site.id, status=ScanStatus.pending, created_at=stale_created))
            await db.commit()

        resp = await client.post(f"/api/sites/{site.id}/scan-now", headers=auth_headers)
        assert resp.status_code == 202, resp.text

        async with db_factory() as db:
            old = (await db.scalars(select(Scan).where(Scan.status == ScanStatus.failed))).one()
            assert old.error == SUPERSEDED_SCAN_ERROR
            assert old.verdict is not None
            assert old.finished_at is not None
            fresh = (await db.scalars(select(Scan).where(Scan.status == ScanStatus.pending))).one()
            assert fresh.created_at > stale_created


# --- Finding: Baselines have no in-flight uniqueness backstop --------------


class TestRebaselineRace:
    async def test_concurrent_rebaselines_single_winner_single_capture(
        self, client, auth_headers, db_factory, widen_commit_window, stub_all_enqueues
    ):
        site = await _seed_site(db_factory, "p18-rebaseline-race")
        # Initial capture already resolved (failed): no in-flight row, so
        # every racer passes the check and heads for the insert.
        async with db_factory() as db:
            db.add(
                Baseline(
                    site_id=site.id,
                    status=BaselineStatus.failed,
                    error="seeded failed initial capture",
                )
            )
            await db.commit()

        barrier = asyncio.Barrier(10)

        async def racer():
            async with barrier:
                return await client.post(f"/api/sites/{site.id}/rebaseline", headers=auth_headers)

        responses = await asyncio.gather(*[racer() for _ in range(10)])
        codes = sorted(r.status_code for r in responses)
        print("CODES:", codes)
        assert codes.count(202) == 1, codes
        assert codes.count(409) == 9, codes

        async with db_factory() as db:
            states = (
                await db.execute(
                    text(
                        "SELECT status::text, count(*) FROM baselines"
                        " WHERE site_id = :s GROUP BY status"
                    ),
                    {"s": str(site.id)},
                )
            ).all()
            audits = await db.scalar(
                text(
                    "SELECT count(*) FROM audit_log"
                    " WHERE action = 'site.rebaseline' AND target_id = :s"
                ),
                {"s": str(site.id)},
            )
        assert {status: int(n) for status, n in states} == {
            "failed": 1,  # the seeded initial capture
            "pending": 1,  # exactly one accepted rebaseline
        }
        # Exactly ONE capture was enqueued for the one accepted request.
        assert len(stub_all_enqueues["baseline"]) == 1
        assert audits == 1

    async def test_concurrent_rebaselines_stale_supersede_single_winner(
        self, client, auth_headers, db_factory, widen_commit_window
    ):
        site = await _seed_site(db_factory, "p18-rebaseline-stale")
        async with db_factory() as db:
            db.add(
                Baseline(
                    site_id=site.id,
                    status=BaselineStatus.pending,
                    created_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await db.commit()

        barrier = asyncio.Barrier(8)

        async def racer():
            async with barrier:
                return await client.post(f"/api/sites/{site.id}/rebaseline", headers=auth_headers)

        responses = await asyncio.gather(*[racer() for _ in range(8)])
        codes = sorted(r.status_code for r in responses)
        assert codes.count(202) == 1, codes
        assert codes.count(409) == 7, codes

        async with db_factory() as db:
            rows = (
                await db.execute(
                    text("SELECT status::text, error FROM baselines WHERE site_id = :s"),
                    {"s": str(site.id)},
                )
            ).all()
        statuses = sorted(status for status, _ in rows)
        assert statuses == ["failed", "pending"]
        superseded = [error for status, error in rows if status == "failed"]
        assert superseded == [SUPERSEDED_CAPTURE_ERROR]

    async def test_baseline_inflight_index_backs_the_contract(self, engine):
        async with engine.begin() as conn:
            indexes = (
                await conn.execute(
                    text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'baselines'")
                )
            ).all()
        names = {r.indexname for r in indexes}
        assert "uq_baselines_one_inflight_per_site" in names
        definition = next(
            r.indexdef for r in indexes if r.indexname == "uq_baselines_one_inflight_per_site"
        )
        assert "unique" in definition.lower()
        assert "capturing" in definition and "pending" in definition

        async def insert_baseline(conn, status: str):
            result = await conn.execute(
                sa.insert(Site.__table__)
                .values(name="ix-probe", url=f"http://127.0.0.1/ix-{uuid.uuid4().hex[:8]}")
                .returning(Site.__table__.c.id)
            )
            site_id = result.scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO baselines (id, site_id, status, is_current, created_at)"
                    " VALUES (:id, :sid, CAST(:st AS baseline_status), false, now())"
                ),
                {"id": str(uuid.uuid4()), "sid": str(site_id), "st": status},
            )
            return site_id

        # One in-flight slot per site...
        async with engine.begin() as conn:
            site_id = await insert_baseline(conn, "pending")
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO baselines (id, site_id, status, is_current,"
                        " created_at)"
                        " VALUES (:id, :sid, 'pending', false, now())"
                    ),
                    {"id": str(uuid.uuid4()), "sid": str(site_id)},
                )
        # ...covering BOTH in-flight statuses...
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO baselines (id, site_id, status, is_current,"
                        " created_at)"
                        " VALUES (:id, :sid, 'capturing', false, now())"
                    ),
                    {"id": str(uuid.uuid4()), "sid": str(site_id)},
                )
        # ...while terminal-history rows coexist freely.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO baselines (id, site_id, status, is_current,"
                    " created_at)"
                    " VALUES (:id, :sid, 'ready', true, now())"
                ),
                {"id": str(uuid.uuid4()), "sid": str(site_id)},
            )
            await conn.execute(
                text(
                    "INSERT INTO baselines (id, site_id, status, is_current,"
                    " created_at)"
                    " VALUES (:id, :sid, 'failed', false, now())"
                ),
                {"id": str(uuid.uuid4()), "sid": str(site_id)},
            )

    async def test_migration_repairs_preexisting_duplicate_inflight_baselines(self, engine):
        """The shipped migration collapses pre-existing duplicate in-flight
        captures (keeping the earliest-created row per site) before building
        the unique index — exercised by downgrading, planting duplicates,
        and upgrading."""
        env = dict(os.environ)
        env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)

        def alembic(*args: str) -> None:
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=str(BACKEND_DIR),
                env=env,
                capture_output=True,
                timeout=300,
            )
            assert proc.returncode == 0, (
                proc.stdout.decode("utf-8", "replace")[-1500:]
                + proc.stderr.decode("utf-8", "replace")[-1500:]
            )

        async def plant_site() -> str:
            async with engine.begin() as conn:
                result = await conn.execute(
                    sa.insert(Site.__table__)
                    .values(name="mig-dup", url="http://127.0.0.1/mig-dup-baseline")
                    .returning(Site.__table__.c.id)
                )
                return str(result.scalar_one())

        async def insert_pending_baseline(site_id: str, created_at: datetime) -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO baselines (id, site_id, status, is_current,"
                        " created_at)"
                        " VALUES (:id, :sid, 'pending', false, :created_at)"
                    ),
                    {"id": str(uuid.uuid4()), "sid": site_id, "created_at": created_at},
                )

        alembic("downgrade", "k5l6m7n8p9q1-1")
        try:
            site_id = await plant_site()
            await insert_pending_baseline(site_id, datetime(2026, 1, 1, tzinfo=UTC))
            await insert_pending_baseline(site_id, datetime(2026, 6, 1, tzinfo=UTC))
            await insert_pending_baseline(site_id, datetime(2026, 8, 1, tzinfo=UTC))
            async with engine.begin() as conn:
                planted = (
                    await conn.execute(
                        text("SELECT count(*) FROM baselines WHERE status = 'pending'")
                    )
                ).scalar_one()
            assert planted == 3
            alembic("upgrade", "head")
        finally:
            # Never leave the shared harness database below head, even if
            # an assertion above fired mid-way.
            alembic("upgrade", "head")

        async with engine.begin() as conn:
            kept = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM baselines WHERE status = 'pending' AND error IS NULL"
                    )
                )
            ).scalar_one()
            repaired = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM baselines"
                        " WHERE status = 'failed'"
                        " AND error LIKE '%duplicate repaired during upgrade%'"
                    )
                )
            ).scalar_one()
            indexes = (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'baselines'")
                )
            ).all()
        assert kept == 1  # the earliest-created capture survives untouched
        assert repaired == 2
        assert "uq_baselines_one_inflight_per_site" in {r.indexname for r in indexes}


# --- Fix-mechanics guards ---------------------------------------------------


class TestViolationClassification:
    def test_sqlstate_predicates(self):
        from app.services import (
            baselines_inflight_unique_violation,
            concurrent_write_aborted,
            scans_inflight_unique_violation,
            sites_url_unique_violation,
        )

        class _Orig(Exception):
            pass

        def wrapped(sqlstate: str | None, constraint: str | None) -> SQLAlchemyError:
            orig = _Orig()
            if sqlstate is not None:
                orig.sqlstate = sqlstate  # type: ignore[attr-defined]
            if constraint is not None:
                orig.constraint_name = constraint  # type: ignore[attr-defined]
            return IntegrityError("INSERT failed", None, orig)

        assert scans_inflight_unique_violation(wrapped("23505", "ix_scans_one_inflight_per_site"))
        assert scans_inflight_unique_violation(wrapped("23505", None))
        assert not scans_inflight_unique_violation(wrapped("23505", "uq_sites_url"))
        assert baselines_inflight_unique_violation(
            wrapped("23505", "uq_baselines_one_inflight_per_site")
        )
        assert baselines_inflight_unique_violation(wrapped("23505", None))
        assert not baselines_inflight_unique_violation(
            wrapped("23505", "ix_scans_one_inflight_per_site")
        )
        # The shared precedents keep behaving.
        assert sites_url_unique_violation(wrapped("23505", "uq_sites_url"))
        assert concurrent_write_aborted(wrapped("40P01", None))
        assert not concurrent_write_aborted(wrapped("23505", None))
